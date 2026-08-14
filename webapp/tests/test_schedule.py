"""Unit tests for schedule.py's recurrence/exdate/conflict logic -- no
network needed. 1.6 (Schedule & recurrence rework) replaced class_to_
event_row (schedule_classes row -> mirrored VEVENT) with build_class_
event_row (day/time/parity/title/room fields -> the class meeting's own
real recurring event -- there's no separate class entity anymore, see
schedule.py's module docstring). Router-level behavior (a class event's
course label, label_config course_* fields, tag wiring) is exercised in
test_schedule_router.py instead of here.
"""

from __future__ import annotations

from datetime import date

from src.schedule import (
    build_class_event_row,
    compute_conflicts,
    event_day,
    event_parity,
    first_occurrence,
    iso_week_parity,
    next_label,
    next_occurrence_for_event,
)


class TestFirstOccurrence:
    def test_all_week_anchors_on_first_matching_weekday(self):
        # 2026-09-01 is a Tuesday (ISO week 36, even)
        start = date(2026, 9, 1)
        assert first_occurrence(start, "Tuesday", "all") == date(2026, 9, 1)

    def test_even_week_matches_immediately_when_already_even(self):
        start = date(2026, 9, 1)  # week 36, even
        assert first_occurrence(start, "Tuesday", "even") == date(2026, 9, 1)

    def test_odd_week_shifts_forward_a_week_when_start_is_even(self):
        start = date(2026, 9, 1)  # week 36, even
        anchor = first_occurrence(start, "Tuesday", "odd")
        assert anchor == date(2026, 9, 8)
        assert iso_week_parity(anchor) == "odd"


