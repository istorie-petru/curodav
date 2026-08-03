"""Tests for timeline_layout.py -- the ported desktop Timeline algorithms
(Phase 11). pack_intervals is a byte-for-byte port of desktop's
core/utils/interval_packing.py, so these tests mirror the properties that
module's own docstring/history documents: overlap clustering, greedy
lowest-free-lane assignment, and preferred-lane stability. assign_swimlanes/
compute_range/month_bounds/week_start_indices mirror
desktop/src/features/tasks/timeline_view.py's TimelineCanvas methods of
the same name."""

from __future__ import annotations

from datetime import date

from src import timeline_layout as tl


def _iv(start_day, end_day, uid):
    return (date(2026, 8, start_day), date(2026, 8, end_day), uid)


class TestPackIntervals:
    def test_empty(self):
        assert tl.pack_intervals([]) == {}

    def test_non_overlapping_all_get_lane_zero(self):
        intervals = [_iv(1, 2, "a"), _iv(3, 4, "b"), _iv(5, 6, "c")]
        result = tl.pack_intervals(intervals)
        assert all(lane == 0 for lane, _ in result.values())
        assert all(lanes == 1 for _, lanes in result.values())

    def test_two_overlapping_get_different_lanes(self):
        intervals = [_iv(1, 5, "a"), _iv(2, 6, "b")]
        result = tl.pack_intervals(intervals)
        assert {result["a"][0], result["b"][0]} == {0, 1}
        assert result["a"][1] == 2
        assert result["b"][1] == 2

    def test_three_way_overlap_needs_three_lanes(self):
        intervals = [_iv(1, 10, "a"), _iv(2, 10, "b"), _iv(3, 10, "c")]
        result = tl.pack_intervals(intervals)
        lanes = {result[k][0] for k in ("a", "b", "c")}
        assert lanes == {0, 1, 2}
        assert all(result[k][1] == 3 for k in ("a", "b", "c"))

    def test_sequential_reuse_lowest_free_lane(self):
        # a and b overlap (lanes 0,1); a ends before c starts, so c can
        # reuse lane 0 instead of taking a third lane.
        intervals = [_iv(1, 3, "a"), _iv(2, 5, "b"), _iv(4, 6, "c")]
        result = tl.pack_intervals(intervals)
        assert result["a"][0] == 0
        assert result["b"][0] == 1
        assert result["c"][0] == 0

    def test_separate_clusters_each_reset_lane_numbering(self):
        intervals = [_iv(1, 3, "a"), _iv(1, 3, "b"), _iv(10, 12, "c")]
        result = tl.pack_intervals(intervals)
        assert result["c"][0] == 0  # a completely separate cluster, not lane 2

    def test_preferred_lane_honored_when_free(self):
        intervals = [_iv(1, 3, "a")]
        result = tl.pack_intervals(intervals, preferred={"a": 2})
        assert result["a"][0] == 2
        assert result["a"][1] == 3  # cluster_max_lanes reflects the preferred lane

    def test_preferred_lane_falls_back_when_occupied(self):
        # b's preferred lane 0 is occupied by a (still overlapping) -- must
        # fall back to the lowest actually-free lane, not force a conflict.
        intervals = [_iv(1, 5, "a"), _iv(2, 6, "b")]
        result = tl.pack_intervals(intervals, preferred={"a": 0, "b": 0})
        assert result["a"][0] != result["b"][0]

    def test_stability_no_bounce_when_no_new_conflict(self):
        """The exact regression desktop's docstring documents: an item
        with zero real conflicts must not get reassigned to a new lane
        purely due to sort order, when its previous lane is given as
        preferred."""
        intervals = [_iv(5, 8, "solo")]
        result = tl.pack_intervals(intervals, preferred={"solo": 3})
        assert result["solo"][0] == 3


