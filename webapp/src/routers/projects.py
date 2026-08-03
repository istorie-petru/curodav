"""Projects: local-only structural grouping on top of the synced CalDAV/
CardDAV data -- see db.py's `projects` table comment for the full
rationale (short version: no CalDAV/CardDAV concept for a project, so a
whole task list/calendar/address book/schedule class points at a project
via its own `project_uid` rather than a new link/graph table).

This router owns three things:
  1. The manage page (`/projects`) -- create/rename/recolor/icon/group/
     merge/archive/delete, same "flat row list in a modal" pattern as
     tags.py/task_lists.py/addressbooks.py.
  2. The project detail page (`/projects/{uid}`) -- centralizes every
     task/event/contact/class belonging to a list linked to this project,
     plus a derived (never stored) progress bar, matching desktop's
     project view ("the project object + everything with parent_id =
     project" -- here, "everything under every linked list" instead, since
     this app has no parent_id-style object graph).
  3. Cover image upload -- same base64-in-SQLite approach as contacts'
     photo, see _read_cover_image below.

Linking an *existing* list to a project (the dropdown on task_lists_manage/
calendars_list/addressbooks_manage/schedule_class_form) is the next phase,
not this one -- this router only needs read access to whatever's already
linked (via Phase 1's set_*_project setters, exercised directly by tests
until that UI exists) to build the detail page correctly.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from .. import db
from ..deps import get_db, templates
from . import dashboard as dashboard_router
from .tasks import PRIORITY_COLORS, PRIORITY_LABELS, STATUS_COLORS, STATUS_LABELS

router = APIRouter(prefix="/projects", tags=["projects"])

COLORS = ["blue", "green", "orange", "red", "purple", "pink", "gray", "yellow"]
DONE_STATUSES = ("done", "archived")

# Curated icon choices for a project's `icon` field (2026-08-02, revised
# same day -- "the emoji selector should work from a curated list of the
# icon library used for the rest of the app", not a one-off emoji set).
# Each entry is a key into the same sprite every `{{ icon(name) }}` call
# in this app already draws from (templates/_icons_sprite.html) -- a
# project's icon is now literally one of the app's own UI icons, not a
# free-text glyph, so it always renders consistently (light/dark, every
# font) instead of depending on whatever emoji font the browser/OS
# happens to have. Deliberately a subset of the full sprite: excludes
# pure-chrome glyphs that only make sense as an action (x, plus, the
# chevrons, move, corner-down-right) since those would read as a stray
# button floating next to a project's name, not an identity for it.
# `icon` remains a plain TEXT column in the DB (db.py's `projects`
# table) -- this list only shapes the picker UI; the server still
# accepts and stores whatever string comes through, same as before.
# Expanded (2026-08-02) from a 20-icon set to ~100 -- "add more icons that
# would also be more representative" -- pulling in the ~120 Feather icons
# templates/_icons_sprite.html gained the same day (a subject a project
# might actually be *about* -- coursework, a business, a hobby, a trip --
# not just generic app chrome). Organized here by rough theme purely for
# anyone editing this list later; the picker itself renders them in this
# same flat order, no grouping in the UI.
PROJECT_ICONS = [
    # Organization / work
    "folder", "briefcase", "clipboard", "file", "file-text", "archive",
    "inbox", "layers", "layout", "grid", "sidebar", "columns", "target",
    "flag", "award", "star", "bookmark", "list", "tag",
    # Education / reading
    "book", "book-open", "edit-3", "pen-tool", "type",
    # Tech / software
    "code", "terminal", "cpu", "monitor", "smartphone", "tablet", "server",
    "hard-drive", "database", "wifi", "bluetooth", "cast", "airplay",
    "github", "git-branch", "git-commit", "git-pull-request", "command",
    "disc", "download", "upload", "share", "share-2", "link", "link-2", "rss",
    # Communication / people
    "mail", "phone", "send", "at-sign", "hash", "address-book", "user",
    "users", "user-plus", "user-check", "heart", "smile", "thumbs-up",
    # Media / creative
    "camera", "video", "film", "music", "headphones", "mic", "image",
    "printer", "scissors", "paperclip", "aperture", "play", "pause",
    "volume-2", "radio", "tv", "speaker",
    # Business / finance
    "dollar-sign", "credit-card", "trending-up", "trending-down",
    "bar-chart", "bar-chart-2", "pie-chart", "shopping-cart",
    "shopping-bag", "package", "box", "truck", "gift",
    # Outdoors / travel / nature
    "sun", "cloud", "cloud-rain", "wind", "thermometer", "droplet",
    "umbrella", "sunrise", "sunset", "globe", "map", "map-pin", "compass",
    "navigation", "navigation-2", "anchor", "feather",
    # Health / security / misc
    "shield", "lock", "unlock", "key", "life-buoy", "eye", "watch",
    "clock", "bell", "tool", "settings", "activity", "calendar", "home",
]

# Same reasoning/allowlist as contacts.py's _read_photo -- this app has no
# auth, so an unauthenticated file upload gets validated against a fixed
# content-type allowlist and a size cap rather than trusted on the
# client's say-so. Unlike contact photos there's no vCard PHOTO property
# to map onto (a project isn't synced at all), so the raw content-type is
# stored as-is and used directly in a `data:{type};base64,...` URI.
_MAX_COVER_BYTES = 5 * 1024 * 1024
_ALLOWED_COVER_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


async def _read_cover_image(image: UploadFile | None) -> tuple[str, str] | None:
    if image is None or not image.filename:
        return None
    content_type = (image.content_type or "").lower()
    if content_type not in _ALLOWED_COVER_TYPES:
        raise HTTPException(400, f"Unsupported image type '{image.content_type}' -- use JPEG, PNG, GIF, or WEBP.")
    data = await image.read()
    if len(data) > _MAX_COVER_BYTES:
        raise HTTPException(400, "Cover image is too large (max 5MB).")
    return base64.b64encode(data).decode("ascii"), content_type


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_collections_by_project(conn) -> dict:
    """Every task list/calendar/address book bucketed by which project it's
    linked to (2026-08-02 -- "link specific webdav lists (calendar, tasks,
    contacts) as subordinates for a project, ... easy add new lists, easy
    add for existing lists, existing lists can not be reused in another
    project"). No new storage or linking mechanism here -- task_lists/
    calendars/addressbooks already each carry their own nullable
    project_uid (see db.py's `projects` table comment); this just buckets
    the existing rows by that column, the same project_by_group split
    manage_projects does one level up for Spaces. "Can't be reused" falls
    out of this split for free: a list with a project_uid already set
    never lands in the unclaimed_* bucket, so it's never offered as a
    "link existing" candidate for a *different* project -- see
    project_lists_modal's Link picker. Shared by manage_projects (which
    only needs the counts, for each project row's "Lists (N)" button) and
    project_lists_modal (which needs the full detail for one project)."""
    task_lists_by_project: dict[str, list[dict]] = {}
    unclaimed_task_lists: list[dict] = []
    for l in db.list_task_lists(conn):
        (task_lists_by_project.setdefault(l["project_uid"], []) if l.get("project_uid") else unclaimed_task_lists).append(l)

    calendars_by_project: dict[str, list[dict]] = {}
    unclaimed_calendars: list[dict] = []
    for c in db.list_calendars(conn):
        (calendars_by_project.setdefault(c["project_uid"], []) if c.get("project_uid") else unclaimed_calendars).append(c)

    addressbooks_by_project: dict[str, list[dict]] = {}
    unclaimed_addressbooks: list[dict] = []
    for a in db.list_addressbooks(conn):
        (addressbooks_by_project.setdefault(a["project_uid"], []) if a.get("project_uid") else unclaimed_addressbooks).append(a)

    return {
        "task_lists_by_project": task_lists_by_project,
        "unclaimed_task_lists": unclaimed_task_lists,
        "calendars_by_project": calendars_by_project,
        "unclaimed_calendars": unclaimed_calendars,
        "addressbooks_by_project": addressbooks_by_project,
        "unclaimed_addressbooks": unclaimed_addressbooks,
    }


@router.get("")
def manage_projects(request: Request, conn=Depends(get_db)):
    groups = db.list_project_groups(conn)
    projects = db.list_projects(conn)
    projects.sort(key=lambda p: p["name"].lower())
    # Nested Space -> Projects structure (2026-08-02 -- "the projects
    # grouped by spaces, and their configs to not be separate, but
    # actually together and subordinated"): each Space's own projects are
    # attached directly to it (projects_by_group[space.uid]) instead of
    # the page rendering two separate flat sections (a Groups list, then
    # a Projects list re-grouped by Jinja's `groupby` filter) the way it
    # did before. Ungrouped projects still get their own bucket, rendered
    # as a trailing section with no Space header of its own.
    projects_by_group: dict[str, list[dict]] = {g["uid"]: [] for g in groups}
    ungrouped_projects: list[dict] = []
    for p in projects:
        bucket = projects_by_group.get(p.get("group_uid"))
        (bucket if bucket is not None else ungrouped_projects).append(p)

    collections = _list_collections_by_project(conn)

    return templates.TemplateResponse(
        "projects_manage.html",
        {
            "request": request,
            "active_tab": "projects",
            "settings_tab": "projects",
            "groups": groups,
            "projects_by_group": projects_by_group,
            "ungrouped_projects": ungrouped_projects,
            "project_count": len(projects),
            "archived_projects": [p for p in db.list_projects(conn, include_archived=True) if p["archived_at"]],
            "colors": COLORS,
            "project_icons": PROJECT_ICONS,
            **collections,
        },
    )


@router.get("/{uid}/lists")
def project_lists_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The "Lists (N)" button on each project row opens this as a modal
    (2026-08-02 -- "the lists is just a button. it opens a modal window",
    replacing the earlier inline collapsed-<details> version) rather than
    expanding inline on the manage page -- same data (_list_collections_
    by_project), just presented the same way Merge already is (project_
    merge.html)."""
    project = db.get_project(conn, uid)
    if project is None:
        return RedirectResponse(url="/projects", status_code=303)
    return templates.TemplateResponse(
        "project_lists_modal.html",
        {
            "request": request,
            "project": project,
            **_list_collections_by_project(conn),
        },
    )


@router.get("/new-project")
def new_project_modal(request: Request, group_uid: str = "", conn=Depends(get_db)):
    """The "+" button next to each Space's project list (2026-08-02 --
    "the new project could just be a + icon button that sits for each
    space") -- a tiny name-only modal instead of the inline text input +
    button quick_add_project used to render directly on the manage page,
    same "just a button, it opens a modal" direction as Lists/Merge
    above. `group_uid` (optional query param, not a path segment --
    there's no project yet to hang a path segment off of) presets which
    Space the new project lands in; "" is a real, valid choice (the
    Ungrouped section's own + button) meaning no Space.

    Registered here, before the catch-all `GET /{uid}` (project_detail,
    further down) -- "new-project" is a literal path, but it's still one
    path segment, exactly what `/{uid}` also matches, so this has to come
    first or `/projects/new-project` would resolve as
    project_detail(uid="new-project") instead. Same reasoning already
    documented on this router's /{uid}/lists and /{uid}/merge above,
    just for a literal segment instead of one that merely happens not to
    collide with any real project uid in practice."""
    group = db.get_project_group(conn, group_uid) if group_uid else None
    return templates.TemplateResponse(
        "project_new_modal.html",
        {"request": request, "group": group, "group_uid": group_uid},
    )


@router.post("")
async def create_project(
    name: str = Form(...),
    color: str = Form("blue"),
    icon: str = Form(""),
    group_uid: str = Form(""),
    conn=Depends(get_db),
):
    name = name.strip()
    if name:
        now = _now()
        db.upsert_project(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "name": name,
                "description": "",
                "color": color,
                "icon": icon.strip() or None,
                "group_uid": group_uid or None,
                "created_at": now,
                "updated_at": now,
            },
        )
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{uid}/edit")
async def edit_project(
    uid: str,
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    group_uid: str = Form(""),
    cover_image: UploadFile | None = File(None),
    remove_cover_image: str = Form(""),
    return_to: str = Form(""),
    conn=Depends(get_db),
):
    # return_to (2026-08-02) -- this endpoint is now posted to from two
    # different places: project_detail.html's own "Edit project" panel
    # (no return_to; keeps the original "land back on this project"
    # behavior below) and projects_manage.html's per-row autosubmit
    # color/icon/name/Space pickers (return_to="/projects" -- picking a
    # color there used to redirect the whole page away to the project's
    # detail page on every single click, which is exactly the "clicking
    # the picker opens the project" bug this fixes). Only accepts a
    # same-origin absolute path (starts with "/"), never an arbitrary
    # URL, so this can't be turned into an open redirect via a crafted
    # form post.
    redirect_url = return_to if isinstance(return_to, str) and return_to.startswith("/") else f"/projects/{uid}"
    existing = db.get_project(conn, uid)
    if existing is None:
        return RedirectResponse(url="/projects", status_code=303)
    row = dict(existing)
    row.update(
        {
            "name": name.strip() or existing["name"],
            "description": description,
            "color": color,
            "icon": icon.strip() or None,
            "group_uid": group_uid or None,
            "updated_at": _now(),
        }
    )
    if remove_cover_image:
        row["cover_image_b64"] = None
        row["cover_image_type"] = None
    else:
        result = await _read_cover_image(cover_image)
        if result:
            row["cover_image_b64"], row["cover_image_type"] = result
        # else: no new file chosen -- row already carries the existing
        # cover_image_b64/type through from dict(existing) above.
    db.upsert_project(conn, row)
    return RedirectResponse(url=redirect_url, status_code=303)


