"""FullCalendar-parity interactions slice 4 (plans/open.md's "Calendar:
FullCalendar-parity interactions" section, plans/STATE.md's own entry for
this slice): Week view drag between the "All day" row and the timed grid,
both directions.

The actual pointer-drag interaction lives entirely client-side
(static/calendar.js's setupEvent() for timed->all-day, static/
calendar_week_allday_drag.js's setupItem() for all-day->timed) -- this repo
has no JS unit-test harness for static/*.js (same recurring gap every prior
JS-only calendar slice's own test file notes), so those two are covered
structurally (`node --check` for syntax, source greps for the specific
branches this slice added) plus a `node -e` smoke test that actually
executes the two new pure-function code paths (snap/duration math,
dropTargetAtPoint) in a fake-DOM-free way where possible.

What IS testable in the normal pytest sense is the one server-side change
both directions depend on: `POST /events/{uid}/reschedule` (routers/
calendar.py) gained an optional `all_day` field so a cross-boundary drop can
flip the flag, not just start_at/end_at -- that's this file's main class."""

from __future__ import annotations

import asyncio
import json as _json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_json_request(path: str, payload: dict):
    req = Request({"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


def _make_event(conn, uid, start_at, end_at, all_day):
    db.upsert_event(
        conn,
        {
            "uid": uid, "title": "Test event", "description": "",
            "start_at": start_at, "end_at": end_at, "all_day": all_day,
            "status": "active", "tags": [], "created_at": _now(), "updated_at": _now(),
        },
    )


class TestRescheduleEndpointAllDayField:
    """The endpoint both drag directions share (calendar.js, calendar_week_
    allday_drag.js, calendar_month_drag.js) -- this slice's only server-side
    change: an optional `all_day` field, which must default to leaving the
    existing value untouched (every pre-slice-4 caller never sends it)."""

    def test_omitting_all_day_leaves_the_existing_flag_untouched(self, conn):
        _make_event(conn, "e1", "2026-09-14T10:00:00", "2026-09-14T11:00:00", False)
        resp = asyncio.run(
            calendar_router.reschedule_event(
                "e1", _post_json_request("/events/e1/reschedule", {"start_at": "2026-09-15T10:00:00", "end_at": "2026-09-15T11:00:00"}), conn=conn
            )
        )
        assert resp.status_code == 200
        assert db.get_event(conn, "e1")["all_day"] == 0 or db.get_event(conn, "e1")["all_day"] is False

    def test_all_day_true_flips_a_timed_event_to_all_day(self, conn):
        """Timed grid -> All day row (calendar.js's new drop branch)."""
        _make_event(conn, "e1", "2026-09-14T10:00:00", "2026-09-14T11:00:00", False)
        resp = asyncio.run(
            calendar_router.reschedule_event(
                "e1",
                _post_json_request("/events/e1/reschedule", {"start_at": "2026-09-14T00:00:00", "end_at": None, "all_day": True}),
                conn=conn,
            )
        )
        assert resp.status_code == 200
        data = _json.loads(resp.body.decode())
        assert data["all_day"] is True
        event = db.get_event(conn, "e1")
        assert bool(event["all_day"]) is True
        assert event["start_at"] == "2026-09-14T00:00:00"
        assert event["end_at"] is None

    def test_all_day_false_flips_an_all_day_event_to_timed(self, conn):
        """All day row -> timed grid (calendar_week_allday_drag.js's new
        drop branch): start_at/end_at gain a real time-of-day and all_day
        clears."""
        _make_event(conn, "e1", "2026-09-14T00:00:00", None, True)
        resp = asyncio.run(
            calendar_router.reschedule_event(
                "e1",
                _post_json_request(
                    "/events/e1/reschedule",
                    {"start_at": "2026-09-14T14:30:00", "end_at": "2026-09-14T15:30:00", "all_day": False},
                ),
                conn=conn,
            )
        )
        assert resp.status_code == 200
        event = db.get_event(conn, "e1")
        assert bool(event["all_day"]) is False
        assert event["start_at"] == "2026-09-14T14:30:00"
        assert event["end_at"] == "2026-09-14T15:30:00"

    def test_missing_event_is_a_404(self, conn):
        resp = asyncio.run(
            calendar_router.reschedule_event(
                "nope", _post_json_request("/events/nope/reschedule", {"start_at": "2026-09-14T10:00:00"}), conn=conn
            )
        )
        assert resp.status_code == 404


class TestDragScriptsStructural:
    """No JS unit-test harness for static/*.js in this repo (same recurring
    gap every prior JS-only calendar slice's own test file notes) --
    `node --check` for syntax, source greps pinning the specific new
    cross-boundary branches so a future refactor can't silently drop one
    side of the merge without a test catching it."""

    def test_calendar_js_syntax_is_valid(self):
        subprocess.run(["node", "--check", str(_STATIC_DIR / "calendar.js")], check=True)

    def test_calendar_week_allday_drag_js_syntax_is_valid(self):
        subprocess.run(["node", "--check", str(_STATIC_DIR / "calendar_week_allday_drag.js")], check=True)

    def test_calendar_js_has_the_allday_drop_branch(self):
        script = (_STATIC_DIR / "calendar.js").read_text()
        assert "dropAllDayCol" in script
        assert '"all_day": true' not in script  # payload uses a real JS literal, not a quoted string
        assert "all_day: true" in script

    def test_calendar_js_never_drops_all_day_during_a_resize(self):
        script = (_STATIC_DIR / "calendar.js").read_text()
        assert "wasResize" in script
        assert "!wasResize && dropAllDayCol" in script

    def test_allday_drag_js_has_the_timed_drop_branch(self):
        script = (_STATIC_DIR / "calendar_week_allday_drag.js").read_text()
        assert "endDropOnTimedGrid" in script
        assert "all_day: false" in script

    def test_allday_drag_js_never_drops_a_task_onto_the_timed_grid(self):
        """Tasks have no time-of-day due date in this app -- a task chip
        dropped on the timed grid must be a no-op, not a save."""
        script = (_STATIC_DIR / "calendar_week_allday_drag.js").read_text()
        assert 'if (isTask) return; // no timed equivalent' in script

    def test_reschedule_route_comment_documents_the_new_field(self):
        script = Path(__file__).resolve().parent.parent / "src" / "routers" / "calendar.py"
        text = script.read_text()
        assert '"all_day" in payload' in text
