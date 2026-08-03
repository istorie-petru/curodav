"""Time-grid layout for the Week/Day calendar views: turns a day's timed
events into positioned blocks (pixel top/height, percentage left/width)
with overlap column-packing, so two events at the same time sit side by
side instead of hiding each other -- port of desktop's `_pack_overlaps`
(`calendar/widgets.py`), same greedy Google-Calendar-style lane algorithm,
reimplemented for CSS absolute positioning instead of Qt widget geometry.
"""

from __future__ import annotations

from typing import Any

PX_PER_HOUR = 48
GRID_HOURS = 24
MIN_BLOCK_HEIGHT_PX = 18


def _minutes(iso_dt: str) -> int:
    """Minutes since midnight from an "...THH:MM..." string."""
    t = iso_dt[11:16]
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _span(event: dict[str, Any]) -> tuple[int, int]:
    start = _minutes(event["start_at"])
    end = _minutes(event["end_at"]) if event.get("end_at") else start + 30
    if end <= start:
        end = start + 30  # zero/negative duration -- floor so it's still visible/clickable
    return start, end


def pack_overlaps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buckets events into overlap clusters and greedily assigns each a
    lane within its cluster. Returns new dicts (originals untouched) with
    `_lane`/`_lane_count` added."""
    ordered = sorted(events, key=lambda e: _span(e))
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_end = -1
    for e in ordered:
        s, en = _span(e)
        if not current or s < current_end:
            current.append(e)
            current_end = max(current_end, en)
        else:
            clusters.append(current)
            current = [e]
            current_end = en
    if current:
        clusters.append(current)

    result: list[dict[str, Any]] = []
    for cluster in clusters:
        lane_ends: list[int] = []
        for e in cluster:
            s, en = _span(e)
            lane_idx = next((i for i, end in enumerate(lane_ends) if s >= end), None)
            if lane_idx is None:
                lane_ends.append(en)
                lane_idx = len(lane_ends) - 1
            else:
                lane_ends[lane_idx] = en
            enriched = dict(e)
            enriched["_lane"] = lane_idx
            result.append(enriched)
        lane_count = len(lane_ends)
        for e in result[-len(cluster):]:
            e["_lane_count"] = lane_count
    return result


def position_event(event: dict[str, Any]) -> dict[str, Any]:
    """Adds top_px/height_px/left_pct/width_pct for absolute positioning
    inside a `position:relative` day column of height
    `GRID_HOURS * PX_PER_HOUR`."""
    start, end = _span(event)
    lane = event.get("_lane", 0)
    lane_count = event.get("_lane_count", 1)
    width_pct = 100 / lane_count
    positioned = dict(event)
    positioned["top_px"] = round(start / 60 * PX_PER_HOUR, 1)
    positioned["height_px"] = max(
        MIN_BLOCK_HEIGHT_PX, round((end - start) / 60 * PX_PER_HOUR, 1)
    )
    positioned["left_pct"] = round(lane * width_pct, 2)
    positioned["width_pct"] = round(width_pct, 2)
    return positioned


def layout_day(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Timed (non-all-day) events for one day, positioned and packed.
    Callers should filter out all-day events before calling this -- those
    render in a separate strip, not on the timed grid."""
    timed = [e for e in events if e.get("start_at") and not e.get("all_day")]
    return [position_event(e) for e in pack_overlaps(timed)]
