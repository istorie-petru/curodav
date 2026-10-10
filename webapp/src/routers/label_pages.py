"""A label's own page, at `/labels/{name}` -- labels-as-modules slice b
(plans/ui-cleanup-2026-09.md item 4, 2026-09-25).

This replaces the three per-kind pages shipped 2026-09-16: the Space
dashboard (`/spaces/{name}`), the Project Kanban+Agenda page
(`/projects/{name}`) and the plain-label Kanban+Agenda page
(`/settings/labels/{name}`). All three old URLs now redirect here. What the
page shows depends on the label's module fields, not on what kind of label
it is:

- `page_type` dashboard: the Home-style customizable widget grid, scoped to this
  label (label_detail.html).
- `page_type` secretariat: the agenda-style Secretariat (secretariat.html).
- otherwise: only the sections switched on in the label's settings
  (`agenda_widget`, `contacts_widget`, `notebook_widget`, and
  `tasks_widget` for the Kanban board), in label_sections.html.

Either way, a label with a deadline (or a project) shows its status and the
archive / unarchive action under the banner (_label_status.html). That's
the "confirm finished -> archive" flow Peter kept on 2026-09-25, now
available to any label rather than only projects.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import clock, db, habit_view, recurrence_expand
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router
from . import secretariat_page
from . import tasks as tasks_router

MAX_AGENDA_HABITS = 2

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
    today = today or clock.today()
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


def _cover_banner(conn, page_key: str, name: str):
    """The banner a view modal's cover strip (_detail_cover.html) shows.
    That macro builds its /banners/image URL from `banner.scope`, a key
    get_page_banner itself never sets (only banner_for_object injects it),
    so passing the raw stored banner rendered a broken image -- the
    "label view modal doesn't show the banner" bug. Resolving through
    effective_page_banner also gives the modal the same flair default the
    label's own page already shows."""
    banner = db.effective_page_banner(conn, page_key, name)
    if banner:
        banner = {**banner, "scope": page_key}
    return banner


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
    ctx.update(dashboard_router._page_banner_context(conn, name, name=name))
    return templates.TemplateResponse("label_detail.html", ctx)


def _agenda_items(conn, scope: set[str] | None, label: dict, tasks: list[dict], limit: int) -> list[dict]:
    """Future events tagged with this label, the label's own deadline, and
    open due-dated tasks (from `tasks`), merged into one chronological list
    and capped at `limit`, led by at most MAX_AGENDA_HABITS of the label's
    habits due today. Shared by the sections page and the preview modal."""
    today_iso = clock.today().isoformat()
    horizon = clock.today() + timedelta(days=364)
    events = [
        e for e in recurrence_expand.expand_events(
            db.list_events(conn, start=clock.now().isoformat()), clock.today(), horizon,
            db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn),
        )
        if dashboard_router._passes_scope(e.get("tags"), scope) and e.get("start_at") and e["start_at"][:10] >= today_iso
    ]
    events.sort(key=lambda e: e["start_at"])
    events = recurrence_expand.collapse_recurring(events)
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
    habits = [
        {"kind": "habit", "uid": h["uid"], "title": h["title"], "detail_url": h["detail_url"],
         "recurrence_label": h["recurrence_label"]}
        for h in habit_view.habit_items(conn)
        if h["due_today"] and not h["is_avoid"] and dashboard_router._passes_scope(h.get("tags"), scope)
    ][:MAX_AGENDA_HABITS]
    return (habits + events)[:limit]


def _sections_page(conn, request: Request, name: str, label: dict):
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    ctx = _sections_context(conn, request, {name}, name, label, tasks)
    ctx.update(
        {
            "page_label_scope": name if label.get("label_group") else None,
            "page_url": label_url(name),
        }
    )
    ctx.update(_status_context(conn, label))
    ctx.update(_page_common(conn, name))
    ctx.update(dashboard_router._page_banner_context(conn, name, name=name))
    return templates.TemplateResponse("label_sections.html", ctx)