@router.post("/{uid}/archive")
def archive_project(uid: str, conn=Depends(get_db)):
    db.archive_project(conn, uid, _now())
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{uid}/unarchive")
def unarchive_project(uid: str, conn=Depends(get_db)):
    db.unarchive_project(conn, uid)
    return RedirectResponse(url="/projects", status_code=303)


def _project_task_count(conn, project_uid: str) -> int:
    """Quick per-project task count for the merge picker (2026-08-02) --
    deliberately lighter than _project_scope below (tasks only, no
    calendars/contacts/classes), since this runs once per *candidate*
    destination project, not just the one project a detail page shows."""
    list_uids = {l["uid"] for l in db.list_task_lists(conn) if l.get("project_uid") == project_uid}
    if not list_uids:
        return 0
    return len([t for t in db.list_tasks(conn) if t.get("list_path") in list_uids])


@router.get("/{uid}/merge")
def merge_project_modal(uid: str, request: Request, conn=Depends(get_db)):
    """Merge picker (2026-08-02 -- "merge into to be a button ... that
    creates a modal window with information of the merged and the
    merger"): shows the project about to be merged away (the "merger")
    plus every other active project as a selectable candidate (the
    "merged [into]"), each with its own task count, before committing --
    replaces the old bare inline dropdown+button. POST /{uid}/merge below
    (unchanged) still does the actual merge."""
    project = db.get_project(conn, uid)
    if project is None:
        return RedirectResponse(url="/projects", status_code=303)
    candidates = [p for p in db.list_projects(conn) if p["uid"] != uid]
    candidates.sort(key=lambda p: p["name"].lower())
    for p in candidates:
        p["tasks_total"] = _project_task_count(conn, p["uid"])
    return templates.TemplateResponse(
        "project_merge.html",
        {
            "request": request,
            "project": project,
            "project_tasks_total": _project_task_count(conn, uid),
            "candidates": candidates,
        },
    )


