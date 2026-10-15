"""One route lives here rather than under the existing /static mount:

  - `GET /sw.js` -- the service worker script. It must be served from the
    same path it wants as its control scope (the whole app, "/"), and a
    service worker's default scope is the directory of the URL it was
    fetched from -- a script served at /static/sw.js would default to
    controlling only /static/*, not the app's real pages. Registering it
    at the root path here (identical file content to static/sw.js, which
    also stays reachable at the versioned/cached static URL for the
    service worker's own precache list) is simpler than threading a
    `Service-Worker-Allowed: /` header through _VersionedStaticFiles for
    just this one file.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["pwa"])

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/sw.js")
def service_worker():
    # media_type pinned explicitly rather than left to guesswork off the
    # extension -- some static-file configs/proxies serve .js as
    # text/plain, which some browsers refuse to register as a service
    # worker from. no-store: the file's own content controls its cache
    # version (sw.js's CACHE_NAME below), so the browser should always
    # refetch this specific script to notice an update promptly, the
    # standard "make the service worker script itself uncacheable"
    # recommendation.
    return FileResponse(
        _STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/favicon.ico")
def favicon():
    return FileResponse(
        _STATIC_DIR / "favicon-32.png",
        media_type="image/x-icon",
    )