def _pooled_sections_page(conn, request: Request, scope_key: str | None, title: str, icon: str, color: str,
                          page_url: str, banner_ctx: dict, header_edit_url: str):
    """The Sections page type for Home (scope_key None) and groups: the same
    sections as a label's page, over every item in scope."""
    tasks = [
        t for t in dashboard_router._filtered_tasks(conn, {"label_name": scope_key}, open_only=False)
        if t["status"] != "archived"
    ]
    label = {
        "name": title, "icon": icon, "color": color, "description": None, "agenda_widget": 1, "tasks_widget": 1,
        "contacts_widget": 1, "notebook_widget": 1, "pooled": True,
    }
    scope = dashboard_router._scope_child_names(conn, scope_key)
    ctx = _sections_context(conn, request, scope, scope_key, label, tasks)
    ctx.update({"page_url": page_url, "label_usage_count": 1, "header_edit_url": header_edit_url})
    ctx.update(banner_ctx)
    return templates.TemplateResponse("label_sections.html", ctx)


def _sections_context(conn, request: Request, scope: set[str] | None, scope_key: str | None, label: dict,
                      tasks: list[dict]) -> dict:
    board_statuses = [s for s in tasks_router.STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    if label.get("tasks_widget"):
        for t in tasks:
            t["banner"] = db.banner_for_task(conn, t)
            columns.setdefault(t["status"], []).append(t)

    agenda_items = _agenda_items(conn, scope, label, tasks, 8) if label.get("agenda_widget") else []

    contacts = []
    if label.get("contacts_widget"):
        contacts = [c for c in db.list_contacts(conn) if dashboard_router._passes_scope(c.get("tags"), scope)][:20]

    notebook_documents = {}
    if label.get("notebook_widget"):
        # Reuses the Dashboard's own scope/tags/limit pipeline so this
        # section and the Notebook List widget cannot drift apart.
        notebook_documents = dashboard_router._render_notebook_list(conn, {"label_name": scope_key})

    return {
        "request": request,
        "active_tab": "label" if scope_key else "dashboard",
        "label": label,
        "agenda_items": agenda_items,
        "contacts": contacts,
        "notebook_documents": notebook_documents,
        "columns": columns,
        "board_statuses": board_statuses,
        "status_labels": tasks_router.STATUS_LABELS,
        "status_colors": tasks_router.STATUS_COLORS,
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "profile_photo": db.get_profile_photo(conn),
        "display_name": db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY),
    }


@router.get("/{name}")
def label_page(name: str, request: Request, conn=Depends(get_db)):
    # 2026-09-25 (UI audit L13): an unknown name used to render an empty
    # 200 page for a label that doesn't exist. Same landing as an emptied
    # group's old link (group_page below): the labels list.
    if not _label_exists(conn, name):
        return RedirectResponse(url="/settings/labels", status_code=303)
    label = db.effective_label_config(conn, name)
    if label.get("page_type") == "secretariat":
        return secretariat_page.render(
            conn, request, scope_key=name, title=name, icon_name=label.get("icon") or "tag", icon_color=label.get("color"),
            banner_ctx=dashboard_router._page_banner_context(conn, name, name=name), page_url=label_url(name), label=label,
        )
    if label.get("page_type") == "dashboard":
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
        "banner": _cover_banner(conn, name, name),
        "agenda_items": _agenda_items(conn, {name}, label, tasks, 8),
        "open_task_count": len([t for t in tasks if t["status"] != "done"]),
        "contact_count": len([c for c in db.list_contacts(conn) if name in (c.get("tags") or [])]),
    }
    ctx.update(_status_context(conn, label))
    ctx.update(_page_common(conn, name))
    return templates.TemplateResponse("label_preview_modal.html", ctx)


