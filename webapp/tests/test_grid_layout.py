"""Unit tests for grid_layout.py's overlap column-packing -- the Week/Day
time-grid's core layout algorithm, ported from desktop's `_pack_overlaps`.
"""

from __future__ import annotations

from src.grid_layout import (
    GRID_HOURS,
    PX_PER_HOUR,
    collapse_minutes,
    grid_height_px,
    layout_day,
    visible_hours,
)


def _ev(uid, start, end):
    return {"uid": uid, "start_at": f"2026-09-01T{start}:00", "end_at": f"2026-09-01T{end}:00"}


class TestLayoutDay:
    def test_single_event_full_width(self):
        laid = layout_day([_ev("a", "09:00", "10:00")])
        assert laid[0]["left_pct"] == 0
        assert laid[0]["width_pct"] == 100
        assert laid[0]["top_px"] == 9 * PX_PER_HOUR
        assert laid[0]["height_px"] == 1 * PX_PER_HOUR

    def test_non_overlapping_events_both_full_width(self):
        laid = layout_day([_ev("a", "09:00", "10:00"), _ev("b", "11:00", "12:00")])
        assert all(e["width_pct"] == 100 for e in laid)

    def test_two_overlapping_events_split_lanes(self):
        laid = layout_day([_ev("a", "09:00", "10:00"), _ev("b", "09:30", "10:30")])
        lefts = {e["uid"]: e["left_pct"] for e in laid}
        assert lefts["a"] != lefts["b"]
        assert all(e["width_pct"] == 50 for e in laid)

    def test_three_way_overlap_splits_three_lanes(self):
        laid = layout_day(
            [_ev("a", "09:00", "10:00"), _ev("b", "09:15", "09:45"), _ev("c", "09:20", "09:40")]
        )
        assert all(round(e["width_pct"], 1) == round(100 / 3, 1) for e in laid)
        lefts = {e["left_pct"] for e in laid}
        assert len(lefts) == 3

    def test_sequential_non_overlapping_after_a_cluster_gets_full_width(self):
        # a+b overlap (2 lanes), c starts after both end -- shouldn't
        # inherit the earlier cluster's lane count.
        laid = layout_day(
            [_ev("a", "09:00", "10:00"), _ev("b", "09:30", "10:00"), _ev("c", "11:00", "12:00")]
        )
        by_uid = {e["uid"]: e for e in laid}
        assert by_uid["c"]["width_pct"] == 100

    def test_all_day_events_excluded(self):
        all_day = {"uid": "x", "start_at": "2026-09-01T00:00:00", "all_day": True}
        laid = layout_day([_ev("a", "09:00", "10:00"), all_day])
        assert len(laid) == 1
        assert laid[0]["uid"] == "a"

    def test_zero_duration_event_gets_minimum_visible_height(self):
        laid = layout_day([_ev("a", "14:00", "14:00")])
        assert laid[0]["height_px"] == 0.5 * PX_PER_HOUR

    def test_events_missing_end_at_default_to_thirty_minutes(self):
        e = {"uid": "a", "start_at": "2026-09-01T09:00:00"}
        laid = layout_day([e])
        assert laid[0]["height_px"] == 0.5 * PX_PER_HOUR


class TestSleepHourCollapse:
    """"Hide sleep hours in Planner" (Settings > General, 2026-09-09) --
    grid_layout.py's own collapse math, decoupled from routers/calendar.py's
    decision of WHETHER to collapse (that's _sleep_collapse_window, covered
    in test_calendar_planner_sleep_collapse.py)."""

    def test_collapse_minutes_before_window_is_unchanged(self):
        assert collapse_minutes(5 * 60, (6 * 60, 14 * 60)) == 5 * 60

    def test_collapse_minutes_after_window_shifts_up_by_its_width(self):
        # 14:00, exactly at the end of a 06:00-14:00 (8h) window, lands
        # right at the seam -- the same collapsed position as 06:00 itself.
        assert collapse_minutes(14 * 60, (6 * 60, 14 * 60)) == 6 * 60
        assert collapse_minutes(15 * 60, (6 * 60, 14 * 60)) == 7 * 60

    def test_collapse_minutes_inside_window_clamps_to_its_start(self):
        assert collapse_minutes(10 * 60, (6 * 60, 14 * 60)) == 6 * 60

    def test_collapse_minutes_none_window_is_a_no_op(self):
        assert collapse_minutes(9 * 60, None) == 9 * 60

    def test_layout_day_shrinks_and_shifts_event_after_the_window(self):
        # 09:00-10:00 with 00:00-06:00 collapsed should render as if it
        # started at 03:00 (9h - 6h removed = 3h in).
        laid = layout_day([_ev("a", "09:00", "10:00")], (0, 6 * 60))
        assert laid[0]["top_px"] == 3 * PX_PER_HOUR
        assert laid[0]["height_px"] == 1 * PX_PER_HOUR

    def test_layout_day_event_entirely_inside_window_collapses_to_the_seam(self):
        laid = layout_day([_ev("a", "02:00", "03:00")], (0, 6 * 60))
        assert laid[0]["top_px"] == 0

    def test_grid_height_px_shrinks_by_the_window_width(self):
        uncollapsed = grid_height_px(None)
        collapsed = grid_height_px((0, 6 * 60))
        assert uncollapsed - collapsed == 6 * PX_PER_HOUR
        assert uncollapsed == (GRID_HOURS + 1) * PX_PER_HOUR

    def test_visible_hours_drops_every_hour_inside_the_window(self):
        hours = visible_hours((0, 6 * 60))
        assert [h["hour"] for h in hours] == list(range(6, 24))

    def test_visible_hours_first_visible_hour_after_window_sits_at_top_zero(self):
        hours = visible_hours((0, 6 * 60))
        assert hours[0] == {"hour": 6, "top_px": 0}

    def test_visible_hours_none_window_returns_every_hour_uncompressed(self):
        hours = visible_hours(None)
        assert [h["hour"] for h in hours] == list(range(24))
        assert hours[9]["top_px"] == 9 * PX_PER_HOUR

    def test_visible_hours_partial_hour_window_keeps_the_boundary_hour_visible(self):
        # A 00:00-06:30 window: hour 6 (06:00) is inside [0, 390) so it's
        # dropped; hour 7 (07:00) is the first one after it, 30 min in.
        hours = visible_hours((0, 6 * 60 + 30))
        assert hours[0]["hour"] == 7
        assert hours[0]["top_px"] == 0.5 * PX_PER_HOUR
