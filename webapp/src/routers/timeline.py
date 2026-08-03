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
from ..deps import get_bridge, get_db, templates

router = APIRouter(tags=["timeline"])

DAY_WIDTH = 24
ROW_HEIGHT = 36
HEADER_HEIGHT = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_context(conn) -> dict:
    task_lists = db.list_task_lists(conn)
    list_names = {l["uid"]: l["name"] for l in task_lists}
    list_row_names = {l["uid"]: l["timeline_row_names"] for l in task_lists}

    tasks = [t for t in db.list_tasks(conn) if t.get("due_at") and t["status"] != "archived"]

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
    swimlanes = tl.assign_swimlanes(tasks, list_names)

    bars = []
    for index, task in enumerate(tasks):
        geo = tl.bar_geometry(task, index, start, total_days, swimlanes.row_of)
        if geo is None:
            continue
        list_uid = task.get("list_path") or "tasks"
        group_start, group_lanes = swimlanes.group_range_by_list.get(list_uid, (0, 1))
        bars.append(
            {
                "task": task,
                "day_from": geo.day_from,
                "day_to": geo.day_to,
                "row": geo.row,
                "color": geo.color,
                "left_px": geo.day_from * DAY_WIDTH,
                "width_px": max((geo.day_to - geo.day_from) * DAY_WIDTH, 4),
                "top_px": HEADER_HEIGHT + geo.row * ROW_HEIGHT + 6,
                "height_px": ROW_HEIGHT - 12,
                # Own list + local lane (row within just this list's own
                # swimlane block) + how many lanes that block currently
                # has -- what a vertical drag (static/timeline.js) needs
                # to compute a target *local* lane the same way desktop's
                # mouseReleaseEvent does (`_drag_orig_local_lane +
                # delta_rows`, clamped to `group_lanes + 4`), rather than
                # hit-testing whatever DOM element happens to be under the
                # cursor -- desktop never does that either; a vertical
                # drag can only ever move a task within its own list's
                # block, not onto some other list's rows.
                "list_path": list_uid,
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
    for row_start, row_count, label, list_uid in swimlanes.group_labels:
        row_names = list_row_names.get(list_uid, {})
        for local_idx in range(row_count):
            default_label = tl.default_row_label(label, local_idx)
            display_label = row_names.get(str(local_idx)) or default_label
            rows.append(
                {
                    "global_row": row_start + local_idx,
                    "local_idx": local_idx,
                    "list_uid": list_uid,
                    "is_header": local_idx == 0,
                    "label": display_label,
                    "default_label": default_label,
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
        "task_lists": task_lists,
    }


@router.get("/tasks/timeline")
def timeline_view(request: Request, conn=Depends(get_db)):
    ctx = _build_context(conn)
    ctx.update({"request": request, "active_tab": "tasks"})
    return templates.TemplateResponse("tasks_timeline.html", ctx)


@router.post("/tasks/{uid}/timeline-reschedule")
async def timeline_reschedule(uid: str, request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """JSON endpoint for drag-to-move / drag-to-resize (static/
    timeline.js) -- day-granularity start_at/due_at only, same minimal-
    surface pattern as calendar.js's /events/{uid}/reschedule. A task
    still round-trips through the bridge here (unlike timeline_lane,
    start_at/due_at ARE real synced fields)."""
    payload = await request.json()
    existing = db.get_task(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["start_at"] = payload["start_at"]
    row["due_at"] = payload["due_at"]
    row["updated_at"] = _now()
    saved = bridge.save_task_row(row)
    db.upsert_task(conn, saved)
    return JSONResponse({"ok": True, "start_at": saved.get("start_at"), "due_at": saved.get("due_at")})


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
async def timeline_create(request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Click-and-drag-to-create on empty grid space (static/timeline.js)
    -- turns a selected (list, date-range, row) into a real task, landing
    in the exact row that was dragged across via the same manual-
    placement mechanism a vertical bar drag uses. Mirrors desktop's
    `_finish_create_drag`."""
    import uuid

    payload = await request.json()
    list_path = payload.get("list_path") or db.DEFAULT_TASK_LIST_UID
    start_at = payload["start_at"]
    due_at = payload["due_at"]
    local_idx = payload.get("local_idx")

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
        "list_path": list_path,
        "created_at": now,
        "updated_at": now,
    }
    saved = bridge.save_task_row(row)
    db.upsert_task(conn, saved)
    if local_idx is not None:
        db.set_task_timeline_lane(conn, saved["uid"], int(local_idx))
    return JSONResponse({"ok": True, "uid": saved["uid"]})


@router.post("/task-lists/{uid}/timeline-row-name")
async def timeline_row_name(uid: str, request: Request, conn=Depends(get_db)):
    """Double-click a gutter label to rename it (static/timeline.js) --
    port of desktop's `_rename_row`/`_set_row_name`. Local-only, see
    set_task_list_row_name."""
    payload = await request.json()
    local_idx = int(payload.get("local_idx", 0))
    name = (payload.get("name") or "").strip()
    db.set_task_list_row_name(conn, uid, local_idx, name or None)
    return JSONResponse({"ok": True})