@router.post("/{uid}/merge")
def merge_project(uid: str, dest_uid: str = Form(...), conn=Depends(get_db)):
    if dest_uid and dest_uid != uid:
        db.merge_projects(conn, uid, dest_uid)
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{uid}/delete")
def delete_project(uid: str, conn=Depends(get_db)):
    db.delete_project(conn, uid)
    return RedirectResponse(url="/projects", status_code=303)


# --------------------------------------------------------------------- #
# Project groups
# --------------------------------------------------------------------- #


@router.post("/groups")
def create_project_group(name: str = Form(...), color: str = Form("blue"), conn=Depends(get_db)):
    name = name.strip()
    if name:
        db.upsert_project_group(conn, {"uid": str(uuid.uuid4()), "name": name, "color": color, "created_at": _now()})
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/groups/{uid}/edit")
def edit_project_group(
    uid: str,
    name: str = Form(...),
    color: str = Form("blue"),
    default_range_days: str = Form(""),
    conn=Depends(get_db),
):
    if name.strip():
        row: dict = {"uid": uid, "name": name.strip(), "color": color, "created_at": None}
        if default_range_days.strip():
            try:
                row["default_range_days"] = max(1, int(default_range_days))
            except ValueError:
                pass
        db.upsert_project_group(conn, row)
    return RedirectResponse(url="/projects", status_code=303)


@router.post("/groups/{uid}/delete")
def delete_project_group(uid: str, conn=Depends(get_db)):
    db.delete_project_group(conn, uid)
    return RedirectResponse(url="/projects", status_code=303)


# --------------------------------------------------------------------- #
# Space detail (spaces-home-pipeline, 2026-08-02; widget grid follow-up
# same day) -- the one genuinely new page this doc adds: a weekly view of
# one project_groups row and the projects under it, now with the same
# customizable widget grid Home has (routers/dashboard.py's
# widget_page_context/WIDGET_TYPES/add_widget/etc, all shared verbatim --
# see _widget_workspace.html). Seeded on first visit with a Weekly
# Overview + Project Cards widget, both auto-scoped to this group via
# config["group_uid"] so they're useful immediately.
# --------------------------------------------------------------------- #


@router.get("/groups/{uid}")
def space_detail(uid: str, request: Request, edit: bool = False, conn=Depends(get_db)):
    group = db.get_project_group(conn, uid)
    if group is None:
        raise HTTPException(404, "Space not found")
    dashboard_router._ensure_default_space_widgets(conn, uid)
    ctx = dashboard_router.widget_page_context(conn, space_uid=uid, edit=edit)
    # Determine whether this space has any schedule classes linked to one of
    # its projects -- if so, expose a Schedule Settings shortcut on the page
    # (space_detail.html). Classes link to *projects* (via project_uid), not
    # directly to groups, so we collect the UIDs of all projects in this
    # space first, then check for any matching class.
    space_project_uids = {
        p["uid"] for p in db.list_projects(conn, include_archived=True)
        if p.get("group_uid") == uid
    }
    has_schedule_classes = any(
        c.get("project_uid") in space_project_uids
        for c in db.list_schedule_classes(conn)
    ) if space_project_uids else False
    ctx.update(
        {
            "request": request,
            "active_tab": "projects",
            "group": group,
            "space": group,
            "has_schedule_classes": has_schedule_classes,
        }
    )
    return templates.TemplateResponse("space_detail.html", ctx)