class TestBuildClassEventRow:
    BASE_FIELDS = {
        "uid": "c1",
        "day": "Tuesday",
        "start_time": "10:00",
        "end_time": "12:00",
        "title": "Algorithms",
        "room": "204",
        "parity": "all",
        "enrolled": True,
    }

    def test_no_semester_dates_still_returns_a_row_anchored_on_today(self):
        # 1.6: there's no separate schedule_classes row anymore, so a class
        # entered before semester dates are configured still needs
        # somewhere to live -- an open-ended (no UNTIL), today-anchored
        # event rather than None.
        row = build_class_event_row(self.BASE_FIELDS, {}, today=date(2026, 9, 1))
        assert row["uid"] == "c1"
        assert row["start_at"] == "2026-09-01T10:00:00"
        assert "UNTIL" not in row["recurrence"]
        assert row["exdates"] == []

    def test_builds_row_with_rrule(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-22"}
        row = build_class_event_row(self.BASE_FIELDS, settings)

        assert row["uid"] == "c1"
        assert row["start_at"] == "2026-09-01T10:00:00"
        assert row["end_at"] == "2026-09-01T12:00:00"
        assert row["location"] == "204"
        assert row["title"] == "Algorithms"
        assert row["exdates"] == []
        assert row["recurrence"] == "FREQ=WEEKLY;UNTIL=2026-09-22"

    def test_holiday_calendar_is_copied_from_settings(self):
        # 1.6: holiday exclusion is no longer computed here at all -- the
        # event just carries which named calendar it should respect,
        # applied generically at read time (recurrence_expand.expand_events).
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-22", "holiday_calendar": "University"}
        row = build_class_event_row(self.BASE_FIELDS, settings)
        assert row["holiday_calendar"] == "University"

    def test_odd_even_parity_adds_interval(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-12-20"}
        row = build_class_event_row(dict(self.BASE_FIELDS, parity="odd"), settings)
        assert "INTERVAL=2" in row["recurrence"]

    def test_disenrolled_class_maps_to_archived_status(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-12-20"}
        row = build_class_event_row(dict(self.BASE_FIELDS, enrolled=False), settings)
        assert row["status"] == "archived"

    def test_semester_too_short_for_parity_excludes_the_only_occurrence(self):
        # Semester ends before the first 'odd'-parity Tuesday would land --
        # the meeting itself still exists (editable/reschedulable), just
        # with its one placeholder occurrence excluded outright.
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-02"}
        row = build_class_event_row(dict(self.BASE_FIELDS, parity="odd"), settings)
        assert row["start_at"] in row["exdates"]


class TestDeriveDayAndParity:
    def test_event_day_reads_start_at_weekday(self):
        event = {"start_at": "2026-09-01T10:00:00"}  # Tuesday
        assert event_day(event) == "Tuesday"

    def test_event_day_none_without_start_at(self):
        assert event_day({}) is None

    def test_event_parity_all_for_plain_weekly_rule(self):
        event = {"start_at": "2026-09-01T10:00:00", "recurrence": "FREQ=WEEKLY;UNTIL=2026-12-01"}
        assert event_parity(event) == "all"

    def test_event_parity_derived_from_interval_and_anchor_week(self):
        # 2026-09-01 is ISO week 36 (even)
        event = {"start_at": "2026-09-01T10:00:00", "recurrence": "FREQ=WEEKLY;INTERVAL=2;UNTIL=2026-12-01"}
        assert event_parity(event) == "even"


class TestNextOccurrenceForEvent:
    def test_finds_next_occurrence_honoring_rrule_and_exdate(self):
        event = {
            "uid": "c1",
            "title": "Algorithms",
            "description": "",
            "start_at": "2026-09-01T10:00:00",
            "end_at": "2026-09-01T12:00:00",
            "all_day": False,
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22",
            "exdates": ["2026-09-08T10:00:00"],
        }
        nxt = next_occurrence_for_event(event, today=date(2026, 9, 2))
        assert nxt == date(2026, 9, 15)  # 9/8 excluded

    def test_none_past_the_last_occurrence(self):
        event = {
            "uid": "c1",
            "title": "Algorithms",
            "description": "",
            "start_at": "2026-09-01T10:00:00",
            "end_at": "2026-09-01T12:00:00",
            "all_day": False,
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-01",
            "exdates": [],
        }
        assert next_occurrence_for_event(event, today=date(2026, 9, 2)) is None


class TestNextLabel:
    def test_today_tomorrow_and_relative(self):
        today = date(2026, 9, 1)
        assert next_label(date(2026, 9, 1), today) == "today"
        assert next_label(date(2026, 9, 2), today) == "tomorrow"
        assert next_label(date(2026, 9, 5), today) == "in 4 days"


class TestConflicts:
    def _event(self, uid, day="Tuesday", start="10:00", end="12:00", parity="all", status="active"):
        anchor = {"Monday": "08-31", "Tuesday": "09-01"}.get(day, "09-01")
        return {
            "uid": uid,
            "title": uid,
            "description": "",
            "start_at": f"2026-{anchor}T{start}:00",
            "end_at": f"2026-{anchor}T{end}:00",
            "all_day": False,
            "status": status,
            "recurrence": "FREQ=WEEKLY" if parity == "all" else "FREQ=WEEKLY;INTERVAL=2",
            "exdates": [],
        }

    def test_overlapping_same_parity_conflicts(self):
        a = self._event("a", start="10:00", end="12:00")
        b = self._event("b", start="11:00", end="13:00")
        assert len(compute_conflicts([a, b])) == 1

    def test_non_overlapping_times_no_conflict(self):
        a = self._event("a", start="10:00", end="12:00")
        b = self._event("b", start="12:00", end="14:00")
        assert compute_conflicts([a, b]) == []

    def test_different_days_no_conflict(self):
        a = self._event("a", day="Monday")
        b = self._event("b", day="Tuesday")
        assert compute_conflicts([a, b]) == []

    def test_disenrolled_classes_excluded_from_conflicts(self):
        a = self._event("a", status="archived")
        b = self._event("b")
        assert compute_conflicts([a, b]) == []
