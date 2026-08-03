"""Unit tests for recurrence_expand.py -- expanding RRULE+EXDATE events/
tasks into concrete occurrences within a date window. Also guards the real
bug found while building this (see ical_rows.py's `_normalize_rrule`
docstring): a DATE-TIME DTSTART with a bare-DATE UNTIL silently drops the
final occurrence."""

from __future__ import annotations

from datetime import date

from src.recurrence_expand import expand_events, expand_tasks


class TestExpandEvents:
    def test_non_recurring_passes_through_unchanged(self):
        row = {"uid": "e1", "title": "One-off", "start_at": "2026-09-05T10:00:00"}
        assert expand_events([row], date(2026, 9, 1), date(2026, 9, 30)) == [row]

    def test_weekly_recurrence_expands_within_window(self):
        row = {
            "uid": "e2",
            "title": "Standup",
            "start_at": "2026-09-01T09:00:00",
            "end_at": "2026-09-01T09:30:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22",
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        assert len(expanded) == 4
        assert all(e["uid"] == "e2" for e in expanded)
        starts = sorted(e["start_at"] for e in expanded)
        assert starts == [
            "2026-09-01T09:00:00", "2026-09-08T09:00:00",
            "2026-09-15T09:00:00", "2026-09-22T09:00:00",
        ]

    def test_last_occurrence_not_dropped_by_bare_date_until(self):
        """Regression test: UNTIL with no time-of-day used to silently
        truncate the final occurrence for any event with a time-of-day
        after midnight, because RFC 5545 requires UNTIL's value type to
        match DTSTART's (see ical_rows._normalize_rrule)."""
        row = {
            "uid": "e3",
            "title": "Late class",
            "start_at": "2026-09-01T22:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-08",
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        assert len(expanded) == 2  # Sep 1 AND Sep 8, not just Sep 1

    def test_exdates_excluded_from_expansion(self):
        row = {
            "uid": "e4",
            "title": "Class",
            "start_at": "2026-09-01T10:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22",
            "exdates": ["2026-09-15T10:00:00"],
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        starts = sorted(e["start_at"] for e in expanded)
        assert "2026-09-15T10:00:00" not in starts
        assert len(expanded) == 3

    def test_malformed_recurrence_does_not_crash_the_view(self):
        """A garbage recurrence string (no valid FREQ) shouldn't raise --
        whether the underlying library treats it as "not recurring" (one
        occurrence, the anchor) or expand.py's own except-branch catches a
        harder failure, either outcome is fine; the view must not 500."""
        row = {
            "uid": "e5",
            "title": "Bad rule",
            "start_at": "2026-09-01T10:00:00",
            "recurrence": "NOT;A;VALID;RULE",
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        assert len(expanded) == 1
        assert expanded[0]["uid"] == "e5"
        assert expanded[0]["start_at"] == "2026-09-01T10:00:00"


class TestExpandTasks:
    def test_weekly_task_expands_within_window(self):
        row = {
            "uid": "t1",
            "title": "Weekly review",
            "due_at": "2026-09-01T10:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-15",
        }
        expanded = expand_tasks([row], date(2026, 9, 1), date(2026, 9, 30))
        assert len(expanded) == 3
        assert all(t["uid"] == "t1" for t in expanded)

    def test_non_recurring_task_passes_through(self):
        row = {"uid": "t2", "title": "One-off", "due_at": "2026-09-05"}
        assert expand_tasks([row], date(2026, 9, 1), date(2026, 9, 30)) == [row]
