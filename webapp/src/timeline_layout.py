"""Timeline (Gantt) view layout -- port of desktop's
`desktop/src/features/tasks/timeline_view.py` (`TimelineCanvas`) and
`desktop/src/core/utils/interval_packing.py`, adapted from Qt
widget-painted geometry to plain data structures a template/JS can
position with CSS. Every algorithm below is the same algorithm as the
desktop source, not a reinterpretation -- see each function's docstring
for the specific desktop counterpart it mirrors.

One deliberate adaptation, forced by this app's data model rather than a
design choice: desktop groups swimlanes by `parent_id` (a task's direct
parent, which for a top-level task IS a project object). This app has no
such field -- a task belongs to a task list (`list_path`), and a list
optionally belongs to a project (`project_uid`, Phase 3/4 of this rework).
Swimlanes here are therefore grouped by task list, not by project
directly -- the row label is the list's name, and (if that list is linked
to a project) the project's own color, per Phase 3/4's existing linking
mechanism. This is the faithful equivalent, not a reduction: it's exactly
the same "whole list can be linked to a project" mental model the rest of
this rework already established, applied to the one place desktop's
model and this app's model genuinely differ.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

NO_LIST_LABEL = "(No list)"

# Same fixed 10-color palette as desktop's BAR_COLORS (timeline_view.py),
# cycled by each task's position in the overall (unsorted) task list --
# not per-swimlane, matching desktop exactly.
BAR_COLORS = [
    "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626", "#4f46e5",
    "#0d9488", "#b45309", "#9333ea", "#0284c7",
]


def pack_intervals(
    intervals: list[tuple[Any, Any, str]],
    preferred: dict[str, int] | None = None,
) -> dict[str, tuple[int, int]]:
    """Verbatim port of desktop's `core/utils/interval_packing.py::pack_intervals`
    -- bucket `intervals` into overlap clusters (sweeping by start,
    closing a cluster whenever nothing is active) and greedily assign
    each item the lowest free lane within its cluster. Every item in a
    cluster gets that cluster's total lane count.

    `intervals` is `(start, end, id)` -- `start`/`end` need only support
    `<`/`<=` (here: `date` objects, one-past-the-due-date exclusive end,
    same convention desktop's timeline uses). Returns
    `{id: (lane, lanes_in_cluster)}`.

    `preferred` maps an id to the lane it occupied last computation --
    kept for stability (an edit that doesn't create a new conflict
    shouldn't visually bounce the task to a different row), same
    reasoning as the desktop docstring: an item keeps its previous lane
    as long as that lane is actually free when it's processed; a genuine
    conflict still bumps it to a new lane.
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


def _task_dates(task: dict) -> tuple[date, date] | None:
    """(start_date, due_date), falling back to due_at for a task with no
    start_at -- same fallback `_bar_rect`/`mousePressEvent` use on the
    desktop side. Returns None if due_at is missing/unparseable (desktop:
    `set_objects` filters to `obj.due_at`-having tasks before the canvas
    ever sees them; here that filter happens in the caller, but this is
    the same "no due date, not on the timeline at all" rule)."""
    due_raw = task.get("due_at")
    if not due_raw:
        return None
    try:
        due = date.fromisoformat(due_raw[:10])
    except ValueError:
        return None
    start_raw = task.get("start_at")
    if start_raw:
        try:
            return date.fromisoformat(start_raw[:10]), due
        except ValueError:
            return due, due
    return due, due


@dataclass
class SwimlaneResult:
    row_of: dict[str, int]  # task uid -> global row index
    group_labels: list[tuple[int, int, str, str | None]]  # (row_start, row_count, label, list_uid)
    group_range_by_list: dict[str | None, tuple[int, int]]  # list_uid -> (row_start, row_count)
    total_rows: int
    local_lane_of: dict[str, int] = field(default_factory=dict)


def assign_swimlanes(
    tasks: list[dict],
    list_names: dict[str, str],
    prev_local_lane: dict[str, int] | None = None,
) -> SwimlaneResult:
    """Port of desktop's `TimelineCanvas._assign_swimlanes` -- group tasks
    by list (desktop: by project via `parent_id`, see this module's own
    docstring for why list is the equivalent grouping key here), bin-pack
    each list's tasks into the minimum rows needed via `pack_intervals`,
    and stack the resulting per-list row blocks vertically so tasks from
    different lists never share a row.

    `prev_local_lane` is this function's own previous `local_lane_of`
    (task uid -> lane within its list's block), threaded through by the
    caller across requests for the same stability `pack_intervals`'
    `preferred` gives -- see that function's docstring. A task's own
    `timeline_lane` (an explicit, user-dragged manual placement -- see
    db.py's `tasks.timeline_lane` column) always wins over the computed
    stability preference and is NOT clamped to the natural minimum lane
    count, since the whole point of a manual placement is deliberately
    leaving gaps for visual grouping -- exactly as desktop's
    `manual_lane`/`clamped_preferred` split documents.
    """
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(t.get("list_path") or "tasks", []).append(t)

    def group_sort_key(list_uid: str) -> str:
        return list_names.get(list_uid, "￿" + list_uid)

    prev_local_lane = prev_local_lane or {}
    next_local_lane: dict[str, int] = {}

    row_of: dict[str, int] = {}
    group_labels: list[tuple[int, int, str, str | None]] = []
    group_range_by_list: dict[str | None, tuple[int, int]] = {}
    row_offset = 0

    for list_uid in sorted(groups, key=group_sort_key):
        group_tasks = groups[list_uid]
        intervals = []
        for t in group_tasks:
            dates = _task_dates(t)
            if dates is None:
                continue
            start_d, due_d = dates
            intervals.append((start_d, due_d + timedelta(days=1), t["uid"]))

        manual_lane = {
            t["uid"]: t["timeline_lane"]
            for t in group_tasks
            if isinstance(t.get("timeline_lane"), int)
        }
        natural = pack_intervals(intervals)
        clamped_preferred = {
            uid: prev_local_lane[uid]
            for uid, (_, natural_lanes) in natural.items()
            if uid in prev_local_lane and prev_local_lane[uid] < natural_lanes
        }
        clamped_preferred.update(manual_lane)  # manual placement wins, unclamped
        packed = pack_intervals(intervals, preferred=clamped_preferred)

        lanes_used = 1
        for uid, (lane, lanes) in packed.items():
            row_of[uid] = row_offset + lane
            next_local_lane[uid] = lane
            lanes_used = max(lanes_used, lanes)

        label = list_names.get(list_uid, list_uid)
        group_labels.append((row_offset, lanes_used, label, list_uid))
        group_range_by_list[list_uid] = (row_offset, lanes_used)
        row_offset += lanes_used

    return SwimlaneResult(
        row_of=row_of,
        group_labels=group_labels,
        group_range_by_list=group_range_by_list,
        total_rows=row_offset,
        local_lane_of=next_local_lane,
    )


def month_bounds(base: date, offset_months: int) -> tuple[date, date]:
    """Verbatim port of desktop's `TimelineCanvas._month_bounds` -- first
    and last day of the calendar month `offset_months` away from base's
    month (negative = earlier, positive = later), handling year
    rollover."""
    month_index = base.month - 1 + offset_months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


MONTH_SPAN = 1  # 1 month before and 1 month after today -- 3 months total


def compute_range(tasks: list[dict], today: date | None = None) -> tuple[date, date]:
    """Verbatim port of desktop's `TimelineCanvas._compute_range` --
    calendar-month-aligned default window (previous/current/next month),
    extended to cover any task whose start or due date falls outside it.
    Desktop additionally enforces a 14-day minimum window; irrelevant
    here since a 3-calendar-month window is always well over that."""
    today = today or date.today()
    start, _ = month_bounds(today, -MONTH_SPAN)
    _, end = month_bounds(today, MONTH_SPAN)
    for t in tasks:
        dates = _task_dates(t)
        if dates is None:
            continue
        start_d, due_d = dates
        if start_d < start:
            start = start_d
        if start_d > end:
            end = start_d
        if due_d < start:
            start = due_d
        if due_d > end:
            end = due_d
    return start, end


def grid_line_day_indices(total_days: int) -> list[int]:
    """Every day gets a header label + vertical gridline -- verbatim port
    of desktop's `_grid_line_day_indices` (its final form, after Week/
    Month zoom's coarser gridline modes were both removed and only this
    per-day mode remained)."""
    return list(range(total_days + 1))


def week_start_indices(start: date, total_days: int) -> list[int]:
    """Day offsets where a 'Week NN' heading should be drawn -- verbatim
    port of desktop's `_week_start_indices`: every Monday in range, plus
    day 0 itself if the range doesn't start on a Monday (so a leading
    partial week still gets a heading)."""
    indices = [i for i in range(total_days + 1) if (start + timedelta(days=i)).weekday() == 0]
    if total_days >= 0 and start.weekday() != 0:
        indices = [0] + indices
    return indices


@dataclass
class BarGeometry:
    day_from: int
    day_to: int  # exclusive
    row: int
    color: str


def bar_geometry(
    task: dict, index: int, start: date, total_days: int, row_of: dict[str, int]
) -> BarGeometry | None:
    """Verbatim port of desktop's `TimelineCanvas._bar_rect`'s date/row
    math (the pixel conversion itself is left to the template/CSS, same
    split `grid_layout.py`'s `position_event` already uses for the
    calendar). `day_to` is exclusive (one past the due date's own column,
    consistent with the `+timedelta(days=1)` exclusive-end convention
    `assign_swimlanes`'s interval packing already uses) and always at
    least `day_from + 1` so a same-day task still paints a visible-width
    bar."""
    dates = _task_dates(task)
    if dates is None:
        return None
    start_d, due_d = dates
    day_from = max(0, (start_d - start).days)
    day_to = min(total_days, (due_d - start).days + 1)
    if day_to <= day_from:
        day_to = day_from + 1
    row = row_of.get(task["uid"], 0)
    color = BAR_COLORS[index % len(BAR_COLORS)]
    return BarGeometry(day_from=day_from, day_to=day_to, row=row, color=color)


def default_row_label(list_label: str, local_idx: int) -> str:
    """Verbatim port of desktop's `_default_row_label` -- the list's own
    name for row 0, 'Row N' for every row after it."""
    if local_idx == 0:
        return list_label
    return f"Row {local_idx}"
