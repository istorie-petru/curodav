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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router
from . import tasks as tasks_router

router = APIRouter(prefix="/labels", tags=["label-pages"])


def label_url(name: str) -> str:
    return f"/labels/{name}"


def _short_date(d: date, today: date) -> str:
    """"10 Sep", with the year only when it isn't this year's."""
    text = f"{d.day} {d.strftime('%b')}"
    return text if d.year == today.year else f"{text} {d.year}"


def deadline_info(label: dict, today: date | None = None) -> dict | None:
    """How a label's deadline should read (2026-09-25, UI audit L6). The
    pill used to be red whether the deadline was 20 days out or 15 days
    past. Now:

    - archived: gray "Deadline · 10 Sep" (it's history, no urgency)
    - overdue: red "Overdue · 10 Sep"
    - due within 7 days: orange "Due today" / "Due tomorrow" /
      "Due in 5 days · 30 Sep"
    - later: neutral gray "Due 15 Oct"

    The date carries its year when it's not this year's. Returns None for a
    label without a deadline. `state` is for CSS/tests; `color` is the
    `tag-*` pill color; `text` is the full pill text; `short` is the
    lowercase phrase the preview modal appends after the status."""
    if not (label.get("has_deadline") and label.get("deadline_date")):
        return None
    try:
        d = date.fromisoformat(str(label["deadline_date"])[:10])
    except ValueError:
        return None
    today = today or date.today()
    when = _short_date(d, today)
    days = (d - today).days
    if label.get("archived_at"):
        return {"state": "archived", "color": "gray", "text": f"Deadline · {when}", "short": f"deadline {when}"}
    if days < 0:
        return {"state": "overdue", "color": "red", "text": f"Overdue · {when}", "short": f"overdue since {when}"}
    if days <= 7:
        if days == 0:
            phrase = "Due today"
        elif days == 1:
            phrase = "Due tomorrow"
        else:
            phrase = f"Due in {days} days"
        text = f"{phrase} · {when}" if days > 1 else phrase
        return {"state": "soon", "color": "orange", "text": text, "short": phrase[0].lower() + phrase[1:]}
    return {"state": "later", "color": "gray", "text": f"Due {when}", "short": f"due {when}"}


def _archived_on(label: dict) -> str | None:
    """"25 Sep 2026" for the page's "Archived on ..." line, or None."""
    raw = label.get("archived_at")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _status_context(conn, label: dict) -> dict:
    """Status + deadline for _label_status.html. Only labels with a
    deadline or the project flag have a lifecycle; every other label gets
    None for the status. 2026-09-25 (UI audit L6 + label page flesh-out):
    also the deadline's state and, for any archived label, the date it was
    archived (the page shows an "Archived on ... · Unarchive" line)."""
    ctx = {
        "label_deadline": deadline_info(label),
        "label_archived_on": _archived_on(label),
        "label_status": None,
    }
    if label.get("has_deadline") or label.get("is_project"):
        ctx["label_status"] = db.project_status(conn, label)
    return ctx


def _label_exists(conn, name: str) -> bool:
    """A label exists when it has a config row or anything carries it."""
    if db.get_label_config(conn, name):
        return True
    row = conn.execute("SELECT 1 FROM object_labels WHERE label_name = ? LIMIT 1", (name,)).fetchone()
    return row is not None


def _page_common(conn, name: str) -> dict:
    """Context both label page layouts share (2026-09-25 flesh-out): how
    many items carry the label, for the one combined "Nothing tagged X
    yet" empty state."""
    count = conn.execute("SELECT COUNT(*) FROM object_labels WHERE label_name = ?", (name,)).fetchone()[0]
    return {"label_usage_count": count}


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
    ctx.update(_page_common(conn, name))
    ctx.update(dashboard_router._page_banner_context(conn, name))
    return templates.TemplateResponse("label_detail.html", ctx)


def _agenda_items(conn, name: str, label: dict, tasks: list[dict], limit: int) -> list[dict]:
    """Future events tagged with this label, the label's own deadline, and
    open due-dated tasks (from `tasks`), merged into one chronological list
    and capped at `limit`. Same recipe the retired project/plain-label
    pages both used; shared by the sections page and the preview modal."""
    today_iso = date.today().isoformat()
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
    return events[:limit]


