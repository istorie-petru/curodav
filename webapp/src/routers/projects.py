"""Projects (1.3, Project-enabled label stack, plans/open-priority.md §
Project-enabled label stack). A project is not a separate entity -- it's a
label with `is_project=1` plus a bounded start/end period and a computed
lifecycle (db.project_status). This router owns the dedicated Projects page
(the primary interface the spec calls for), the promote/demote/dates/
archive actions that manage a label's Project behavior, and (1.4) the
project's own detail page.

Scope note (1.3 vs 1.4/1.5): 1.3 shipped the label + lifecycle + cards half
of the spec. 1.4 slice 2 (2026-08-14) added `project_detail` (`GET
/projects/{name}`) -- the project's own page, currently just its Tasks
view (§ Project pages & views: "opening a project provides two principal
views"). The Week Calendar view (the drag-and-drop scheduling surface) is
still open -- see plans/STATE.md's breadcrumbs. Card progress is still
completed/total *task count*, not completed/total *scheduled work hours* --
`db.task_work_hours` exists per-task (1.4 slice 1) but nothing aggregates it
to project level yet; this is the interim "counting pattern" STATE.md's 1.3
breadcrumb calls for, reusing derived_state.py-style counting rather than
inventing a second one to reconcile later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates
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
