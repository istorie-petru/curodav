"""Unit tests for schedule.py's recurrence/exdate/conflict logic -- no
network needed. See test_caldav_bridge_live.py for the pattern used to
test the live Radicale integration side; the Schedule feature's live path
(class -> mirrored VEVENT -> Radicale) is exercised manually in the
smoke test described in the PR/commit notes, not duplicated here since
routers/schedule.py's `_regenerate_class_event` is a thin wrapper around
already-tested `class_to_event_row` + already-tested `caldav_bridge`.
"""

from __future__ import annotations

from datetime import date

from src.schedule import (
    class_to_event_row,
    compute_conflicts,
    compute_excluded,
    credits_summary,
    first_occurrence,
    generate_occurrences,
    iso_week_parity,
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


class TestGenerateOccurrences:
    def test_all_week_steps_by_one_week(self):
        occs = generate_occurrences(date(2026, 9, 1), date(2026, 9, 22), "all")
        assert occs == [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]

    def test_parity_week_steps_by_two_weeks(self):
        occs = generate_occurrences(date(2026, 9, 8), date(2026, 10, 1), "odd")
        assert occs == [date(2026, 9, 8), date(2026, 9, 22)]


class TestComputeExcluded:
    def test_holiday_range_excludes_occurrences_inside_it(self):
        occs = [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15)]
        holidays = [{"label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"}]
        assert compute_excluded(occs, holidays) == [date(2026, 9, 15)]

    def test_no_holidays_excludes_nothing(self):
        occs = [date(2026, 9, 1), date(2026, 9, 8)]
        assert compute_excluded(occs, []) == []


class TestClassToEventRow:
    BASE_CLASS = {
        "uid": "c1",
        "event_uid": None,
        "day": "Tuesday",
        "start_time": "10:00",
        "end_time": "12:00",
        "name": "Algorithms",
        "acronym": "ALG",
        "class_type": "Course",
        "professor": "Dr. X",
        "room": "204",
        "credits": 6,
        "parity": "all",
        "enrolled": True,
    }

    def test_returns_none_without_semester_dates(self):
        assert class_to_event_row(self.BASE_CLASS, {}, []) is None

    def test_builds_row_with_rrule_and_exdates(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-22", "reminder_minutes": 15}
        holidays = [{"label": "Break", "date_from": "2026-09-14", "date_to": "2026-09-16"}]
        row = class_to_event_row(self.BASE_CLASS, settings, holidays)

        assert row["uid"] == "c1"
        assert row["start_at"] == "2026-09-01T10:00:00"
        assert row["end_at"] == "2026-09-01T12:00:00"
        assert row["location"] == "204"
        assert "Professor: Dr. X" in row["description"]
        assert row["exdates"] == ["2026-09-15T10:00:00"]
        assert row["recurrence"] == "FREQ=WEEKLY;UNTIL=2026-09-22"
        # 2026-08-08: the tag is a real per-install setting now
        # (schedule_label, default "Schedule"), not a hardcoded literal --
        # this settings dict doesn't set one, so class_to_event_row falls
        # back to the same default get_schedule_settings would return.
        assert row["tags"] == ["Schedule"]

    def test_schedule_label_setting_is_used_as_the_tag(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-22", "schedule_label": "University"}
        row = class_to_event_row(self.BASE_CLASS, settings, [])
        assert row["tags"] == ["University"]

    def test_odd_even_parity_adds_interval(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-12-20"}
        row = class_to_event_row(dict(self.BASE_CLASS, parity="odd"), settings, [])
        assert "INTERVAL=2" in row["recurrence"]

    def test_disenrolled_class_maps_to_archived_status(self):
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-12-20"}
        row = class_to_event_row(dict(self.BASE_CLASS, enrolled=False), settings, [])
        assert row["status"] == "archived"

    def test_semester_too_short_for_parity_returns_none(self):
        # Semester ends before the first 'odd'-parity Tuesday would land.
        settings = {"semester_start": "2026-09-01", "semester_end": "2026-09-02"}
        row = class_to_event_row(dict(self.BASE_CLASS, parity="odd"), settings, [])
        assert row is None


class TestConflictsAndCredits:
    def _cls(self, **overrides):
        base = dict(
            uid="x", day="Tuesday", start_time="10:00", end_time="12:00",
            parity="all", enrolled=True, credits=6,
        )
        base.update(overrides)
        return base

    def test_overlapping_same_parity_conflicts(self):
        a = self._cls(uid="a", start_time="10:00", end_time="12:00")
        b = self._cls(uid="b", start_time="11:00", end_time="13:00")
        assert len(compute_conflicts([a, b])) == 1

    def test_non_overlapping_times_no_conflict(self):
        a = self._cls(uid="a", start_time="10:00", end_time="12:00")
        b = self._cls(uid="b", start_time="12:00", end_time="14:00")
        assert compute_conflicts([a, b]) == []

    def test_alternating_odd_even_never_conflicts(self):
        a = self._cls(uid="a", parity="odd")
        b = self._cls(uid="b", parity="even")
        assert compute_conflicts([a, b]) == []

    def test_disenrolled_classes_excluded_from_conflicts(self):
        a = self._cls(uid="a", enrolled=False)
        b = self._cls(uid="b")
        assert compute_conflicts([a, b]) == []

    def test_credits_summary_only_counts_enrolled(self):
        a = self._cls(uid="a", credits=6, enrolled=True)
        b = self._cls(uid="b", credits=4, enrolled=False)
        assert credits_summary([a, b]) == 6