@router.post("/{name}/archive")
def archive_label(name: str, x_requested_with: str | None = Header(None), conn=Depends(get_db)):
    """The explicit "this is finished" confirmation. It's never automatic;
    see db.project_status for how Pending Archiving is computed.
    2026-09-25: every label page offers Archive in its header now, and a
    label that only exists through usage has no config row for
    db.archive_project's UPDATE to hit, so one is created first."""
    if not db.get_label_config(conn, name):
        db.upsert_label_config(conn, {"name": name, "created_at": clock.now().isoformat()})
    db.archive_project(conn, name)
    if x_requested_with == "fetch":
        return Response(status_code=204)
    return RedirectResponse(url=label_url(name), status_code=303)


@router.post("/{name}/unarchive")
def unarchive_label(name: str, x_requested_with: str | None = Header(None), conn=Depends(get_db)):
    db.unarchive_label(conn, name)
    if x_requested_with == "fetch":
        return Response(status_code=204)
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


def _usage_by_label(conn) -> dict[str, int]:
    return {lbl["name"]: lbl.get("usage_count") or 0 for lbl in db.list_labels(conn)}


def _group_or_404(conn, name: str) -> dict:
    g = db.get_group(conn, name)
    if not g:
        raise HTTPException(404, "No such group")
    return g


def _group_form_context(conn, request: Request, group: dict | None, copy_of: dict | None = None) -> dict:
    """Context for group_form_modal.html -- create (group None) or edit.
    `copy_of` (Duplicate): a group whose look and page type fill the empty
    create form; its labels are not copied (a label has one group)."""
    from .labels import COLORS, icon_groups_for

    name = group["name"] if group else ""
    members = set(db.group_member_names(conn, name)) if group else set()
    # Every label with its current group, so the Labels dropdown can say
    # "(in People)" for a label that's in another group already.
    group_of = {
        r["name"]: (r["label_group"] or "").strip()
        for r in conn.execute("SELECT name, label_group FROM label_config").fetchall()
    }
    candidates = [
        {"name": n, "member": n in members, "other_group": (group_of.get(n) or "") if n not in members else ""}
        for n in db.list_all_known_label_names(conn)
        if not db.effective_label_config(conn, n).get("is_archived")
    ]
    style = db.get_group_style(conn, name) if group else {"icon": None, "color": "gray"}
    if copy_of:
        style = db.get_group_style(conn, copy_of["name"])
    return {
        "request": request,
        "group": {"name": name, **style} if group else None,
        "prefill": {"name": copy_of["name"] + " copy", **style} if copy_of else None,
        "candidates": candidates,
        "colors": COLORS,
        "icon_groups": icon_groups_for(style["icon"]),
        "group_default_icon": db.GROUP_DEFAULT_ICON,
        "banner": db.get_page_banner(conn, db.group_page_key(name)) if group else None,
        "page_types": [(k, db.PAGE_TYPE_LABELS[k]) for k in db.PAGE_TYPES],
        "page_type": db.get_group_page_type(conn, (group or copy_of)["name"]) if (group or copy_of) else "dashboard",
    }


# 2026-09-26 (Peter): groups are standalone -- created empty from Settings
# > Groups, with a view modal (like a label's preview) and an edit modal
# (rename, look, banner, labels). Declared before GET /{name} so "new"
# isn't read as a group name.


@group_router.get("/new")
def new_group_modal(request: Request, copy: str = "", conn=Depends(get_db)):
    copy_of = db.get_group(conn, copy) if copy else None
    return templates.TemplateResponse("group_form_modal.html", _group_form_context(conn, request, None, copy_of))


