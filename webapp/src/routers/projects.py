"""Projects (1.3, Project-enabled label stack, plans/open-priority.md §
Project-enabled label stack). A project is not a separate entity -- it's a
label with `is_project=1` plus a bounded start/end period and a computed
lifecycle (db.project_status). This router owns the dedicated Projects page
(the primary interface the spec calls for), the promote/demote/dates/
archive actions that manage a label's Project behavior, and (1.4) the
project's own detail page + Week Calendar view.

Scope note (1.3 -> 1.4): 1.3 shipped the label + lifecycle + cards half of
the spec. 1.4 slice 2 (2026-08-14) added `project_detail` (`GET
/projects/{name}`) -- the project's own page's Tasks view (§ Project pages
& views: "opening a project provides two principal views"). 1.4 slice 3
(2026-08-13) adds the second: `project_calendar` (`GET
/projects/{name}/calendar`) -- the drag-and-drop scheduling surface, plus
`create_allocation`/`move_allocation`/`delete_allocation` below, which are
plain form-POST wrappers around the already-tested `db.create_work_allocation`
/`delete_work_allocation` (and, for move/resize, a plain `db.upsert_event`
start/end edit -- the same technique `routers/calendar.py`'s own
`reschedule_event` uses, just a synchronous form/redirect endpoint instead
of that route's JSON/fetch contract, to match every other action on this
page). Card progress is still completed/total *task count*, not
completed/total *scheduled work hours* -- `db.task_work_hours` exists
per-task (1.4 slice 1) but nothing aggregates it to project level yet;
still deliberately out of scope for slice 3 too, see plans/STATE.md.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db, grid_layout, recurrence_expand
from ..deps import _week_start, get_db, templates
from . import calendar as calendar_router
from . import tasks as tasks_router

router = APIRouter(prefix="/projects", tags=["projects"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_card(conn, cfg: dict) -> dict:
    name = cfg["name"]
    tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    completed_count = sum(1 for t in tasks if t.get("status") in ("done", "archived"))
    total = len(tasks)
    remaining_count = total - completed_count
    progress = round(completed_count / total * 100) if total else 0
    incomplete_due = sorted(
        t.get("due_at") for t in tasks
        if t.get("status") not in ("done", "archived") and t.get("due_at")
    )
    card = dict(cfg)
    card.update(
        {
            "status": db.project_status(conn, cfg),
            "task_count": total,
            "completed_count": completed_count,
            "remaining_count": remaining_count,
            "progress": progress,
            "upcoming_deadline": incomplete_due[0] if incomplete_due else None,
        }
    )
    return card


@router.get("")
def list_projects(request: Request, conn=Depends(get_db)):
    projects = [_project_card(conn, cfg) for cfg in db.list_project_labels(conn)]
    # Open/Pending/Pending Archiving first (still-live work), Archived last
    # -- an archived project is historical record, not something to hunt
    # for above the projects still being worked on.
    order = {"Open": 0, "Pending": 1, "Pending Archiving": 2, "Archived": 3}
    projects.sort(key=lambda p: (order.get(p["status"], 0), p["name"].lower()))

    overlap_name = request.query_params.get("overlap")
    pending = None
    if overlap_name:
        pending = {
            "name": request.query_params.get("pending_name", ""),
            "start_date": request.query_params.get("pending_start", ""),
            "end_date": request.query_params.get("pending_end", ""),
        }

    # Existing non-project labels -- offered as the promote form's
    # datalist, so promoting reuses a label already applied to real tasks
    # rather than always typing a brand-new name.
    existing_labels = [l["name"] for l in db.list_labels(conn) if not l.get("is_project")]

    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "active_tab": "projects",
            "title": "Projects",
            "projects": projects,
            "overlap_name": overlap_name,
            "pending": pending,
            "existing_labels": existing_labels,
        },
    )


@router.get("/{name}")
def project_detail(name: str, request: Request, conn=Depends(get_db)):
    """The project's own page (1.4, `open-priority.md` § Project pages &
    views): "opening a project provides two principal views" -- this ships
    the first, the Tasks view. The Week Calendar view (the drag-and-drop
    scheduling surface) is a later slice; see plans/STATE.md's breadcrumbs.

    Tasks are filtered the same way `_project_card` counts them -- direct
    `object_labels`-via-`tags` membership, no separate query layer (there's
    no dedicated "tasks for a project" SQL helper; the label filter is
    cheap enough as a plain Python pass, same idiom `_label_scope` in
    routers/labels.py already uses for a label's generated page)."""
    cfg = db.effective_label_config(conn, name)
    if not cfg.get("is_project"):
        return RedirectResponse(url="/projects", status_code=303)
    project = _project_card(conn, cfg)
    tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    # 1.5 slice (deadline-vs-work-allocation surfacing, see routers/
    # tasks.py::list_tasks' matching comment): same batched
    # db.task_work_hours_bulk call so this Tasks view's rows (the shared
    # _task_row.html macro) get their "Scheduled" column without an N+1.
    _hours = db.task_work_hours_bulk(conn, [t["uid"] for t in tasks])
    for t in tasks:
        t["work_hours"] = _hours[t["uid"]]
    open_tasks = [t for t in tasks if t.get("status") not in ("done", "archived")]
    completed_tasks = [t for t in tasks if t.get("status") in ("done", "archived")]
    ctx = tasks_router._task_context(request)
    ctx.update(
        {
            "active_tab": "projects",
            "project": project,
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
        }
    )
    return templates.TemplateResponse("project_detail.html", ctx)


@router.get("/{name}/calendar")
def project_calendar(name: str, request: Request, date_: str | None = None, conn=Depends(get_db)):
    """The project's Week Calendar view (1.4 slice 3, `open-priority.md` §
    Project pages & views' Week Calendar bullet): "the project's scheduling
    surface. Unscheduled tasks are presented above or beside the calendar
    and can be dragged into available time." Reuses the Week grid's own
    layout math (`grid_layout.layout_day`, the same function
    `routers/calendar.py::week_view` calls) rather than reinventing it --
    this is a *different page* over the same week-grid geometry, not a
    duplicate implementation of it (§ Project pages & views: "does not
    attempt to replace the global Calendar").

    Every event in the week is shown (ordinary events as visually subdued
    context per the spec), but only work-allocation events belonging to
    THIS project's own tasks (`is_allocation`) are prominent/interactive --
    a work allocation for a different project's task is still just
    context here, same as any other event."""
    cfg = db.effective_label_config(conn, name)
    if not cfg.get("is_project"):
        return RedirectResponse(url="/projects", status_code=303)
    project = _project_card(conn, cfg)

    anchor = date.fromisoformat(date_) if date_ else date.today()
    week_start_date, week_end_date = calendar_router._week_bounds(anchor, _week_start(request))

    events = db.list_events(
        conn, start=week_start_date.isoformat(), end=week_end_date.isoformat() + "T23:59:59"
    )
    events = recurrence_expand.expand_events(events, week_start_date, week_end_date, db.list_holidays_by_calendar(conn))
    events = calendar_router._annotate_calendar_colors(conn, events)

    # Tag each event with whether it's a work allocation belonging to THIS
    # project's own task -- the only ones that get the prominent/draggable
    # treatment (see docstring above).
    for e in events:
        task_uid = db.work_allocation_task_uid(conn, e["uid"])
        task = db.get_task(conn, task_uid) if task_uid else None
        is_project_allocation = bool(task) and name in (task.get("tags") or [])
        e["is_allocation"] = is_project_allocation
        e["task_uid"] = task_uid if is_project_allocation else None

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
        days.append(
            {
                "date": d,
                "iso": key,
                "is_today": d == date.today(),
                "all_day": day_all_day,
                "timed": timed,
            }
        )

    # Unscheduled tasks (the drag source, § Project pages & views): open
    # project tasks with no work allocation at all yet -- once a task has
    # at least one scheduled block it's represented by that block on the
    # grid instead of staying in this list. Each item's hours are the
    # task's own `db.task_work_hours` remaining total (STATE.md's
    # breadcrumb: "the task's remaining hours from db.task_work_hours,
    # NOT the shared `_task_row.html` macro").
    project_tasks = [t for t in db.list_tasks(conn) if name in (t.get("tags") or [])]
    open_tasks = [t for t in project_tasks if t.get("status") not in ("done", "archived")]
    unscheduled_tasks = []
    for t in open_tasks:
        if db.list_work_allocations_for_task(conn, t["uid"]):
            continue
        hours = db.task_work_hours(conn, t["uid"])
        unscheduled_tasks.append({"task": t, "hours": hours})

    return templates.TemplateResponse(
        "project_calendar.html",
        {
            "request": request,
            "active_tab": "projects",
            "project": project,
            "days": days,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "monday": week_start_date,
            "sunday": week_end_date,
            "prev_week": (week_start_date - timedelta(days=7)).isoformat(),
            "next_week": (week_start_date + timedelta(days=7)).isoformat(),
            "today_iso": date.today().isoformat(),
            "unscheduled_tasks": unscheduled_tasks,
        },
    )


def _calendar_redirect(name: str, date_: str) -> RedirectResponse:
    url = f"/projects/{quote(name)}/calendar"
    if date_:
        url += f"?date_={quote(date_)}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/{name}/calendar/allocations")
