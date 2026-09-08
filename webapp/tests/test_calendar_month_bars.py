"""Tests for Month view's spanning-bar layout (`_month_grid`/`_week_bars`
in routers/calendar.py) -- the 2026-09-08 rework that reverses the
2026-08-08 "flat per-day list" design for all-day (bar-worthy) events only:
they now lane-pack into ONE continuous bar per week row they touch
(`week["bars"]`), instead of a repeated `kind: "all_day"` row inside every
day cell's own flat list. Timed events and tasks are unaffected -- still a
flat per-day list (`day["rows"]`), capped at MONTH_MAX_VISIBLE_ITEMS with a
"+N more" overflow link to the day view, unchanged since 2026-08-08.

FullCalendar-parity interactions, slice 1 (backend lane-packing +
spanning-bar rendering, Month + 4-Week, no drag/resize yet) -- see
documentation/plans/open.md.

Follows the fixture/request-building conventions already used for this
router in test_calendar_month_quickcreate.py."""

from __future__ import annotations

from datetime import date

from src.routers import calendar as calendar_router

MONDAY = date(2026, 8, 3)  # 2026-08-03 is a Monday


def _event(uid: str, start: str, end: str | None = None, all_day: bool = False) -> dict:
    return {"uid": uid, "title": uid, "start_at": start, "end_at": end, "all_day": all_day}


def _task(uid: str, due_at: str) -> dict:
    return {"uid": uid, "title": uid, "due_at": due_at}


def _day(weeks, iso: str) -> dict:
    return next(d for w in weeks for d in w["days"] if d["iso"] == iso)


def _week_of(weeks, iso: str) -> dict:
    return next(w for w in weeks if any(d["iso"] == iso for d in w["days"]))


def _bar_uids(week: dict) -> list[str]:
    return [b["event"]["uid"] for b in week["bars"]]