def _sections_page(conn, request: Request, name: str, label: dict):
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    board_statuses = [s for s in tasks_router.STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    if label.get("tasks_widget"):
        for t in tasks:
            t["banner"] = db.banner_for_task(conn, t)
            columns.setdefault(t["status"], []).append(t)

    agenda_items = _agenda_items(conn, name, label, tasks, 8) if label.get("agenda_widget") else []

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
    ctx.update(_page_common(conn, name))
    ctx.update(dashboard_router._page_banner_context(conn, name))
    return templates.TemplateResponse("label_sections.html", ctx)


@router.get("/{name}")
def label_page(name: str, request: Request, conn=Depends(get_db)):
    # 2026-09-25 (UI audit L13): an unknown name used to render an empty
    # 200 page for a label that doesn't exist. Same landing as an emptied
    # group's old link (group_page below): the labels list.
    if not _label_exists(conn, name):
        return RedirectResponse(url="/settings/labels", status_code=303)
    label = db.effective_label_config(conn, name)
    if label.get("has_dashboard"):
        return _dashboard_page(conn, request, name, label)
    return _sections_page(conn, request, name, label)


@router.get("/{name}/preview")
def label_preview(name: str, request: Request, conn=Depends(get_db)):
    """A label's compact preview modal (labels-as-modules slice d,
    2026-09-25). A label pill inside a card or a detail modal opens this
    rather than leaving the page (Peter, 2026-09-24: "context-dependent" --
    modal from inside a widget/card, full page from the sidebar or a label
    list). It shows the label's status, group, a short agenda and counts,
    with an Open page link and an Edit button."""
    if not _label_exists(conn, name):
        raise HTTPException(404, "No such label")
    label = db.effective_label_config(conn, name)
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    # 2026-09-25 (UI audit L11): a pill inside a task/event modal opens this
    # preview in the same modal, replacing it. `from` is that modal's URL
    # (_label_pill.html passes it), so the footer offers "Back" to it
    # instead of stranding you. Only a same-site path is accepted.
    back_to = request.query_params.get("from") or ""
    if not back_to.startswith("/") or back_to.startswith("//"):
        back_to = ""
    ctx = {
        "request": request,
        "back_to": back_to,
        "label": label,
        "banner": db.get_page_banner(conn, name),
        "agenda_items": _agenda_items(conn, name, label, tasks, 5),
        "open_task_count": len([t for t in tasks if t["status"] != "done"]),
        "contact_count": len([c for c in db.list_contacts(conn) if name in (c.get("tags") or [])]),
    }
    ctx.update(_status_context(conn, label))
    ctx.update(_page_common(conn, name))
    return templates.TemplateResponse("label_preview_modal.html", ctx)


@router.post("/{name}/archive")
def archive_label(name: str, conn=Depends(get_db)):
    """The explicit "this is finished" confirmation. It's never automatic;
    see db.project_status for how Pending Archiving is computed.
    2026-09-25: every label page offers Archive in its header now, and a
    label that only exists through usage has no config row for
    db.archive_project's UPDATE to hit, so one is created first."""
    if not db.get_label_config(conn, name):
        db.upsert_label_config(conn, {"name": name, "created_at": datetime.now(timezone.utc).isoformat()})
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
    style = db.get_group_style(conn, name)
    dashboard_router._ensure_default_label_widgets(conn, key)
    ctx = dashboard_router.widget_page_context(conn, project_uid=key)
    ctx.update(
        {
            "request": request,
            "active_tab": "group",
            # label_detail.html renders a group through the same `label`
            # shape: title, icon tile, and `uid` as the page key its
            # New widget / Reset layout controls post back.
            # 2026-09-25 (UI audit L3): the group's own icon/color when set.
            "label": {"name": name, "uid": key, "icon": style["icon"] or "layers", "color": style["color"],
                      "description": None},
            "group_style": style,
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


# 2026-09-25 (UI audit L3, part of flesh-out item 7): a group's own icon
# and color, so groups stop sharing one `layers` glyph in the rail. Stored
# by db.set_group_style (app_meta, no schema change). No icon picked = the
# rail shows the group's first letter. Renaming a group and adding members
# still happen through each label's Group field.


@group_router.get("/{name}/edit")
def edit_group_modal(name: str, request: Request, conn=Depends(get_db)):
    from .labels import COLORS, icon_groups_for

    if not db.group_member_names(conn, name):
        raise HTTPException(404, "No such group")
    style = db.get_group_style(conn, name)
    return templates.TemplateResponse(
        "group_form_modal.html",
        {
            "request": request,
            "group": {"name": name, **style},
            "colors": COLORS,
            "icon_groups": icon_groups_for(style["icon"]),
        },
    )


@group_router.post("/{name}/update")
def update_group(name: str, color: str = Form("gray"), icon: str = Form(""), conn=Depends(get_db)):
    from .labels import COLORS

    if not db.group_member_names(conn, name):
        raise HTTPException(404, "No such group")
    color = color if isinstance(color, str) and color in COLORS else "gray"
    icon = icon.strip() if isinstance(icon, str) else ""
    db.set_group_style(conn, name, icon or None, color)
    return RedirectResponse(url=group_url(name), status_code=303)
