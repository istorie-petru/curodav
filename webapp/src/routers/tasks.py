from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, habit_heatmap
from ..deps import get_db, templates
from . import dashboard as dashboard_router
from . import calendar as calendar_router  # _annotate_calendar_colors, for related events' identity dots

router = APIRouter(prefix="/tasks", tags=["tasks"])

# "Auto-archive completed tasks" (Settings > Advanced, 2026-08-08) -- the
# stored preference is a plain string count of days ("" or "0" = Never,
# the default; otherwise a positive integer). Checked lazily on every
# visit to the main Table view (_auto_archive_if_configured below) rather
# than on a scheduler, matching this app's existing "no cron, check on
# page visit" idiom (see routers/dashboard.py's _ensure_default_widgets)
# -- this app has no background job runner (main.py's only background
# task is the Radicale sync loop), and a cheap conditional DELETE that's
# almost always a no-op costs nothing meaningful to run on each visit.
TASK_AUTO_ARCHIVE_DAYS_KEY = "task_auto_archive_days"


def _auto_archive_if_configured(conn) -> None:
    raw = db.get_app_meta(conn, TASK_AUTO_ARCHIVE_DAYS_KEY) or "0"
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if days > 0:
        db.delete_old_completed_tasks(conn, days)


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

# 2026-08-08 direct feedback ("rework Priority/Status/Recurrence to look
# the same as Range/View/Labels") -- task_form.html's Priority/Status
# fields moved from plain `<select>`s (a browser's own unstyleable open-
# dropdown chrome, the same problem View/Range had before their 2026-08-07
# rework -- see _widget_list_multiselect.html's header comment) to the
# same single-mode multiselect panel View/Range/Labels already share.
# {uid, name} pairs, the same shape that partial expects everywhere else.
PRIORITY_ITEMS = [{"uid": "", "name": "(none)"}] + [
    {"uid": str(p), "name": f"{p} - {label}"} for p, label in PRIORITY_LABELS.items()
]
STATUS_ITEMS = [{"uid": s, "name": STATUS_LABELS[s]} for s in STATUSES]

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


def _apply_label_filter(tasks: list[dict], label: str | None) -> list[dict]:
    """Phase 9b toolbar rework -- Tasks' new label filter, same
    case-insensitive single-label match Contacts' `?tag=` filter already
    uses (routers/contacts.py::list_contacts). Shared by Table/Timeline/
    Board so a label picked in one view carries the same meaning in every
    other."""
    if not label:
        return tasks
    wanted = label.lower()
    return [t for t in tasks if any((tg or "").lower() == wanted for tg in t.get("tags") or [])]


def _active_filter_count(date_filter: str, status_filter: str, priority_filter: str, label: str | None) -> int:
    """How many of the row-2 filters are currently non-default -- drives
    both the collapsible `<details>`'s auto-open state and the "Filters
    (N)" badge in its `<summary>` (see the new toolbar-filters CSS in
    style.css and the *_toolbar.html partials)."""
    return sum(
        [
            date_filter != "all",
            status_filter != "all",
            priority_filter != "all",
            bool(label),
        ]
    )


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _shares_label(a_tags: list[str] | None, b_tags: list[str] | None) -> bool:
    """The defining rule of a relation (2026-08-09): an event and a task
    may only be linked when they carry at least one label in common --
    "both have at least one label in common." Enforced by the picker (it
    only offers already-shared candidates) and re-checked defensively by
    the add-relation routes, since labels can change between render and
    submit."""
    return bool(set(a_tags or []) & set(b_tags or []))


