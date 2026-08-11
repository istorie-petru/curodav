"""Regression test for a real bug found 2026-08-07 while reworking Month
view's multi-day bars: every calendar template (Month/Week/Day/Agenda)
has always read `e.calendar_color` to color-code events
(`cal-{{ e.calendar_color }}`), but nothing in db.py ever set that key --
it's been silently undefined (rendering as `cal-`, no color) on every
event, on every calendar view, since the label-space rework removed the
old per-calendar color concept. See routers/calendar.py's
`_annotate_calendar_colors` docstring for the fix: an event's color is
its first (alphabetical) label's own color, falling back to a neutral
default for an unlabeled event."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import calendar as calendar_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_event(conn, uid, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": "active",
        "all_day": 0, "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return uid


class TestAnnotateCalendarColors:
    def test_unlabeled_event_gets_the_default_color(self, conn):
        _make_event(conn, "e1")
        events = [db.get_event(conn, "e1")]
        result = calendar_router._annotate_calendar_colors(conn, events)
        assert result[0]["calendar_color"] == calendar_router._DEFAULT_EVENT_COLOR

    def test_labeled_event_uses_its_labels_color(self, conn):
        db.upsert_label_config(conn, {"name": "Work", "color": "purple", "created_at": _now()})
        _make_event(conn, "e1", tags=["Work"])
        events = [db.get_event(conn, "e1")]
        result = calendar_router._annotate_calendar_colors(conn, events)
        assert result[0]["calendar_color"] == "purple"

    def test_multiple_labels_picks_alphabetically_first(self, conn):
        db.upsert_label_config(conn, {"name": "Alpha", "color": "green", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Zeta", "color": "red", "created_at": _now()})
        _make_event(conn, "e1", tags=["Zeta", "Alpha"])
        events = [db.get_event(conn, "e1")]
        result = calendar_router._annotate_calendar_colors(conn, events)
        assert result[0]["calendar_color"] == "green"

    def test_label_with_no_config_row_defaults_to_blue(self, conn):
        # A label that's only ever been applied (object_labels) but never
        # explicitly configured (no label_config row) still has an
        # effective color -- 'blue', same default label_config's own
        # column DEFAULT uses, via effective_label_config.
        _make_event(conn, "e1", tags=["Unconfigured"])
        events = [db.get_event(conn, "e1")]
        result = calendar_router._annotate_calendar_colors(conn, events)
        assert result[0]["calendar_color"] == "blue"

    def test_month_view_events_carry_a_real_color(self, conn):
        from starlette.requests import Request

        db.upsert_label_config(conn, {"name": "Work", "color": "orange", "created_at": _now()})
        _make_event(conn, "e1", start_at="2026-08-10T09:00:00", tags=["Work"])
        req = Request({"type": "http", "method": "GET", "path": "/calendar", "query_string": b"", "headers": []})
        resp = calendar_router.month_view(req, year=2026, month=8, conn=conn)
        body = resp.body.decode()
        assert 'cal-orange' in body
        assert 'cal-"' not in body  # never an empty color suffix
