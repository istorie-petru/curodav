"""Holidays moved from Schedule's Table view into Settings > Holidays
(2026-08-14, routers/settings.py's "2026-08-14 follow-up" docstring note)
-- a Tasks-table-style grid (title/calendar/start/end columns, inline
editing) replacing the old compact add-form-plus-plain-table pair that
lived inside schedule_classes.html. See test_holiday_calendars.py for the
underlying db.py accessor coverage and the generalized-recurrence
mechanism this UI configures; this file covers the page/routes themselves.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src import db
from src.routers import schedule as schedule_router
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _request(path="/settings/holidays"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [],
        }
    )


class TestSettingsHolidaysPage:
    def test_renders_with_breadcrumb_and_active_tab(self, conn):
        resp = settings_router.settings_holidays(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_holidays"
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]
        body = resp.body.decode()
        assert 'href="/settings"' in body

    def test_empty_state_when_no_holidays(self, conn):
        resp = settings_router.settings_holidays(_request(), conn=conn)
        body = resp.body.decode()
        assert "No holidays configured yet" in body
        assert 'id="holiday-table"' not in body

    def test_lists_existing_holidays_as_a_table(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Winter break", "date_from": "2026-12-20", "date_to": "2027-01-05"})
        resp = settings_router.settings_holidays(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="holiday-table"' in body
        assert "Winter break" in body
        assert 'value="2026-12-20"' in body
        assert 'value="2027-01-05"' in body

    def test_hub_links_to_holidays(self, conn):
        resp = settings_router.settings_index(_request("/settings"), conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/holidays"' in body
        assert "Holidays" in body


class TestCreateHoliday:
    def test_creates_and_redirects_to_holidays_page(self, conn):
        resp = settings_router.create_holiday(calendar_name="University", label="Break", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        holidays = db.list_holidays(conn)
        assert len(holidays) == 1
        assert holidays[0]["calendar_name"] == "University"

    def test_blank_calendar_name_defaults_to_default(self, conn):
        settings_router.create_holiday(calendar_name="  ", label="Break", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Default"


class TestUpdateHolidayField:
    def test_updates_title(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Old", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        import asyncio

        async def _call():
            req = _FakeJsonRequest({"field": "label", "value": "New title"})
            return await settings_router.update_holiday_field("h1", req, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 200
        assert db.list_holidays(conn)[0]["label"] == "New title"

    def test_updates_dates(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        import asyncio

        async def _call():
            req = _FakeJsonRequest({"field": "date_from", "value": "2026-09-10"})
            return await settings_router.update_holiday_field("h1", req, conn=conn)

        asyncio.run(_call())
        assert db.list_holidays(conn)[0]["date_from"] == "2026-09-10"

    def test_updates_calendar_name_reassigning_the_holiday(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        import asyncio

        async def _call():
            req = _FakeJsonRequest({"field": "calendar_name", "value": "University"})
            return await settings_router.update_holiday_field("h1", req, conn=conn)

        asyncio.run(_call())
        assert db.list_holidays(conn)[0]["calendar_name"] == "University"
        assert "University" in db.list_holiday_calendar_names(conn)

    def test_rejects_a_non_allowlisted_field(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        import asyncio

        async def _call():
            req = _FakeJsonRequest({"field": "uid", "value": "h2"})
            return await settings_router.update_holiday_field("h1", req, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 400

    def test_404s_for_unknown_uid(self, conn):
        import asyncio

        async def _call():
            req = _FakeJsonRequest({"field": "label", "value": "New"})
            return await settings_router.update_holiday_field("missing", req, conn=conn)

        resp = asyncio.run(_call())
        assert resp.status_code == 404


class TestDeleteHoliday:
    def test_deletes_and_redirects_to_holidays_page(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.delete_holiday("h1", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        assert db.list_holidays(conn) == []


class TestScheduleTablePageNoLongerManagesHolidays:
    """The old inline add-form/table pair is gone from
    schedule_classes.html; the Settings panel keeps the `holiday_calendar`
    picker (which named calendar the semester's classes respect) and links
    out to /settings/holidays for managing the calendars' own contents."""

    def test_schedule_module_has_no_holiday_crud_routes(self):
        assert not hasattr(schedule_router, "create_holiday")
        assert not hasattr(schedule_router, "delete_holiday")

    def test_classes_view_links_to_settings_holidays(self, conn):
        req = _request("/schedule")
        resp = schedule_router.classes_view(req, conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/holidays"' in body
        assert 'action="/schedule/holidays"' not in body

    def test_classes_view_still_passes_calendar_names_for_the_datalist(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        req = _request("/schedule")
        resp = schedule_router.classes_view(req, conn=conn)
        assert resp.context["holiday_calendar_names"] == ["University"]
        assert "holidays" not in resp.context


class _FakeJsonRequest:
    """Minimal stand-in for starlette.Request's `.json()` -- the update-
    field routes only ever call that one awaitable method."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload
