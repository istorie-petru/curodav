"""Banners (2026-08-09) -- a per-dashboard-page header image ("banner"/
"cover") for Home and every label/Space/Project page that renders the
shared widget grid (dashboard.html / label_detail.html both include
_page_banner.html). One source, one editor modal:

  Uploaded: a local image file stored base64 (kind="upload") -- same
  no-transcoding/no-resizing approach as contact photos
  (routers/contacts.py's _read_photo), just a bigger size cap since a
  wide banner is more bytes than a small avatar. 2026-08-11: the
  SearXNG-backed "search the web" picker was removed -- upload is the
  only way to set a new banner now. Banners set while that feature
  existed (kind="remote", including any that were hotlink-only) keep
  rendering: _page_banner.html serves them through /banners/image when
  they have local bytes, else hotlinks the stored image_url, and the
  editor still shows its Clear control for them.

Storage is app_meta (see db.py's get_page_banner/set_page_banner -- one
JSON blob keyed per page, page_key "" = Home, otherwise the label name).
The editor (/banners/editor) is a server-rendered #modal-target fragment
(like dashboard_customize.html) opened from edit mode on a dashboard
page; every mutating form inside is a plain POST that static/modal.js
submits via fetch, then closes the dialog and reloads the page.

2026-09-27 (item 10, flairs): a page with no upload/remote banner of its
own AND no explicit `db.set_page_banner_cleared` marker now defaults to
a keyword-matched "flair" photo (src/flairs.py) when its own name
matches one -- resolved through `db.effective_page_banner`, not the raw
`get_page_banner`, everywhere that default needs to apply (this file's
own `banner_editor` route, routers/dashboard.py's `_page_banner_context`
for a label/group/project's own page, and db.py's `banner_for_object` for
an event/task/habit that inherits its label's banner or falls back to
its own name). A flair is `kind="remote"` pointing at a bundled local
static image (webapp/src/static/flairs/*.jpg), not a hotlink -- renders
through the exact same `image_url` branch a legacy searched banner
always has, no template changes needed for it at all.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db
from ..deps import get_db, templates
from ..image_sniff import sniff_image_type

router = APIRouter(tags=["banners"])

# Cap + content-type allowlist for uploaded banners -- same reasoning as
# routers/contacts.py's _read_photo comment (this app has no auth, so
# validate what the browser actually handed us, not its filename
# extension; no transcoding, the cap is the only guard). Banners are wide
# landscape images, so 8MB rather than a contact photo's 5MB.
_MAX_BANNER_BYTES = 8 * 1024 * 1024
_CONTENT_TYPE_TO_TYPE = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _flair_name_for_scope(scope: str) -> str | None:
    """Item 10 (2026-09-27, flairs): the display name to try a flair
    match against for this banner scope, or None for a scope with no
    real "name" at all (Home, the global page-header default, the four
    season scopes -- a season photo gets its OWN flair default a
    different way, see db.banner_for_object's own season tier, not
    matched by name here). A plain label/project's own scope IS its name
    already; a group's scope is the prefixed `group:<name>` key, unwrapped
    back to the plain name `db.flairs.match_flair` actually needs."""
    if not scope or scope == db.PAGE_HEADER_BANNER_SCOPE or scope in db.SEASON_BANNER_SCOPES.values():
        return None
    return db.group_from_page_key(scope) or scope


def _safe_page_url(page_url: str, scope: str) -> str:
    """Where a banner-mutating POST should redirect back to -- the
    `page_url` hidden field the opening page supplied when it's a valid
    same-site path (no scheme/host, so a forged value can't open-redirect
    anywhere off-instance), otherwise derived from `scope` ("" = Home,
    else that label's page). Falls back to a working redirect rather than
    erving a bare 303 with no Location."""
    if isinstance(page_url, str) and page_url.startswith("/") and "://" not in page_url:
        return page_url
    return f"/labels/{scope}" if scope else "/"


@router.get("/banners/editor")
def banner_editor(
    request: Request,
    scope: str = "",
    page_url: str = "",
    from_modal: bool = False,
    conn=Depends(get_db),
):
    """The banner editor modal fragment -- upload and remove in one dialog,
    plus the current banner (if any). `scope` is the page key ("" = Home,
    else the label name), `page_url` where a mutation should return to.
    2026-08-11: the SearXNG "search the web" tab was removed; upload is the
    only way to set a banner now.

    `from_modal` (2026-09-21 direct request: "if a button allows the user
    to navigate from one modal to the other, instead of the 'Done' there
    should always be a 'Cancel'/back button") -- true only when this modal
    was opened from INSIDE another already-open modal (today, just
    label_form_modal.html's own inline Banner field -- see
    _label_form_fields.html's own comment), as opposed to every other
    caller's edit-mode "Add/Change banner" button on a real page
    (Home/Space/Project/label). This app's modal system has no stack (one
    #modal-target, swapped in place) -- `data-modal-cancel` just closes to
    the real underlying page, which would drop the user back on the plain
    labels list instead of the edit modal they came from. `page_url`
    already points at the right destination either way (the caller sets
    it); this flag only decides HOW to get there: fetch-and-swap back into
    that modal (`from_modal=True`) vs. just close (every other caller,
    unchanged).

    2026-09-27 (item 10, flairs): `banner` now resolves through
    `db.effective_page_banner` (not the raw `get_page_banner`), so this
    modal shows a computed flair default exactly the same as a real
    upload -- confirmed via AskUserQuestion: no visual distinction, it's
    just "the current banner" either way. `_flair_name_for_scope` above
    is what turns this route's own `scope` (a plain label's name already,
    or a group's prefixed `group:<name>` key, or a sentinel scope with no
    real name at all) into the value `effective_page_banner` needs to try
    a flair match with."""
    return templates.TemplateResponse(
        "banner_editor.html",
        {
            "request": request,
            "active_tab": "dashboard",
            "scope": scope,
            "page_url": page_url,
            "from_modal": from_modal,
            "banner": db.effective_page_banner(conn, scope, name=_flair_name_for_scope(scope)),
        },
    )


@router.post("/banners/upload")
def upload_banner(
    scope: str = Form(""),
    page_url: str = Form(""),
    banner_file: UploadFile | None = File(None),
    conn=Depends(get_db),
):
    """Upload a local image as this page's banner (kind="upload", stored
    base64 like a contact photo). Reads the file synchronously via
    UploadFile.file (same as routers/export.py's import routes) so this is
    a plain sync route -- directly callable in tests. An empty file field
    (FastAPI still hands back an UploadFile with no filename for an
    unfilled <input type=file>) is a no-op redirect, not an error: the
    upload form submits it every time alongside the hidden scope/page_url
    fields."""
    if banner_file is not None and banner_file.filename:
        image_type = _CONTENT_TYPE_TO_TYPE.get((banner_file.content_type or "").lower())
        if image_type is None:
            raise HTTPException(400, "Unsupported image type -- use JPEG, PNG, GIF, or WEBP.")
        data = banner_file.file.read()
        if len(data) > _MAX_BANNER_BYTES:
            raise HTTPException(400, "Image is too large (max 8MB).")
        # 2026-09-07 fix (flagged in an earlier audit): `image_type` above
        # only reflects the browser's own Content-Type claim -- confirm the
        # bytes actually are a real image of one of the four supported
        # kinds before storing them, using whatever the bytes actually are
        # rather than trusting the (possibly spoofed) header any further.
        sniffed = sniff_image_type(data)
        if sniffed is None:
            raise HTTPException(400, "That file doesn't look like a real JPEG, PNG, GIF, or WEBP image.")
        image_type = sniffed
        db.set_page_banner(
            conn,
            scope,
            {
                "kind": "upload",
                "image_b64": base64.b64encode(data).decode("ascii"),
                "image_type": image_type,
                # Short content hash -- cache-busts the /banners/image URL
                # (see db.get_page_banner's version backfill), so a
                # re-uploaded banner always gets a fresh immutable-cache URL
                # instead of the browser re-serving the old image forever.
                "version": hashlib.md5(data).hexdigest()[:12],
            },
        )
    return RedirectResponse(url=_safe_page_url(page_url, scope), status_code=303)


@router.get("/banners/image")
def banner_image(scope: str = "", conn=Depends(get_db)):
    """Serves a banner's locally-stored decoded bytes for `<img src>`
    (2026-08-10, extended 2026-08-11 to cover cached remote images).

    Uploaded banners used to be embedded in the page's HTML as an inline
    `data:` URI (see _page_banner.html) -- a multi-MB base64 blob riding
    along in every page render, which is exactly what made a label page
    with a banner load at 100+ms/2MB+ while identical pages without one
    were 7ms. Moving the bytes to their own request keeps the HTML small
    and lets the browser cache the image separately. Any banner that has
    local bytes -- uploads, and legacy remote banners set while the
    web-search feature existed that were downloaded at set time -- takes
    this route; only a legacy hotlink-only remote banner has no local
    bytes and keeps hotlinking.

    `scope` is the page key ("" = Home, else the label name), same value
    the page templates already pass as `banner_scope`. The `version` query
    param the templates append (`?v=...`, db.get_page_banner's `version`)
    makes the URL change whenever the image changes, so the immutable
    Cache-Control below is safe -- a stale cached response can never be
    served under the URL a freshly-rendered page asks for (same pattern as
    _VersionedStaticFiles in main.py). `Content-Encoding: identity` just
    tells main.py's GZipMiddleware to skip this response: a JPEG is already
    compressed, so gzipping it costs CPU and shrinks nothing.
    """
    banner = db.get_page_banner(conn, scope)
    if not banner or not banner.get("image_b64"):
        raise HTTPException(404)
    try:
        data = base64.b64decode(banner.get("image_b64") or "", validate=True)
    except (ValueError, TypeError):
        raise HTTPException(404)
    # image_type comes from upload_banner's own allowlist, but a hand-edited
    # app_meta row could carry anything -- re-validate into a known set
    # rather than echoing it into a Content-Type header (same guard as
    # deps.py's _avatar).
    image_type = str(banner.get("image_type") or "").lower()
    if image_type not in ("jpeg", "png", "gif", "webp"):
        image_type = "jpeg"
    return Response(
        content=data,
        media_type=f"image/{image_type}",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Encoding": "identity",
        },
    )


@router.post("/banners/remove")
def remove_banner(scope: str = Form(""), page_url: str = Form(""), conn=Depends(get_db)):
    """The editor's "Clear banner" button (renamed from "Remove banner"
    2026-09-27, item 10 -- see banner_editor.html's own comment). Scope +
    page_url ride along as hidden fields so the redirect lands back on
    the exact page the editor was opened from. (2026-08-29: page_url no
    longer carries a `?edit=1` -- edit mode is a persistent Settings >
    Appearance toggle now, not part of the page's own URL.)

    2026-09-29 (direct request): "Clear" is a two-step ladder, not a
    single jump straight to blank. When there's a real explicit banner
    stored (`db.get_page_banner` returns something -- an upload, or a
    legacy remote), this button's first job is just to remove THAT
    (`db.clear_page_banner`, a plain blank-out) and let the next tier
    decide -- which means a label/project/task/event whose name matches a
    flair keyword lands on its flair, not on a forced blank, exactly the
    same as it would if no explicit banner had ever been uploaded. Only
    when there's no explicit banner left to remove (this same button
    showing because `effective_page_banner` is already resolving to a
    flair default, or there was never anything at all) does firing it
    mean "stay blank even though my name matches a keyword" -- that's
    when it stores the sticky "no image, deliberately" marker
    (`db.set_page_banner_cleared`), so the flair doesn't just silently
    reappear the moment this second Clear click is over."""
    if db.get_page_banner(conn, scope):
        db.clear_page_banner(conn, scope)
    else:
        db.set_page_banner_cleared(conn, scope)
    return RedirectResponse(url=_safe_page_url(page_url, scope), status_code=303)
