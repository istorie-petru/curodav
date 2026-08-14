"""Week -- planning (1.7 slice 2, plans/open-priority.md § Information
architecture & view surfaces' "Week -- planning" bullet): "How should I
allocate my time over the coming week?" A cross-project scheduling surface
-- every open task with no work allocation yet, across every project (or
none), draggable onto a real week grid alongside existing calendar
commitments and due dates.

Deliberately NOT a third copy of the week-grid geometry: reuses
`grid_layout.layout_day` (the same function `routers/calendar.py::week_view`
and `routers/projects.py::project_calendar` already call) and this page's
own create/move/delete allocation endpoints below are the same shape as
`routers/projects.py`'s `create_allocation`/`move_allocation`/
`delete_allocation`, just without the "must carry this project's label"
scoping -- any open task is fair game for the *global* planning surface,
where `routers/projects.py`'s trio deliberately only accepts one project's
own tasks (that page's job is "when can I do THIS project's work", this
page's job is "how do I spend the week overall"). The client-side drag/
resize interaction is `static/project_calendar.js` verbatim (its own
`window.PROJECT_CALENDAR` config object, just pointed at this page's
endpoints) -- same generic class-selector script, no second copy of that
logic either.

This is a *different page* from the global Calendar's own Week view
(`routers/calendar.py::week_view`, `/calendar/week`): that one is the
direct management surface for events ("what's on my calendar this week"),
this one is the planning surface for unscheduled work ("what should I do
with my open time this week"). Both render the same underlying events, just
for different purposes -- see `open-priority.md`'s "Core management views"
note: "Other surfaces provide contextual projections of these entities
rather than duplicating their management logic.\""""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db, grid_layout, recurrence_expand
from ..deps import _week_start, get_db, templates
from . import calendar as calendar_router

router = APIRouter(prefix="/week", tags=["week"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
def week_view(request: Request, date_: str | None = None, conn=Depends(get_db)):
    anchor = date.fromisoformat(date_) if date_ else date.today()
    week_start_date, week_end_date = calendar_router._week_bounds(anchor, _week_start(request))

    events = db.list_events(
        conn, start=week_start_date.isoformat(), end=week_end_date.isoformat() + "T23:59:59"
    )
    events = recurrence_expand.expand_events(
        events, week_start_date, week_end_date, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn)
    )
    events = calendar_router._annotate_calendar_colors(conn, events)

    # Every work-allocation event is schedulable-work-made-visible on this
    # page (prominent), regardless of which task/project it belongs to --
    # unlike routers/projects.py::project_calendar, which only prominents
    # ONE project's own allocations and treats every other event (including
    # other projects' own allocations) as subdued context. This page's
    # whole point is seeing all scheduled work at once.
    for e in events:
        task_uid = db.work_allocation_task_uid(conn, e["uid"])
        e["is_allocation"] = bool(task_uid)
        e["task_uid"] = task_uid

    open_tasks = [t for t in db.list_tasks(conn) if t.get("status") not in ("done", "archived")]

    days = []
    for i in range(7):
        d = week_start_date + timedelta(days=i)
        key = d.isoformat()
        day_events = [e for e in events if e.get("start_at", "").startswith(key)]
        timed = grid_layout.layout_day(day_events)
        day_all_day = []
        for e in events:
            if not e.get("all_day"):
                continue
            rng = calendar_router._event_date_range(e)
            if rng and rng[0] <= d <= rng[1]:
                day_all_day.append(e)
        # Due-today chips (open tasks only -- a planning surface cares about
        # what's still outstanding, not a completed task's historical due
        # date), same "which day does this task's due_at fall on" match
        # routers/calendar.py::week_view's own day_tasks uses.
        day_due_tasks = [t for t in open_tasks if (t.get("due_at") or "").startswith(key)]
        days.append(
            {
                "date": d,
                "iso": key,
                "is_today": d == date.today(),
                "all_day": day_all_day,
                "timed": timed,
                "due_tasks": day_due_tasks,
            }
        )

    # Unscheduled work (the drag source): every open task with no work
    # allocation at all yet, across every project (or none) -- same
    # "already-allocated tasks drop off the list entirely" rule
    # project_calendar's own unscheduled_tasks uses, just not scoped to one
    # project's label. Sorted by due date (earliest/most time-pressured
    # first), no-due-date tasks last. Each item carries its
    # db.work_allocation_panel_info summary (session count + scheduled/total
    # hours) for the stepper and x/y readout the shared
    # _unscheduled_task_item.html partial renders.
    unscheduled_tasks = []
    for t in open_tasks:
        # Unscheduled = no work session at all, OR any session still has no
        # date (a "+"-added placeholder from the task modal's Work sessions
        # card awaiting placement on a grid -- see db.create_work_allocation's
        # undated form). Only a task whose every session is dated has nothing
        # left to place, so only those drop off the panel.
        info = db.work_allocation_panel_info(conn, t["uid"])
        if info["count"] and not info["undated_count"]:
            continue
        project = db.project_label_config_for(conn, "task", t["uid"])
        unscheduled_tasks.append({"task": t, "project": project, "sessions": info})
    unscheduled_tasks.sort(key=lambda item: item["task"].get("due_at") or "9999-99-99")

    return templates.TemplateResponse(
        "week_planning.html",
        {
            "request": request,
            "active_tab": "week",
            "days": days,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "monday": week_start_date,
            "sunday": week_end_date,
            "prev_week": (week_start_date - timedelta(days=7)).isoformat(),
            "next_week": (week_start_date + timedelta(days=7)).isoformat(),
            "unscheduled_tasks": unscheduled_tasks,
            "unscheduled_next": f"/week?date_={week_start_date.isoformat()}",
        },
    )


def _week_redirect(date_: str) -> RedirectResponse:
    url = "/week"
    if date_:
        url += f"?date_={date_}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/allocations")
