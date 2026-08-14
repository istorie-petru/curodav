"""FastAPI entrypoint. Wires together config, the SQLite cache, the
Radicale bridge, background sync, and the three routers (calendar, tasks,
contacts). Styling deliberately deferred -- see webapp/README.md -- this
is about full CRUD functionality first."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from . import db, sync
from .caldav_bridge import CalDavBridge
from .config import load_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent


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
    app.state.settings = settings

    bridge = CalDavBridge(settings)
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
    from .routers import banners, calendar, contacts, dashboard, export, habits, labels, projects, published_lists, pwa, schedule, search, settings, sync_api, tasks, timeline

    app.include_router(dashboard.router)
    app.include_router(search.router)
    # 1.8 slice 1 -- the sync API skeleton (routers/sync_api.py,
    # src/offline_sync.py). No PWA client calls this yet (§11 slices 3+);
    # it's exercised synthetically by tests today. Named `sync_api` (not
    # `sync`) to avoid shadowing this module's own already-imported
    # `sync` (the unrelated Radicale Published-Lists background sync).
    app.include_router(sync_api.router)
    # 1.8 slice 3 -- the PWA shell's own two routes (GET /sw.js, GET
    # /offline). Neither path collides with anything else already
    # registered, so ordering relative to the rest of this list doesn't
    # matter the way timeline.router's does below.
    app.include_router(pwa.router)
    app.include_router(calendar.router)
    app.include_router(calendar.events_router)
    app.include_router(schedule.router)
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
    app.include_router(labels.router)
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
