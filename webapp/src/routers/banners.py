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
  editor still shows its Remove control for them.

Storage is app_meta (see db.py's get_page_banner/set_page_banner -- one
JSON blob keyed per page, page_key "" = Home, otherwise the label name).
The editor (/banners/editor) is a server-rendered #modal-target fragment
(like dashboard_customize.html) opened from edit mode on a dashboard
page; every mutating form inside is a plain POST that static/modal.js
submits via fetch, then closes the dialog and reloads the page.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db
from ..deps import get_db, templates

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


def _safe_page_url(page_url: str, scope: str) -> str:
    """Where a banner-mutating POST should redirect back to -- the
    `page_url` hidden field the opening page supplied when it's a valid
    same-site path (no scheme/host, so a forged value can't open-redirect
    anywhere off-instance), otherwise derived from `scope` ("" = Home,
    else that label's page). Falls back to a working redirect rather than
    erving a bare 303 with no Location."""
    if isinstance(page_url, str) and page_url.startswith("/") and "://" not in page_url:
        return page_url
    return f"/settings/labels/{scope}" if scope else "/"


@router.get("/banners/editor")
def banner_editor(
    request: Request,
    scope: str = "",
    page_url: str = "",
    conn=Depends(get_db),
):
    """The banner editor modal fragment -- upload and remove in one dialog,
    plus the current banner (if any). `scope` is the page key ("" = Home,
    else the label name), `page_url` where a mutation should return to.
    2026-08-11: the SearXNG "search the web" tab was removed; upload is the
    only way to set a banner now."""
    return templates.TemplateResponse(
        "banner_editor.html",
        {
            "request": request,
            "active_tab": "dashboard",
            "scope": scope,
            "page_url": page_url,
            "banner": db.get_page_banner(conn, scope),
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
    """Clear this page's banner entirely (the editor's "Remove banner"
    button). Scope + page_url ride along as hidden fields so the redirect
    lands back on the exact page the editor was opened from, including its
    ?edit=1 state."""
    db.clear_page_banner(conn, scope)
    return RedirectResponse(url=_safe_page_url(page_url, scope), status_code=303)