# --------------------------------------------------------------------- #
# Project detail -- centralizes tasks/events/contacts/classes from every
# list linked to this project.
# --------------------------------------------------------------------- #


def _project_scope(conn, project_uid: str) -> dict:
    """Every list linked to this project, and the actual tasks/events/
    contacts/classes inside those lists -- the "centralizes all tasks,
    events, contacts" behavior. All four collection types are scanned in
    Python (not a SQL join) since project_uid lives on four differently-
    shaped tables with no shared parent -- at personal-scale row counts
    this is simpler and cheap, same tradeoff db.py's tag usage-count query
    already makes."""
    task_lists = [l for l in db.list_task_lists(conn) if l.get("project_uid") == project_uid]
    calendars = [c for c in db.list_calendars(conn) if c.get("project_uid") == project_uid]
    addressbooks = [a for a in db.list_addressbooks(conn) if a.get("project_uid") == project_uid]
    classes = [c for c in db.list_schedule_classes(conn) if c.get("project_uid") == project_uid]

    tasks: list[dict] = []
    for l in task_lists:
        tasks.extend(db.list_tasks(conn, list_path=l["uid"]))

    calendar_uids = {c["uid"] for c in calendars}
    events = [e for e in db.list_events(conn) if e.get("calendar_path") in calendar_uids] if calendar_uids else []
    events.sort(key=lambda e: e.get("start_at") or "9999")

    contacts: list[dict] = []
    for a in addressbooks:
        contacts.extend(db.list_contacts(conn, addressbook_path=a["uid"]))

    total = len(tasks)
    done = len([t for t in tasks if t["status"] in DONE_STATUSES])
    progress = round(100 * done / total) if total else None

    return {
        "task_lists": task_lists,
        "calendars": calendars,
        "addressbooks": addressbooks,
        "classes": classes,
        "tasks": tasks,
        "events": events,
        "contacts": contacts,
        "progress": progress,
        "tasks_done": done,
        "tasks_total": total,
    }