@group_router.post("/create")
def create_group(
    new_name: str = Form(""),
    color: str = Form("gray"),
    icon: str = Form(""),
    members: list[str] = Form([]),
    page_type: str = Form("dashboard"),
    conn=Depends(get_db),
):
    from .labels import COLORS

    new_name = new_name.strip() if isinstance(new_name, str) else ""
    if new_name.startswith(db.GROUP_KEY_PREFIX):
        raise HTTPException(400, "A group name can't start with \"group:\".")
    color = color if isinstance(color, str) and color in COLORS else "gray"
    icon = icon.strip() if isinstance(icon, str) else ""
    try:
        name = db.create_group(conn, new_name, icon or None, color)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    members = members if isinstance(members, list) else []
    if members:
        db.set_group_members(conn, name, members)
    db.set_group_page_type(conn, name, page_type if isinstance(page_type, str) else "dashboard")
    return RedirectResponse(url="/settings/groups", status_code=303)


@group_router.get("/{name}/view")
def group_view_modal(name: str, request: Request, conn=Depends(get_db)):
    """A group's view modal: its cover (banner, or its colour), icon,
    labels and usage; Edit swaps in the edit form, Open page leaves."""
    g = _group_or_404(conn, name)
    style = db.get_group_style(conn, g["name"])
    labels = [db.effective_label_config(conn, n) for n in db.group_member_names(conn, g["name"])]
    return templates.TemplateResponse(
        "group_view_modal.html",
        {
            "request": request,
            "group": {"name": g["name"], **style},
            "labels": labels,
            "usage": sum(_usage_by_label(conn).get(lbl["name"], 0) for lbl in labels),
            "banner": _cover_banner(conn, db.group_page_key(g["name"]), g["name"]),
            "group_default_icon": db.GROUP_DEFAULT_ICON,
        },
    )


@group_router.post("/{name}/delete")
def delete_group(name: str, conn=Depends(get_db)):
    """Deletes the group; its labels stay, ungrouped."""
    g = _group_or_404(conn, name)
    db.delete_group(conn, g["name"])
    return RedirectResponse(url="/settings/groups", status_code=303)


