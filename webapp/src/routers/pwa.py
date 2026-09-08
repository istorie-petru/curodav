"""1.8 slice 3 -- PWA shell (plans/open-priority.md § Offline-first editing
& synchronization §11 slice 3; architecture fork in §0). Manifest + service
worker + an app-shell cache, so the app is installable and opens to a real
shell offline, per plans/ofline-first-pwa.md's own acceptance line.

2026-09-09 -- the client-side "Offline Mode" feature (the `/offline` page,
its Quick Add builder, the local IndexedDB mirror/write queue, and the
service worker's offline-navigation fallback) was purged outright, direct
request, after repeated UI complaints against screenshots concluded the
whole surface wasn't worth salvaging. `templates/offline.html` and every
`static/offline_*.js` file are gone; the `GET /offline` route that used to
render that template is gone with them. The server-side sync engine
(`src/offline_sync.py`, `routers/sync_api.py`, the Sync card on Settings >
Data & Maintenance) was explicitly kept out of scope -- it doesn't depend
on this route or these files existing, so it's left exactly as it was, now
just unreachable from any UI until/unless something else calls it. `/sw.js`
and `/favicon.ico` below are unrelated to any of this and stay as they were.

One route lives here rather than under the existing /static mount:

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
