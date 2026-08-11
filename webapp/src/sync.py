"""Pulled Radicale's calendar/tasks/contacts collections into the local
SQLite cache (db.py) prior to the Phase 1 label-space rework
(2026-08-06, see features/architecture.md §1). That's no longer
what this module does.

Per §1 of the plan: the base pool (`tasks`/`events`/`contacts`) is now
plain SQL, full stop -- there is no invisible default Radicale collection
for it to poll into anymore, and no other CalDAV/CardDAV client to
reconcile the base pool against (this app is the only writer of it now;
nothing else round-trips through Radicale for base storage). routers/
tasks.py, routers/calendar.py, routers/contacts.py, routers/schedule.py
write straight to db.py, no bridge call in that path (see each router's
own module docstring).

Phase 6 (published Lists, 2026-08-07) gave this module a real job again:
`full_refresh` now materializes every `published_lists` row (see
src/published_lists.py's `materialize_all`) -- a List is a named subset of
the base pool, filtered by a boolean label expression, kept in sync as its
own real Radicale collection. This is deliberately the *only* trigger
implemented (periodic, via the background thread below) -- "materialize on
every write to a matching label" is explicitly optional per the plan text
(§3 Phase 6) and periodic re-sync already satisfies the acceptance
criterion ("editing an item's labels updates List membership without a
manual re-publish step" -- true within one sync interval, same tradeoff
this app already made for the old Radicale-polling design pre-Phase-1).
"""

from __future__ import annotations

import logging
import sqlite3
import threading

from . import db
from .caldav_bridge import CalDavBridge
from .published_lists import materialize_all

logger = logging.getLogger(__name__)


def full_refresh(bridge: CalDavBridge, conn: sqlite3.Connection) -> None:
    """Materializes every published List against the current label state
    -- see module docstring. Per-List failures are isolated inside
    materialize_all, so one bad List/collection never blocks the others
    or raises out of here (this is called from main.py's startup lifespan,
    which must not fail the whole app boot over one Radicale hiccup)."""
    materialize_all(bridge=bridge, conn=conn)


def run_periodic(
    bridge: CalDavBridge,
    db_path,
    interval_seconds: int,
    stop_event: threading.Event,
) -> None:
    """Runs in a background thread (see main.py's startup hook). Opens its
    own SQLite connection -- sqlite3 connections aren't safe to share
    across threads with FastAPI's request-handling threadpool. Each tick
    calls `full_refresh`, which materializes every published List (see
    module docstring)."""
    while not stop_event.is_set():
        try:
            with db.connect(db_path) as conn:
                full_refresh(bridge, conn)
        except Exception:
            logger.exception("Background sync failed; will retry next interval")
        stop_event.wait(interval_seconds)


def start_background_sync(
    bridge: CalDavBridge, db_path, interval_seconds: int
) -> tuple[threading.Thread, threading.Event]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_periodic,
        args=(bridge, db_path, interval_seconds, stop_event),
        daemon=True,
        name="radicale-sync",
    )
    thread.start()
    return thread, stop_event
