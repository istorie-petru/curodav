"""1.8 slice 3 -- PWA shell (plans/open-priority.md § Offline-first editing
& synchronization §11 slice 3; architecture fork in §0). Manifest + service
worker + an app-shell cache, so the app is installable and opens to a real
shell offline, per plans/ofline-first-pwa.md's own acceptance line. No sync,
no IndexedDB, no local read/write path yet -- those are slices 4-6; this
slice is purely "can the app open at all with no network."

Two routes live here rather than under the existing /static mount:

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
  - `GET /offline` -- the offline fallback shell (templates/offline.html).
    Reachable normally online too (a plain route, not sw.js-only) so it
    can be loaded/tested without simulating a dropped connection; sw.js's
    fetch handler falls back to its cached copy of this same URL when a
    navigation request fails with nothing better cached.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from ..deps import templates

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


@router.get("/offline")
def offline_shell(request: Request):
    return templates.TemplateResponse(
        "offline.html",
        {"request": request, "active_tab": ""},
    )
