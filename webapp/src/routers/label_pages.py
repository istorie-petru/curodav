"""A label's own page, at `/labels/{name}` -- labels-as-modules slice b
(plans/ui-cleanup-2026-09.md item 4, 2026-09-25).

This replaces the three per-kind pages shipped 2026-09-16: the Space
dashboard (`/spaces/{name}`), the Project Kanban+Agenda page
(`/projects/{name}`) and the plain-label Kanban+Agenda page
(`/settings/labels/{name}`). All three old URLs now redirect here. What the
page shows depends on the label's module fields, not on what kind of label
it is:

- `has_dashboard`: the Home-style customizable widget grid, scoped to this
  label (label_detail.html).
- otherwise: only the sections switched on in the label's settings
  (`agenda_widget`, `contacts_widget`, and `tasks_widget` for the Kanban
  board), in label_sections.html.

Either way, a label with a deadline (or a project) shows its status and the
archive / unarchive action under the banner (_label_status.html). That's
the "confirm finished -> archive" flow Peter kept on 2026-09-25, now
available to any label rather than only projects.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router
from . import tasks as tasks_router

router = APIRouter(prefix="/labels", tags=["label-pages"])


def label_url(name: str) -> str:
    return f"/labels/{name}"


def _status_context(conn, label: dict) -> dict:
    """Status + deadline for _label_status.html. Only labels with a
    deadline or the project flag have a lifecycle; every other label gets
    None and the partial renders nothing."""
    if not (label.get("has_deadline") or label.get("is_project")):
        return {"label_status": None}
    return {"label_status": db.project_status(conn, label)}


def _dashboard_page(conn, request: Request, name: str, label: dict):
    dashboard_router._ensure_default_label_widgets(conn, name)
    ctx = dashboard_router.widget_page_context(conn, project_uid=name)
    ctx.update(
        {
            "request": request,
            "active_tab": "label",
            "label": label,
            "group_labels": [],
            # base.html's quick-add restricts the Labels picker to this
            # label's group (db.label_selector_scope); None when ungrouped.
            "page_label_scope": name if label.get("label_group") else None,
            "profile_photo": db.get_profile_photo(conn),
            "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
            "page_url": label_url(name),
        }
    )
    ctx.update(_status_context(conn, label))
    ctx.update(dashboard_router._page_banner_context(conn, name))
    return templates.TemplateResponse("label_detail.html", ctx)


def _sections_page(conn, request: Request, name: str, label: dict):
    today_iso = date.today().isoformat()
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    board_statuses = [s for s in tasks_router.STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    if label.get("tasks_widget"):
        for t in tasks:
            t["banner"] = db.banner_for_task(conn, t)
            columns.setdefault(t["status"], []).append(t)

    agenda_items: list[dict] = []
    if label.get("agenda_widget"):
        # Future events tagged with this label, the label's own deadline,
        # and open due-dated tasks, merged into one chronological list. Same
        # recipe the retired project/plain-label pages both used.
        events = [
            e for e in db.list_events(conn, start=datetime.now(timezone.utc).isoformat())
            if name in (e.get("tags") or []) and e.get("start_at") and e["start_at"][:10] >= today_iso
        ]
        db.annotate_item_colors(conn, events)
        deadline = label.get("deadline_date") if label.get("has_deadline") else None
        if deadline and deadline >= today_iso and not label.get("archived_at"):
            events.append({
                "uid": None,
                "title": "Deadline",
                "start_at": f"{deadline}T00:00:00",
                "all_day": True,
                "is_deadline": True,
            })
        for t in tasks:
            if t["status"] == "done" or not t.get("due_at") or t["due_at"][:10] < today_iso:
                continue
            events.append({"uid": t["uid"], "title": t["title"], "start_at": t["due_at"], "kind": "task"})
        events.sort(key=lambda e: e["start_at"])
        agenda_items = events[:8]

    contacts = []
    if label.get("contacts_widget"):
        contacts = [c for c in db.list_contacts(conn) if name in (c.get("tags") or [])][:20]

    ctx = {
        "request": request,
        "active_tab": "label",
        "label": label,
        "page_label_scope": name if label.get("label_group") else None,
        "agenda_items": agenda_items,
        "contacts": contacts,
        "columns": columns,
        "board_statuses": board_statuses,
        "status_labels": tasks_router.STATUS_LABELS,
        "status_colors": tasks_router.STATUS_COLORS,
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "profile_photo": db.get_profile_photo(conn),
        "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
        "page_url": label_url(name),
    }
    ctx.update(_status_context(conn, label))
    ctx.update(dashboard_router._page_banner_context(conn, name))
    return templates.TemplateResponse("label_sections.html", ctx)


@router.get("/{name}")
def label_page(name: str, request: Request, conn=Depends(get_db)):
    label = db.effective_label_config(conn, name)
    if label.get("has_dashboard"):
        return _dashboard_page(conn, request, name, label)
    return _sections_page(conn, request, name, label)


@router.post("/{name}/archive")
def archive_label(name: str, conn=Depends(get_db)):
    """The explicit "this is finished" confirmation. It's never automatic;
    see db.project_status for how Pending Archiving is computed."""
    db.archive_project(conn, name)
    return RedirectResponse(url=label_url(name), status_code=303)


@router.post("/{name}/unarchive")
def unarchive_label(name: str, conn=Depends(get_db)):
    db.unarchive_label(conn, name)
    return RedirectResponse(url=label_url(name), status_code=303)


# --------------------------------------------------------------------- #
# Group pages -- labels-as-modules slice c (2026-09-25). A group is the
# plain-text label_group shared by some labels (what used to be a Space).
# Its page is a widget dashboard scoped to every member label, stored under
# db.group_page_key(name) ("group:<name>") in the same per-page storage a
# label's dashboard uses. Every member label is also linked from the page,
# since the collapsed sidebar has no room to expand a group.
# --------------------------------------------------------------------- #

group_router = APIRouter(prefix="/groups", tags=["group-pages"])


def group_url(name: str) -> str:
    return f"/groups/{name}"


@group_router.get("/{name}")
def group_page(name: str, request: Request, conn=Depends(get_db)):
    members = db.group_member_names(conn, name)
    if not members:
        # A group only exists while a label names it; an old link to an
        # emptied group lands on the labels list rather than a blank page.
        return RedirectResponse(url="/settings/labels", status_code=303)
    key = db.group_page_key(name)
    dashboard_router._ensure_default_label_widgets(conn, key)
    ctx = dashboard_router.widget_page_context(conn, project_uid=key)
    ctx.update(
        {
            "request": request,
            "active_tab": "group",
            # label_detail.html renders a group through the same `label`
            # shape: title, icon tile, and `uid` as the page key its
            # New widget / Reset layout controls post back.
            "label": {"name": name, "uid": key, "icon": "layers", "color": "gray", "description": None},
            "group_labels": [db.effective_label_config(conn, n) for n in members],
            "page_label_scope": key,
            "label_status": None,
            "profile_photo": db.get_profile_photo(conn),
            "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
            "page_url": group_url(name),
        }
    )
    ctx.update(dashboard_router._page_banner_context(conn, key))
    return templates.TemplateResponse("label_detail.html", ctx)
