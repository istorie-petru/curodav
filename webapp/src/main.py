"""FastAPI entrypoint. Wires together config, the SQLite cache, the
Radicale bridge, background sync, and the three routers (calendar, tasks,
contacts). Styling deliberately deferred -- see webapp/README.md -- this
is about full CRUD functionality first."""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from .log import get_logger
from . import db, perf, reminders, sync
from .auth import AuthMiddleware, CSRFMiddleware
from .caldav_bridge import CalDavBridge
from .config import apply_persisted_radicale_overrides, apply_persisted_timezone, load_settings, uses_default_radicale_credentials
from .security_headers import SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO)
logger = get_logger(__name__)

_BASE_DIR = Path(__file__).resolve().parent

_PICTURES_DIR = _BASE_DIR.parent.parent / "assets"
_DEFAULT_MEDIA_SEEDED_KEY = "default_media_seeded_v1"
_DEFAULT_PAGE_BANNER_FILE = "banner_51.jpg"
_DEFAULT_AVATAR_FILE = "avatar.jpg"
_DEFAULT_SEASON_FILES = {
    "spring": "spring_51.jpg",
    "summer": "summer_51.jpg",
    "autumn": "autumn_51.jpg",
    "winter": "winter_51.jpg",
}


def _seed_default_media(conn: sqlite3.Connection, pictures_dir: Path = _PICTURES_DIR) -> None:
    """Pre-populates the global page banner (db.PAGE_HEADER_BANNER_SCOPE,
    all pages' fallback), the four seasonal task/event banners
    (db.SEASON_BANNER_SCOPES), and the app's own avatar (db.
    set_profile_photo) from `pictures_dir` so a fresh install already looks
    finished instead of showing bare gradients/initials everywhere.

    Gated on a one-time app_meta flag, checked and set unconditionally
    (even when some/all source files are missing) so this only ever
    attempts the seed once per database -- a value the user has since
    edited or removed in Settings is never re-applied or overwritten by a
    later startup. Each file is read independently and a missing/unreadable
    one is skipped with a warning rather than failing the others or
    aborting startup -- a partial `assets/` directory still boots the app
    and seeds whatever it can.

    Stores images the exact same way an upload through routers/banners.py
    or routers/settings.py's profile-photo route would (base64 in app_meta,
    content-hash `version` for cache-busting) -- these seeded defaults are
    real, normal banners/avatar from every other code path's point of view,
    not a separate mechanism."""
    if db.get_app_meta(conn, _DEFAULT_MEDIA_SEEDED_KEY):
        return

    def _read(filename: str) -> bytes | None:
        path = pictures_dir / filename
        try:
            return path.read_bytes()
        except OSError:
            logger.warning("Default media seed: could not read %s, skipping", path)
            return None

    def _upload_banner(scope: str, data: bytes) -> None:
        db.set_page_banner(
            conn,
            scope,
            {
                "kind": "upload",
                "image_b64": base64.b64encode(data).decode("ascii"),
                "image_type": "jpeg",
                "version": hashlib.md5(data).hexdigest()[:12],
            },
        )

    banner_bytes = _read(_DEFAULT_PAGE_BANNER_FILE)
    if banner_bytes:
        _upload_banner(db.PAGE_HEADER_BANNER_SCOPE, banner_bytes)

    for season, filename in _DEFAULT_SEASON_FILES.items():
        season_bytes = _read(filename)
        if season_bytes:
            _upload_banner(db.SEASON_BANNER_SCOPES[season], season_bytes)

    avatar_bytes = _read(_DEFAULT_AVATAR_FILE)
    if avatar_bytes:
        db.set_profile_photo(conn, base64.b64encode(avatar_bytes).decode("ascii"), "jpeg")

    db.set_app_meta(conn, _DEFAULT_MEDIA_SEEDED_KEY, "1")


