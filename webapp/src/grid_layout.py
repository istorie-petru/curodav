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
# Below this a block can't fit its name AND time lines (3px padding + two
# ~15px lines) -- see position_event's `is_short`.
SHORT_BLOCK_PX = 36

# Planner (Week view) "Hide sleep hours" setting (2026-09-09, Settings >
# General, off by default) -- a `(skip_start_min, skip_end_min)` pair, or
# None when the setting is off (or on but no single uniform Sleep-kind
# time-block window exists to collapse -- routers/calendar.py's
# `_sleep_collapse_window` decides that; this module just does the math
# once a window is handed to it). Threaded through as the optional
# `collapse` argument below rather than a module-level flag: this module
# has no request/db access of its own, and Day view never collapses at all
# (direct decision -- Week/Planner only), so every caller must opt in
# explicitly per call instead of a global toggle a Day-view caller could
# forget to leave off.
CollapseWindow = tuple[int, int] | None


def collapse_minutes(minute: int, collapse: CollapseWindow) -> int:
    """Maps a real minutes-since-midnight value onto a grid with
    `[skip_start, skip_end)` removed -- the actual "hide sleep hours"
    transform: everything at or before the window is unchanged, everything
    at or after it slides up by the window's width, and anything that
    would land INSIDE the (now-invisible) window itself clamps to its
    start -- the one seam pixel every hidden minute collapses onto. That
    last case only matters for something whose real time already falls in
    the window (e.g. a leftover event scheduled before the block/setting
    existed) -- nothing a user can newly interact with ever produces one
    (there's no visible pixel to drag from), see static/sleep_collapse.js's
    `toReal` for the client-side inverse used by drag create/move/resize."""
    if not collapse:
        return minute
    skip_start, skip_end = collapse
    if minute <= skip_start:
        return minute
    if minute >= skip_end:
        return minute - (skip_end - skip_start)
    return skip_start


def grid_height_px(collapse: CollapseWindow) -> float:
    """Total height of the time-grid-body's 24(ish)-hour column, in the
    same `+1 hour` (half a padding-hour top and bottom) shape as
    style.css's default `height:calc(25 * var(--hr-h))` -- collapsing a
    window out of the middle shrinks this by exactly that window's width,
    nothing else changes."""
    total_minutes = GRID_HOURS * 60
    if collapse:
        total_minutes -= collapse[1] - collapse[0]
    return round((total_minutes / 60 + 1) * PX_PER_HOUR, 1)


def visible_hours(collapse: CollapseWindow) -> list[dict[str, Any]]:
    """The hour-gutter's own labels: `{hour, top_px}` for every hour whose
    boundary isn't itself hidden inside the collapsed window -- e.g.
    collapsing 00:00-06:00 drops hours 0-5 entirely and leaves 6-23
    rendered at their now-compressed top_px. Uncollapsed (collapse=None)
    this is exactly the old plain `range(GRID_HOURS)` gutter, just
    pre-computing each label's top_px instead of leaving the template to
    multiply `h * px_per_hour` itself (that multiplication stops being
    correct once a window's been removed from the middle)."""
    hours = []
    for h in range(GRID_HOURS):
        minute = h * 60
        if collapse and collapse[0] <= minute < collapse[1]:
            continue
        top = collapse_minutes(minute, collapse)
        hours.append({"hour": h, "top_px": round(top / 60 * PX_PER_HOUR, 1)})
    return hours


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
    for cluster_idx, cluster in enumerate(clusters):
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
            enriched["_cluster"] = cluster_idx
            result.append(enriched)
        lane_count = len(lane_ends)
        for e in result[-len(cluster):]:
            e["_lane_count"] = lane_count
    return result


def position_event(event: dict[str, Any], collapse: CollapseWindow = None) -> dict[str, Any]:
    """Adds top_px/height_px/left_pct/width_pct for absolute positioning
    inside a `position:relative` day column of height
    `GRID_HOURS * PX_PER_HOUR` (or `grid_height_px(collapse)` when a
    Planner "Hide sleep hours" window is active -- both start and end are
    mapped through `collapse_minutes` BEFORE the pixel math below, so an
    event's block shrinks/shifts exactly as much as the hidden window
    removes, same as everything else on a collapsed grid)."""
    start, end = _span(event)
    start = collapse_minutes(start, collapse)
    end = collapse_minutes(end, collapse)
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
    # 2026-09-25 (UI audit C-18): a block shorter than two text lines (a
    # 30-minute event is 24px) cut its time line in half -- the templates
    # add `.is-short`, which puts name and time on one line.
    positioned["is_short"] = positioned["height_px"] < SHORT_BLOCK_PX
    return positioned


def layout_day(events: list[dict[str, Any]], collapse: CollapseWindow = None) -> list[dict[str, Any]]:
    """Timed (non-all-day) events for one day, positioned and packed.
    Callers should filter out all-day events before calling this -- those
    render in a separate strip, not on the timed grid. `collapse` (Planner
    "Hide sleep hours") is passed straight through to `position_event`;
    lane-packing itself is unaffected -- overlap is about real start/end
    order, which collapsing a window out of the middle never reorders."""
    timed = [e for e in events if e.get("start_at") and not e.get("all_day")]
    positioned = [position_event(e, collapse) for e in pack_overlaps(timed)]
    _cascade_clusters(positioned)
    return positioned


# 2026-09-25 (UI audit C-19): three or more mutually overlapping events
# split a Week column (~180px) into ~60px lanes that only ever showed
# "Overl...". When every overlapping pair in a cluster starts at least
# CASCADE_MIN_START_GAP_MIN apart, the cluster cascades instead (Google
# Calendar style): each event is indented by its nesting depth and runs to
# the column's right edge, later-starting events painting on top (DOM order
# is start order), so every title has the full remaining width and the
# start-gap guarantees it isn't covered by the next event's block. Clusters
# with near-simultaneous starts keep the side-by-side lanes (a cascade
# would hide the earlier event's title under the later one), and 2-lane
# clusters are unchanged (50% is still readable). Only left_pct/width_pct
# change -- calendar.js's drag math never reads either (it re-renders the
# region from the server after a move), so this stays inside the layout.
CASCADE_MIN_LANES = 3
CASCADE_MIN_START_GAP_MIN = 30
CASCADE_MAX_STEP_PCT = 25.0
CASCADE_MIN_WIDTH_PCT = 40.0


def _cascade_clusters(positioned: list[dict[str, Any]]) -> None:
    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for e in positioned:
        by_cluster.setdefault(e.get("_cluster", -1), []).append(e)
    for cluster in by_cluster.values():
        if cluster[0].get("_lane_count", 1) < CASCADE_MIN_LANES:
            continue
        spans = [_span(e) for e in cluster]  # cluster is already in start order
        depths: list[int] = []
        ok = True
        for i, (s, en) in enumerate(spans):
            depth = 0
            for j in range(i):
                ps, pe = spans[j]
                if ps < en and s < pe:  # overlaps an earlier-starting event
                    if s - ps < CASCADE_MIN_START_GAP_MIN:
                        ok = False
                        break
                    depth = max(depth, depths[j] + 1)
            if not ok:
                break
            depths.append(depth)
        if not ok:
            continue
        levels = max(depths) + 1
        step = min(CASCADE_MAX_STEP_PCT, (100 - CASCADE_MIN_WIDTH_PCT) / max(1, levels - 1))
        for e, depth in zip(cluster, depths):
            e["left_pct"] = round(depth * step, 2)
            e["width_pct"] = round(100 - depth * step, 2)
            e["is_cascaded"] = True
