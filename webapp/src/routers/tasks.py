from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import get_bridge, get_db, templates

router = APIRouter(prefix="/tasks", tags=["tasks"])

STATUSES = ["active", "in_progress", "waiting", "done", "archived"]
STATUS_LABELS = {
    "active": "Active",
    "in_progress": "In Progress",
    "waiting": "Waiting",
    "done": "Done",
    "archived": "Archived",
}
STATUS_COLORS = {
    "active": "blue",
    "in_progress": "orange",
    "waiting": "yellow",
    "done": "green",
    "archived": "gray",
}
PRIORITY_LABELS = {1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
PRIORITY_COLORS = {1: "red", 2: "orange", 3: "yellow", 4: "gray"}

# Reworked 2026-08-01: the single "smart filter" dropdown above (Today /
# Overdue / High Priority / Waiting / Completed / Archived / All Open /
# All) conflated three genuinely independent questions -- which dates,
# which status, which priority -- into one flat list of preset
# combinations, so you could never ask for e.g. "today's high-priority
# waiting tasks" without a new preset. Replaced by three independent
# filters that AND together. Each is computed in Python rather than SQL
# since "today"/"this week"/"overdue" depend on the current date, not a
# stored column.
DATE_FILTERS = ["all", "today", "this_week", "overdue"]
DATE_FILTER_LABELS = {"all": "All dates", "today": "Today", "this_week": "This week", "overdue": "Overdue"}

STATUS_FILTERS = ["all"] + STATUSES
STATUS_FILTER_LABELS = {"all": "All statuses", **STATUS_LABELS}

PRIORITY_FILTERS = ["all", "1", "2", "3", "4"]
PRIORITY_FILTER_LABELS = {"all": "All priorities", **{str(k): v for k, v in PRIORITY_LABELS.items()}}

DONE_STATUSES = ("done", "archived")


def _apply_date_filter(tasks: list[dict], date_filter: str) -> list[dict]:
    today = date.today()
    today_iso = today.isoformat()
    if date_filter == "today":
        return [t for t in tasks if t.get("due_at") and t["due_at"][:10] == today_iso]
    if date_filter == "this_week":
        end_iso = (today + timedelta(days=6)).isoformat()
        return [t for t in tasks if t.get("due_at") and today_iso <= t["due_at"][:10] <= end_iso]
    if date_filter == "overdue":
        return [t for t in tasks if t.get("due_at") and t["due_at"][:10] < today_iso]
    return tasks  # "all" -- no date filter, including tasks with no due date at all


def _apply_status_filter(tasks: list[dict], status_filter: str) -> list[dict]:
    if status_filter == "all":
        return tasks
    return [t for t in tasks if t["status"] == status_filter]


def _apply_priority_filter(tasks: list[dict], priority_filter: str) -> list[dict]:
    if priority_filter == "all":
        return tasks
    try:
        wanted = int(priority_filter)
    except ValueError:
        return tasks
    return [t for t in tasks if t.get("priority") == wanted]


def _apply_project_filter(
    tasks: list[dict],
    project_uid: str | None,
    group_uid: str | None,
    task_lists: list[dict],
    projects: list[dict],
) -> list[dict]:
    """Filter tasks to those whose task_list belongs to the given project or
    space (project_group). Both filters are additive (AND), but in practice
    only one of the two will normally be set at a time from the UI dropdowns.
    When neither is set this is a no-op."""
    if not project_uid and not group_uid:
        return tasks

    # Build a set of list UIDs that satisfy the filter.
    if project_uid:
        # Tasks whose list is directly linked to the chosen project.
        wanted_list_uids = {l["uid"] for l in task_lists if l.get("project_uid") == project_uid}
    else:
        # Space (group) filter: collect all project UIDs in this group, then
        # all list UIDs linked to those projects.
        group_project_uids = {p["uid"] for p in projects if p.get("group_uid") == group_uid}
        wanted_list_uids = {
            l["uid"] for l in task_lists if l.get("project_uid") in group_project_uids
        }

    return [t for t in tasks if t.get("list_path") in wanted_list_uids]


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _progress_for_status(status: str) -> float:
    """Same derived-progress mapping desktop uses (progress_for_status() in
    core/models/object.py) -- progress isn't independently editable here
    either, it just follows whatever status was last set."""
    return {"active": 0.0, "in_progress": 0.5, "waiting": 0.9, "done": 1.0, "archived": 1.0}.get(status, 0.0)


def _task_context(request: Request) -> dict:
    """Shared label/color lookups every task template needs for pill
    rendering -- one place so table/board/detail stay visually consistent."""
    return {
        "request": request,
        "active_tab": "tasks",
        "statuses": STATUSES,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "priority_labels": PRIORITY_LABELS,
        "priority_colors": PRIORITY_COLORS,
    }


_SORT_KEYS = {
    "title": lambda t: (t.get("title") or "").lower(),
    "due_at": lambda t: t.get("due_at") or "9999",
    "priority": lambda t: t.get("priority") if t.get("priority") is not None else 9,
    "status": lambda t: STATUSES.index(t["status"]) if t["status"] in STATUSES else 99,
}


@router.get("")
def list_tasks(
    request: Request,
    date_filter: str = "all",
    status_filter: str = "all",
    priority_filter: str = "all",
    q: str | None = None,
    sort: str = "due_at",
    dir: str = "asc",
    list_path: str | None = None,
    project_uid: str | None = None,
    group_uid: str | None = None,
    conn=Depends(get_db),
):
    task_lists = db.list_task_lists(conn)
    tasks = db.list_tasks(conn, q=q, list_path=list_path)
    tasks = _apply_date_filter(tasks, date_filter)
    tasks = _apply_status_filter(tasks, status_filter)
    tasks = _apply_priority_filter(tasks, priority_filter)
    tasks = _apply_project_filter(
        tasks,
        project_uid,
        group_uid,
        task_lists,
        db.list_projects(conn, include_archived=False),
    )
    key_fn = _SORT_KEYS.get(sort, _SORT_KEYS["due_at"])
    tasks.sort(key=key_fn, reverse=(dir == "desc"))

    # Completed tasks (done/archived) stay visible in every view -- Today,
    # This week, All -- rather than disappearing the moment they're
    # checked off, but are clearly separated and pushed below the open
    # ones (see tasks_list.html's two <tbody> sections) instead of
    # interleaved by date/priority with active work. If status_filter
    # already narrows to a single status, "separating" a single-status
    # list from itself would just be a redundant empty section, so the
    # split only actually matters (and the template only shows a divider)
    # when both groups are non-empty.
    open_tasks = [t for t in tasks if t["status"] not in DONE_STATUSES]
    completed_tasks = [t for t in tasks if t["status"] in DONE_STATUSES]

    # Which of the rows on this page have their own subtasks -- app-wide,
    # not just within the current filter/search (a subtask can easily not
    # match whatever filter its parent does). Used only so the row's
    # delete button can show an accurate "this also deletes N subtasks"
    # confirmation (see tasks_list.html) instead of a generic one -- see
    # plans/webapp-action-pipelines-audit.md's delete-confirmation finding.
    parent_uids = {t["parent_uid"] for t in db.list_tasks(conn) if t.get("parent_uid")}

    # Habits & Recurring section -- §3 of the plan. Recurring tasks are
    # surfaced here alongside active habits for daily use. Habit completions
    # stay local-only (no CalDAV sync of habit_entries). We only show
    # active (non-archived) habits; today's completion is a single lookup
    # per habit so the toggle checkbox has the right initial state.
    today_iso = date.today().isoformat()
    recurring_tasks = [t for t in db.list_tasks(conn) if t.get("recurrence") and t["status"] not in DONE_STATUSES]
    habits = db.list_habits(conn, include_archived=False)
    habit_entries_today = {
        h["uid"]: db.get_habit_entry(conn, h["uid"], today_iso)
        for h in habits
    }

    projects = db.list_projects(conn, include_archived=False)
    groups = db.list_project_groups(conn)
    ctx = _task_context(request)
    ctx.update(
        {
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "parent_uids": parent_uids,
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "status_filters": STATUS_FILTERS,
            "status_filter_labels": STATUS_FILTER_LABELS,
            "priority_filters": PRIORITY_FILTERS,
            "priority_filter_labels": PRIORITY_FILTER_LABELS,
            "active_date_filter": date_filter,
            "active_status_filter": status_filter,
            "active_priority_filter": priority_filter,
            "q": q or "",
            "sort": sort,
            "dir": dir,
            "task_lists": task_lists,
            "active_list": list_path or "",
            "tag_names": db.list_tag_names_in_use(conn),
            "recurring_tasks": recurring_tasks,
            "habits": habits,
            "habit_entries_today": habit_entries_today,
            "today_iso": today_iso,
            "projects": projects,
            "project_groups": groups,
            "active_project_uid": project_uid or "",
            "active_group_uid": group_uid or "",
        }
    )
    return templates.TemplateResponse("tasks_list.html", ctx)


# --------------------------------------------------------------------- #
# Inbox (spaces-home-pipeline, 2026-08-02) -- not new storage, a filtered
# view: an "Inbox" item is just a task whose list_path resolves to a
# task_lists row with no project_uid (see db.py's `projects` table comment
# for why project membership lives on the *list*, not the task). Reuses
# tasks_list.html wholesale -- same table macro, same bulk "Move to list"
# triage action -- just a pre-filtered dataset and different page copy
# (is_inbox in the template). Registered here, before the `/{uid}`-shaped
# routes below (same "literal routes before catch-all {uid}" ordering
# this router's own bulk_action comment already documents), so `GET
# /tasks/inbox` doesn't get swallowed by `task_detail`'s `/{uid}` with
# uid="inbox".
# --------------------------------------------------------------------- #


@router.get("/inbox")
def inbox_tasks(request: Request, conn=Depends(get_db)):
    task_lists = db.list_task_lists(conn)
    unassigned_list_uids = {l["uid"] for l in task_lists if not l.get("project_uid")}
    tasks = [t for t in db.list_tasks(conn) if t.get("list_path") in unassigned_list_uids]
    tasks.sort(key=_SORT_KEYS["due_at"])

    open_tasks = [t for t in tasks if t["status"] not in DONE_STATUSES]
    completed_tasks = [t for t in tasks if t["status"] in DONE_STATUSES]
    parent_uids = {t["parent_uid"] for t in db.list_tasks(conn) if t.get("parent_uid")}

    ctx = _task_context(request)
    ctx.update(
        {
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "parent_uids": parent_uids,
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "status_filters": STATUS_FILTERS,
            "status_filter_labels": STATUS_FILTER_LABELS,
            "priority_filters": PRIORITY_FILTERS,
            "priority_filter_labels": PRIORITY_FILTER_LABELS,
            "active_date_filter": "all",
            "active_status_filter": "all",
            "active_priority_filter": "all",
            "q": "",
            "sort": "due_at",
            "dir": "asc",
            "task_lists": task_lists,
            "active_list": "",
            "tag_names": db.list_tag_names_in_use(conn),
            "is_inbox": True,
        }
    )
    return templates.TemplateResponse("tasks_list.html", ctx)


@router.get("/board")
def board_view(request: Request, q: str | None = None, list_path: str | None = None, conn=Depends(get_db)):
    tasks = db.list_tasks(conn, q=q, list_path=list_path)
    # Board only ever shows open/active work by convention (matches
    # desktop's Kanban, which has no "show archived" toggle either) --
    # otherwise every completed task ever created accumulates forever in
    # the Done column with no way to clear it.
    tasks = [t for t in tasks if t["status"] != "archived"]
    columns = {s: [] for s in STATUSES if s != "archived"}
    for t in tasks:
        columns.setdefault(t["status"], []).append(t)
    ctx = _task_context(request)
    ctx.update(
        {
            "columns": columns,
            "board_statuses": [s for s in STATUSES if s != "archived"],
            "q": q or "",
            "task_lists": db.list_task_lists(conn),
            "active_list": list_path or "",
        }
    )
    return templates.TemplateResponse("tasks_board.html", ctx)


@router.get("/new")
def new_task_form(request: Request, parent_uid: str | None = None, list_path: str | None = None, conn=Depends(get_db)):
    parent = db.get_task(conn, parent_uid) if parent_uid else None
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": None,
            "statuses": STATUSES,
            "parent_uid": parent_uid,
            "task_lists": db.list_task_lists(conn),
            # A subtask defaults to its parent's list rather than whichever
            # list happened to be open in the table/board filter -- keeping
            # a task and its subtasks together is the more useful default.
            "selected_list": (parent.get("list_path") if parent else None) or list_path or db.DEFAULT_TASK_LIST_UID,
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@router.post("")
def create_task(
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    priority: str = Form(""),
    status: str = Form("active"),
    tags: str = Form(""),
    recurrence: str = Form(""),
    parent_uid: str = Form(""),
    list_path: str = Form(db.DEFAULT_TASK_LIST_UID),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "due_at": due_at or None,
        # "For tasks the start date is always today" -- deliberately not
        # a form field at all here (see task_form.html, which drops the
        # Start date input on the *new*-task form but keeps it on the
        # *edit* form). A task's start date can still be pushed out later
        # via editing -- this rule is about what a brand-new task starts
        # as, not a permanent lock.
        "start_at": date.today().isoformat(),
        "priority": int(priority) if priority else None,
        "status": status,
        "progress": _progress_for_status(status),
        "tags": _tags_list(tags),
        "parent_uid": parent_uid or None,
        "recurrence": recurrence or None,
        "list_path": list_path or db.DEFAULT_TASK_LIST_UID,
        "created_at": now,
        "updated_at": now,
    }
    saved = bridge.save_task_row(row)
    db.upsert_task(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    # A subtask created from its parent's detail page (see task_detail.html's
    # quick-add form) should land back on that same parent, not the flat
    # /tasks list -- otherwise "add subtask" would feel like it navigated
    # away rather than adding to what you were just looking at.
    dest = f"/tasks/{parent_uid}" if parent_uid else "/tasks"
    return RedirectResponse(url=dest, status_code=303)


# --------------------------------------------------------------------- #
# Bulk actions (Table view's row-select checkboxes, static/tasks_table.js)
# 2026-08-01 -- see plans/webapp-action-pipelines-audit.md's "no bulk
# select/bulk action anywhere in Tasks" finding. One JSON endpoint
# dispatching on `action`, mirroring update_field's "JSON body, fetch-only,
# no plain-form fallback" shape below -- a bulk action only ever makes
# sense from a JS-driven multi-select UI in the first place, there's no
# meaningful no-JS equivalent to degrade to the way every single-task
# action in this router has one.
#
# Registered here, right after create_task and before any `/{uid}`-shaped
# route -- same "literal routes before catch-all {uid} routes" ordering
# this router's own timeline.router comment already documents elsewhere
# in this codebase. `POST /tasks/{uid}` (update_task, below) would
# otherwise match `/tasks/bulk` first (uid="bulk") and shadow this route
# entirely -- confirmed the hard way, the exact same class of bug.
# --------------------------------------------------------------------- #


@router.post("/bulk")
async def bulk_action(request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)):
    payload = await request.json()
    action = payload.get("action")
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no tasks selected"}, status_code=400)

    if action == "delete":
        # Same cascade-to-subtasks logic as the single-task delete_task
        # below, just looped -- deliberately not deduped against uids that
        # are themselves already in the selection (deleting a task twice,
        # once directly and once as another selected task's subtask
        # cascade, is a harmless no-op the second time: get_task/
        # list_subtasks on an already-gone uid just returns nothing).
        for uid in uids:
            existing = db.get_task(conn, uid)
            for child in db.list_subtasks(conn, uid):
                bridge.delete_task(child["uid"], child.get("list_path") or db.DEFAULT_TASK_LIST_UID)
                db.delete_task(conn, child["uid"])
                db.delete_checklist_items_for_task(conn, child["uid"])
            bridge.delete_task(uid, (existing or {}).get("list_path") or db.DEFAULT_TASK_LIST_UID)
            db.delete_task(conn, uid)
            db.delete_checklist_items_for_task(conn, uid)
        return JSONResponse({"ok": True, "count": len(uids)})

    if action == "status":
        status = payload.get("status")
        if status not in STATUSES:
            return JSONResponse({"error": f"invalid status '{status}'"}, status_code=400)
        for uid in uids:
            row = db.get_task(conn, uid)
            if row is None:
                continue
            row["status"] = status
            row["progress"] = _progress_for_status(status)
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            saved = bridge.save_task_row(row)
            db.upsert_task(conn, saved)
        return JSONResponse({"ok": True, "count": len(uids)})

    if action == "move_list":
        list_path = payload.get("list_path")
        if not list_path:
            return JSONResponse({"error": "list_path required"}, status_code=400)
        for uid in uids:
            row = db.get_task(conn, uid)
            if row is None:
                continue
            old_list_path = row.get("list_path") or db.DEFAULT_TASK_LIST_UID
            if list_path == old_list_path:
                continue
            # Same "different CalDAV collection = delete-then-recreate"
            # move as the single-task edit form's update_task below.
            bridge.delete_task(uid, old_list_path)
            row["list_path"] = list_path
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            saved = bridge.save_task_row(row)
            db.upsert_task(conn, saved)
        return JSONResponse({"ok": True, "count": len(uids)})

    if action == "tag":
        tag = (payload.get("tag") or "").strip()
        mode = payload.get("mode")  # "add" | "remove"
        if not tag or mode not in ("add", "remove"):
            return JSONResponse({"error": "tag and mode ('add'/'remove') required"}, status_code=400)
        for uid in uids:
            row = db.get_task(conn, uid)
            if row is None:
                continue
            tags = set(row.get("tags") or [])
            if mode == "add":
                tags.add(tag)
            else:
                tags.discard(tag)
            row["tags"] = sorted(tags)
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            saved = bridge.save_task_row(row)
            db.upsert_task(conn, saved)
            db.ensure_tags_registered(conn, row["tags"])
        return JSONResponse({"ok": True, "count": len(uids)})

    return JSONResponse({"error": f"unknown action '{action}'"}, status_code=400)


@router.get("/{uid}/edit")
def edit_task_form(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    # Same accurate-delete-confirmation reasoning as task_detail.html/
    # tasks_list.html -- this form's own Delete button needs to know
    # whether it's about to cascade too.
    subtask_count = len([t for t in db.list_tasks(conn) if t.get("parent_uid") == uid]) if task else 0
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": task,
            "statuses": STATUSES,
            "parent_uid": None,
            "task_lists": db.list_task_lists(conn),
            "selected_list": task.get("list_path") if task else db.DEFAULT_TASK_LIST_UID,
            "tag_names": db.list_tag_names_in_use(conn),
            "subtask_count": subtask_count,
        },
    )


@router.get("/{uid}")
def task_detail(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    ctx = _task_context(request)
    parent = db.get_task(conn, task["parent_uid"]) if task and task.get("parent_uid") else None
    task_list = db.get_task_list(conn, task["list_path"]) if task and task.get("list_path") else None
    ctx.update(
        {
            "task": task,
            "parent": parent,
            "task_list": task_list,
            "subtasks": db.list_subtasks(conn, uid) if task else [],
            "checklist": db.list_checklist_items(conn, uid) if task else [],
        }
    )
    return templates.TemplateResponse("task_detail.html", ctx)


@router.post("/{uid}")
def update_task(
    uid: str,
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    start_at: str = Form(""),
    priority: str = Form(""),
    status: str = Form("active"),
    tags: str = Form(""),
    recurrence: str = Form(""),
    list_path: str = Form(""),
    bridge=Depends(get_bridge),
    conn=Depends(get_db),
):
    existing = db.get_task(conn, uid) or {}
    old_list_path = existing.get("list_path") or db.DEFAULT_TASK_LIST_UID
    new_list_path = list_path or old_list_path
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "title": title,
            "description": description,
            "due_at": due_at or None,
            "start_at": start_at or None,
            "priority": int(priority) if priority else None,
            "status": status,
            "progress": _progress_for_status(status),
            "tags": _tags_list(tags),
            "recurrence": recurrence or None,
            "list_path": new_list_path,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if new_list_path != old_list_path:
        # Moving between lists = different CalDAV collection = delete from
        # the old one, create fresh in the new one (same uid), matching how
        # update_event handles a calendar move (routers/calendar.py).
        bridge.delete_task(uid, old_list_path)
    saved = bridge.save_task_row(row)
    db.upsert_task(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return RedirectResponse(url="/tasks", status_code=303)


_UPDATABLE_FIELDS = {"status", "priority", "due_at", "title"}


@router.post("/{uid}/update-field")
async def update_field(uid: str, request: Request, bridge=Depends(get_bridge), conn=Depends(get_db)):
    """Single-field inline edit, used by both the Table view's click-to-edit
    pills/date cell and the Kanban board's drag-to-a-new-column (which is
    just a `field=status` call). Deliberately a JSON body, not a Form --
    this is only ever called from tasks_table.js/tasks_kanban.js via
    fetch(), never from a plain HTML form/no-JS fallback, unlike every
    other route in this router."""
    payload = await request.json()
    field = payload.get("field")
    value = payload.get("value")
    if field not in _UPDATABLE_FIELDS:
        return JSONResponse({"error": f"field '{field}' is not inline-editable"}, status_code=400)
    existing = db.get_task(conn, uid)
    if existing is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    row = dict(existing)
    if field == "priority":
        row["priority"] = int(value) if value else None
    elif field == "due_at":
        row["due_at"] = value or None
    elif field == "status":
        row["status"] = value
        row["progress"] = _progress_for_status(value)
    else:  # title
        row["title"] = value
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    saved = bridge.save_task_row(row)
    db.upsert_task(conn, saved)
    db.ensure_tags_registered(conn, row["tags"])
    return JSONResponse({"ok": True})


@router.post("/{uid}/complete")
def complete_task(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    row = db.get_task(conn, uid)
    if row:
        row["status"] = "done"
        row["progress"] = 1.0
        saved = bridge.save_task_row(row)
        db.upsert_task(conn, saved)
    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/{uid}/delete")
def delete_task(uid: str, bridge=Depends(get_bridge), conn=Depends(get_db)):
    # Cascade to subtasks -- a subtask with a parent_uid pointing at a task
    # that no longer exists would be an orphan with no way to reach it from
    # the UI (subtasks are only ever listed via their parent's detail page).
    # Desktop doesn't cascade (its subtasks are independent objects you can
    # still find via Table/Kanban/Timeline), but this app's only path to a
    # subtask *is* its parent's detail page, so leaving them behind here
    # would make them permanently unreachable rather than just "independent."
    existing = db.get_task(conn, uid)
    for child in db.list_subtasks(conn, uid):
        bridge.delete_task(child["uid"], child.get("list_path") or db.DEFAULT_TASK_LIST_UID)
        db.delete_task(conn, child["uid"])
        db.delete_checklist_items_for_task(conn, child["uid"])
    bridge.delete_task(uid, (existing or {}).get("list_path") or db.DEFAULT_TASK_LIST_UID)
    db.delete_task(conn, uid)
    db.delete_checklist_items_for_task(conn, uid)
    return RedirectResponse(url="/tasks", status_code=303)


# --------------------------------------------------------------------- #
# Checklist (local-only, see db.py module docstring)
# --------------------------------------------------------------------- #


@router.post("/{uid}/checklist")
def add_checklist_item(uid: str, text: str = Form(...), conn=Depends(get_db)):
    if text.strip():
        db.add_checklist_item(
            conn, uid, str(uuid.uuid4()), text.strip(), datetime.now(timezone.utc).isoformat()
        )
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/checklist/{item_uid}/toggle")
def toggle_checklist_item(uid: str, item_uid: str, conn=Depends(get_db)):
    db.toggle_checklist_item(conn, item_uid)
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/checklist/{item_uid}/delete")
def delete_checklist_item(uid: str, item_uid: str, conn=Depends(get_db)):
    db.delete_checklist_item(conn, item_uid)
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)
