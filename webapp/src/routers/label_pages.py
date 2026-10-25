"""A label's own page, at `/labels/{name}` -- labels-as-modules slice b.

- `?view=agenda`: the agenda-style Secretariat (secretariat.html), scoped to this label.
- `?view=board`: every open task of the label on a status board (scope_board.html).
- otherwise the Overview: only the sections switched on in the label's settings
  (`agenda_widget`, `contacts_widget`, `notebook_widget`, and
  `tasks_widget` for the Kanban board), in label_sections.html.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import clock, db, habit_view, modules, recurrence_expand
from .. import tags as tag_store
from ..deps import EDIT_MODE_KEY, get_db, templates
from . import dashboard as dashboard_router
from . import secretariat_page
from . import tasks as tasks_router

MAX_AGENDA_HABITS = 2

router = APIRouter(prefix="/labels", tags=["label-pages"])


def requested_view(request: Request) -> str:
    """The page's `?view=` choice (agenda or board); anything else is the Overview."""
    query = parse_qs(request.scope.get("query_string", b"").decode())
    value = (query.get("view") or [""])[0]
    return value if value in ("agenda", "board") else ""


def label_url(name: str) -> str:
    return f"/labels/{name}"


def _short_date(d: date, today: date) -> str:
    """"10 Sep", with the year only when it isn't this year's."""
    text = f"{d.day} {d.strftime('%b')}"
    return text if d.year == today.year else f"{text} {d.year}"


