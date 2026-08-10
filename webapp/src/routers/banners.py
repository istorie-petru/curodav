"""Banners (2026-08-09) -- a per-dashboard-page header image ("banner"/
"cover") for Home and every label/Space/Project page that renders the
shared widget grid (dashboard.html / label_detail.html both include
_page_banner.html). Two sources, one editor modal:

  1. Searched & hotlinked: the banner editor's search box proxies
     SearXNG's image category server-side (src/searxng.py) and stores the
     remote image URL (kind="remote") with the result page for
     attribution. The search is always strict-safe and always prefers
     high-resolution images -- both hardcoded in src/searxng.py, no user
     toggle (2026-08-09 follow-up: the SFW radio and the image-type/size
     dropdowns were removed). Hotlinking rather than downloading is the
     pragmatic default for a personal tool browsing wallpaper-type
     sources; if a source blocks hotlinking, the same modal's upload tab
     is the fallback.
  2. Uploaded: a local image file stored base64 (kind="upload") -- same
     no-transcoding/no-resizing approach as contact photos
     (routers/contacts.py's _read_photo), just a bigger size cap since a
     wide banner is more bytes than a small avatar.

Storage is app_meta (see db.py's get_page_banner/set_page_banner -- one
JSON blob keyed per page, page_key "" = Home, otherwise the label name).
The editor (/banners/editor) is a server-rendered #modal-target fragment
(like dashboard_customize.html) opened from edit mode on a dashboard
page; every mutating form inside is a plain POST that static/modal.js
submits via fetch, then closes the dialog and reloads the page. The
search form is `data-modal-get`, so submitting it re-fetches this same
editor URL with the new query params and swaps the fragment in place --
no client-side result rendering.
"""

from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db, searxng
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
    return f"/labels/{scope}" if scope else "/"


def _searxng_base_url(request: Request) -> str:
    """The configured SearXNG instance, or the module default when the
    request has no real app settings to read (this app's own test suite
    constructs bare Request({...}) objects -- same graceful-fallback
    convention as deps.py's globals)."""
    try:
        return request.app.state.settings.searxng_base_url
    except Exception:
        return searxng.DEFAULT_BASE_URL


@router.get("/banners/editor")
def banner_editor(
    request: Request,
    scope: str = "",
    page_url: str = "",
    q: str = "",
    edit: bool = False,
    conn=Depends(get_db),
):
    """The banner editor modal fragment -- search (via SearXNG), upload,
    and remove in one dialog, plus the current banner (if any). `scope` is
    the page key ("" = Home, else the label name), `page_url` where a
    mutation should return to. When `q` is present the SearXNG search runs
    server-side and its results render inside the same modal (the search
    form is `data-modal-get`, so modal.js re-fetches this same URL with the
    new query and swaps the fragment in place -- see this module's
    docstring). Search failures render as an inline error rather than
    failing the modal, since a SearXNG instance being down shouldn't block
    the upload tab from still working.

    2026-08-09 follow-up: the SFW toggle and the image-type/size filter
    dropdowns are gone -- safesearch is always strict and the search
    always prefers high-res images (both hardcoded in src/searxng.py), so
    this route only carries the search query now."""
    results: list[dict] = []
    search_error: str | None = None
    query = (q or "").strip()
    if query:
        try:
            results = searxng.search_banner_images(_searxng_base_url(request), query)
        except Exception as exc:
            search_error = f"Search failed: {exc}"
    return templates.TemplateResponse(
        "banner_editor.html",
        {
            "request": request,
            "active_tab": "dashboard",
            "scope": scope,
            "page_url": page_url,
            "banner": db.get_page_banner(conn, scope),
            "query": query,
            "results": results,
            "search_error": search_error,
            "edit": edit,
        },
    )


@router.post("/banners/set")
def set_banner(
    scope: str = Form(""),
    page_url: str = Form(""),
    image_url: str = Form(""),
    source_url: str = Form(""),
    alt: str = Form(""),
    conn=Depends(get_db),
):
    """Pick a searched result as this page's banner -- stores the remote
    image URL (kind="remote") plus the result page for attribution. Only
    http(s) URLs are accepted: SearXNG returns real image URLs, but a
    forged/stale form could submit javascript: or data: and that would end
    up as an <img src> in the page. Anything else is a silent no-op that
    still redirects back (the page just keeps its old banner)."""
    image_url = image_url.strip()
    if image_url.lower().startswith(("http://", "https://")):
        banner: dict = {"kind": "remote", "image_url": image_url}
        if source_url and source_url.lower().startswith(("http://", "https://")):
            banner["source_url"] = source_url
        if alt:
            banner["alt"] = alt.strip()
        db.set_page_banner(conn, scope, banner)
    return RedirectResponse(url=_safe_page_url(page_url, scope), status_code=303)


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
    """Serves an uploaded banner's decoded bytes for `<img src>` (2026-08-10).

    Uploaded banners used to be embedded in the page's HTML as an inline
    `data:` URI (see _page_banner.html) -- a multi-MB base64 blob riding
    along in every page render, which is exactly what made a label page
    with a banner load at 100+ms/2MB+ while identical pages without one
    were 7ms. Moving the bytes to their own request keeps the HTML small
    and lets the browser cache the image separately.

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
    if not banner or banner.get("kind") != "upload":
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