def _related_context(conn, task: dict) -> dict:
    """Context keys every task view modal needs for its Relations card:
    the events already linked to this task, plus the not-yet-linked events
    sharing at least one label (the "link an existing event" picker pool).
    `None` task -> empty lists, so templates never branch on the object
    existing."""
    if task is None:
        return {"related_events": [], "linkable_events": []}
    related = db.related_events_for_task(conn, task["uid"])
    # Events fetched via db don't carry calendar_color (only the calendar
    # views' _annotate_calendar_colors sets it) -- annotate so the card's
    # identity dots follow each event's first-label color like everywhere
    # else in the app.
    related = calendar_router._annotate_calendar_colors(conn, related)
    linked = {e["uid"] for e in related}
    linkable = [
        e for e in db.list_events_sharing_labels(conn, task.get("tags") or []) if e["uid"] not in linked
    ]
    return {"related_events": related, "linkable_events": linkable}


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
    label: str | None = None,
    q: str | None = None,
    sort: str = "due_at",
    dir: str = "asc",
    conn=Depends(get_db),
):
    _auto_archive_if_configured(conn)
    tasks = db.list_tasks(conn, q=q)
    tasks = _apply_date_filter(tasks, date_filter)
    tasks = _apply_status_filter(tasks, status_filter)
    tasks = _apply_priority_filter(tasks, priority_filter)
    # Phase 9b toolbar rework: label filter, the real replacement for the
    # old dead Space/Project dropdowns (see routers/labels.py and
    # db.list_task_label_names) -- narrows by object_labels membership
    # (object_type='task'), same case-insensitive single-label match
    # Contacts' `?tag=` filter already uses.
    tasks = _apply_label_filter(tasks, label)
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

    tag_names = db.list_tag_names_in_use(conn)
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
            "active_label": label or "",
            "task_label_names": db.list_task_label_names(conn),
            "active_filter_count": _active_filter_count(date_filter, status_filter, priority_filter, label),
            "q": q or "",
            "sort": sort,
            "dir": dir,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
        }
    )
    return templates.TemplateResponse("tasks_list.html", ctx)


@router.get("/board")
def board_view(
    request: Request,
    date_filter: str = "all",
    status_filter: str = "all",
    priority_filter: str = "all",
    label: str | None = None,
    q: str | None = None,
    conn=Depends(get_db),
):
    tasks = db.list_tasks(conn, q=q)
    # Board only ever shows open/active work by convention (matches
    # desktop's Kanban, which has no "show archived" toggle either) --
    # otherwise every completed task ever created accumulates forever in
    # the Done column with no way to clear it.
    tasks = [t for t in tasks if t["status"] != "archived"]
    # Phase 9b toolbar rework: Board gains the same date/status/priority/
    # label filters Table already has. Board's whole layout is already a
    # status grouping, so `status_filter` here narrows *which* tasks
    # appear in their columns rather than removing columns -- e.g.
    # "only Active-priority-High tasks, still grouped by status" is a
    # meaningful, non-redundant combination.
    tasks = _apply_date_filter(tasks, date_filter)
    tasks = _apply_status_filter(tasks, status_filter)
    tasks = _apply_priority_filter(tasks, priority_filter)
    tasks = _apply_label_filter(tasks, label)
    columns = {s: [] for s in STATUSES if s != "archived"}
    for t in tasks:
        columns.setdefault(t["status"], []).append(t)
    ctx = _task_context(request)
    ctx.update(
        {
            "columns": columns,
            "board_statuses": [s for s in STATUSES if s != "archived"],
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "status_filters": STATUS_FILTERS,
            "status_filter_labels": STATUS_FILTER_LABELS,
            "priority_filters": PRIORITY_FILTERS,
            "priority_filter_labels": PRIORITY_FILTER_LABELS,
            "active_date_filter": date_filter,
            "active_status_filter": status_filter,
            "active_priority_filter": priority_filter,
            "active_label": label or "",
            "task_label_names": db.list_task_label_names(conn),
            "active_filter_count": _active_filter_count(date_filter, status_filter, priority_filter, label),
            "q": q or "",
        }
    )
    return templates.TemplateResponse("tasks_board.html", ctx)