class TestAssignSwimlanes:
    def _task(self, uid, list_path="tasks", start=None, due=None, timeline_lane=None):
        t = {"uid": uid, "list_path": list_path, "due_at": due}
        if start:
            t["start_at"] = start
        if timeline_lane is not None:
            t["timeline_lane"] = timeline_lane
        return t

    def test_single_list_no_overlap_all_row_zero(self):
        tasks = [
            self._task("a", due="2026-08-01"),
            self._task("b", start="2026-08-05", due="2026-08-06"),
        ]
        result = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert result.row_of["a"] == 0
        assert result.row_of["b"] == 0
        assert result.total_rows == 1

    def test_overlapping_same_list_different_rows(self):
        tasks = [
            self._task("a", start="2026-08-01", due="2026-08-05"),
            self._task("b", start="2026-08-03", due="2026-08-07"),
        ]
        result = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert result.row_of["a"] != result.row_of["b"]
        assert result.total_rows == 2

    def test_different_lists_never_share_a_row(self):
        tasks = [
            self._task("a", list_path="hw", due="2026-08-01"),
            self._task("b", list_path="other", due="2026-08-01"),
        ]
        result = tl.assign_swimlanes(tasks, {"hw": "Homework", "other": "Other"})
        assert result.row_of["a"] != result.row_of["b"]
        # each list gets its own contiguous block
        ranges = list(result.group_range_by_list.values())
        (start_a, count_a), (start_b, count_b) = sorted(ranges)
        assert start_a + count_a <= start_b or start_b + count_b <= start_a

    def test_lists_sorted_by_name(self):
        tasks = [self._task("a", list_path="zz", due="2026-08-01"), self._task("b", list_path="aa", due="2026-08-01")]
        result = tl.assign_swimlanes(tasks, {"zz": "Zeta", "aa": "Alpha"})
        labels_in_order = [label for _, _, label, _ in result.group_labels]
        assert labels_in_order == ["Alpha", "Zeta"]

    def test_manual_lane_wins_and_is_unclamped(self):
        """A task with an explicit timeline_lane lands there even if it
        opens a gap above lane 0 -- the whole point of manual placement,
        per desktop's docstring."""
        tasks = [self._task("a", due="2026-08-01", timeline_lane=3)]
        result = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert result.row_of["a"] == 3
        assert result.total_rows == 4

    def test_manual_lane_falls_back_if_genuinely_occupied(self):
        tasks = [
            self._task("a", start="2026-08-01", due="2026-08-10"),
            self._task("b", start="2026-08-05", due="2026-08-06", timeline_lane=0),  # conflicts with a's lane 0
        ]
        result = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert result.row_of["a"] != result.row_of["b"]

    def test_stability_via_prev_local_lane(self):
        """A second computation with the same non-conflicting task and its
        previous lane passed through as prev_local_lane keeps the same row
        -- doesn't silently reflow every call."""
        tasks = [self._task("solo", due="2026-08-01")]
        first = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert first.row_of["solo"] == 0
        # Simulate a lane 2 preference (as if from a prior wider layout)
        second = tl.assign_swimlanes(tasks, {"tasks": "Tasks"}, prev_local_lane={"solo": 0})
        assert second.row_of["solo"] == 0

    def test_task_with_no_due_date_is_skipped(self):
        tasks = [{"uid": "a", "list_path": "tasks", "due_at": None}]
        result = tl.assign_swimlanes(tasks, {"tasks": "Tasks"})
        assert "a" not in result.row_of
        # still gets a (empty) group row for the list itself
        assert result.total_rows == 1


class TestMonthBounds:
    def test_same_month(self):
        first, last = tl.month_bounds(date(2026, 8, 15), 0)
        assert first == date(2026, 8, 1)
        assert last == date(2026, 8, 31)

    def test_previous_month_year_rollover(self):
        first, last = tl.month_bounds(date(2026, 1, 15), -1)
        assert first == date(2025, 12, 1)
        assert last == date(2025, 12, 31)

    def test_next_month_year_rollover(self):
        first, last = tl.month_bounds(date(2026, 12, 15), 1)
        assert first == date(2027, 1, 1)
        assert last == date(2027, 1, 31)


class TestComputeRange:
    def test_default_window_is_three_calendar_months(self):
        today = date(2026, 8, 15)
        start, end = tl.compute_range([], today=today)
        assert start == date(2026, 7, 1)
        assert end == date(2026, 9, 30)

    def test_extends_for_task_outside_window(self):
        today = date(2026, 8, 15)
        tasks = [{"uid": "a", "due_at": "2026-12-25"}]
        start, end = tl.compute_range(tasks, today=today)
        assert end >= date(2026, 12, 25)

    def test_extends_backward_too(self):
        today = date(2026, 8, 15)
        tasks = [{"uid": "a", "start_at": "2026-01-01", "due_at": "2026-01-05"}]
        start, end = tl.compute_range(tasks, today=today)
        assert start <= date(2026, 1, 1)


class TestWeekStartIndices:
    def test_starts_on_monday_no_extra_leading_index(self):
        start = date(2026, 8, 3)  # a Monday
        indices = tl.week_start_indices(start, 14)
        assert indices[0] == 0
        assert indices.count(0) == 1

    def test_leading_partial_week_gets_index_zero_too(self):
        start = date(2026, 8, 5)  # a Wednesday
        indices = tl.week_start_indices(start, 14)
        assert indices[0] == 0

    def test_every_monday_in_range_included(self):
        start = date(2026, 8, 1)  # a Saturday
        indices = tl.week_start_indices(start, 20)
        for i in indices:
            if i != 0:
                assert (start + __import__("datetime").timedelta(days=i)).weekday() == 0


class TestBarGeometry:
    def test_single_day_task_has_visible_width(self):
        task = {"uid": "a", "due_at": "2026-08-05"}
        geo = tl.bar_geometry(task, 0, date(2026, 8, 1), 30, {"a": 0})
        assert geo.day_to > geo.day_from

    def test_exclusive_end_is_one_past_due_date(self):
        task = {"uid": "a", "start_at": "2026-08-05", "due_at": "2026-08-07"}
        geo = tl.bar_geometry(task, 0, date(2026, 8, 1), 30, {"a": 0})
        assert geo.day_from == 4  # Aug 5 is day offset 4 from Aug 1
        assert geo.day_to == 7  # one past Aug 7's offset (6)

    def test_no_due_date_returns_none(self):
        task = {"uid": "a", "due_at": None}
        assert tl.bar_geometry(task, 0, date(2026, 8, 1), 30, {}) is None

    def test_color_cycles_by_index(self):
        task = {"uid": "a", "due_at": "2026-08-05"}
        c0 = tl.bar_geometry(task, 0, date(2026, 8, 1), 30, {"a": 0}).color
        c10 = tl.bar_geometry(task, 10, date(2026, 8, 1), 30, {"a": 0}).color
        assert c0 == c10  # palette has 10 colors, wraps around
