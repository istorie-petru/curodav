"""1.6 ("Configurable terminology", open-priority.md § Schedule &
recurrence rework) -- a Settings > General toggle between "standard" and
"playful" labels on the recurrence editor's holiday-calendar/weekend
controls. Presentation-layer only: the underlying holiday_calendar/
exclude_saturday/exclude_sunday fields never change name or meaning, only
their on-screen label. Same app_meta-backed display-preference pattern as
week_start/time_format (see test_display_prefs_settings.py, whose fixtures
this file mirrors).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db, deps
from src.routers import calendar as calendar_router
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bare_request(path="/"):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


def _request_with_app(path, db_path):
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "",
        "headers": [], "app": fake_app,
    })


class TestRecurrenceTerminologyDefault:
    def test_defaults_to_standard_without_app_scope(self):
        assert deps._recurrence_terminology(_bare_request()) == "standard"

    def test_defaults_to_standard_with_real_app_scope_and_nothing_set(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path):
            pass
        assert deps._recurrence_terminology(_request_with_app("/", db_path)) == "standard"

    def test_respects_stored_playful(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.RECURRENCE_TERMINOLOGY_KEY, "playful")
        assert deps._recurrence_terminology(_request_with_app("/", db_path)) == "playful"


class TestSettingsRoute:
    def test_renders_the_toggle(self, conn):
        resp = settings_router.settings_general(_bare_request("/settings/general"), conn=conn)
        body = resp.body.decode()
        assert 'action="/settings/recurrence-terminology"' in body
        assert resp.context["current_recurrence_terminology"] == "standard"

    def test_set_route_stores_playful(self, conn):
        resp = settings_router.set_recurrence_terminology(terminology="playful", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/general"
        assert db.get_app_meta(conn, deps.RECURRENCE_TERMINOLOGY_KEY) == "playful"

    def test_set_route_rejects_unrecognized_values(self, conn):
        settings_router.set_recurrence_terminology(terminology="silly", conn=conn)
        assert db.get_app_meta(conn, deps.RECURRENCE_TERMINOLOGY_KEY) == "standard"


class TestEventFormLabelsSwap:
    def test_standard_terminology_shows_neutral_labels(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as conn:
            resp = calendar_router.new_event_form(_request_with_app("/events/new", db_path), conn=conn)
        body = resp.body.decode()
        assert "Holiday calendar" in body
        assert "Exclude Saturday" in body
        assert "Exclude Sunday" in body
        assert "Respects Labor Laws" not in body
        assert "Marx Weekend" not in body

    def test_playful_terminology_shows_irreverent_labels(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as conn:
            db.set_app_meta(conn, deps.RECURRENCE_TERMINOLOGY_KEY, "playful")
            resp = calendar_router.new_event_form(_request_with_app("/events/new", db_path), conn=conn)
        body = resp.body.decode()
        assert "Respects Labor Laws" in body
        assert "Marx Weekend: Saturday" in body
        assert "Marx Weekend: Sunday" in body
        # Only the label changed -- the real field names underneath never do.
        assert 'name="holiday_calendar"' in body
        assert 'name="exclude_saturday"' in body
        assert 'name="exclude_sunday"' in body

    def test_playful_terminology_does_not_change_the_submitted_field_names(self, tmp_path):
        # Round-trip proof: submitting the playful-labeled form still
        # writes to the same neutral holiday_calendar/exclude_saturday/
        # exclude_sunday columns.
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as conn:
            db.set_app_meta(conn, deps.RECURRENCE_TERMINOLOGY_KEY, "playful")
            calendar_router.create_event(
                title="Class", description="", start_at="2026-09-01T10:00", end_at="",
                all_day="", location="", meeting_url="", tags="",
                recurrence="FREQ=WEEKLY;UNTIL=2026-09-22", reminders="",
                holiday_calendar="University", exclude_saturday="1", exclude_sunday="",
                conn=conn,
            )
            event = next(e for e in db.list_events(conn) if e["title"] == "Class")
        assert event["holiday_calendar"] == "University"
        assert event["exclude_saturday"]


class TestScheduleSettingsLabelsSwap:
    def test_schedule_settings_page_respects_the_toggle(self, tmp_path):
        from src.routers import schedule as schedule_router

        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as conn:
            db.set_app_meta(conn, deps.RECURRENCE_TERMINOLOGY_KEY, "playful")
            resp = schedule_router.classes_view(_request_with_app("/schedule", db_path), conn=conn)
        body = resp.body.decode()
        assert "Respects Labor Laws" in body
        assert 'name="holiday_calendar"' in body
