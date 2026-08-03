"""Tests for core/recurrence.py -- schedule/repeat expansion.

Purpose-built recurrence subset (daily/weekly, interval, weekdays,
until/count, exception dates) -- see the module docstring for why this
isn't full RFC 5545. Added 2026-07-19 alongside the calendar/task
"schedule list" feature (plans/calendar-and-tasks-rework.md §1).
"""

from __future__ import annotations

from datetime import date

from src.core.recurrence import RecurrenceRule, expand_occurrences


class TestDailyExpansion:
    def test_every_day(self):
        rule = RecurrenceRule(freq="daily", interval=1)
        occ = expand_occurrences(rule, date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 5))
        assert occ == [date(2026, 7, i) for i in range(1, 6)]

    def test_every_n_days(self):
        rule = RecurrenceRule(freq="daily", interval=2)
        occ = expand_occurrences(rule, date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 10))
        assert occ == [date(2026, 7, d) for d in [1, 3, 5, 7, 9]]


class TestWeeklyExpansion:
    def test_specific_weekdays(self):
        rule = RecurrenceRule(freq="weekly", weekdays=frozenset({0, 2, 4}))  # Mon/Wed/Fri
        start = date(2026, 7, 6)  # a Monday
        occ = expand_occurrences(rule, start, start, date(2026, 7, 19))
        assert occ == [
            date(2026, 7, 6), date(2026, 7, 8), date(2026, 7, 10),
            date(2026, 7, 13), date(2026, 7, 15), date(2026, 7, 17),
        ]

    def test_default_weekday_is_dtstart_weekday(self):
        rule = RecurrenceRule(freq="weekly")
        start = date(2026, 7, 7)  # Tuesday
        occ = expand_occurrences(rule, start, start, date(2026, 7, 28))
        assert all(d.weekday() == 1 for d in occ)
        assert len(occ) == 4

    def test_interval_biweekly(self):
        rule = RecurrenceRule(freq="weekly", interval=2, weekdays=frozenset({0}))
        start = date(2026, 7, 6)
        occ = expand_occurrences(rule, start, start, date(2026, 8, 17))
        assert occ == [date(2026, 7, 6), date(2026, 7, 20), date(2026, 8, 3), date(2026, 8, 17)]


class TestBoundsAndExceptions:
    def test_until_bounds_expansion(self):
        rule = RecurrenceRule(freq="weekly", weekdays=frozenset({0}), until=date(2026, 7, 20))
        occ = expand_occurrences(rule, date(2026, 7, 6), date(2026, 7, 6), date(2026, 9, 1))
        assert occ == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20)]

    def test_count_bounds_expansion(self):
        rule = RecurrenceRule(freq="weekly", weekdays=frozenset({0}), count=3)
        occ = expand_occurrences(rule, date(2026, 7, 6), date(2026, 7, 6), date(2026, 12, 31))
        assert occ == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20)]

    def test_exception_dates_excluded(self):
        rule = RecurrenceRule(
            freq="weekly", weekdays=frozenset({0}), exceptions=frozenset({date(2026, 7, 13)})
        )
        occ = expand_occurrences(rule, date(2026, 7, 6), date(2026, 7, 6), date(2026, 7, 27))
        assert date(2026, 7, 13) not in occ
        assert len(occ) == 3

    def test_window_entirely_before_dtstart_is_empty(self):
        rule = RecurrenceRule(freq="daily")
        occ = expand_occurrences(rule, date(2026, 7, 10), date(2026, 7, 1), date(2026, 7, 5))
        assert occ == []

    def test_window_partial_overlap_clips_correctly(self):
        rule = RecurrenceRule(freq="daily")
        occ = expand_occurrences(rule, date(2026, 7, 1), date(2026, 7, 5), date(2026, 7, 8))
        assert occ == [date(2026, 7, d) for d in [5, 6, 7, 8]]

    def test_hard_cap_bounds_unbounded_rule(self):
        rule = RecurrenceRule(freq="daily")
        occ = expand_occurrences(rule, date(2020, 1, 1), date(2020, 1, 1), date(2030, 1, 1), hard_cap=500)
        assert len(occ) <= 500


class TestRuleStringRoundTrip:
    def test_serialize_and_parse(self):
        rule = RecurrenceRule(
            freq="weekly", interval=2, weekdays=frozenset({0, 2, 4}),
            until=date(2026, 12, 31), exceptions=frozenset({date(2026, 8, 15)}),
        )
        s = rule.to_rule_string()
        assert RecurrenceRule.from_rule_string(s) == rule

    def test_malformed_input_never_raises(self):
        assert RecurrenceRule.from_rule_string("") is None
        assert RecurrenceRule.from_rule_string(None) is None
        assert RecurrenceRule.from_rule_string("not a rule at all!!") is None
        assert RecurrenceRule.from_rule_string("FREQ=MONTHLY") is None
