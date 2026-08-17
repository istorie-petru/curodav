"""Holidays moved from the (now-removed) Schedule module's Table view into
Settings > Holidays (2026-08-14, routers/settings.py's "2026-08-14
follow-up" docstring note). The page was a Tasks-table-style grid with
inline editing; the 2026-08-17 settings HTML uniformity pass
(SETTINGS_UI_GUIDE.md pattern B) rebuilt it onto the grouped-list + modal
pattern the Labels list uses -- a read-only row per holiday, one Edit
button opening holiday_edit_modal.html (delete lives in that modal's
footer), and a single "+ Add holiday" toolbar button opening the same modal
empty. The old per-field inline edit (update_holiday_field +
static/settings_holidays.js) is gone, replaced by one whole-form
update_holiday endpoint. See test_holiday_calendars.py for the underlying
db.py accessor coverage and the generalized-recurrence mechanism this UI
configures; this file covers the page/routes themselves.

2026-08-15: `TestScheduleTablePageNoLongerManagesHolidays` is deleted --
the whole Schedule module it was asserting the ABSENCE of holiday CRUD
routes on is itself gone now. See plans/STATE.md's removal entry.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src import db
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
        assert 'id="holiday-list"' not in body
        assert 'href="/settings/holidays/new"' in body

    def test_lists_existing_holidays_as_rows_with_edit_buttons(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Winter break", "date_from": "2026-12-20", "date_to": "2027-01-05"})
        resp = settings_router.settings_holidays(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="holiday-list"' in body
        assert "Winter break" in body
        assert "University &middot; 2026-12-20 &rarr; 2027-01-05" in body
        assert 'href="/settings/holidays/h1/edit"' in body
        assert "data-modal" in body
        assert 'class="inline-text"' not in body
        assert 'id="holiday-table"' not in body

    def test_hub_links_to_holidays(self, conn):
        resp = settings_router.settings_index(_request("/settings"), conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/holidays"' in body
        assert "Holidays" in body


class TestHolidayEditModal:
    def test_new_modal_renders_empty_add_form(self, conn):
        resp = settings_router.new_holiday_modal(_request("/settings/holidays/new"), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Add holiday" in body
        assert 'action="/settings/holidays"' in body
        assert 'id="holiday-form"' in body
        assert 'name="calendar_name"' in body
        assert 'value="2026-12-20"' not in body

    def test_new_modal_lists_existing_calendar_names(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.new_holiday_modal(_request("/settings/holidays/new"), conn=conn)
        body = resp.body.decode()
        assert "University" in body

    def test_edit_modal_prefills_values_and_posts_to_update(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Winter break", "date_from": "2026-12-20", "date_to": "2027-01-05"})
        resp = settings_router.edit_holiday_modal("h1", _request("/settings/holidays/h1/edit"), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Edit holiday" in body
        assert 'action="/settings/holidays/h1/update"' in body
        assert 'value="Winter break"' in body
        assert 'value="2026-12-20"' in body
        assert 'value="2027-01-05"' in body
        assert 'action="/settings/holidays/h1/delete"' in body

    def test_edit_modal_404s_for_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.edit_holiday_modal("missing", _request("/settings/holidays/missing/edit"), conn=conn)
        assert exc.value.status_code == 404

    def test_modal_dates_use_shared_themed_date_picker(self, conn):
        """2026-08-17: the From/To fields were native <input type="date">s,
        which pop the browser's own unstylable calendar (its month/year
        header + Clear button can't be themed by the app's CSS) -- replaced
        with the shared picker in date mode, whose hidden inputs keep the
        exact date_from/date_to value contract the native inputs had."""
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.edit_holiday_modal("h1", _request("/settings/holidays/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'data-dtp-mode="date"' in body
        assert 'name="date_from"' in body
        assert 'name="date_to"' in body
        assert 'value="2026-09-14"' in body
        assert 'value="2026-09-16"' in body
        assert 'type="date"' not in body


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


class TestUpdateHoliday:
    def test_updates_title(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Old", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.update_holiday("h1", label="New title", calendar_name="Default", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        assert db.list_holidays(conn)[0]["label"] == "New title"

    def test_updates_dates(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="Default", date_from="2026-09-10", date_to="2026-09-16", conn=conn)
        assert db.list_holidays(conn)[0]["date_from"] == "2026-09-10"

    def test_updates_calendar_name_reassigning_the_holiday(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="University", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "University"
        assert "University" in db.list_holiday_calendar_names(conn)

    def test_blank_calendar_name_defaults_to_default(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="  ", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Default"

    def test_404s_for_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.update_holiday("missing", label="New", calendar_name="Default", date_from="2026-09-14", date_to="2026-09-16", conn=conn)
        assert exc.value.status_code == 404


class TestDeleteHoliday:
    def test_deletes_and_redirects_to_holidays_page(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.delete_holiday("h1", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        assert db.list_holidays(conn) == []