@router.get("/habits")
def habits_view(request: Request, q: str | None = None, conn=Depends(get_db)):
    """4th Tasks view (2026-08-08, "add habits page as a view on tasks")
    -- every task carrying the configured habit label (task_habit_settings,
    default "Habit"), shown with a checkbox/number-stepper check-in row
    (like the Dashboard's habit check-in widget) plus a per-task heatmap
    (like the standalone Habits feature), sourced entirely from
    task_completions/tasks.target_per_day rather than the habits/
    habit_entries tables -- these are real tasks, just hidden from every
    other task view/widget by db.list_tasks' default exclusion. Reuses
    ../habit_heatmap.py's heatmap_range/streaks/current_half_year
    (identical {date: value} shape, also used by routers/habits.py's own
    heatmap_weeks) rather than a second copy of that math.

    2026-08-08 follow-up (direct feedback on the first version of this
    page): the heatmap is a *fixed* calendar range now, not "N weeks
    ending today" -- every card starts on the same date (the current
    half-year's first day) so they line up for comparison instead of each
    scrolling its own rolling window, and covers 6 months so the grid is
    wide enough to genuinely fill a card's width once stretched (see
    style.css's .heatmap-wide). Each card also gets a second, full
    calendar-year grid (`weeks_full`) alongside the half-year one
    (`weeks`) -- normally hidden, revealed by the card's own "View full
    year" toggle (static/task_habit_checkin.js) -- computed up front here
    rather than fetched on demand since it's the same cheap query/loop
    either way and avoids a second request."""
    settings = db.get_task_habit_settings(conn)
    habit_label = settings["habit_label"]
    tasks = db.list_habit_tasks(conn)
    if q:
        needle = q.lower()
        tasks = [t for t in tasks if needle in t["title"].lower()]

    today = date.today()
    today_iso = today.isoformat()
    half_start, half_end = habit_heatmap.current_half_year(today)
    year_start, year_end = date(today.year, 1, 1), date(today.year, 12, 31)
    cards = []
    for t in tasks:
        entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, t["uid"])}
        target = t.get("target_per_day") or 1
        current_streak, longest_streak = habit_heatmap.streaks(entries_by_date)
        today_value = entries_by_date.get(today_iso, 0)
        cards.append(
            {
                "task": t,
                "weeks": habit_heatmap.heatmap_range(entries_by_date, target, half_start, half_end, today),
                "weeks_full": habit_heatmap.heatmap_range(entries_by_date, target, year_start, year_end, today),
                "current_streak": current_streak,
                "longest_streak": longest_streak,
                "today_value": today_value,
                "target": target,
                # Same shape as routers/dashboard.py's _render_habit_checkin
                # rows, for the identical checkbox-vs-stepper check-in row.
                "is_quantity": target > 1,
                "done_today": today_value > 0,
                "next_value": today_value + 1,
            }
        )

    ctx = _task_context(request)
    ctx.update(
        {
            "cards": cards,
            "habit_label": habit_label,
            "today_iso": today_iso,
            "q": q or "",
            "active_filter_count": 0,
        }
    )
    return templates.TemplateResponse("tasks_habits.html", ctx)


@router.post("/habits/settings")
def save_habit_settings(habit_label: str = Form("Habit"), conn=Depends(get_db)):
    db.save_task_habit_settings(conn, habit_label)
    return RedirectResponse(url="/tasks/habits", status_code=303)


@router.get("/new")
def new_task_form(request: Request, parent_uid: str | None = None, habit: bool = False, conn=Depends(get_db)):
    # 2026-08-08 follow-up: Tasks > Habits' own "New" button (?habit=1)
    # renders a real, separate, stripped-down form now -- not task_form.html
    # with a field pre-checked -- direct feedback that a habit doesn't need
    # (and shouldn't show) Start/Due date, Status, or Priority at all, and
    # that Recurrence should be obligatory (a habit is defined by
    # recurring; the old form left it optional like any other task's).
    # The habit label itself is a hidden field there, not a removable
    # checkbox -- "adding a task in that view should automatically add the
    # default habit label," not just default to it.
    if habit:
        habit_label = db.get_task_habit_settings(conn)["habit_label"]
        return templates.TemplateResponse(
            "habit_task_form.html",
            {
                "request": request,
                "active_tab": "tasks",
                "habit_label": habit_label,
            },
        )
    parent = db.get_task(conn, parent_uid) if parent_uid else None
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": None,
            "statuses": STATUSES,
            "priority_items": PRIORITY_ITEMS,
            "status_items": STATUS_ITEMS,
            "parent_uid": parent_uid,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            # 2026-08-08: Start date is a real field on the new-task form
            # now (see task_form.html) -- prefilled to today so the field
            # reads as "defaults to today, override if you want" rather
            # than starting blank.
            "today": date.today().isoformat(),
            "habit_label": db.get_task_habit_settings(conn)["habit_label"],
        },
    )


