"""Generic interval packing -- assign each of a set of possibly-overlapping
(start, end) intervals the lowest free "lane" among items active at the
same time.

Originally written for the calendar's week/day grid (lay concurrent events
out side by side instead of stacking them on top of each other,
Google-Calendar style) and reused for the Tasks timeline's per-project
row-packing (2026-07-19) -- same algorithm either way, just applied to a
different axis (lane = a horizontal column sharing a day in the calendar;
lane = a vertical row sharing a project's swimlane in the timeline).
"""

from __future__ import annotations

from typing import Any


def pack_intervals(
    intervals: list[tuple[Any, Any, str]],
    preferred: dict[str, int] | None = None,
) -> dict[str, tuple[int, int]]:
    """Bucket `intervals` into overlap clusters (sweeping by start time,
    closing a cluster whenever nothing is active) and greedily assign each
    item the lowest free lane within its cluster -- the classic interval
    graph coloring layout. Every item in a cluster gets that cluster's
    total lane count, so callers can divide available space evenly.

    `intervals` is `(start, end, id)` -- `start`/`end` just need to support
    `<`/`<=` comparison (datetimes for the calendar, dates for the
    timeline). Returns `{id: (lane, lanes_in_cluster)}`.

    `preferred` optionally maps an item's id to the lane it occupied last
    time this was computed. Bug (2026-07-18): the timeline recomputes
    packing on every drag release now (previously it never did, which was
    a *different* bug -- rows never merged back after a move resolved an
    overlap). But this function always assigned lanes lowest-free-first
    with no memory of prior layout, so resizing/moving a task that still
    had zero actual conflicts could still get reassigned a new lane purely
    because of where it now landed in the (start, end) sort order --
    visually, an untouched or lightly-edited task would jump to a
    different row, often the last (bottom) one in its project's block.
    When `preferred` is given, an item keeps its previous lane as long as
    that lane is actually free at the time it's processed; it only gets
    bumped to a new lane when there's a genuine, unavoidable conflict.
    """
    if not intervals:
        return {}
    items = sorted(intervals, key=lambda t: (t[0], t[1]))
    result: dict[str, tuple[int, int]] = {}

    cluster_members: list[tuple[str, int]] = []
    active_end_by_lane: dict[int, Any] = {}
    cluster_max_lanes = 0

    def flush_cluster() -> None:
        nonlocal cluster_members, cluster_max_lanes
        total = cluster_max_lanes if cluster_max_lanes > 0 else 1
        for item_id, lane in cluster_members:
            result[item_id] = (lane, total)
        cluster_members = []
        cluster_max_lanes = 0

    for start, end, item_id in items:
        finished = [c for c, e in active_end_by_lane.items() if e <= start]
        for c in finished:
            del active_end_by_lane[c]
        if not active_end_by_lane and cluster_members:
            flush_cluster()

        used = set(active_end_by_lane.keys())
        pref_lane = preferred.get(item_id) if preferred else None
        if pref_lane is not None and pref_lane not in used:
            lane = pref_lane
        else:
            lane = 0
            while lane in used:
                lane += 1
        active_end_by_lane[lane] = end
        cluster_members.append((item_id, lane))
        cluster_max_lanes = max(cluster_max_lanes, lane + 1)

    flush_cluster()
    return result
