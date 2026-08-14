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


class TestNonWorkingDayPolicy:
    """1.6 ("Generalized recurrence and the non-working-day policy") --
    holiday_calendar/exclude_saturday/exclude_sunday are applied at read
    time, on top of the RRULE/EXDATE expansion, never materialized into
    exdates_json."""

    def test_exclude_saturday_drops_saturday_occurrences(self):
        # 2026-09-05 is a Saturday.
        row = {
            "uid": "e1", "title": "Daily", "start_at": "2026-09-01T09:00:00",
            "recurrence": "FREQ=DAILY;UNTIL=2026-09-07", "exclude_saturday": True,
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        starts = {e["start_at"][:10] for e in expanded}
        assert "2026-09-05" not in starts
        assert "2026-09-06" in starts  # Sunday, not excluded by this flag

    def test_exclude_sunday_drops_sunday_occurrences(self):
        row = {
            "uid": "e2", "title": "Daily", "start_at": "2026-09-01T09:00:00",
            "recurrence": "FREQ=DAILY;UNTIL=2026-09-07", "exclude_sunday": True,
        }
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30))
        starts = {e["start_at"][:10] for e in expanded}
        assert "2026-09-06" not in starts  # Sunday
        assert "2026-09-05" in starts  # Saturday, not excluded by this flag

    def test_holiday_calendar_excludes_occurrences_in_range(self):
        row = {
            "uid": "e3", "title": "Weekly", "start_at": "2026-09-01T10:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22", "holiday_calendar": "University",
        }
        calendars = {"University": [{"date_from": "2026-09-14", "date_to": "2026-09-16"}]}
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30), calendars)
        starts = {e["start_at"] for e in expanded}
        assert "2026-09-15T10:00:00" not in starts
        assert len(expanded) == 3

    def test_holiday_calendar_is_scoped_by_name_not_shared(self):
        # An event referencing 'University' must not be affected by dates
        # under a differently-named calendar -- calendars are independent
        # (open-priority.md: "the engine never assumes every event
        # respects the same calendar").
        row = {
            "uid": "e4", "title": "Weekly", "start_at": "2026-09-01T10:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22", "holiday_calendar": "University",
        }
        calendars = {"Romania": [{"date_from": "2026-09-14", "date_to": "2026-09-16"}]}
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30), calendars)
        assert len(expanded) == 4  # nothing excluded -- 'University' calendar has no entries here

    def test_no_holiday_calendar_set_ignores_holidays_entirely(self):
        row = {
            "uid": "e5", "title": "Weekly", "start_at": "2026-09-01T10:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22",
        }
        calendars = {"University": [{"date_from": "2026-09-01", "date_to": "2026-09-30"}]}
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30), calendars)
        assert len(expanded) == 4  # this event ignores holidays and weekends by default

    def test_holiday_and_weekend_exclusions_combine(self):
        row = {
            "uid": "e6", "title": "Daily", "start_at": "2026-09-01T09:00:00",
            "recurrence": "FREQ=DAILY;UNTIL=2026-09-07",
            "exclude_saturday": True, "exclude_sunday": True,
            "holiday_calendar": "University",
        }
        calendars = {"University": [{"date_from": "2026-09-02", "date_to": "2026-09-02"}]}
        expanded = expand_events([row], date(2026, 9, 1), date(2026, 9, 30), calendars)
        starts = {e["start_at"][:10] for e in expanded}
        # Sep 1 (Tue) ok, Sep 2 (Wed) excluded by holiday, Sep 3-4 ok,
        # Sep 5 (Sat)/Sep 6 (Sun) excluded by weekend, Sep 7 (Mon) ok.
        assert starts == {"2026-09-01", "2026-09-03", "2026-09-04", "2026-09-07"}


class TestManualRecurrenceExceptions:
    """1.6 ("Manual recurrence exceptions") -- a specific occurrence can be
    cancelled or moved without touching the master's own recurrence rule.
    overrides_by_master's shape: {master_uid: [override row, ...]}, each
    {occurrence_date, cancelled, start_at, end_at, title} -- see db.py's
    event_occurrence_overrides CREATE TABLE comment."""

    BASE = {
        "uid": "e1", "title": "Class", "description": "", "start_at": "2026-09-01T10:00:00",
        "end_at": "2026-09-01T12:00:00", "all_day": False, "status": "active",
        "recurrence": "FREQ=WEEKLY;UNTIL=2026-09-22", "exdates": [],
    }

    def test_cancelled_occurrence_is_dropped_others_unaffected(self):
        overrides = {"e1": [{"occurrence_date": "2026-09-08T10:00:00", "cancelled": True}]}
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        starts = {e["start_at"] for e in expanded}
        assert "2026-09-08T10:00:00" not in starts
        assert len(expanded) == 3  # Sep 1, 15, 22 still present

    def test_moved_occurrence_appears_at_its_new_time_not_the_old_slot(self):
        overrides = {
            "e1": [{
                "occurrence_date": "2026-09-08T10:00:00", "cancelled": False,
                "start_at": "2026-09-09T14:00:00", "end_at": "2026-09-09T16:00:00",
            }]
        }
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        starts = {e["start_at"] for e in expanded}
        assert "2026-09-08T10:00:00" not in starts  # old slot gone
        assert "2026-09-09T14:00:00" in starts  # new slot present
        assert len(expanded) == 4  # still 4 total occurrences, just one relocated

    def test_moved_occurrence_keeps_master_uid(self):
        overrides = {
            "e1": [{
                "occurrence_date": "2026-09-08T10:00:00", "cancelled": False,
                "start_at": "2026-09-09T14:00:00", "end_at": "2026-09-09T16:00:00",
            }]
        }
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        assert all(e["uid"] == "e1" for e in expanded)

    def test_moved_occurrence_can_override_title(self):
        overrides = {
            "e1": [{
                "occurrence_date": "2026-09-08T10:00:00", "cancelled": False,
                "start_at": "2026-09-08T14:00:00", "end_at": "2026-09-08T16:00:00",
                "title": "Class (rescheduled)",
            }]
        }
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        moved = next(e for e in expanded if e["start_at"] == "2026-09-08T14:00:00")
        assert moved["title"] == "Class (rescheduled)"
        others = [e for e in expanded if e["start_at"] != "2026-09-08T14:00:00"]
        assert all(e["title"] == "Class" for e in others)

    def test_no_overrides_behaves_exactly_like_before(self):
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30))
        assert len(expanded) == 4

    def test_override_for_a_different_master_is_ignored(self):
        overrides = {"other-event": [{"occurrence_date": "2026-09-08T10:00:00", "cancelled": True}]}
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        assert len(expanded) == 4  # unaffected -- override belongs to a different master

    def test_cancel_and_move_combine_on_the_same_master(self):
        overrides = {
            "e1": [
                {"occurrence_date": "2026-09-08T10:00:00", "cancelled": True},
                {
                    "occurrence_date": "2026-09-15T10:00:00", "cancelled": False,
                    "start_at": "2026-09-16T14:00:00", "end_at": "2026-09-16T16:00:00",
                },
            ]
        }
        expanded = expand_events([self.BASE], date(2026, 9, 1), date(2026, 9, 30), overrides_by_master=overrides)
        starts = sorted(e["start_at"] for e in expanded)
        assert starts == ["2026-09-01T10:00:00", "2026-09-16T14:00:00", "2026-09-22T10:00:00"]


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