@router.get("/{uid}")
def project_detail(uid: str, request: Request, conn=Depends(get_db)):
    project = db.get_project(conn, uid)
    ctx = {
        "request": request,
        "active_tab": "projects",
        "project": project,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "priority_labels": PRIORITY_LABELS,
        "priority_colors": PRIORITY_COLORS,
        "all_projects": [p for p in db.list_projects(conn) if p["uid"] != uid],
        # Breadcrumb (Step 5, spaces-home-pipeline) -- only set when this
        # project actually belongs to a Space, so _breadcrumb.html's `{%
        # if space %}` segment simply doesn't render otherwise.
        "space": db.get_project_group(conn, project["group_uid"]) if project and project.get("group_uid") else None,
        # Same color/icon pickers as the manage page (2026-08-02) -- this
        # page's own "Edit project" details panel edits the same two
        # fields, so it uses the identical picker components/lists rather
        # than a second, differently-behaved color select + free-text
        # icon input.
        "colors": COLORS,
        "project_icons": PROJECT_ICONS,
    }
    if project:
        scope = _project_scope(conn, uid)
        ctx.update(scope)

        # §5 University module: separate "Homework" tasks from other tasks
        # so the template can render them in their own section. This is a
        # pure template-level filter -- no new DB query, just two views of
        # the same `scope["tasks"]` list that _project_scope already built.
        # "Homework" is matched case-insensitively so a tag typed as
        # "homework" or "HOMEWORK" also qualifies.
        all_tasks = scope.get("tasks", [])
        ctx["homework_tasks"] = [
            t for t in all_tasks
            if any(tag.lower() == "homework" for tag in (t.get("tags") or []))
        ]
        ctx["other_tasks"] = [
            t for t in all_tasks
            if not any(tag.lower() == "homework" for tag in (t.get("tags") or []))
        ]

        # §5 Professor contact: look up the contact for each linked class
        # so the template can render a mailto: link without a DB call.
        # classes is already in scope["classes"]; we build a uid->contact
        # dict covering every professor_contact_uid that actually exists.
        classes = scope.get("classes", [])
        professor_contacts: dict[str, dict] = {}
        for cl in classes:
            puid = cl.get("professor_contact_uid")
            if puid and puid not in professor_contacts:
                contact = db.get_contact(conn, puid)
                if contact:
                    professor_contacts[puid] = contact
        ctx["professor_contacts"] = professor_contacts

        # §5 Grades databases: any database linked to this project so the
        # template can show a direct link to the grade tracker.
        ctx["project_databases"] = db.list_databases(conn, project_uid=uid)

    return templates.TemplateResponse("project_detail.html", ctx)