class _VersionedStaticFiles(StaticFiles):
    """Plain StaticFiles sets no Cache-Control at all, so browsers fall
    back to heuristic caching -- inconsistent across browsers and the
    reason a hard refresh used to be needed to see a CSS/JS change. Every
    static URL is now cache-busted (deps.py's `static_url()` appends the
    file's mtime as `?v=...`), which makes a long, aggressive cache
    completely safe: the URL itself changes whenever the file's content
    does, so a stale cached response can never be served under the URL a
    freshly-rendered page actually asks for. `immutable` additionally
    tells supporting browsers not to even revalidate (no conditional GET)
    for the lifetime of that specific `?v=...` URL."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    boot = time.perf_counter()
    steps: dict[str, float] = {}
    settings = load_settings()

    with db.connect(settings.db_path) as _conn:
        settings = apply_persisted_radicale_overrides(settings, _conn)
        apply_persisted_timezone(_conn)
        try:
            _seed_default_media(_conn)
        except Exception:
            logger.exception("Default media seed failed; continuing without it")
        from . import auth as auth_core

        auth_core.ensure_recovery_token(_conn)
    app.state.settings = settings
    steps["database"] = time.perf_counter() - boot

    from . import flairs

    flairs.configure(settings.flairs_dir)

    # The bridge's constructor connects to Radicale (DAVClient -> principal,
    # plus eager default collection lookups). Radicale is OPTIONAL -- the app
    # is fully usable standalone (writes are plain SQL to the local SQLite
    # store; see routers/tasks.py's "no bridge in this path anymore" notes) --
    # so an unreachable server must not refuse to boot. On failure the app
    # keeps running without sync/published lists; the background thread and
    # the Settings > Published lists surface both degrade gracefully on the
    # None bridge, and a restart re-attempts the connection.
    bridge_started = time.perf_counter()
    try:
        bridge = CalDavBridge(settings)
    except Exception as exc:
        bridge = None
        if type(exc).__name__ == "AuthorizationError":
            logger.error(
                "Radicale rejected the credentials (401) at %s for user %r; running without the "
                "sync bridge. Check CC_RADICALE_USER/CC_RADICALE_PASSWORD against Radicale's users file.",
                settings.radicale_base_url,
                settings.radicale_username,
            )
        else:
            logger.exception("Radicale unreachable at startup; running without the sync bridge")
    else:
        if settings.deploy_mode == "production" and uses_default_radicale_credentials(settings):
            raise RuntimeError(
                "CC_DEPLOY_MODE=production connected to a live Radicale "
                "server using the dev-only fallback credentials "
                "(devuser/devpass) -- set CC_RADICALE_USER/"
                "CC_RADICALE_PASSWORD (or configure real credentials via "
                "Settings > Data & Maintenance) before running this in "
                "production."
            )
    app.state.bridge = bridge
    steps["radicale connection"] = time.perf_counter() - bridge_started

    # The sync only materializes published Lists into Radicale (nothing the
    # pages read), and the thread's first tick runs right away. It must not
    # run before the port opens: a large first sync once outlasted the
    # deploy health check and got a healthy release rolled back.
    stop_event = None
    if bridge is not None:
        _thread, stop_event = sync.start_background_sync(
            bridge, settings.db_path, settings.sync_interval_seconds
        )
        logger.info(
            "Started background Radicale sync every %ss", settings.sync_interval_seconds
        )
    else:
        logger.warning("Background Radicale sync not started (no bridge); restart to retry")
    _reminder_thread, reminder_stop = reminders.start_scheduler(settings.db_path)
    perf_stop = perf.start_flusher(settings.db_path)

    total_ms = (time.perf_counter() - boot) * 1000
    breakdown = ", ".join(f"{name} {round(seconds * 1000)} ms" for name, seconds in steps.items())
    perf.record("startup", "ready", total_ms, breakdown)
    logger.info("Ready to serve after %d ms (%s)", round(total_ms), breakdown)
    for name, seconds in steps.items():
        perf.record("startup", name, seconds * 1000)

    yield

    if stop_event is not None:
        stop_event.set()
    reminder_stop.set()
    perf_stop.set()


def create_app() -> FastAPI:
    app = FastAPI(title="Command Center Web", lifespan=lifespan)

    # Every page here is server-rendered HTML built fresh from the SQLite
    # cache on each request (Tasks/Contacts/Calendar all read live DB
    # state) -- deliberately NOT cached at the HTTP level the way
    # /static now is (_VersionedStaticFiles below), since a cached page
    # would mean editing a task and then seeing the old version on the
    # next load until the cache expired. That staleness risk is the
    # actual reason full-page caching isn't the fix here, even though
    # these pages can get large (a Tasks table with ~15 rows -- each with
    # its own inline status/importance/urgency <select> full of <option>s
    # plus a handful of inline <svg> icons -- runs to ~75KB uncompressed,
    # confirmed by measuring one directly).
    #
    # gzip is the right lever instead: it doesn't cache anything (every
    # request still hits the DB and re-renders), it just shrinks what's
    # actually sent over the wire before the browser can start painting.
    # HTML/SVG compress very well (highly repetitive markup, as above) --
    # typically 70-85% smaller -- which directly cuts the transfer time
    # behind the "large page = brief blank screen" symptom without any of
    # caching's staleness risk. `minimum_size` skips compressing the tiny
    # JSON responses (e.g. /tasks/{uid}/update-field) where gzip's own
    # overhead would net-lose.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def _remember_request(request, call_next):
        from . import terminology

        token = terminology.current_request.set(request)
        try:
            return await call_next(request)
        finally:
            terminology.current_request.reset(token)

    app.add_middleware(CSRFMiddleware)

    app.add_middleware(AuthMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(perf.TimingMiddleware)

    app.mount("/static", _VersionedStaticFiles(directory=_BASE_DIR / "static"), name="static")

    from .routers import auth, banners, calendar, contacts, dashboard, export, finance, flairs as flairs_router, habits, label_pages, labels, notebook, perf as perf_router, projects, public_lists, published_lists, push, pwa, quick_capture, search, secretariat_page, settings, spaces, sync_api, tasks, taxonomy, timeline

    @app.exception_handler(StarletteHTTPException)
    async def http_error_page(request: Request, exc: StarletteHTTPException):
        wants_html = "text/html" in request.headers.get("accept", "") and request.headers.get("x-requested-with") != "fetch"
        if exc.status_code == 404 and wants_html and not request.url.path.startswith("/static"):
            from .deps import templates

            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Something went wrong. It was logged."}, status_code=500)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(public_lists.router)
    app.include_router(dashboard.router)
    app.include_router(secretariat_page.home_router)
    app.include_router(search.router)
    app.include_router(sync_api.router)
    app.include_router(pwa.router)
    app.include_router(calendar.router)
    app.include_router(calendar.events_router)
    # timeline.router's literal routes (/tasks/timeline, /tasks/timeline/
    # create) must be registered BEFORE tasks.router -- tasks.router
    # defines a catch-all GET /tasks/{uid} (task_detail) that would
    # otherwise match "/tasks/timeline" first (uid="timeline") and shadow
    # this router's own /tasks/timeline entirely, since FastAPI tries
    # routes in registration order across routers, not just within one.
    # Confirmed the hard way: without this ordering, GET /tasks/timeline
    # silently rendered task_detail.html's "Task not found" page instead
    # of the Timeline view.
    app.include_router(timeline.router)
    app.include_router(tasks.router)
    app.include_router(contacts.router)
    app.include_router(quick_capture.router)
    app.include_router(taxonomy.router)
    app.include_router(labels.router)
    app.include_router(labels.projects_settings_router)
    app.include_router(label_pages.groups_settings_router)
    app.include_router(label_pages.router)
    app.include_router(label_pages.group_router)
    app.include_router(spaces.router)
    app.include_router(projects.router)
    app.include_router(habits.router)
    app.include_router(notebook.citations_router)
    app.include_router(notebook.glossary_router)
    app.include_router(notebook.router)
    app.include_router(notebook.field_settings_router)
    app.include_router(notebook.frontmatter_settings_router)
    app.include_router(finance.router)
    app.include_router(finance.settings_router)
    app.include_router(push.router)
    app.include_router(perf_router.router)
    app.include_router(banners.router)
    app.include_router(flairs_router.router)
    app.include_router(settings.router)
    app.include_router(published_lists.router)
    app.include_router(export.router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
