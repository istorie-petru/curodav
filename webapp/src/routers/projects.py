"""Projects (1.3, Project-enabled label stack, plans/open-priority.md §
Project-enabled label stack). A project is not a separate entity -- it's a
label with `is_project=1` plus a bounded start/end period and a computed
lifecycle (db.project_status). This router owns the promote/demote/dates/
archive actions that manage a label's Project behavior.

Scope note (2026-08-15, "Retire the standalone /projects page" -- see
plans/open.md's decision record): 1.3 shipped a dedicated `/projects`
listing page and 1.4 added its two child views (`project_detail`'s Tasks
view, `project_calendar`'s Week Calendar view). All three page routes are
now GONE, per direct feedback that they were redundant with capability that
already exists elsewhere -- the Tasks view duplicated `/tasks?group_by=
project` (1.5), and the Week Calendar view duplicated the merged
`/calendar/week` grid (2026-08-14 side work), which already shows every
work allocation regardless of project. `GET /projects` and `GET
/projects/{name}` now just redirect (any bookmark still lands somewhere
real -- same precedent as `/today`/`/week`/`/calendar/timetable`'s own
retirements). This was **presentation-only**: `promote`/`set_dates`/
`demote`/`archive` below are completely unchanged, still the only way a
label gains/loses Project behavior, still reached from Settings > Labels
(routers/labels.py). `_project_card`'s project-scoped calendar
(create/move/delete allocation) is gone too -- it was that removed page's
own drag-and-drop backend, not used anywhere else (the global `/calendar/
week` grid has its own independent, cross-project allocation endpoints in
routers/calendar.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db

router = APIRouter(prefix="/projects", tags=["projects"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
def list_projects_redirect():
    """The `/projects` listing page is gone (see this module's docstring)
    -- redirect to the Table view, the closest existing equivalent.

    2026-08-28 "major rework" session update: `?group_by=project` dropped
    from this URL -- the Table view's grouping is unconditional now (every
    project gets its own group automatically, see routers/tasks.py's
    _build_task_groups), so the query param has nothing left to opt into
    and would just be silently ignored by list_tasks."""
    return RedirectResponse(url="/tasks", status_code=302)


@router.get("/{name}")
def project_detail_redirect(name: str):
    """The project detail page (Tasks view + Week Calendar view) is gone
    (see this module's docstring) -- redirect to the global Tasks table,
    the closest existing equivalent.

    2026-08-28 "major rework" session update: this used to redirect to
    `/tasks?label={name}`, pre-filtered to just this project -- the Table
    view's label filter is gone entirely now (item 3, "filtering reduced
    to date only"), so there's no query param left to carry the same
    precision. Landing on the plain Table view still surfaces this
    project's tasks, just as one of its own groups rather than the whole
    page scoped to it -- the smaller, safer change per this session's own
    scoping instructions, not a redesign of the redirect's purpose."""
    return RedirectResponse(url="/tasks", status_code=302)


@router.get("/{name}/calendar")
def project_calendar_redirect(name: str):
    """The project's Week Calendar view is gone (see this module's
    docstring) -- redirect the same place project_detail_redirect does;
    the merged `/calendar/week` grid already shows this project's work
    allocations, just not pre-filtered to only them."""
    return RedirectResponse(url="/tasks", status_code=302)


def _redirect_with_conflict(name: str, start_date: str, end_date: str, conflict_name: str) -> RedirectResponse:
    # Targets /labels, not /projects -- promote/dates now live entirely on
    # Settings > Labels (see list_projects' docstring above), so the
    # overlap warning needs to surface where the form that triggered it
    # actually is.
    url = (
        f"/labels?overlap={quote(conflict_name)}"
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
        return RedirectResponse(url="/settings/labels", status_code=303)
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
    return RedirectResponse(url="/settings/labels", status_code=303)


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
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/demote")
def demote(name: str, conn=Depends(get_db)):
    """Removes Project behavior -- the label and every entity carrying it
    stay exactly as-is (§ Projects are labels, not a stored thing: "removing
    Project behavior drops its project-specific semantics and views but
    preserves the label and every entity associated with it")."""
    db.upsert_label_config(conn, {"name": name, "is_project": 0, "start_date": None, "end_date": None, "archived_at": None})
    return RedirectResponse(url="/settings/labels", status_code=303)


@router.post("/{name}/archive")
def archive(name: str, conn=Depends(get_db)):
    """The user's explicit confirmation that a project is finished (§
    Project lifecycle) -- never automatic, see db.project_status."""
    db.archive_project(conn, name)
    return RedirectResponse(url="/settings/labels", status_code=303)