def create_allocation(
    task_uid: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag a task from the "Unscheduled work" list onto the grid. Any open
    task is a valid drop target here (no project-membership re-check --
    unlike routers/projects.py::create_allocation, this page isn't scoped
    to one project's tasks); still re-validates the task exists and the
    dropped range is well-formed, same defensive shape as that endpoint."""
    task = db.get_task(conn, task_uid)
    if task is not None and task.get("status") not in ("done", "archived") and start_at and end_at and end_at > start_at:
        # A task with an undated session placeholder (added via the task
        # modal's Work sessions "+" button) gets THAT session placed onto
        # the dropped slot instead of creating yet another block; a task
        # with no sessions yet creates its first dated block, as before.
        undated = db.first_undated_work_allocation_for_task(conn, task_uid)
        if undated:
            db.set_work_allocation_times(conn, undated["uid"], start_at, end_at)
        else:
            db.create_work_allocation(conn, task_uid, start_at, end_at)
    return _week_redirect(date_)


@router.post("/allocations/{event_uid}/move")
def move_allocation(
    event_uid: str,
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag-to-move / drag-to-resize an existing work-allocation block --
    only a real work-allocation event may be moved from here (re-checked via
    db.work_allocation_task_uid, same idiom routers/projects.py::
    move_allocation uses for its own project-scoped re-check)."""
    task_uid = db.work_allocation_task_uid(conn, event_uid)
    if task_uid and start_at and end_at and end_at > start_at:
        existing = db.get_event(conn, event_uid)
        if existing is not None:
            row = dict(existing)
            row["start_at"] = start_at
            row["end_at"] = end_at
            row["updated_at"] = _now()
            db.upsert_event(conn, row)
    return _week_redirect(date_)


@router.post("/allocations/{event_uid}/delete")
def delete_allocation(event_uid: str, date_: str = Form(""), conn=Depends(get_db)):
    """Unschedule a block (the block's own delete button, or dragging it
    back onto the "Unscheduled work" panel) -- clears this ONE session's
    start/end back to undated (`db.unschedule_work_allocation`) instead of
    deleting it outright. The task's total session count never changes just
    because a session was moved off the calendar; only the panel's own +/-
    stepper (or the task's Work sessions card) adds/removes sessions. Went
    through two earlier same-day (2026-08-14) designs, both wrong in
    opposite directions: first this collapsed the task's ENTIRE session
    count down to one undated placeholder on any single unschedule
    (discarding the task's other sessions); the fix for that swapped in a
    hard `db.delete_work_allocation` (deleting just this one session for
    real) -- which then made a single-session task's count visibly drop to
    0 the moment you unscheduled its only block, since "unschedule" isn't
    "I don't need this session anymore." Unscheduling should never change
    the count either way, so this route name still says "/delete" (URL
    compat, other code links to it) but no longer deletes anything for a
    real work allocation -- `unschedule_work_allocation` falls back to
    `delete_work_allocation` only if `event_uid` isn't a work-allocation
    event at all (nothing to unschedule)."""
    if not db.unschedule_work_allocation(conn, event_uid):
        db.delete_work_allocation(conn, event_uid)
    return _week_redirect(date_)