@router.post("")
def create_task(
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    start_at: str = Form(""),
    priority: str = Form(""),
    status: str = Form("active"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    parent_uid: str = Form(""),
    target_per_day: str = Form("1"),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    # Same defensive-coercion pattern as start_at below -- target_per_day
    # is a new Form field too, so any pre-existing direct caller of
    # create_task() that doesn't pass it gets the literal Form(...) marker
    # object as its default, not a real string.
    if not isinstance(target_per_day, str):
        target_per_day = "1"
    try:
        target_per_day_value = float(target_per_day) if target_per_day else 1.0
    except ValueError:
        target_per_day_value = 1.0
    if target_per_day_value < 1:
        target_per_day_value = 1.0
    # Defensively coerced, same reasoning/pattern as _combine_tags's own
    # tags_labels handling just above -- every pre-existing test in this
    # suite (and any other direct caller bypassing FastAPI's real request
    # parsing) posts every OTHER Form field explicitly but predates this
    # one entirely, so `start_at`'s own `Form("")` default -- a FastAPI
    # marker object, not an actual empty string, outside of real request
    # handling -- would otherwise blow up the SQL insert below.
    if not isinstance(start_at, str):
        start_at = ""
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "due_at": due_at or None,
        # 2026-08-08 direct feedback -- Start date is a real field on the
        # new-task form now too (task_form.html), not edit-only. Still
        # defaults to today if left blank (every caller that doesn't send
        # start_at at all -- e.g. task_detail.html's subtask quick-add
        # form, which only posts title/status/parent_uid -- keeps the old
        # "starts today" behavior unchanged).
        "start_at": start_at or date.today().isoformat(),
        "priority": int(priority) if priority else None,
        "status": status,
        "progress": _progress_for_status(status),
        "tags": _tags_list(tags),
        "parent_uid": parent_uid or None,
        "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
        "target_per_day": target_per_day_value,
        "created_at": now,
        "updated_at": now,
    }
    # Phase 1 (label-space rework): plain SQL write, no Radicale/bridge
    # call in this path anymore -- see db.py's Phase 1 comments and
    # features/architecture.md §1.
    db.upsert_task(conn, row)
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
#
# `move_list` is gone (Phase 1, label-space rework) -- there's no more
# list to move a task to, only labels to add/remove (the `tag` action
# below already does that generically).
# --------------------------------------------------------------------- #


@router.post("/bulk")
async def bulk_action(request: Request, conn=Depends(get_db)):
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
            for child in db.list_subtasks(conn, uid):
                db.delete_task(conn, child["uid"])
                db.delete_checklist_items_for_task(conn, child["uid"])
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
            db.upsert_task(conn, row)
        return JSONResponse({"ok": True, "count": len(uids)})

    if action == "tag":
        # tasks_list.html's Labels picker became a chip multiselect
        # (2026-08-07, modal-input-design Phase B) -- the checkbox picker
        # can tick several labels at once, so the request now carries
        # `tags` (a list) instead of a single `tag` string. `tag` is still
        # accepted for backward compatibility (any stale client/test still
        # posting the old singular shape keeps working unchanged) and is
        # folded into the same list. mode ("add"/"remove") is unchanged --
        # this is still the same per-uid, per-label delta apply, just
        # looped over every requested label too now, not a replace.
        raw_tags = payload.get("tags")
        if not isinstance(raw_tags, list):
            raw_tags = []
        single = (payload.get("tag") or "").strip()
        if single:
            raw_tags = [*raw_tags, single]
        tags_to_apply = [t.strip() for t in raw_tags if isinstance(t, str) and t.strip()]
        mode = payload.get("mode")  # "add" | "remove"
        if not tags_to_apply or mode not in ("add", "remove"):
            return JSONResponse({"error": "tags and mode ('add'/'remove') required"}, status_code=400)
        for uid in uids:
            row = db.get_task(conn, uid)
            if row is None:
                continue
            tags = set(row.get("tags") or [])
            if mode == "add":
                tags.update(tags_to_apply)
            else:
                tags.difference_update(tags_to_apply)
            row["tags"] = sorted(tags)
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            db.upsert_task(conn, row)
        return JSONResponse({"ok": True, "count": len(uids)})

    return JSONResponse({"error": f"unknown action '{action}'"}, status_code=400)


@router.get("/{uid}/edit")
def edit_task_form(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    # Same accurate-delete-confirmation reasoning as task_detail.html/
    # tasks_list.html -- this form's own Delete button needs to know
    # whether it's about to cascade too. db.list_subtasks (a direct,
    # already-existing query) instead of the old ad hoc db.list_tasks()
    # scan-and-filter -- also sidesteps db.list_tasks' default habit-task
    # exclusion, which would otherwise silently undercount a habit-labeled
    # subtask.
    subtasks = db.list_subtasks(conn, uid) if task else []
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": task,
            "statuses": STATUSES,
            "priority_items": PRIORITY_ITEMS,
            "status_items": STATUS_ITEMS,
            "parent_uid": None,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "subtask_count": len(subtasks),
            # 2026-08-08 ("add a way to add subtasks in place of
            # [Recurrence]") -- the edit form shows the same compact
            # subtasks list/add-row task_detail.html does now (see
            # _task_relations.html), not just a count.
            "subtasks": subtasks,
            # Relations card (2026-08-09) -- see _related_context above.
            **_related_context(conn, task),
            # Fallback only -- every task has a real start_at since
            # create_task always sets one now, this just covers a legacy
            # row from before that was true.
            "today": date.today().isoformat(),
            # 2026-08-08 ("hide Daily target unless the label is habit") --
            # task_form.html only shows that field once this label is
            # actually applied.
            "habit_label": db.get_task_habit_settings(conn)["habit_label"],
        },
    )


