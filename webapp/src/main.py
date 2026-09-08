"""FastAPI entrypoint. Wires together config, the SQLite cache, the
Radicale bridge, background sync, and the three routers (calendar, tasks,
contacts). Styling deliberately deferred -- see webapp/README.md -- this
is about full CRUD functionality first."""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from . import db, sync
from .auth import AuthMiddleware, CSRFMiddleware
from .caldav_bridge import CalDavBridge
from .config import apply_persisted_radicale_overrides, load_settings, uses_default_radicale_credentials
from .security_headers import SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent

# 2026-09-07 (direct request) -- first-run defaults, sourced from image
# files the user dropped in the repo-root `pictures/` directory (a sibling
# of `webapp/`, hence the two `.parent`s off this file's own `src/`
# directory). Seeded ONCE into app_meta (see _seed_default_media below);
# after that they're indistinguishable from any other user-set banner/
# avatar -- editable/removable as normal in Settings > Appearance/General,
# never re-applied over a value the user has since changed.
_PICTURES_DIR = _BASE_DIR.parent.parent / "pictures"
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
    aborting startup -- a partial `pictures/` directory still boots the app
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
    settings = load_settings()

    # 2026-08-29 -- a Radicale connection entered through /setup or
    # Settings (routers/auth.py, routers/settings.py) lives in app_meta,
    # not the environment; apply it here, before the settings are
    # published to app.state and before the bridge below is built, so
    # both see the effective (possibly overridden) connection. A no-op
    # when CC_RADICALE_URL was set in the environment (env always wins,
    # see apply_persisted_radicale_overrides's docstring) or when nothing
    # was ever saved.
    with db.connect(settings.db_path) as _conn:
        settings = apply_persisted_radicale_overrides(settings, _conn)
        # First-run default banners/avatar (2026-09-07, direct request) --
        # see _seed_default_media's own docstring. Must not be allowed to
        # fail startup over e.g. a missing pictures/ directory on a deploy
        # that never got one; that's just "nothing seeded," not fatal.
        try:
            _seed_default_media(_conn)
        except Exception:
            logger.exception("Default media seed failed; continuing without it")
    app.state.settings = settings

    # The bridge's constructor connects to Radicale (DAVClient -> principal,
    # plus eager default collection lookups). Radicale is OPTIONAL -- the app
    # is fully usable standalone (writes are plain SQL to the local SQLite
    # store; see routers/tasks.py's "no bridge in this path anymore" notes) --
    # so an unreachable server must not refuse to boot. On failure the app
    # keeps running without sync/published lists; the background thread and
    # the Settings > Published lists surface both degrade gracefully on the
    # None bridge, and a restart re-attempts the connection.
    try:
        bridge = CalDavBridge(settings)
    except Exception:
        bridge = None
        logger.exception("Radicale unreachable at startup; running without the sync bridge")
    else:
        # 2026-09-07 audit fix (documentation/reports/
        # full-app-audit-2026-09-07.md): a production deploy that just
        # authenticated to a REACHABLE Radicale server using the dev-only
        # devuser/devpass fallback (config.py's load_settings default) is
        # refused outright -- unlike the broad except above, this is
        # deliberately allowed to raise and fail the whole lifespan startup.
        # Gated on the bridge having actually connected (the `else` branch,
        # not a bare settings check before the try) so a standalone install
        # with no Radicale server at all -- which never authenticates
        # against anything with these credentials -- isn't forced to set
        # them just to boot; only a deploy where the fallback pair is
        # genuinely live and reachable is the real exposure the audit
        # flagged ("only reachable if a real deploy forgets to set
        # CC_RADICALE_URL/CC_RADICALE_PASSWORD").
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

    # Populate the cache synchronously once at startup so the first page
    # load has real data instead of an empty database until the first
    # background poll completes. full_refresh already isolates failures
    # per-collection (see sync.py), but this call itself must not be
    # allowed to raise either -- letting a Radicale-side error escape
    # here would fail FastAPI's lifespan startup and refuse to boot the
    # *entire* app over what might be one bad object in one calendar. If
    # this does fail, the cache just stays empty/stale until the
    # background sync thread's own retry loop (started below) succeeds.
    with db.connect(settings.db_path) as conn:
        try:
            sync.full_refresh(bridge, conn)
        except Exception:
            logger.exception("Initial Radicale sync failed at startup; continuing with an empty/stale cache")

    thread, stop_event = sync.start_background_sync(
        bridge, settings.db_path, settings.sync_interval_seconds
    )
    logger.info(
        "Started background Radicale sync every %ss", settings.sync_interval_seconds
    )

    yield

    stop_event.set()


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

    # CSRF protection (2026-08-29, src/auth.py::CSRFMiddleware) -- added
    # before AuthMiddleware below so Auth ends up the outer layer (Starlette
    # runs the most-recently-added middleware first): an unauthenticated
    # forged request gets Auth's normal 401/redirect, never reaching this
    # check at all; only a request that already carries a session cookie
    # goes through the Origin/Referer verification.
    app.add_middleware(CSRFMiddleware)

    # Single-user login (2026-08-16, src/auth.py) -- a no-op gate when no
    # CC_AUTH_USERNAME/CC_AUTH_PASSWORD are configured, otherwise every
    # request except /login and /static needs a valid session cookie. The
    # middleware reads its settings off `app.state.settings` (set by the
    # lifespan below), so an unset pair keeps the app behaving exactly as
    # it always has. 2026-08-29: also forces GET/POST /setup on an
    # unconfigured production deploy (CC_DEPLOY_MODE=production) -- see
    # auth.py's module docstring.
    app.add_middleware(AuthMiddleware)

    # Security headers (2026-08-29, src/security_headers.py) -- added
    # LAST (after CSRF and Auth above), so it ends up the OUTERMOST layer
    # (Starlette runs the most-recently-added middleware first, wrapping
    # everything registered before it -- see CSRFMiddleware's own comment
    # on this same ordering rule). Being outermost is the whole point
    # here: a middleware that short-circuits a request (Auth's 302/401,
    # CSRF's 403) never calls further into the stack, so anything added
    # BEFORE it would simply never run for a denied request. Being
    # outermost means this one still wraps `send` before Auth/CSRF get a
    # chance to respond, so these headers land on every response,
    # including denials -- a denied response is still a response a
    # browser renders/acts on, so it needs the same X-Frame-Options/CSP/
    # nosniff protection as a normal page.
    app.add_middleware(SecurityHeadersMiddleware)

    app.mount("/static", _VersionedStaticFiles(directory=_BASE_DIR / "static"), name="static")

    # Phase 1 (label-space rework, 2026-08-06): routers/calendars.py,
    # routers/task_lists.py, routers/addressbooks.py are deleted -- those
    # collection-management concepts are gone (see plans/
    # label-space-rework.md §3 Phase 1 and db.py's Phase 1 comments).
    #
    # 2026-08-07: routers/databases.py and routers/grades.py are deleted
    # too -- Databases (and Grades, which was built on top of it) is
    # deactivated and removed entirely, not just unlinked from nav. See
    # features/architecture.md's Grades/Databases removal note and
    # db.py's own removal comments on the `databases`/`database_columns`/
    # `database_rows`/`grades` tables.
    # routers/today.py and routers/week.py are gone (1.9 side work,
    # "Today"/"Week" folded into the Dashboard's widget registry and the
    # merged /calendar/week respectively -- see routers/dashboard.py::
    # today_redirect and routers/calendar.py::week_redirect for the
    # bookmark-preserving redirects that replaced them, same precedent as
    # the earlier /calendar/timetable retirement).
    from .routers import auth, banners, calendar, contacts, dashboard, export, habits, labels, notes, projects, public_lists, published_lists, pwa, quick_capture, search, settings, spaces, sync_api, tasks, timeline

    app.include_router(auth.router)
    # Published Lists' standalone public feed (2026-08-29) -- no login, no
    # Radicale account, see routers/public_lists.py's module docstring and
    # AuthMiddleware's "/public/" exemption in src/auth.py. Registered
    # early alongside auth.router since both define the app's few
    # genuinely public-without-a-session routes.
    app.include_router(public_lists.router)
    app.include_router(dashboard.router)
    app.include_router(search.router)
    # 1.8 slice 1 -- the sync API skeleton (routers/sync_api.py,
    # src/offline_sync.py). No PWA client calls this yet (§11 slices 3+);
    # it's exercised synthetically by tests today. Named `sync_api` (not
    # `sync`) to avoid shadowing this module's own already-imported
    # `sync` (the unrelated Radicale Published-Lists background sync).
    app.include_router(sync_api.router)
    # 1.8 slice 3 -- the PWA shell's own two routes (GET /sw.js, GET
    # /offline)
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
    app.include_router(notes.router)
    # Quick Capture (plans/quick-capture.md) -- POST /api/quick-capture +
    # GET /api/quick-capture/preview, its own tiny router since /api/search
    # and /api/labels (routers/search.py) already own the /api/ namespace's
    # other two endpoints and this is a distinct concern (parsing + create,
    # not query).
    app.include_router(quick_capture.router)
    app.include_router(labels.router)
    app.include_router(spaces.router)
    app.include_router(projects.router)
    app.include_router(habits.router)
    app.include_router(banners.router)
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