def deadline_info(label: dict, today: date | None = None) -> dict | None:
    """How a label's deadline should read. The
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
        lowercase phrase the preview modal appends after the status.
    """
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
        None for the status. · Unarchive" line).
    """
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
    return db.label_is_carried(conn, name)


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
    """Context both label page layouts share: how
        many items carry the label, for the one combined "Nothing tagged X
        yet" empty state.
    """
    return {"label_usage_count": db.label_usage_count(conn, name)}


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


def _agenda_items(conn, scope: set[str] | None, label: dict, tasks: list[dict], limit: int, tag: str = "") -> list[dict]:
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
    if tag:
        match = tag_store.matcher(conn, "event", [tag])
        events = [e for e in events if match(e)]
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


def _tag_filter(conn, request: Request, name: str) -> tuple[str, list[dict]]:
    """The tag picked on this label's page (`?tag=`) and the dropdown's options; none when the label has one tag."""
    own = tag_store.tags_of_label(conn, name)
    picked = request.query_params.get("tag", "")
    if len(own) < 2 or picked.lower() not in {t["name"].lower() for t in own}:
        picked = ""
    items = [{"value": "", "name": "All tags"}] + [{"value": t["name"], "name": t["name"]} for t in own] if len(own) > 1 else []
    return picked, items


def _group_by_tag(by_status: list) -> list[tuple[dict, list[dict], int]]:
    """A label page whose label has several tags groups its open tasks by tag (the task's first tag), instead of by status."""
    groups: dict[str, tuple[dict, list[dict]]] = {}
    for _title, rows, _count in by_status:
        for t in rows:
            tag = (t.get("tag_items") or [{"name": "Other", "color": "gray", "icon": ""}])[0]
            groups.setdefault(tag["name"], (tag, []))[1].append(t)
    return [(tag, rows, len(rows)) for tag, rows in sorted(groups.values(), key=lambda g: g[0]["name"].lower())]


def _sections_page(conn, request: Request, name: str, label: dict):
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
    picked, tag_items = _tag_filter(conn, request, name)
    if picked:
        match = tag_store.matcher(conn, "task", [picked])
        tasks = [t for t in tasks if match(t)]
    ctx = _sections_context(conn, request, {name}, name, label, tasks, tag=picked)
    ctx.update(
        {
            "page_label_scope": name if label.get("label_group") else None,
            "page_url": label_url(name),
            "tag_items": tag_items,
            "active_tag": picked,
            "ov_by_tag": _group_by_tag(ctx.get("ov_by_status") or []) if len(tag_items) > 1 and not picked else [],
        }
    )
    ctx.update(_status_context(conn, label))
    ctx.update(_page_common(conn, name))
    ctx.update(dashboard_router._page_banner_context(conn, name, name=name))
    return templates.TemplateResponse("label_sections.html", ctx)


def scope_board_page(conn, request: Request, scope: set[str] | None, scope_key: str | None, label: dict,
                     tasks: list[dict], page_url: str, banner_ctx: dict, header_edit_url: str | None):
    """The Board view of a label, group or Home: every open task in scope, by status."""
    ctx = _sections_context(conn, request, scope, scope_key, label, tasks)
    ctx.update({"page_url": page_url, "header_edit_url": header_edit_url})
    ctx.update(banner_ctx)
    return templates.TemplateResponse("scope_board.html", ctx)


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


def _overview_context(conn, scope: set[str] | None, scope_key: str | None, label: dict, tasks: list[dict],
                      group_members: dict | None) -> dict:
    """What the Overview shows besides the widget sections: its kind (project, group,
    label or home), the Next row, the open tasks by status, progress and, for a
    group, its labels and attention items."""
    today_iso = clock.today().isoformat()
    is_group = bool(scope_key and scope_key.startswith(db.GROUP_KEY_PREFIX))
    kind = "group" if is_group else "home" if scope_key is None else "project" if label.get("is_project") else "label"
    open_tasks = [t for t in tasks if t["status"] not in ("done", "archived")]
    dated = sorted((t for t in open_tasks if t.get("due_at")), key=lambda t: t["due_at"])
    overdue = [t for t in dated if t["due_at"][:10] < today_iso]
    upcoming = [t for t in dated if t["due_at"][:10] >= today_iso]
    events = [
        e for e in _agenda_items(conn, scope, label, [], 30)
        if e.get("kind") != "habit" and not e.get("is_deadline")
    ]
    by_status = [
        (title, [t for t in open_tasks if t["status"] == status])
        for status, title in (("in_progress", "In progress"), ("active", "To do"), ("waiting", "Waiting"))
    ]
    done = len([t for t in tasks if t["status"] == "done"])
    total = len([t for t in tasks if t["status"] != "archived"])
    attention = []
    if kind == "group" and group_members:
        for row in group_members["rows"]:
            name = row["label"]["name"]
            row["overdue_count"] = len([t for t in overdue if name in (t.get("tags") or [])])
            cfg = db.effective_label_config(conn, name)
            info = deadline_info(cfg)
            if info and info["state"] in ("overdue", "soon") and not cfg.get("archived_at"):
                attention.append({"name": name, "text": info["text"], "color": info["color"]})
    return {
        "ov_kind": kind,
        "ov_next_event": events[0] if events else None,
        "ov_next_tasks": upcoming[:3],
        "ov_overdue": overdue[:5],
        "ov_overdue_count": len(overdue),
        "ov_by_status": [(title, rows[:6], len(rows)) for title, rows in by_status if rows],
        "ov_open_count": len(open_tasks),
        "ov_done": done,
        "ov_total": total,
        "ov_percent": round(100 * done / total) if total else 0,
        "ov_attention": attention,
    }


def _sections_context(conn, request: Request, scope: set[str] | None, scope_key: str | None, label: dict,
                      tasks: list[dict], tag: str = "") -> dict:
    board_statuses = [s for s in tasks_router.STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    if label.get("tasks_widget"):
        for t in tasks:
            t["strip"] = db.card_strip(conn, t)
            columns.setdefault(t["status"], []).append(t)

    agenda_items = _agenda_items(conn, scope, label, tasks, 8, tag) if label.get("agenda_widget") else []

    contacts = []
    if label.get("contacts_widget"):
        contacts = [c for c in db.list_contacts(conn) if dashboard_router._passes_scope(c.get("tags"), scope)]
        if tag:
            match = tag_store.matcher(conn, "contact", [tag])
            contacts = [c for c in contacts if match(c)]
        contacts = contacts[:20]

    notebook_documents = {}
    if label.get("notebook_widget"):
        # Reuses the Dashboard's own scope/tags/limit pipeline so this
        # section and the Notebook List widget cannot drift apart.
        notebook_documents = dashboard_router._render_notebook_list(conn, {"label_name": scope_key})
        if tag and notebook_documents.get("documents"):
            match = tag_store.matcher(conn, "notebook", [tag])
            notebook_documents = {**notebook_documents, "documents": [d for d in notebook_documents["documents"] if match(d)]}

    glance = dashboard_router._render_at_a_glance(conn, {"label_name": scope_key}) if tasks else None
    group_members = (
        dashboard_router._render_group_members(conn, {"label_name": scope_key})
        if scope_key and scope_key.startswith(db.GROUP_KEY_PREFIX) else None
    )
    ctx_overview = _overview_context(conn, scope, scope_key, label, tasks, group_members)
    return {
        **ctx_overview,
        "request": request,
        "glance": glance,
        "group_members": group_members,
        "active_tab": ("group" if scope_key.startswith(db.GROUP_KEY_PREFIX) else "label") if scope_key else "dashboard",
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
    if not _label_exists(conn, name):
        return RedirectResponse(url="/settings/labels", status_code=303)
    label = db.effective_label_config(conn, name)
    view = requested_view(request)
    if view == "agenda":
        return secretariat_page.render(
            conn, request, scope_key=name, title=name, icon_name=label.get("icon") or "tag", icon_color=label.get("color"),
            banner_ctx=dashboard_router._page_banner_context(conn, name, name=name), page_url=label_url(name), label=label,
            view="agenda",
        )
    if view == "board":
        tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
        return scope_board_page(
            conn, request, {name}, name, {**label, "tasks_widget": 1}, tasks, label_url(name),
            dashboard_router._page_banner_context(conn, name, name=name), None,
        )
    module_page = modules.PAGE_TYPES.get(label.get("page_type"))
    if module_page and module_page.module in modules.enabled_keys():
        return module_page.render(conn, request, name, label)
    return _sections_page(conn, request, name, label)


@router.get("/{name}/preview")
def label_preview(name: str, request: Request, conn=Depends(get_db)):
    """A label's compact preview modal. A label pill inside a card or a detail modal opens this
        rather than leaving the page. It shows the label's status, group, a short agenda and counts,
        with an Open page link and an Edit button.
    """
    if not _label_exists(conn, name):
        raise HTTPException(404, "No such shelf")
    label = db.effective_label_config(conn, name)
    tasks = [t for t in db.list_tasks_sharing_labels(conn, [name]) if t["status"] != "archived"]
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
    ctx["label_tag_pills"] = tag_store.tags_of_label(conn, name)
    return templates.TemplateResponse("label_preview_modal.html", ctx)


@router.post("/{name}/archive")
def archive_label(name: str, x_requested_with: str | None = Header(None), conn=Depends(get_db)):
    """The explicit "this is finished" confirmation. It's never automatic;
        see db.project_status for how Pending Archiving is computed.
    """
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


group_router = APIRouter(prefix="/groups", tags=["group-pages"])


def group_url(name: str) -> str:
    return f"/groups/{name}"


def _usage_by_label(conn) -> dict[str, int]:
    return {lbl["name"]: lbl.get("usage_count") or 0 for lbl in db.list_labels(conn)}


def _group_or_404(conn, name: str) -> dict:
    g = db.get_group(conn, name)
    if not g:
        raise HTTPException(404, "No such space")
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
    group_of = db.label_group_by_name(conn)
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
        raise HTTPException(400, "A space name can't start with \"group:\".")
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
    key = db.group_page_key(name)
    style = db.get_group_style(conn, name)
    banner_ctx = dashboard_router._page_banner_context(conn, key, name=name)
    icon_name = style["icon"] or db.GROUP_DEFAULT_ICON
    edit_url = f"/groups/{quote(name)}/edit"
    view = requested_view(request)
    if view == "agenda":
        return secretariat_page.render(
            conn, request, scope_key=key, title=name, icon_name=icon_name, icon_color=style["color"],
            banner_ctx=banner_ctx, page_url=group_url(name), header_edit_url=edit_url, view="agenda",
        )
    if view == "board":
        tasks = [
            t for t in dashboard_router._filtered_tasks(conn, {"label_name": key}, open_only=False)
            if t["status"] != "archived"
        ]
        label = {"name": name, "icon": icon_name, "color": style["color"], "tasks_widget": 1}
        return scope_board_page(
            conn, request, dashboard_router._scope_child_names(conn, key), key, label, tasks, group_url(name),
            banner_ctx, edit_url,
        )
    return _pooled_sections_page(
        conn, request, key, name, icon_name, style["color"], group_url(name), banner_ctx, edit_url
    )


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
        raise HTTPException(400, "A space name can't start with \"group:\".")
    if members_submitted:
        db.set_group_members(conn, name, members)
    db.set_group_style(conn, name, icon or None, color)
    if isinstance(page_type, str) and page_type:
        db.set_group_page_type(conn, name, page_type)
    final = db.rename_group(conn, name, new_name) if new_name else name
    ref = urlparse((request.headers.get("referer") if request is not None else "") or "")
    if ref.path.startswith("/settings/groups"):
        return RedirectResponse(url="/settings/groups", status_code=303)
    return RedirectResponse(url=group_url(final), status_code=303)


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
