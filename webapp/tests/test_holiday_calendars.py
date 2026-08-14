"""1.6 ("Generalized recurrence and the non-working-day policy") -- router-
level coverage on top of test_recurrence_expand.py's pure-logic tests and
test_schedule.py's build_class_event_row tests. Covers: named holiday
calendars round-tripping through db.py, an ordinary Calendar event's
holiday_calendar/exclude_saturday/exclude_sunday fields surviving create/
update, and Schedule's class events picking up schedule_settings'
holiday_calendar (replacing the old per-write EXDATE-stuffing) so a holiday
add/delete takes effect without touching any event row.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src import db
from src.routers import calendar as calendar_router
from src.routers import schedule as schedule_router


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


class TestScheduleUsesTheGeneralizedMechanism:
    """Schedule's own class events stop computing a static per-holiday
    EXDATE at write time -- they just carry schedule_settings'
    holiday_calendar, applied generically at read time."""

    def test_new_class_event_carries_the_configured_holiday_calendar(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-12-20", "holiday_calendar": "University"})
        schedule_router.create_class(
            day="Tuesday", start_time="10:00", end_time="12:00", name="Algorithms",
            acronym="", class_type_select="", class_type_other="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="on", project_uid="", conn=conn,
        )
        event = db.list_schedule_class_events(conn)[0]
        assert event["holiday_calendar"] == "University"

    def test_adding_a_holiday_excludes_the_occurrence_without_regenerating(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-09-22", "holiday_calendar": "University"})
        schedule_router.create_class(
            day="Tuesday", start_time="10:00", end_time="12:00", name="Algorithms",
            acronym="", class_type_select="", class_type_other="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="on", project_uid="", conn=conn,
        )
        event_before = db.list_schedule_class_events(conn)[0]

        schedule_router.create_holiday(calendar_name="University", label="Break", date_from="2026-09-14", date_to="2026-09-16", conn=conn)

        # The event row itself is untouched (no _regenerate_all call
        # anymore) -- same recurrence/exdates as before the holiday.
        event_after = db.list_schedule_class_events(conn)[0]
        assert event_after["recurrence"] == event_before["recurrence"]
        assert event_after["exdates"] == event_before["exdates"]

        # But the exclusion is real at read time.
        from src import recurrence_expand

        expanded = recurrence_expand.expand_events(
            [event_after], date(2026, 9, 1), date(2026, 9, 30), db.list_holidays_by_calendar(conn)
        )
        starts = {e["start_at"] for e in expanded}
        assert "2026-09-15T10:00:00" not in starts

    def test_renaming_the_settings_holiday_calendar_regenerates_class_events(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-12-20", "holiday_calendar": "Default"})
        schedule_router.create_class(
            day="Tuesday", start_time="10:00", end_time="12:00", name="Algorithms",
            acronym="", class_type_select="", class_type_other="", professor_select="", professor_new="",
            room="", credits="0", parity="all", enrolled="on", project_uid="", conn=conn,
        )
        schedule_router.save_settings(
            semester_start="2026-09-01", semester_end="2026-12-20", credits_needed="",
            reminder_minutes="15", schedule_label="Schedule", holiday_calendar="University",
            conn=conn,
        )
        event = db.list_schedule_class_events(conn)[0]
        assert event["holiday_calendar"] == "University"
