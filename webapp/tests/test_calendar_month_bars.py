"""Tests for the Month-view per-day unified list (`_month_grid` in
routers/calendar.py) -- the 2026-08-08 rework that replaced the old
lane-packed multi-day bar layout with a single flat list per day cell
covering all three item types (all-day events as colored rows, timed
events as text rows, tasks as text rows), capped at MONTH_MAX_VISIBLE_ITEMS
with a "+N more" overflow link to the day view.

The old `_month_week_bars` lane system is gone; what's tested here is the
replacement: multi-day events still appear on every day they touch (not
just their start date), the list is ordered all-day -> timed by time ->
tasks, the cap produces an accurate overflow count, and timed multi-day
spans repeat per-day as text instead of becoming bars.

Follows the fixture/request-building conventions already used for this
router in test_calendar_month_quickcreate.py."""

from __future__ import annotations

from datetime import date, timedelta

from src.routers import calendar as calendar_router

MONDAY = date(2026, 8, 3)  # 2026-08-03 is a Monday


def _event(uid: str, start: str, end: str | None = None, all_day: bool = False) -> dict:
    return {"uid": uid, "title": uid, "start_at": start, "end_at": end, "all_day": all_day}


def _task(uid: str, due_at: str) -> dict:
    return {"uid": uid, "title": uid, "due_at": due_at}


def _day(weeks, iso: str) -> dict:
    return next(d for w in weeks for d in w["days"] if d["iso"] == iso)


class TestUnifiedListKinds:
    def test_all_day_event_becomes_kind_all_day(self):
        events = [_event("e1", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 1
        assert day["rows"][0]["kind"] == "all_day"
        assert day["rows"][0]["event"]["uid"] == "e1"

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

    def test_week_dicts_carry_days_with_no_bars_key(self):
        weeks = calendar_router._month_grid(2026, 8, [], [])
        assert isinstance(weeks, list)
        assert all(set(w.keys()) == {"days"} for w in weeks)
        assert all(len(w["days"]) == 7 for w in weeks)


class TestMultiDayRepeatsEveryDay:
    def test_all_day_multiday_event_on_every_day_it_touches(self):
        # Regression test for the original bug: `_month_grid` used to bucket
        # events only by their start date, so a 3-day event was invisible on
        # its 2nd/3rd day. Now every day it touches carries its own copy as
        # an all-day item -- never simply vanishes.
        events = [_event("e1", "2026-08-05T00:00:00", "2026-08-07T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        touched = {d["iso"] for w in weeks for d in w["days"] if d["rows"]}
        assert touched == {"2026-08-05", "2026-08-06", "2026-08-07"}
        for iso in touched:
            assert [i["kind"] for i in _day(weeks, iso)["rows"]] == ["all_day"]

    def test_timed_multiday_event_repeats_as_text_per_day(self):
        # A *timed* multi-day span (e.g. a conference with real daily
        # times) is still text, not a colored row -- only all_day earns
        # that. It repeats on every day it touches as kind "event".
        events = [_event("e1", "2026-08-05T09:00:00", "2026-08-07T17:00:00")]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        touched = {d["iso"] for w in weeks for d in w["days"] if d["rows"]}
        assert touched == {"2026-08-05", "2026-08-06", "2026-08-07"}
        for iso in touched:
            assert [i["kind"] for i in _day(weeks, iso)["rows"]] == ["event"]


class TestOrdering:
    def test_all_day_first_then_timed_by_time_then_tasks(self):
        events = [
            _event("late", "2026-08-05T16:00:00", "2026-08-05T17:00:00"),
            _event("early", "2026-08-05T09:00:00", "2026-08-05T10:00:00"),
            _event("trip", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True),
        ]
        tasks = [_task("t1", "2026-08-05")]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        kinds = [i["kind"] for i in day["rows"]]
        assert kinds == ["all_day", "event", "event", "task"]
        timed_uids = [i["event"]["uid"] for i in day["rows"] if i["kind"] == "event"]
        assert timed_uids == ["early", "late"]


class TestOverflowCap:
    def test_caps_at_four_and_counts_overflow(self):
        # 6 items on one day: 4 visible, 2 in "+N more".
        events = [
            _event(f"a{i}", "2026-08-05T00:00:00", "2026-08-05T23:59:00", all_day=True)
            for i in range(3)
        ]
        tasks = [_task(f"t{i}", "2026-08-05") for i in range(3)]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == calendar_router.MONTH_MAX_VISIBLE_ITEMS == 4
        assert day["overflow_count"] == 2
        # Every other day in the week is untouched.
        for iso in {d["iso"] for w in weeks for d in w["days"] if d["iso"] != "2026-08-05"}:
            assert _day(weeks, iso)["rows"] == []
            assert _day(weeks, iso)["overflow_count"] == 0

    def test_overflow_includes_all_types_combined(self):
        events = [_event("e1", "2026-08-05T09:00:00", "2026-08-05T10:00:00")]
        tasks = [_task(f"t{i}", "2026-08-05") for i in range(5)]
        weeks = calendar_router._month_grid(2026, 8, events, tasks)
        day = _day(weeks, "2026-08-05")
        assert len(day["rows"]) == 4
        assert day["overflow_count"] == 2
        # The visible budget holds the event plus the first three tasks.
        assert day["rows"][0]["kind"] == "event"
        assert all(i["kind"] == "task" for i in day["rows"][1:])

    def test_empty_day_has_zero_overflow(self):
        weeks = calendar_router._month_grid(2026, 8, [], [])
        day = _day(weeks, "2026-08-04")
        assert day["rows"] == []
        assert day["overflow_count"] == 0


class TestBarWorthySplit:
    """2026-08-07: bar-worthy is `all_day` alone, not "all_day OR spans
    multiple days" -- only a genuinely all-day event (single- or multi-day)
    gets the colored row treatment; every timed event, regardless of span,
    renders as compact text, the same visual weight as a task."""

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
        # times) is still text, not a colored row -- only all_day earns
        # the colored treatment.
        e = _event("e1", "2026-08-04T09:00:00", "2026-08-06T17:00:00")
        assert calendar_router._is_bar_worthy(e) is False

    def test_month_grid_routes_single_day_timed_event_to_event_kind_not_all_day(self):
        events = [_event("e1", "2026-08-04T14:00:00", "2026-08-04T15:00:00")]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        day = _day(weeks, "2026-08-04")
        assert [i["kind"] for i in day["rows"]] == ["event"]

    def test_month_grid_routes_multiday_all_day_event_to_all_day_kind(self):
        events = [_event("e1", "2026-08-04T00:00:00", "2026-08-06T23:59:00", all_day=True)]
        weeks = calendar_router._month_grid(2026, 8, events, [])
        touched = {d["iso"] for w in weeks for d in w["days"] if d["rows"]}
        assert touched == {"2026-08-04", "2026-08-05", "2026-08-06"}
        for iso in touched:
            assert [i["kind"] for i in _day(weeks, iso)["rows"]] == ["all_day"]
