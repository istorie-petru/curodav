"""Unit tests for grid_layout.py's overlap column-packing -- the Week/Day
time-grid's core layout algorithm, ported from desktop's `_pack_overlaps`.
"""

from __future__ import annotations

from src.grid_layout import PX_PER_HOUR, layout_day


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