class TestUnifiedListKinds:
    def test_all_day_event_is_not_in_day_rows_anymore(self):
        # 2026-09-08: all-day events are bars now, not a `day["rows"]`
        # entry -- see TestBars below for where they actually show up.
        events = [_event("e1", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        day = _day(weeks, "2026-08-05")
        assert day["rows"] == []
        week = _week_of(weeks, "2026-08-05")
        assert _bar_uids(week) == ["e1"]

    def test_timed_event_becomes_kind_event(self):
        events = [_event("e1", "2026-08-05T14:00:00", "2026-08-05T15:00:00")]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 1
        assert day["rows"][0]["kind"] == "event"
        assert day["rows"][0]["event"]["uid"] == "e1"

    def test_task_becomes_kind_task(self):
        tasks = [_task("t1", "2026-08-05")]
        weeks = calendar_router._month_grid(2026, 8, [], tasks)
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 1
        assert day["rows"][0]["kind"] == "task"
        assert day["rows"][0]["task"]["uid"] == "t1"

    def test_week_dicts_carry_days_bars_and_lane_count(self):
        weeks = calendar_router._month_grid(2026, 8, [], [])
        assert isinstance(weeks, list)
        assert all(set(w.keys()) == {"days", "bars", "lane_count"} for w in weeks)
        assert all(len(w["days"]) == 7 for w in weeks)
        # No all-day events anywhere in this fixture -- every week's bar
        # layer is empty and reserves no lane space.
        assert all(w["bars"] == [] and w["lane_count"] == 0 for w in weeks)


class TestBars:
    """The 2026-09-08 replacement for the old per-day all_day rows: one
    continuous bar per week row an all-day event touches, lane-packed
    against any other bar-worthy event overlapping the same week."""

    def test_single_day_all_day_event_is_one_bar_spanning_one_column(self):
        events = [_event("e1", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-05")
        assert len(week["bars"]) == 1
        bar = week["bars"][0]
        # 2026-08-05 is a Wednesday -- 3rd column of a Monday-start week.
        assert bar["col_start"] == 3
        assert bar["col_span"] == 1
        assert bar["lane"] == 0
        assert week["lane_count"] == 1

    def test_multiday_event_is_one_bar_spanning_every_day_it_touches(self):
        # Regression test for the original per-day-repeat bug this rework
        # deliberately reverses for all-day events: instead of N repeated
        # per-day rows, this is now exactly ONE bar per week row, spanning
        # every column the event covers within that week.
        events = [_event("e1", "2026-08-05T00:00:00", "2026-08-07T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-05")
        assert len(week["bars"]) == 1
        bar = week["bars"][0]
        assert bar["col_start"] == 3  # Wed
        assert bar["col_span"] == 3  # Wed, Thu, Fri
        # No day cell carries any rows for it any more.
        for iso in ("2026-08-05", "2026-08-06", "2026-08-07"):
            assert _day(weeks, iso)["rows"] == []

    def test_event_spanning_a_week_boundary_gets_a_separate_bar_per_week(self):
        # Sat 2026-08-08 -> Tue 2026-08-11 crosses from the week of Aug 3-9
        # into the week of Aug 10-16 -- two independent bars, each clipped
        # to its own week's bounds, per the "wraps at week boundaries"
        # acceptance line.
        events = [_event("e1", "2026-08-08T00:00:00", "2026-08-11T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week1 = _week_of(weeks, "2026-08-08")
        week2 = _week_of(weeks, "2026-08-11")
        assert week1 is not week2
        bar1 = week1["bars"][0]
        assert bar1["col_start"] == 6  # Saturday
        assert bar1["col_span"] == 2  # Sat, Sun -- clipped at the week edge
        bar2 = week2["bars"][0]
        assert bar2["col_start"] == 1  # Monday
        assert bar2["col_span"] == 2  # Mon, Tue

    def test_non_overlapping_bars_share_lane_zero(self):
        events = [
            _event("mon", "2026-08-03T00:00:00", "2026-08-03T23:59:00", all_day=True),
            _event("wed", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True),
        ]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-03")
        by_uid = {b["event"]["uid"]: b for b in week["bars"]}
        assert by_uid["mon"]["lane"] == 0
        assert by_uid["wed"]["lane"] == 0
        assert week["lane_count"] == 1

    def test_overlapping_bars_get_different_lanes(self):
        events = [
            _event("a", "2026-08-03T00:00:00", "2026-08-05T23:59:00", all_day=True),
            _event("b", "2026-08-04T00:00:00", "2026-08-06T23:59:00", all_day=True),
        ]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-03")
        by_uid = {b["event"]["uid"]: b for b in week["bars"]}
        assert by_uid["a"]["lane"] != by_uid["b"]["lane"]
        assert week["lane_count"] == 2

    def test_longer_bar_claims_lane_zero_over_a_shorter_same_start_bar(self):
        events = [
            _event("short", "2026-08-03T00:00:00", "2026-08-03T23:59:00", all_day=True),
            _event("long", "2026-08-03T00:00:00", "2026-08-07T23:59:00", all_day=True),
        ]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-03")
        by_uid = {b["event"]["uid"]: b for b in week["bars"]}
        assert by_uid["long"]["lane"] == 0
        assert by_uid["short"]["lane"] == 1

    def test_three_way_stack_uses_three_lanes(self):
        events = [
            _event(f"e{i}", "2026-08-03T00:00:00", "2026-08-03T23:59:00", all_day=True)
            for i in range(3)
        ]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-03")
        assert {b["lane"] for b in week["bars"]} == {0, 1, 2}
        assert week["lane_count"] == 3

    def test_a_lane_freed_after_a_bar_ends_is_reused(self):
        # "a" (Mon-Tue) ends before "b" (Wed-Thu) starts -- both fit in
        # lane 0 rather than "b" opening a new lane it doesn't need.
        events = [
            _event("a", "2026-08-03T00:00:00", "2026-08-04T23:59:00", all_day=True),
            _event("b", "2026-08-05T00:00:00", "2026-08-06T23:59:00", all_day=True),
        ]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        week = _week_of(weeks, "2026-08-03")
        by_uid = {b["event"]["uid"]: b for b in week["bars"]}
        assert by_uid["a"]["lane"] == 0
        assert by_uid["b"]["lane"] == 0
        assert week["lane_count"] == 1


class TestTimedMultiDayStillRepeatsAsText:
    def test_timed_multiday_event_repeats_as_text_per_day(self):
        # A *timed* multi-day span (e.g. a conference with real daily
        # times) is still text, not a bar -- only all_day earns a bar.
        # This is the one behavior 2026-08-08's rework introduced that
        # 2026-09-08 does NOT reverse: timed events still repeat per day
        # as a flat text row, not a spanning bar.
        events = [_event("e1", "2026-08-05T09:00:00", "2026-08-07T17:00:00")]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        touched = {d["iso"] for w in weeks for d in w["days"] if d["rows"]}
        assert touched == {"2026-08-05", "2026-08-06", "2026-08-07"}
        for iso in touched:
            assert [i["kind"] for i in _day(weeks, iso)["rows"]] == ["event"]
        week = _week_of(weeks, "2026-08-05")
        assert week["bars"] == []


class TestOrdering:
    def test_timed_by_time_then_tasks_no_all_day_in_rows(self):
        events = [
            _event("late", "2026-08-05T16:00:00", "2026-08-05T17:00:00"),
            _event("early", "2026-08-05T09:00:00", "2026-08-05T10:00:00"),
            _event("trip", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True),
        ]
        tasks = [_task("t1", "2026-08-05")]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        kinds = [i["kind"] for i in day["rows"]]
        assert kinds == ["event", "event", "task"]
        timed_uids = [i["event"]["uid"] for i in day["rows"] if i["kind"] == "event"]
        assert timed_uids == ["early", "late"]
        week = _week_of(weeks, "2026-08-05")
        assert _bar_uids(week) == ["trip"]


class TestOverflowCap:
    def test_caps_at_four_and_counts_overflow_all_day_excluded(self):
        # 3 all-day (now bars, not counted here) + 3 tasks: all 3 tasks
        # fit under the 4-item cap on their own, no overflow -- the cap now
        # only ever applies to the timed-event/task flat list.
        events = [
            _event(f"a{i}", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True)
            for i in range(3)
        ]
        tasks = [_task(f"t{i}", "2026-08-05") for i in range(3)]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 3
        assert day["overflow_count"] == 0
        week = _week_of(weeks, "2026-08-05")
        assert len(week["bars"]) == 3
        # Every other day in the week is untouched.
        for iso in {d["iso"] for w in weeks for d in w["days"] if d["iso"] != "2026-08-05"}:
            assert _day(weeks, iso)["rows"] == []
            assert _day(weeks, iso)["overflow_count"] == 0

    def test_overflow_over_timed_events_and_tasks_combined(self):
        events = [_event(f"e{i}", "2026-08-05T09:00:00", "2026-08-05T10:00:00") for i in range(2)]
        tasks = [_task(f"t{i}", "2026-08-05") for i in range(4)]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 4
        assert day["overflow_count"] == 2
        assert day["rows"][0]["kind"] == "event"
        assert day["rows"][1]["kind"] == "event"
        assert all(i["kind"] == "task" for i in day["rows"][2:])

    def test_empty_day_has_zero_overflow(self):
        weeks = calendar_router._month_grid(2026, 8, [], [])
        day = _day(weeks, "2026-08-04")
        assert day["rows"] == []
        assert day["overflow_count"] == 0


class TestBarWorthySplit:
    """2026-08-07: bar-worthy is `all_day` alone, not "all_day OR spans
    multiple days" -- only a genuinely all-day event (single- or multi-day)
    gets the bar treatment; every timed event, regardless of span, renders
    as compact text, the same visual weight as a task."""

    def test_single_day_timed_event_is_not_bar_worthy(self):
        e = _event("e1", "2026-08-04T14:00:00", "2026-08-04T15:00:00")
        assert calendar_router._is_bar_worthy(e) is False

    def test_single_day_all_day_event_is_bar_worthy(self):
        e = _event("e1", "2026-08-04T00:00:00", "2026-08-04T23:59:00", all_day=True)
        assert calendar_router._is_bar_worthy(e) is True

    def test_multiday_all_day_event_is_bar_worthy(self):
        e = _event("e1", "2026-08-04T00:00:00", "2026-08-06T23:59:00", all_day=True)
        assert calendar_router._is_bar_worthy(e) is True

    def test_multiday_timed_event_is_not_bar_worthy(self):
        # The specific case corrected by this feedback: a multi-day
        # *timed* span (e.g. a conference with real daily start/end
        # times) is still text, not a bar -- only all_day earns it.
        e = _event("e1", "2026-08-04T09:00:00", "2026-08-06T17:00:00")
        assert calendar_router._is_bar_worthy(e) is False

    def test_month_grid_routes_single_day_timed_event_to_event_kind(self):
        events = [_event("e1", "2026-08-04T14:00:00", "2026-08-04T15:00:00")]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        day = _day(weeks, "2026-08-04")
        assert [i["kind"] for i in day["rows"]] == ["event"]

    def test_month_grid_routes_multiday_all_day_event_to_a_bar(self):
        events = [_event("e1", "2026-08-04T00:00:00", "2026-08-06T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        for iso in ("2026-08-04", "2026-08-05", "2026-08-06"):
            assert _day(weeks, iso)["rows"] == []
        week = _week_of(weeks, "2026-08-04")
        assert _bar_uids(week) == ["e1"]
