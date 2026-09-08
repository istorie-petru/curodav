"""Projects (1.3, Project-enabled label stack, plans/open-priority.md §
Project-enabled label stack). A project is not a separate entity -- it's a
label with `is_project=1` plus a bounded start/end period and a computed
lifecycle (db.project_status). This router owns the promote/demote/dates/
archive actions that manage a label's Project behavior.

History: 1.3 shipped a dedicated `/projects` listing page and 1.4 added its
two child views (`project_detail`'s Tasks view, `project_calendar`'s Week
Calendar view). 2026-08-15 retired all three to plain redirects, on the
grounds that the Tasks view duplicated `/tasks?group_by=project` and the
Week Calendar view duplicated the merged `/calendar/week` grid -- see
plans/open.md's "Retire the standalone /projects page" decision record for
that reasoning, which was correct for those two specific views.

Rebuild (2026-08-30, direct request, STATE.md backlog item 9 "Projects page
-- view-like, not dashboard-like"): `GET /projects/{name}` is a real page
again below (`project_detail`), but not a revival of the old Tasks-view
page -- a project's *default* landing spot until now was actually
`/settings/labels/{name}` (a project is just a label, so it fell through to
the same customizable widget-grid dashboard every plain label/Space gets),
which is the "traditional dashboard" feedback was aimed at. This page is
task-focused instead: a Kanban board (columns = task status) of every task
carrying the project's label, with an upcoming-events card above it (real
calendar events tagged with the same label, not a widget). `GET /projects`
(the listing) and `GET /projects/{name}/calendar` (the Week Calendar view)
are unaffected -- still redirects, per the reasoning above; an Agenda-style
full events view is tracked separately in STATE.md, not part of this slice.
`promote`/`set_dates`/`demote`/`archive` below are untouched throughout,
still the only way a label gains/loses Project behavior, still reached
from Settings > Labels (routers/labels.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router
from . import tasks as tasks_router

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
def project_detail(name: str, request: Request, conn=Depends(get_db)):
    """The real project page (rebuilt 2026-08-30, see this module's
    docstring) -- a Kanban board of every task carrying this project's
    label, with an upcoming-events card above it.

    A label that isn't (or is no longer) a project redirects to its plain
    label page rather than 404ing or rendering an empty board -- same "a
    stale bookmark/link still lands somewhere real" precedent this
    module's other redirects (and routers/spaces.py's own generate_space
    guard) already establish. Reachable this way if a project gets
    demoted (routers/projects.py::demote) while something still links to
    its old /projects/{name} URL."""
    label = db.effective_label_config(conn, name)
    if not label.get("is_project"):
        return RedirectResponse(url=f"/settings/labels/{name}", status_code=303)

    # Board pool: every task carrying this label, minus archived -- same
    # "archived tasks don't pile up in a Done-adjacent column forever"
    # convention the old tasks_board.html Kanban used (routers/tasks.py's
    # retired board_view). list_tasks_sharing_labels already excludes
    # habit-tracked tasks (a habit is never a Kanban card, on the global
    # board or here).
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    board_statuses = [s for s in tasks_router.STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    for t in tasks:
        # 2026-08-30 (direct request): resolved once per card here rather
        # than in the template -- db.banner_for_task's label > project >
        # Space priority chain needs a real DB lookup (project_label_for +
        # get_page_banner, possibly twice more for the Space fallback),
        # not something a template should be doing per row. Every card on
        # this board already carries this project's own label, so most
        # cards resolve to the same banner unless one has a more specific
        # plain label of its own -- exactly the "normal label wins" rule.
        t["banner"] = db.banner_for_task(conn, t)
        columns.setdefault(t["status"], []).append(t)

    # Upcoming events card: every future event carrying this label, same
    # "list_events(start=now) + tag membership + sort + cap" recipe
    # routers/dashboard.py's Agenda widget uses for its own "All upcoming"
    # events section (_render_agenda) -- deliberately not expanded through
    # recurrence_expand like the Calendar grids are: a project's upcoming
    # list is a short glance, not a schedule to page through, and this
    # keeps it consistent with the one other "upcoming events" surface
    # this app already has.
    now_iso = _now()
    events = [
        e for e in db.list_events(conn, start=now_iso)
        if name in (e.get("tags") or []) and e.get("start_at") and e["start_at"] >= now_iso
    ]
    # The project's own deadline (label_config.end_date) as a synthetic,
    # non-clickable entry in the same list -- direct request. Not a real
    # `events` row (a project's period is a label_config field, § Projects
    # are labels, not a stored thing -- it doesn't get a shadow calendar
    # event just to appear here), so it's built as a plain dict shaped
    # like one, `is_deadline` marking it for the template's own
    # "no link, different pill" branch. All-day-style naive
    # `T00:00:00` start_at (no tz offset), same convention real all-day
    # events use (see test_calendar_allday_strip.py's own seeds) --
    # end_date has no time component to be more precise about. Compared
    # against just today's date (not the full `now_iso` timestamp) so a
    # deadline dated *today* still counts as upcoming regardless of what
    # time it currently is -- a bare date has no "already passed today"
    # concept the way a timed event does.
    if label.get("end_date") and label["end_date"] >= now_iso[:10]:
        events.append({
            "uid": None,
            "title": "Project deadline",
            "start_at": f"{label['end_date']}T00:00:00",
            "all_day": True,
            "is_deadline": True,
        })
    events.sort(key=lambda e: e["start_at"])
    events = events[:8]

    ctx = {
        "request": request,
        "active_tab": "label",
        "project": label,
        "project_status": db.project_status(conn, label),
        "events": events,
        "columns": columns,
        "board_statuses": board_statuses,
        "status_labels": tasks_router.STATUS_LABELS,
        "status_colors": tasks_router.STATUS_COLORS,
        # Header banner + avatar (2026-08-30, direct request -- "the banner
        # header, the profile picture") -- same page-header treatment
        # every other "dashboard type" page gets (Home/label_detail.html/
        # spaces.py's own space_detail, per _page_banner.html's own
        # docstring, which already named this route as a future caller).
        # Not part of the widget-grid machinery this page deliberately
        # doesn't have (no "New widget"/"Reset layout" -- those are
        # per-widget actions with nothing to act on here); just the shared
        # cover image + avatar overlap and the "Add/Change banner" control.
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "profile_photo": db.get_profile_photo(conn),
        "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
        # Not dashboard_router._return_url(name, conn=conn) -- that helper
        # resolves a project label to /settings/labels/{name} (it predates
        # this page), which would bounce the banner editor's save back to
        # the wrong URL. This page's own path is simply /projects/{name}.
        "page_url": f"/projects/{name}",
    }
    ctx.update(dashboard_router._page_banner_context(conn, name))
    return templates.TemplateResponse("project_detail.html", ctx)


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