@router.get("/{uid}")
def task_detail(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    ctx = _task_context(request)
    parent = db.get_task(conn, task["parent_uid"]) if task and task.get("parent_uid") else None
    ctx.update(
        {
            "task": task,
            "parent": parent,
            "subtasks": db.list_subtasks(conn, uid) if task else [],
            # Relations card (2026-08-09) -- see _related_context above.
            **(_related_context(conn, task)),
        }
    )
    # Recurring-task completion history (heatmap + streaks), Phase 5 rework.
    # A non-recurring task has no check-off history to show -- but the
    # context keys are still present (empty) so task_detail.html renders
    # unchanged either way and never has to branch on "is this recurring?".
    if task and task.get("recurrence"):
        completions = {c["due_date"]: "x" for c in db.list_task_completions(conn, uid)}
        current_streak, longest_streak = _completion_streaks(completions)
        ctx.update(
            {
                "completions": completions,
                "completion_weeks": _completion_heatmap_weeks(completions),
                "current_streak": current_streak,
                "longest_streak": longest_streak,
            }
        )
    else:
        ctx.update(
            {
                "completions": {},
                "completion_weeks": [],
                "current_streak": 0,
                "longest_streak": 0,
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
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    if not isinstance(target_per_day, str):
        target_per_day = "1"
    try:
        target_per_day_value = float(target_per_day) if target_per_day else 1.0
    except ValueError:
        target_per_day_value = 1.0
    if target_per_day_value < 1:
        target_per_day_value = 1.0
    existing = db.get_task(conn, uid) or {}
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
            "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
            "target_per_day": target_per_day_value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.upsert_task(conn, row)
    return RedirectResponse(url="/tasks", status_code=303)


_UPDATABLE_FIELDS = {"status", "priority", "due_at", "title"}


@router.post("/{uid}/update-field")
async def update_field(uid: str, request: Request, conn=Depends(get_db)):
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
    db.upsert_task(conn, row)
    return JSONResponse({"ok": True})


@router.post("/{uid}/complete")
def complete_task(uid: str, conn=Depends(get_db)):
    row = db.get_task(conn, uid)
    if row:
        row["status"] = "done"
        row["progress"] = 1.0
        db.upsert_task(conn, row)
        # A recurring task's check-off isn't a one-time flip to done -- it
        # also records today in its completion history (the row that feeds
        # the heatmap/streak), so the same recurring task can be checked off
        # again tomorrow. Plain tasks just flip to done, no history row.
        if row.get("recurrence"):
            db.upsert_task_completion(conn, uid, date.today().isoformat(), datetime.now(timezone.utc).isoformat())
    return RedirectResponse(url="/tasks", status_code=303)


def _completion_streaks(completions: dict[str, str], today: date | None = None) -> tuple[int, int]:
    """(current_streak, longest_streak) in days for a recurring task's
    completion history (dict of {due_date: ...}). Any present date counts
    as done. The current streak tolerates today not being checked off yet
    (you haven't lost the streak because it's 9am) but breaks the moment a
    full calendar day is skipped -- same semantics as habits' _streaks."""
    today = today or date.today()
    done_dates = sorted(d for d in completions if d)
    if not done_dates:
        return 0, 0
    done_set = set(done_dates)

    longest = current_run = 0
    prev: date | None = None
    for d_str in done_dates:
        d = date.fromisoformat(d_str)
        current_run = current_run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, current_run)
        prev = d

    cursor = today
    if cursor.isoformat() not in done_set:
        cursor -= timedelta(days=1)
    current = 0
    while cursor.isoformat() in done_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def _completion_heatmap_weeks(
    completions: dict[str, str], weeks: int = 12, today: date | None = None
) -> list[list[dict]]:
    """Monday-aligned grid of `weeks` columns x 7 rows ending on `today`,
    same shape habits' _heatmap_weeks produces (so the shared
    _habit_heatmap.html macro can paint it). A present date is "full"
    (level 4 -- there's no target-per-day concept for task check-offs);
    future days render blank/non-interactive (level -1)."""
    today = today or date.today()
    start = today - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())  # snap back to the preceding Monday

    days = []
    d = start
    while d <= today:
        days.append(d)
        d += timedelta(days=1)
    while len(days) % 7 != 0:
        days.append(days[-1] + timedelta(days=1))

    result: list[list[dict]] = []
    for week_start in range(0, len(days), 7):
        col = []
        for day in days[week_start : week_start + 7]:
            iso = day.isoformat()
            is_future = day > today
            present = iso in completions
            level = -1 if is_future else (4 if present else 0)
            col.append(
                {
                    "date": iso,
                    "value": 1 if present else 0,
                    "level": level,
                    "is_future": is_future,
                    "weekday": day.weekday(),
                    "month_label": day.strftime("%b") if day.day <= 7 and day.weekday() == 0 else None,
                }
            )
        result.append(col)
    return result


@router.post("/{uid}/completion/{completion_date}/toggle")
def toggle_task_completion(
    uid: str, completion_date: str, request: Request, conn=Depends(get_db)
) -> RedirectResponse:
    """The heatmap/list toggle for a recurring task's daily check-off: no
    completion for that date -> record one; already logged -> remove it
    (back to true "not done", not a hidden zero row). Redirects back to the
    referer (the tasks list's Today column), falling back to the task's own
    detail page when there's no referer -- same pattern as the habits
    toggle."""
    if db.get_task_completion(conn, uid, completion_date) is not None:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(
            conn, uid, completion_date, datetime.now(timezone.utc).isoformat()
        )
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/completions")
def set_task_completion(
    uid: str,
    request: Request,
    completion_date: str = Form(...),
    value: str = Form("1"),
    conn=Depends(get_db),
):
    """Explicit-value counterpart to toggle_task_completion above -- same
    role habits.py's add_entry plays for habit_entries (a >target_per_day
    "+1" quick check-in button on Tasks > Habits posts today's date and
    the pre-computed next value here; referer-aware redirect is what lets
    that work from the check-in row without bouncing to the task's own
    detail page). Only relevant for a habit-labeled task with
    target_per_day > 1 -- a plain checkbox habit (or an ordinary recurring
    task) never has anything that posts here, it just uses the toggle
    route above."""
    try:
        parsed_value = float(value) if value else 1.0
    except ValueError:
        parsed_value = 1.0
    if parsed_value <= 0:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(conn, uid, completion_date, datetime.now(timezone.utc).isoformat(), parsed_value)
    referer = request.headers.get("referer")
    return RedirectResponse(url=referer or f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/delete")
def delete_task(uid: str, conn=Depends(get_db)):
    # Cascade to subtasks -- a subtask with a parent_uid pointing at a task
    # that no longer exists would be an orphan with no way to reach it from
    # the UI (subtasks are only ever listed via their parent's detail page).
    # Desktop doesn't cascade (its subtasks are independent objects you can
    # still find via Table/Kanban/Timeline), but this app's only path to a
    # subtask *is* its parent's detail page, so leaving them behind here
    # would make them permanently unreachable rather than just "independent."
    for child in db.list_subtasks(conn, uid):
        db.delete_task(conn, child["uid"])
        db.delete_checklist_items_for_task(conn, child["uid"])
    db.delete_task(conn, uid)
    db.delete_checklist_items_for_task(conn, uid)
    return RedirectResponse(url="/tasks", status_code=303)


# --------------------------------------------------------------------- #
# Relations -- 2026-08-09, event<->task associative links ("a relation can
# link an event with existing/new tasks that both have at least one label
# in common"; see the event_task_relations comment in db.py). The task
# side of the feature: a task's Relations card links it to events -- either
# an existing event (the picker only offers ones already sharing a label,
# and _shares_label re-checks defensively) or a brand-new event created
# inline that inherits this task's labels, which guarantees the rule. Both
# routes redirect back to the task's own detail page so the card's
# data-modal-keep-open forms re-render in place (modal.js).
# --------------------------------------------------------------------- #


def _create_related_event(conn, task: dict, title: str) -> str | None:
    """Create a new event related to `task` from the Relations card's
    "＋ New event…" path. Inherits the task's labels (guaranteeing the
    shared-label rule) and starts today at 09:00 -- the same default
    routers/calendar.py's own new-event form prefills -- the user edits
    time/labels later. Returns None (no event created) when the task has no
    labels at all, since no shared-label link could ever hold."""
    task_tags = task.get("tags") or []
    if not task_tags:
        return None
    title = (title or "").strip()
    if not title:
        return None
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": "",
        "start_at": f"{date.today().isoformat()}T09:00",
        "end_at": None,
        "all_day": False,
        "location": None,
        "meeting_url": None,
        "status": "active",
        "tags": task_tags,
        "recurrence": None,
        "reminders": [],
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_event(conn, event)
    return event["uid"]


@router.post("/{uid}/relations")
def add_task_relation(
    uid: str,
    target_uid: str = Form(""),
    new_title: str = Form(""),
    conn=Depends(get_db),
):
    task = db.get_task(conn, uid)
    if task is None:
        return RedirectResponse(url="/tasks", status_code=303)
    event_uid = None
    if target_uid == "__new__":
        event_uid = _create_related_event(conn, task, new_title)
    elif target_uid:
        event = db.get_event(conn, target_uid)
        if event and _shares_label(task.get("tags") or [], event.get("tags") or []):
            event_uid = event["uid"]
    if event_uid:
        db.add_event_task_relation(conn, event_uid, uid)
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/relations/remove")
def remove_task_relation(uid: str, event_uid: str = Form(...), conn=Depends(get_db)):
    """Unlink an event from a task's Relations card. Graph link only -- the
    event itself is left entirely alone (relations are associative, not
    ownership; no cascade, matching delete_event/delete_task's cleanup)."""
    db.remove_event_task_relation(conn, event_uid, uid)
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)


# --------------------------------------------------------------------- #
# Checklist -- 2026-08-08 direct feedback ("merge checklists and subtasks
# into one feature") -- the add/toggle/delete-single-item routes that used
# to live here are gone; task_detail.html/task_form.html now show one
# list, backed entirely by real subtasks (parent_uid tasks, already a
# strictly more capable mechanism -- a subtask can carry its own due
# date/priority/labels/subtasks of its own, a checklist item never
# could). delete_checklist_items_for_task above is the one survivor
# -- cascade cleanup for any checklist rows a database from before this
# change still physically has (db.py's table itself is deliberately not
# dropped, same "don't force-drop old data" convention as every other
# removed-feature table in this app).
# --------------------------------------------------------------------- #
