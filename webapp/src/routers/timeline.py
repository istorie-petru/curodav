"""Timeline (Gantt) view (Phase 11) -- port of desktop's
`features/tasks/timeline_view.py`. See `timeline_layout.py` for the
ported algorithms (interval packing, swimlane assignment, calendar-aligned
window, bar geometry) -- this router turns that data into a template
context and owns the handful of endpoints the drag interactions
(static/timeline.js) call.

Deliberate, documented scope reduction from desktop: no custom right-click
context menu (status-set/duplicate/delete via right-click). Desktop's
`contextMenuEvent` is a genuinely separate feature from the core Gantt
mechanics (drag reschedule/resize, swimlanes, zoom-aligned range, bar
rendering, row renaming) that this port focuses on faithfully
reproducing; double-click a bar to open it (same as every other object
card in this app) covers the primary navigation need. Every other
documented behavior -- including the specific bug fixes desktop's history
records (single-day/no-start right-resize, narrow-bar hit-test split,
week-label clipping, stability-without-clamping) -- is reproduced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, timeline_layout as tl
from ..deps import get_db, templates
from .labels import CAL_COLOR_FOREGROUND, CAL_COLOR_HEX
from .tasks import (
    DATE_FILTER_LABELS,
    DATE_FILTERS,
    IMPORTANCE_FILTER_LABELS,
    IMPORTANCE_FILTERS,
    STATUS_FILTER_LABELS,
    STATUS_FILTERS,
    URGENCY_FILTER_LABELS,
    URGENCY_FILTERS,
    _active_filter_count,
    _apply_date_filter,
    _apply_importance_filter,
    _apply_label_filter,
    _apply_status_filter,
    _apply_urgency_filter,
    _task_label_rules,
)

router = APIRouter(tags=["timeline"])

DAY_WIDTH = 24
ROW_HEIGHT = 36
HEADER_HEIGHT = 40

# Neutral fallback for the "(No label)" block -- it has no label_config
# to carry an assigned color, so it paints gray (style.css's cal-gray).
# 2026-08-09: unified medium swatch set (see CAL_COLOR_HEX) -- the gray
# medium-tone background / white foreground here back the `color` fields
# for anything still reading a hex; the *rendered* paint is CSS vars
# (--cal-bg-* / --cal-fg-*), which are theme-independent now.
NO_LABEL_BLOCK_COLOR = "#70767d"
NO_LABEL_BLOCK_FOREGROUND = "#ffffff"


def _label_block_appearance(conn, label_key: str, display_label: str) -> tuple[str, str]:
    """(color_name, icon) for one timeline label block -- the label's own
    assigned color/icon from `label_config` (matched case-insensitively,
    since labels are deduped case-insensitively), so a block's task bars
    paint the label's pastel tint while the gutter header icon paints its
    hue-matched foreground, both via CSS variables (the bar's
    `var(--cal-bg-{color_name})`, the icon's `var(--cal-fg-{color_name})`)
    so the swatch set's light/dark theme variants apply automatically.
    The "(No label)" block has no config: neutral gray + the generic tag
    icon. `color_name` (not a hex) is what the template needs; the hex
    fields on bars/rows are derived from it for anything reading a value."""
    if label_key == tl.NO_LABEL_KEY:
        return "gray", "tag"
    cfg = db.effective_label_config_ci(conn, display_label)
    return cfg.get("color") or "gray", cfg.get("icon") or "tag"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_context(
    conn,
    q: str | None = None,
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
    label: str | None = None,
) -> dict:
    # Timeline's gutter is organized by *label*: assign_swimlanes groups
    # tasks by their first tag (timeline_layout.py's task_label_key -- the
    # same `object_labels`-backed tags Table/Board/Calendar already show),
    # so each distinct label gets its own swimlane block whose header row
    # shows the label's name, and untagged tasks fall into a trailing
    # "(No label)" block. This replaces the Phase 1 (label-space rework)
    # dead `task_lists` grouping -- `list_names`/`list_row_names` (and the
    # per-row rename endpoint they backed) are gone with `task_lists`.

    # 2026-08-07: `q` added so Timeline's toolbar can offer the same
    # search box Table/Board already have (features/architecture.md
    # Phase 9's toolbar-consistency pass) -- filters which tasks get laid
    # out as bars, same title-substring match `db.list_tasks` already does
    # for every other view.
    tasks = [t for t in db.list_tasks(conn, q=q) if t.get("due_at") and t["status"] != "archived"]
    # Phase 9b toolbar rework: Timeline gains the same date/status/
    # importance/urgency/label filters Table/Board already have, reusing
    # the exact same helpers rather than duplicating the filtering logic
    # (see routers/tasks.py). Archived tasks are already excluded above by
    # Timeline's own long-standing convention (a Gantt bar for something
    # already done/archived isn't useful), so picking `status_filter=
    # archived` here yields an empty timeline rather than reintroducing
    # them -- a deliberate, narrow edge case, not a bug.
    label_rules = _task_label_rules(conn)
    tasks = _apply_date_filter(tasks, date_filter, label_rules)
    tasks = _apply_status_filter(tasks, status_filter)
    tasks = _apply_importance_filter(tasks, importance_filter)
    tasks = _apply_urgency_filter(tasks, urgency_filter)
    tasks = _apply_label_filter(tasks, label)

    start, end = tl.compute_range(tasks)
    total_days = max((end - start).days, 14)

    # Stability preference (desktop's `prev_local_lane`) has no natural
    # home in a stateless request/response cycle -- there's no in-memory
    # canvas session to remember a prior layout against. Manual placement
    # (`timeline_lane`, persisted in the DB and always honored, see
    # assign_swimlanes) covers the actual use case that mattered
    # ("don't let my deliberately-placed task jump around"); auto-packed
    # tasks recompute fresh each page load, which is the correct behavior
    # for a page that can be reloaded from a different device/session
    # anyway.
    swimlanes = tl.assign_swimlanes(tasks)

    # Resolve each block's color + icon once (from the label's own
    # config), then hand them to both the block's bars and gutter rows so
    # the label reads as the color of its tasks.
    block_appearance = {
        label_key: _label_block_appearance(conn, label_key, label)
        for _row_start, _row_count, label, label_key in swimlanes.group_labels
    }
    bars = []
    for index, task in enumerate(tasks):
        geo = tl.bar_geometry(task, start, total_days, swimlanes.row_of)
        if geo is None:
            continue
        label_key = tl.task_label_key(task)
        group_start, group_lanes = swimlanes.group_range_by_label.get(label_key, (0, 1))
        color_name = block_appearance[label_key][0]
        bars.append(
            {
                "task": task,
                "day_from": geo.day_from,
                "day_to": geo.day_to,
                "row": geo.row,
                # The label's own assigned color -- every task under a
                # label paints the same color as that label (its gutter
                # header icon), so the label reads as "the color of its
                # tasks" (see _label_block_appearance). `color_name`
                # feeds the CSS var the bar's background uses
                # (var(--cal-bg-{color_name})); `color` is the light-
                # theme hex, kept for anything reading a concrete value.
                "color_name": color_name,
                "color": CAL_COLOR_HEX.get(color_name, NO_LABEL_BLOCK_COLOR),
                "left_px": geo.day_from * DAY_WIDTH,
                "width_px": max((geo.day_to - geo.day_from) * DAY_WIDTH, 4),
                "top_px": HEADER_HEIGHT + geo.row * ROW_HEIGHT + 6,
                "height_px": ROW_HEIGHT - 12,
                # Own label + local lane (row within just this label's own
                # swimlane block) + how many lanes that block currently
                # has -- what a vertical drag (static/timeline.js) needs
                # to compute a target *local* lane the same way desktop's
                # mouseReleaseEvent does (`_drag_orig_local_lane +
                # delta_rows`, clamped to `group_lanes + 4`), rather than
                # hit-testing whatever DOM element happens to be under the
                # cursor -- desktop never does that either; a vertical
                # drag can only ever move a task within its own label's
                # block, not onto some other label's rows.
                "label_key": label_key,
                "local_idx": geo.row - group_start,
                "group_lanes": group_lanes,
            }
        )

    day_headers = [
        {"index": i, "x_px": i * DAY_WIDTH, "day_number": (start + timedelta(days=i)).strftime("%d")}
        for i in tl.grid_line_day_indices(total_days)
        if i < total_days
    ]

    week_indices = tl.week_start_indices(start, total_days)
    week_headers = []
    for pos, i in enumerate(week_indices):
        d = start + timedelta(days=i)
        next_i = week_indices[pos + 1] if pos + 1 < len(week_indices) else total_days
        week_headers.append(
            {
                "x_px": i * DAY_WIDTH,
                "width_px": max((next_i - i) * DAY_WIDTH, 0),
                "label": f"Week {d.isocalendar()[1]}",
            }
        )

    rows = []
    for row_start, row_count, label, label_key in swimlanes.group_labels:
        block_color_name, block_icon = block_appearance[label_key]
        for local_idx in range(row_count):
            rows.append(
                {
                    "global_row": row_start + local_idx,
                    "local_idx": local_idx,
                    "label_key": label_key,
                    "is_header": local_idx == 0,
                    "label": tl.default_row_label(label, local_idx),
                    "group_label": label,
                    # The block's label color + icon, rendered on the
                    # header (is-header) gutter row as a colored icon to
                    # the left of the label text (the text itself stays
                    # uncolored). `color_name` feeds the CSS var the icon
                    # paints with (var(--cal-fg-{color_name})) so the
                    # swatch set's dark-theme foreground applies
                    # automatically; `color` is that var's light-theme
                    # value, kept for anything reading a concrete hex.
                    "color_name": block_color_name,
                    "color": CAL_COLOR_FOREGROUND.get(block_color_name, NO_LABEL_BLOCK_FOREGROUND),
                    "icon": block_icon,
                    "top_px": HEADER_HEIGHT + (row_start + local_idx) * ROW_HEIGHT,
                }
            )

    return {
        "start": start.isoformat(),
        "total_days": total_days,
        "total_rows": swimlanes.total_rows,
        "day_width": DAY_WIDTH,
        "row_height": ROW_HEIGHT,
        "header_height": HEADER_HEIGHT,
        "grid_width_px": total_days * DAY_WIDTH,
        "grid_height_px": swimlanes.total_rows * ROW_HEIGHT,
        "day_headers": day_headers,
        "week_headers": week_headers,
        "rows": rows,
        "bars": bars,
    }


@router.get("/tasks/timeline")
def timeline_view(
    request: Request,
    q: str | None = None,
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
    label: str | None = None,
    conn=Depends(get_db),
):
    ctx = _build_context(
        conn,
        q=q,
        date_filter=date_filter,
        status_filter=status_filter,
        importance_filter=importance_filter,
        urgency_filter=urgency_filter,
        label=label,
    )
    ctx.update(
        {
            "request": request,
            "active_tab": "tasks",
            "q": q or "",
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "status_filters": STATUS_FILTERS,
            "status_filter_labels": STATUS_FILTER_LABELS,
            "importance_filters": IMPORTANCE_FILTERS,
            "importance_filter_labels": IMPORTANCE_FILTER_LABELS,
            "urgency_filters": URGENCY_FILTERS,
            "urgency_filter_labels": URGENCY_FILTER_LABELS,
            "active_date_filter": date_filter,
            "active_status_filter": status_filter,
            "active_importance_filter": importance_filter,
            "active_urgency_filter": urgency_filter,
            "active_label": label or "",
            "task_label_names": db.list_task_label_names(conn),
            "active_filter_count": _active_filter_count(
                date_filter, status_filter, importance_filter, urgency_filter, label
            ),
        }
    )
    return templates.TemplateResponse("tasks_timeline.html", ctx)


@router.post("/tasks/{uid}/timeline-reschedule")
async def timeline_reschedule(uid: str, request: Request, conn=Depends(get_db)):
    """JSON endpoint for drag-to-move / drag-to-resize (static/
    timeline.js) -- day-granularity start_at/due_at only, same minimal-
    surface pattern as calendar.js's /events/{uid}/reschedule. Plain SQL
    write (Phase 1, label-space rework) -- no bridge in this path anymore,
    see db.py's Phase 1 comments."""
    payload = await request.json()
    existing = db.get_task(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["start_at"] = payload["start_at"]
    row["due_at"] = payload["due_at"]
    row["updated_at"] = _now()
    db.upsert_task(conn, row)
    return JSONResponse({"ok": True, "start_at": row.get("start_at"), "due_at": row.get("due_at")})


@router.post("/tasks/{uid}/timeline-lane")
async def timeline_set_lane(uid: str, request: Request, conn=Depends(get_db)):
    """Manual vertical placement within a task's list swimlane block (a
    completed 'move' drag with a vertical component -- static/
    timeline.js). Local-only, no bridge involved (see db.py's
    `tasks.timeline_lane` column comment) -- this is display layout, not
    a real task field any other CalDAV client would understand."""
    payload = await request.json()
    lane = payload.get("lane")
    db.set_task_timeline_lane(conn, uid, int(lane) if lane is not None else None)
    return JSONResponse({"ok": True})


@router.post("/tasks/timeline/create")
async def timeline_create(request: Request, conn=Depends(get_db)):
    """Click-and-drag-to-create on empty grid space (static/timeline.js)
    -- turns a selected (date-range, row) into a real task, landing in the
    exact row that was dragged across via the same manual-placement
    mechanism a vertical bar drag uses. Mirrors desktop's
    `_finish_create_drag`. Plain SQL write (Phase 1, label-space rework)
    -- `list_path` is gone (see db.py's Phase 1 comments and this
    router's `_build_context` comment above). Since the gutter is now
    organized by label (each block's rows carry its label), dragging in a
    labeled block carries that label's name through and attaches it to the
    new task so it lands back in the same block on the next layout; a
    drag on the "(No label)" block just creates an unlabeled task."""
    import uuid

    payload = await request.json()
    start_at = payload["start_at"]
    due_at = payload["due_at"]
    local_idx = payload.get("local_idx")
    label = (payload.get("label") or "").strip()

    now = _now()
    row = {
        "uid": str(uuid.uuid4()),
        "title": "New task",
        "description": "",
        "start_at": start_at,
        "due_at": due_at,
        "status": "active",
        "progress": 0.0,
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_task(conn, row)
    if label:
        db.set_object_labels(conn, "task", row["uid"], [label])
    if local_idx is not None:
        db.set_task_timeline_lane(conn, row["uid"], int(local_idx))
    return JSONResponse({"ok": True, "uid": row["uid"]})


# Double-clicking a gutter label used to rename a task-list row (POST
# /task-lists/{uid}/timeline-row-name) -- Phase 1 of the label-space
# rework dropped that endpoint and `task_lists` itself. Gutter rows are
# now generated directly from labels (see `_build_context`), so there is
# no client-side rename handler to point at a removed endpoint anymore.