def create_allocation(
    name: str,
    task_uid: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag a task from the "unscheduled" list onto the grid -- creates a
    work allocation via the already-tested `db.create_work_allocation`
    (1.4 slice 1), same function the task-detail "Work sessions" card's
    plain form already calls. `task_uid` must actually carry this
    project's label -- defensive re-check, same idiom
    `routers/calendar.py::add_event_relation`'s `_shares_label` re-check
    uses, since the dragged task's identity is client-submitted."""
    task = db.get_task(conn, task_uid)
    if task is not None and name in (task.get("tags") or []) and start_at and end_at and end_at > start_at:
        db.create_work_allocation(conn, task_uid, start_at, end_at)
    return _calendar_redirect(name, date_)


@router.post("/{name}/calendar/allocations/{event_uid}/move")
def move_allocation(
    name: str,
    event_uid: str,
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag-to-move / drag-to-resize an existing work-allocation block.
    Only this project's own work allocations may be moved from here --
    same defensive re-check as create_allocation above. Changes only
    start_at/end_at (a plain `db.upsert_event` edit, the exact technique
    `routers/calendar.py::reschedule_event` already uses for the global
    Week/Day grid's drag -- this is that same operation as a form-POST/
    redirect endpoint instead of that route's JSON/fetch contract, to
    match this page's other actions)."""
    task_uid = db.work_allocation_task_uid(conn, event_uid)
    task = db.get_task(conn, task_uid) if task_uid else None
    if task is not None and name in (task.get("tags") or []) and start_at and end_at and end_at > start_at:
        existing = db.get_event(conn, event_uid)
        if existing is not None:
            row = dict(existing)
            row["start_at"] = start_at
            row["end_at"] = end_at
            row["updated_at"] = _now()
            db.upsert_event(conn, row)
    return _calendar_redirect(name, date_)


@router.post("/{name}/calendar/allocations/{event_uid}/delete")
def delete_allocation(name: str, event_uid: str, date_: str = Form(""), conn=Depends(get_db)):
    """"Deleting a work allocation removes only that scheduled block -- not
    the task." (§ Task & calendar semantics) -- db.delete_work_allocation
    is delete_event under a name that states that explicitly at the call
    site, same as the task-detail card's own remove_work_allocation."""
    db.delete_work_allocation(conn, event_uid)
    return _calendar_redirect(name, date_)


def _redirect_with_conflict(name: str, start_date: str, end_date: str, conflict_name: str) -> RedirectResponse:
    url = (
        f"/projects?overlap={quote(conflict_name)}"
        f"&pending_name={quote(name)}&pending_start={quote(start_date)}&pending_end={quote(end_date)}"
    )
    return RedirectResponse(url=url, status_code=303)


@router.post("/promote")
def promote(
    name: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    confirm_overlap: str = Form(""),
    conn=Depends(get_db),
):
    """Turn a label into a project -- empty labels are valid promotion
    targets (§ Projects are labels, not a stored thing), so this works
    identically whether `name` already has real object_labels membership
    or is being typed fresh (upsert_label_config creates the label_config
    row either way, same as set_label already does for color/icon)."""
    name = name.strip()
    start_date = start_date.strip()
    end_date = end_date.strip()
    if not name or not start_date or not end_date:
        return RedirectResponse(url="/projects", status_code=303)
    conflict = db.find_overlapping_project(conn, name, start_date, end_date)
    if conflict and confirm_overlap not in ("1", "true", "on"):
        return _redirect_with_conflict(name, start_date, end_date, conflict["name"])
    db.upsert_label_config(
        conn,
        {
            "name": name,
            "is_project": 1,
            "start_date": start_date,
            "end_date": end_date,
            "archived_at": None,
            "created_at": _now(),
        },
    )
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{name}/dates")
def set_dates(
    name: str,
    start_date: str = Form(...),
    end_date: str = Form(...),
    confirm_overlap: str = Form(""),
    conn=Depends(get_db),
):
    start_date = start_date.strip()
    end_date = end_date.strip()
    conflict = db.find_overlapping_project(conn, name, start_date, end_date)
    if conflict and confirm_overlap not in ("1", "true", "on"):
        return _redirect_with_conflict(name, start_date, end_date, conflict["name"])
    db.upsert_label_config(conn, {"name": name, "start_date": start_date, "end_date": end_date})
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{name}/demote")
def demote(name: str, conn=Depends(get_db)):
    """Removes Project behavior -- the label and every entity carrying it
    stay exactly as-is (§ Projects are labels, not a stored thing: "removing
    Project behavior drops its project-specific semantics and views but
    preserves the label and every entity associated with it")."""
    db.upsert_label_config(conn, {"name": name, "is_project": 0, "start_date": None, "end_date": None, "archived_at": None})
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{name}/archive")
def archive(name: str, conn=Depends(get_db)):
    """The user's explicit confirmation that a project is finished (§
    Project lifecycle) -- never automatic, see db.project_status."""
    db.archive_project(conn, name)
    return RedirectResponse(url="/projects", status_code=303)
