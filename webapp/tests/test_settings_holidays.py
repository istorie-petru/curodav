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
        assert 'id="holidays-table"' in body
        assert 'href="/settings/holidays/new"' in body

    def test_lists_existing_holidays_as_rows_with_edit_buttons(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Winter break", "date_from": "2026-12-20", "date_to": "2027-01-05"})
        resp = settings_router.settings_holidays(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="holidays-table"' in body
        assert "Winter break" in body
        assert "University" in body
        assert "20 Dec" in body
        assert "5 Jan 2027" in body
        assert 'href="/settings/holidays/h1/edit"' in body
        assert "data-modal" in body
        assert 'class="inline-text"' not in body

    def test_lists_a_year_agnostic_holiday_without_a_year(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "National", "label": "Christmas", "date_from": "--12-25", "date_to": "--12-25"})
        resp = settings_router.settings_holidays(_request(), conn=conn)
        body = resp.body.decode()
        assert "25 Dec" in body
        assert "--12-25" not in body

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
        # audit-fixes-2.1.md fix: the Calendar picker's free-text "new"
        # input is named calendar_name_new in single mode (see
        # _widget_list_multiselect.html's ms_allow_new docstring) --
        # distinct from the radios' own calendar_name, so a bare
        # "calendar_name" match doesn't apply here when no calendars
        # exist yet (no radios at all, only this text input).
        assert 'name="calendar_name_new"' in body
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


class TestHolidayEditModalYearAgnostic:
    """audit-fixes-2.1.md ("only day hollydays, withot the year") --
    edit_holiday_modal feeding a year-agnostic holiday's stored "--MM-DD"
    back into the shared (year-requiring) date picker."""

    def test_new_modal_has_the_repeats_every_year_checkbox_unchecked(self, conn):
        resp = settings_router.new_holiday_modal(_request("/settings/holidays/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="year_agnostic"' in body
        assert 'id="year_agnostic" name="year_agnostic" value="1" checked' not in body

    def test_edit_modal_prefills_placeholder_year_and_checks_the_box(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "National", "label": "Christmas", "date_from": "--12-25", "date_to": "--12-25"})
        resp = settings_router.edit_holiday_modal("h1", _request("/settings/holidays/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'value="2000-12-25"' in body
        assert 'id="year_agnostic" name="year_agnostic" value="1" checked' in body

    def test_edit_modal_leaves_the_checkbox_unchecked_for_an_ordinary_holiday(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.edit_holiday_modal("h1", _request("/settings/holidays/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'id="year_agnostic" name="year_agnostic" value="1" checked' not in body


class TestHolidayCalendarNameResolution:
    """audit-fixes-2.1.md ("not allowed to add more holidays to the same
    calendar, defaults to Default"): _widget_list_multiselect.html's
    single-mode Calendar picker submits a checked radio's value under
    `calendar_name` and the free-text "new" input's value under the
    distinct `calendar_name_new` (see that partial's own docstring) --
    routers/settings.py's `_resolve_calendar_name` combines them. Before
    the fix, both shared one name and the always-present, always-blank
    text input silently won over a picked radio via Starlette's
    last-value-wins scalar Form parsing -- this reproduces the exact
    reported symptom (pick an *existing* calendar, still get Default) at
    the router level."""

    def test_picking_an_existing_calendar_keeps_it_not_default(self, conn):
        # Simulates the real bug: a radio for the already-used "Romania"
        # calendar is checked (calendar_name="Romania"), and the
        # always-present free-text field is untouched/blank
        # (calendar_name_new="") -- must NOT fall back to Default.
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Romania", "label": "Existing", "date_from": "2026-01-01", "date_to": "2026-01-01"})
        settings_router.create_holiday(calendar_name="Romania", calendar_name_new="", label="Second one", date_from="2026-09-14", date_to="2026-09-16", year_agnostic="", conn=conn)
        romania_holidays = db.list_holidays(conn, calendar_name="Romania")
        assert len(romania_holidays) == 2
        assert {h["label"] for h in romania_holidays} == {"Existing", "Second one"}

    def test_typed_new_calendar_name_wins_over_a_stale_checked_radio(self, conn):
        # A radio may still be "checked" (whichever the picker defaults
        # to) even while the user is typing a brand-new name -- the typed
        # value must win since typing is always a deliberate choice.
        settings_router.create_holiday(calendar_name="Default", calendar_name_new="Bulgaria", label="New", date_from="2026-09-14", date_to="2026-09-16", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Bulgaria"

    def test_blank_new_field_falls_back_to_the_picked_radio(self, conn):
        settings_router.create_holiday(calendar_name="University", calendar_name_new="   ", label="Break", date_from="2026-09-14", date_to="2026-09-16", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "University"

    def test_both_blank_falls_back_to_default(self, conn):
        settings_router.create_holiday(calendar_name="  ", calendar_name_new="  ", label="Break", date_from="2026-09-14", date_to="2026-09-16", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Default"

    def test_update_holiday_also_keeps_an_existing_picked_calendar(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Romania", "label": "First", "date_from": "2026-01-01", "date_to": "2026-01-01"})
        db.upsert_holiday(conn, {"uid": "h2", "calendar_name": "Default", "label": "Other", "date_from": "2026-02-01", "date_to": "2026-02-01"})
        settings_router.update_holiday("h2", label="Other", calendar_name="Romania", calendar_name_new="", date_from="2026-02-01", date_to="2026-02-01", year_agnostic="", conn=conn)
        assert db.get_holiday(conn, "h2")["calendar_name"] == "Romania"
        assert len(db.list_holidays(conn, calendar_name="Romania")) == 2

    def test_new_holiday_modal_and_create_holiday_field_names_match(self, conn):
        """The rendered form field name and the router's Form parameter
        name must agree, or this whole fix is inert -- guards against the
        template and router drifting apart."""
        resp = settings_router.new_holiday_modal(_request("/settings/holidays/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="calendar_name_new"' in body
        import inspect

        params = inspect.signature(settings_router.create_holiday).parameters
        assert "calendar_name_new" in params
        assert "calendar_name" in params


class TestCreateHoliday:
    def test_creates_and_redirects_to_holidays_page(self, conn):
        resp = settings_router.create_holiday(calendar_name="University", label="Break", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        holidays = db.list_holidays(conn)
        assert len(holidays) == 1
        assert holidays[0]["calendar_name"] == "University"

    def test_blank_calendar_name_defaults_to_default(self, conn):
        settings_router.create_holiday(calendar_name="  ", label="Break", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Default"

    def test_year_agnostic_checkbox_stores_a_yearless_date(self, conn):
        settings_router.create_holiday(calendar_name="National", label="Christmas", date_from="2026-12-25", date_to="2026-12-25", calendar_name_new="", year_agnostic="1", conn=conn)
        holiday = db.list_holidays(conn)[0]
        assert holiday["date_from"] == "--12-25"
        assert holiday["date_to"] == "--12-25"

    def test_omitting_year_agnostic_keeps_the_full_date(self, conn):
        settings_router.create_holiday(calendar_name="University", label="Break", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        holiday = db.list_holidays(conn)[0]
        assert holiday["date_from"] == "2026-09-14"

    def test_invalid_date_raises_400(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.create_holiday(calendar_name="Default", label="Bad", date_from="not-a-date", date_to="not-a-date", calendar_name_new="", year_agnostic="", conn=conn)
        assert exc.value.status_code == 400


class TestUpdateHoliday:
    def test_updates_title(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Old", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.update_holiday("h1", label="New title", calendar_name="Default", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        assert db.list_holidays(conn)[0]["label"] == "New title"

    def test_updates_dates(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="Default", date_from="2026-09-10", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["date_from"] == "2026-09-10"

    def test_updates_calendar_name_reassigning_the_holiday(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="University", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "University"
        assert "University" in db.list_holiday_calendar_names(conn)

    def test_blank_calendar_name_defaults_to_default(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        settings_router.update_holiday("h1", label="Break", calendar_name="  ", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert db.list_holidays(conn)[0]["calendar_name"] == "Default"

    def test_404s_for_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.update_holiday("missing", label="New", calendar_name="Default", date_from="2026-09-14", date_to="2026-09-16", calendar_name_new="", year_agnostic="", conn=conn)
        assert exc.value.status_code == 404

    def test_checking_year_agnostic_converts_an_ordinary_holiday_to_yearless(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "National", "label": "Christmas", "date_from": "2026-12-25", "date_to": "2026-12-25"})
        settings_router.update_holiday("h1", label="Christmas", calendar_name="National", date_from="2026-12-25", date_to="2026-12-25", calendar_name_new="", year_agnostic="1", conn=conn)
        assert db.list_holidays(conn)[0]["date_from"] == "--12-25"

    def test_resubmitting_a_year_agnostic_holiday_unchanged_stays_yearless(self, conn):
        # The edit form's picker shows the placeholder-year value
        # (holiday_date_picker_value) -- re-saving without touching the
        # dates must still come back out as "--MM-DD", not the placeholder
        # year, as long as the checkbox stays checked.
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "National", "label": "Christmas", "date_from": "--12-25", "date_to": "--12-25"})
        placeholder = db.holiday_date_picker_value("--12-25")
        settings_router.update_holiday("h1", label="Christmas", calendar_name="National", date_from=placeholder, date_to=placeholder, calendar_name_new="", year_agnostic="1", conn=conn)
        assert db.list_holidays(conn)[0]["date_from"] == "--12-25"


class TestDeleteHoliday:
    def test_deletes_and_redirects_to_holidays_page(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Default", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        resp = settings_router.delete_holiday("h1", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/holidays"
        assert db.list_holidays(conn) == []