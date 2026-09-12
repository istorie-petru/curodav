"""1.6 ("Generalized recurrence and the non-working-day policy") -- router-
level coverage on top of test_recurrence_expand.py's pure-logic tests.
Covers: named holiday calendars round-tripping through db.py, and an
ordinary Calendar event's holiday_calendar/exclude_saturday/exclude_sunday
fields surviving create/update.

2026-08-15: `TestScheduleUsesTheGeneralizedMechanism` (Schedule's own class
events picking up schedule_settings' holiday_calendar) removed along with
the whole Schedule module -- see plans/STATE.md's removal entry.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

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


class TestHolidayCalendarAccessors:
    def test_holidays_default_to_the_default_calendar(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        holidays = db.list_holidays(conn)
        assert holidays[0]["calendar_name"] == "Default"

    def test_holidays_scoped_by_explicit_calendar_name(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"})
        db.upsert_holiday(conn, {"uid": "h2", "calendar_name": "Romania", "label": "National day", "date_from": "2026-12-01", "date_to": "2026-12-01"})
        assert [h["uid"] for h in db.list_holidays(conn, calendar_name="University")] == ["h1"]
        assert [h["uid"] for h in db.list_holidays(conn, calendar_name="Romania")] == ["h2"]

    def test_list_holiday_calendar_names_is_distinct_and_sorted(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "date_from": "2026-09-01", "date_to": "2026-09-01"})
        db.upsert_holiday(conn, {"uid": "h2", "calendar_name": "Romania", "date_from": "2026-09-01", "date_to": "2026-09-01"})
        db.upsert_holiday(conn, {"uid": "h3", "calendar_name": "Romania", "date_from": "2026-10-01", "date_to": "2026-10-01"})
        assert db.list_holiday_calendar_names(conn) == ["Romania", "University"]

    def test_list_holidays_by_calendar_groups_correctly(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "date_from": "2026-09-01", "date_to": "2026-09-01"})
        db.upsert_holiday(conn, {"uid": "h2", "calendar_name": "Romania", "date_from": "2026-10-01", "date_to": "2026-10-01"})
        by_cal = db.list_holidays_by_calendar(conn)
        assert set(by_cal) == {"University", "Romania"}
        assert by_cal["University"][0]["uid"] == "h1"


class TestYearAgnosticHolidayDates:
    """audit-fixes-2.1.md ("only day hollydays, withot the year") -- the
    db.py helpers behind the Holiday modal's "Repeats every year"
    checkbox. Stores the same "--MM-DD" convention Contacts' year-less
    Birthday already uses (see parse_contact_birthday), so no schema
    change -- date_from/date_to stay plain TEXT."""

    def test_parse_holiday_date_strips_the_year_when_year_agnostic(self):
        assert db.parse_holiday_date("2026-12-25", year_agnostic=True) == "--12-25"

    def test_parse_holiday_date_keeps_a_full_date_when_not_year_agnostic(self):
        assert db.parse_holiday_date("2026-12-25", year_agnostic=False) == "2026-12-25"

    def test_parse_holiday_date_accepts_an_already_yearless_value_round_tripping(self):
        assert db.parse_holiday_date("--12-25", year_agnostic=True) == "--12-25"

    def test_parse_holiday_date_rejects_a_yearless_value_when_not_year_agnostic(self):
        with pytest.raises(ValueError):
            db.parse_holiday_date("--12-25", year_agnostic=False)

    def test_parse_holiday_date_allows_feb_29_via_the_leap_year_placeholder(self):
        assert db.parse_holiday_date("2028-02-29", year_agnostic=True) == "--02-29"

    def test_parse_holiday_date_rejects_an_invalid_date(self):
        with pytest.raises(ValueError):
            db.parse_holiday_date("2026-13-40", year_agnostic=False)

    def test_is_year_agnostic_holiday_date(self):
        assert db.is_year_agnostic_holiday_date("--12-25")
        assert not db.is_year_agnostic_holiday_date("2026-12-25")
        assert not db.is_year_agnostic_holiday_date("")
        assert not db.is_year_agnostic_holiday_date(None)

    def test_holiday_date_picker_value_anchors_a_yearless_date_to_a_placeholder_year(self):
        assert db.holiday_date_picker_value("--12-25") == "2000-12-25"
        assert db.holiday_date_picker_value("2026-12-25") == "2026-12-25"

    def test_format_holiday_date_drops_the_year(self):
        assert db.format_holiday_date("--12-25") == "25 Dec"

    def test_upsert_and_round_trip_a_year_agnostic_holiday(self, conn):
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "National", "label": "Christmas", "date_from": "--12-25", "date_to": "--12-25"})
        holiday = db.get_holiday(conn, "h1")
        assert holiday["date_from"] == "--12-25"
        assert holiday["date_to"] == "--12-25"
        assert db.is_year_agnostic_holiday_date(holiday["date_from"])


class TestOrdinaryEventHolidayPolicy:
    """Any recurring Calendar event -- not just a Schedule class -- can
    set holiday_calendar/exclude_saturday/exclude_sunday via the same
    create_event/update_event routes; this is the "generalized" half of
    the rework."""

    def test_create_event_persists_the_policy_fields(self, conn):
        calendar_router.create_event(
            title="Standup", description="", start_at="2026-09-01T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=DAILY;UNTIL=2026-09-10", reminders="",
            holiday_calendar="University", exclude_saturday="1", exclude_sunday="1",
            conn=conn,
        )
        event = next(e for e in db.list_events(conn) if e["title"] == "Standup")
        assert event["holiday_calendar"] == "University"
        assert event["exclude_saturday"] is True or event["exclude_saturday"] == 1
        assert event["exclude_sunday"] is True or event["exclude_sunday"] == 1

    def test_omitting_the_policy_fields_defaults_to_no_exclusion(self, conn):
        calendar_router.create_event(
            title="One-off", description="", start_at="2026-09-01T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="", recurrence="", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        event = next(e for e in db.list_events(conn) if e["title"] == "One-off")
        assert event["holiday_calendar"] is None
        assert not event["exclude_saturday"]
        assert not event["exclude_sunday"]

    def test_update_event_can_change_the_policy(self, conn):
        calendar_router.create_event(
            title="Weekly sync", description="", start_at="2026-09-01T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=WEEKLY;UNTIL=2026-10-01", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        event = next(e for e in db.list_events(conn) if e["title"] == "Weekly sync")
        calendar_router.update_event(
            event["uid"], title="Weekly sync", description="", start_at="2026-09-01T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=WEEKLY;UNTIL=2026-10-01", reminders="",
            holiday_calendar="Romania", exclude_saturday="1", exclude_sunday="",
            conn=conn,
        )
        updated = db.get_event(conn, event["uid"])
        assert updated["holiday_calendar"] == "Romania"
        assert updated["exclude_saturday"]
        assert not updated["exclude_sunday"]

    def test_week_view_actually_excludes_the_holiday_occurrence(self, conn):
        # End-to-end: the event references a calendar with a holiday
        # inside the visible window -- week_view must not render that
        # occurrence, via db.list_holidays_by_calendar wired into
        # recurrence_expand.expand_events.
        db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "University", "label": "Break", "date_from": "2026-09-08", "date_to": "2026-09-08"})
        calendar_router.create_event(
            title="Class", description="", start_at="2026-09-01T10:00", end_at="2026-09-01T11:00",
            all_day="", location="", meeting_url="", tags="",
            recurrence="FREQ=WEEKLY;UNTIL=2026-09-22", reminders="",
            holiday_calendar="University", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        from starlette.requests import Request

        def _req(path):
            return Request({
                "type": "http", "method": "GET", "path": path, "query_string": b"",
                "scheme": "http", "server": ("t", 80), "root_path": "", "headers": [],
            })

        resp = calendar_router.week_view(_req("/calendar/week"), date_="2026-09-07", conn=conn)
        # Sep 7-13 is the visible week; the only occurrence in it (Sep 8)
        # is the excluded holiday -- so the event must not appear at all.
        body = resp.body.decode()
        assert "Class" not in body