@group_router.get("/{name}")
def group_page(name: str, request: Request, conn=Depends(get_db)):
    if not db.get_group(conn, name):
        # An old link to a deleted group lands on the groups list rather
        # than a blank page.
        return RedirectResponse(url="/settings/groups", status_code=303)
    name = db.get_group(conn, name)["name"]
    members = db.group_member_names(conn, name)
    key = db.group_page_key(name)
    style = db.get_group_style(conn, name)
    page_type = db.get_group_page_type(conn, name)
    if page_type != "dashboard":
        banner_ctx = dashboard_router._page_banner_context(conn, key, name=name)
        icon_name = style["icon"] or db.GROUP_DEFAULT_ICON
        edit_url = f"/groups/{quote(name)}/edit"
        if page_type == "secretariat":
            return secretariat_page.render(
                conn, request, scope_key=key, title=name, icon_name=icon_name, icon_color=style["color"],
                banner_ctx=banner_ctx, page_url=group_url(name), header_edit_url=edit_url,
            )
        return _pooled_sections_page(
            conn, request, key, name, icon_name, style["color"], group_url(name), banner_ctx, edit_url
        )
    dashboard_router._ensure_default_label_widgets(conn, key)
    # Item 20 (2026-09-26): label_detail.html's old always-visible
    # "group-labels" toolbar is gone. It was first replaced by an always-
    # pinned, full-width `group_members` widget seeded separately from the
    # rest of the page's layout (_ensure_group_members_widget) -- 2026-09-28
    # direct request ("I don't want Labels in this group to be visible by
    # default") retired that: `_ensure_default_label_widgets` above now
    # seeds a group page with the same 25/50/25 row Home gets, the group's
    # own label list living in the ordinary quarter-width third column
    # (_seed_agenda_stack_layout) instead of a second, unmissable widget.
    # `_ensure_group_members_widget` itself is kept only as the shape
    # `_migrate_group_layout_2026_09_28` (widget_page_context) converts an
    # existing installation's old pinned widget from.
    ctx = dashboard_router.widget_page_context(conn, project_uid=key)
    ctx.update(
        {
            "request": request,
            "active_tab": "group",
            # label_detail.html renders a group through the same `label`
            # shape: title, icon tile, and `uid` as the page key its
            # New widget / Reset layout controls post back.
            # 2026-09-25 (UI audit L3): the group's own icon/color when set.
            "label": {"name": name, "uid": key, "icon": style["icon"] or db.GROUP_DEFAULT_ICON, "color": style["color"],
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
    ctx.update(dashboard_router._page_banner_context(conn, key, name=name))
    return templates.TemplateResponse("label_detail.html", ctx)


# 2026-09-25 (UI audit L3, part of flesh-out item 7): a group's own icon
# and color, so groups stop sharing one `layers` glyph in the rail. Stored
# by db.set_group_style (app_meta, no schema change). No icon picked = the
# rail shows the group's first letter. Same day, the rest of item 7: the
# modal also renames the group (db.rename_group moves its dashboard,
# banner and look with it) and picks its member labels
# (db.set_group_members), which used to mean editing each label's Group
# field one by one.


@group_router.get("/{name}/edit")
def edit_group_modal(name: str, request: Request, conn=Depends(get_db)):
    g = _group_or_404(conn, name)
    return templates.TemplateResponse("group_form_modal.html", _group_form_context(conn, request, g))


@group_router.post("/{name}/update")
def update_group(
    name: str,
    color: str = Form("gray"),
    icon: str = Form(""),
    new_name: str = Form(""),
    members: list[str] = Form([]),
    members_submitted: str = Form(""),
    page_type: str = Form(""),
    request: Request = None,
    conn=Depends(get_db),
):
    from urllib.parse import urlparse

    from .labels import COLORS

    name = _group_or_404(conn, name)["name"]
    color = color if isinstance(color, str) and color in COLORS else "gray"
    icon = icon.strip() if isinstance(icon, str) else ""
    new_name = new_name.strip() if isinstance(new_name, str) else ""
    members = members if isinstance(members, list) else []
    members_submitted = members_submitted if isinstance(members_submitted, str) else ""
    if new_name.startswith(db.GROUP_KEY_PREFIX):
        raise HTTPException(400, "A group name can't start with \"group:\".")
    # `members_submitted` marks a form that rendered the Labels dropdown,
    # so an older/partial post without it never empties the group by
    # accident. Since 2026-09-26 an empty list is allowed: the group stays.
    if members_submitted:
        db.set_group_members(conn, name, members)
    db.set_group_style(conn, name, icon or None, color)
    if isinstance(page_type, str) and page_type:
        db.set_group_page_type(conn, name, page_type)
    final = db.rename_group(conn, name, new_name) if new_name else name
    # 2026-09-26: saved from Settings > Groups -> stay there (the list
    # refreshes in place); from the group's own page -> its (maybe
    # renamed) page, as before.
    ref = urlparse((request.headers.get("referer") if request is not None else "") or "")
    if ref.path.startswith("/settings/groups"):
        return RedirectResponse(url="/settings/groups", status_code=303)
    return RedirectResponse(url=group_url(final), status_code=303)


# --------------------------------------------------------------------- #
# Settings > Groups (2026-09-26, Peter: separate settings pages for
# labels, groups and projects).
# --------------------------------------------------------------------- #

groups_settings_router = APIRouter(prefix="/settings/groups", tags=["groups-settings"])


def _groups_context(conn, request: Request) -> dict:
    groups = db.list_groups(conn)
    usage = _usage_by_label(conn)
    for g in groups:
        g["usage"] = sum(usage.get(lbl["name"], 0) for lbl in g["labels"])
    return {
        "request": request,
        "active_tab": "labels",
        "crumbs": [{"url": "/settings", "name": "Settings"}],
        "groups": groups,
        "group_default_icon": db.GROUP_DEFAULT_ICON,
    }


@groups_settings_router.get("")
def manage_groups(request: Request, conn=Depends(get_db)):
    from .taxonomy import page_response

    return page_response(conn, request, "groups")
