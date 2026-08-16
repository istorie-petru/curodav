from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db, derived_state, habit_heatmap
from ..deps import get_db, respond, templates
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


# --------------------------------------------------------------------- #
# Dual-mode responses (async-CRUD design, features/async-crud.md) --
# every task mutation endpoint keeps its plain-HTML 303 Redirect default
# (so a form still works with no JS at all), but returns JSON when the
# request carries `X-Requested-With: fetch` (static/async_crud.js always
# sends it). Read via a FastAPI Header param (default None) rather than a
# Request object because this suite's direct-call tests invoke the router
# functions as plain Python functions without building a Request -- those
# keep getting the redirect default. Shared helpers live in deps.py.
# --------------------------------------------------------------------- #


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
# 1.1 (virtual & derived states, plans/open-priority.md § Virtual & derived
# states): the single 1-4 WebDAV `priority` axis is gone from the UI,
# replaced by two independent 1-3 axes -- Importance and Urgency (higher =
# more; 0/None = unset). The display labels live in src/derived_state.py
# (the one source of truth for the axes); colors are a UI concern kept
# here. The old `tasks.priority` column stays physically on disk, unused.
IMPORTANCE_LABELS = derived_state.IMPORTANCE_LABELS
URGENCY_LABELS = derived_state.URGENCY_LABELS
IMPORTANCE_COLORS = {1: "gray", 2: "yellow", 3: "red"}
URGENCY_COLORS = {1: "gray", 2: "yellow", 3: "red"}

# 2026-08-08 direct feedback ("rework Priority/Status/Recurrence to look
# the same as Range/View/Labels") -- task_form.html's Status field moved
# from a plain `<select>` (a browser's own unstyleable open-dropdown
# chrome, the same problem View/Range had before their 2026-08-07 rework
# -- see _widget_list_multiselect.html's header comment) to the same
# single-mode multiselect panel View/Range/Labels already share. {uid,
# name} pairs, the same shape that partial expects everywhere else.
# Importance/Urgency used to have their own *_ITEMS lists here too (the
# 1.1 manual multiselect fields); side work (post-1.1) removed the fields
# entirely -- see _task_form_fields.html's header comment.
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
#
# 1.1 (virtual & derived states, plans/open-priority.md § Virtual & derived
# states) originally grew this dropdown with `tomorrow`/`this_month` plus the
# two derived virtual states `important`/`urgent`, and later folded the
# temporal `overdue` state in here too. Tasks page filter cleanup (small,
# 2026-08-15, plans/open.md § Tasks page filter cleanup): direct feedback
# said `overdue`/`important`/`urgent` read as clutter/wrong-drawer in the
# Date dropdown -- they aren't dates, they're virtual states on other axes.
# `important` moved into IMPORTANCE_FILTERS (an "(any level)" option
# alongside the explicit 1/2/3 values -- decided), `urgent` moved into
# URGENCY_FILTERS the same way (decided), and `overdue` moved into
# STATUS_FILTERS as a virtual pseudo-status (the "fold it into the Status
# dropdown" candidate from that section, since it isn't a value on any real
# axis and a toolbar chip would've been a second, redundant filtering
# mechanism). DATE_FILTERS is back to being just real date buckets.
DATE_FILTERS = ["all", "today", "tomorrow", "this_week", "this_month"]
DATE_FILTER_LABELS = {
    "all": "All dates",
    "today": "Today",
    "tomorrow": "Tomorrow",
    "this_week": "This week",
    "this_month": "This month",
}

# `overdue` is a virtual pseudo-status (src/derived_state.py's `overdue`
# state, computed from due_at vs. today) -- not a real `tasks.status` value,
# same "query projection, never stored" nature DATE_FILTERS' old
# important/urgent entries had. See _apply_status_filter.
STATUS_FILTERS = ["all"] + STATUSES + ["overdue"]
STATUS_FILTER_LABELS = {"all": "All statuses", **STATUS_LABELS, "overdue": "Overdue"}

# `important` is an "(any level)" virtual option -- src/derived_state.py's
# `is_important` (effective importance >= IMPORTANT_THRESHOLD), distinct
# from picking an exact 1/2/3 level below it. See _apply_importance_filter.
IMPORTANCE_FILTERS = ["all", "1", "2", "3", "important"]
IMPORTANCE_FILTER_LABELS = {
    "all": "All importance",
    **{str(k): v for k, v in IMPORTANCE_LABELS.items()},
    "important": "Important (any level)",
}
# `urgent` is the urgency-axis sibling of `important` above (`is_urgent`).
URGENCY_FILTERS = ["all", "1", "2", "3", "urgent"]
URGENCY_FILTER_LABELS = {
    "all": "All urgency",
    **{str(k): v for k, v in URGENCY_LABELS.items()},
    "urgent": "Urgent (any level)",
}

DONE_STATUSES = ("done", "archived")


def _apply_date_filter(tasks: list[dict], date_filter: str, label_rules: dict | None = None) -> list[dict]:
    """Filters tasks by the real date buckets (today/tomorrow/this_week/
    this_month). Delegates to src/derived_state.py's `virtual_states`
    predicate -- the single place per-state membership is computed -- so
    this filter, the Dashboard's aggregation service, and any future
    surface agree by construction rather than by each re-implementing the
    date math.

    Tasks page filter cleanup (2026-08-15, plans/open.md): `overdue`/
    `important`/`urgent` used to live here too (1.1) but have moved to
    STATUS_FILTERS/IMPORTANCE_FILTERS/URGENCY_FILTERS respectively -- see
    _apply_status_filter/_apply_importance_filter/_apply_urgency_filter.
    `label_rules` is kept as a parameter (unused by the remaining, purely
    temporal buckets) rather than dropped, so every call site can keep
    passing it uniformly across all four `_apply_*_filter` functions
    without special-casing this one."""
    if date_filter == "all":
        return tasks
    states = {date_filter}
    return [t for t in tasks if states & derived_state.virtual_states(t, label_rules or {})]


def _apply_status_filter(tasks: list[dict], status_filter: str, label_rules: dict | None = None) -> list[dict]:
    """Status filter (toolbar Status dropdown). `overdue` (2026-08-15,
    Tasks page filter cleanup) is a virtual pseudo-status, not a real
    `tasks.status` value -- it delegates to src/derived_state.py's
    `virtual_states` the same way the old DATE_FILTERS `overdue` entry did,
    which is why this function now takes `label_rules` too (unused by the
    real-status branch, needed for the virtual one) -- same "each `_apply_*`
    takes label_rules uniformly" reasoning as _apply_date_filter above."""
    if status_filter == "all":
        return tasks
    if status_filter == "overdue":
        return [t for t in tasks if "overdue" in derived_state.virtual_states(t, label_rules or {})]
    return [t for t in tasks if t["status"] == status_filter]


def _apply_importance_filter(tasks: list[dict], importance_filter: str, label_rules: dict | None = None) -> list[dict]:
    """Importance-level filter (toolbar Importance dropdown) -- matches
    the *computed* effective importance value (1..3, src/derived_state.py:
    label-derived, no manual per-task value exists anymore). `important`
    (2026-08-15, Tasks page filter cleanup -- moved here from DATE_FILTERS)
    is the "(any level)" virtual option: at/above the Important threshold
    (`derived_state.is_important`) rather than one exact level."""
    if importance_filter == "all":
        return tasks
    label_rules = label_rules or {}
    if importance_filter == "important":
        return [t for t in tasks if derived_state.is_important(t, label_rules)]
    try:
        wanted = int(importance_filter)
    except ValueError:
        return tasks
    return [t for t in tasks if derived_state.effective_importance(t, label_rules) == wanted]


def _apply_urgency_filter(tasks: list[dict], urgency_filter: str, label_rules: dict | None = None) -> list[dict]:
    """Urgency-level filter (toolbar Urgency dropdown) -- the urgency-axis
    sibling of _apply_importance_filter, same "exact level, plus an
    `urgent` (any level) virtual option moved here from DATE_FILTERS
    2026-08-15" shape."""
    if urgency_filter == "all":
        return tasks
    label_rules = label_rules or {}
    if urgency_filter == "urgent":
        return [t for t in tasks if derived_state.is_urgent(t, label_rules)]
    try:
        wanted = int(urgency_filter)
    except ValueError:
        return tasks
    return [t for t in tasks if derived_state.effective_urgency(t, label_rules) == wanted]


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


def _task_label_rules(conn) -> dict[str, dict]:
    """{label name: effective label config} for every label -- the resolved
    rules the `important`/`urgent` derived-state filters feed to
    src/derived_state.py. Delegates to db.list_label_rules (one call, never
    per task) -- see that function's docstring. Kept as a thin alias so the
    router's call sites read naturally and so dashboard.py (which imports
    this helper for its aggregation-service widget) has one stable name."""
    return db.list_label_rules(conn)


def _active_filter_count(
    date_filter: str, status_filter: str, importance_filter: str, urgency_filter: str, label: str | None
) -> int:
    """How many of the row-2 filters are currently non-default -- drives
    both the collapsible `<details>`'s auto-open state and the "Filters
    (N)" badge in its `<summary>` (see the new toolbar-filters CSS in
    style.css and the *_toolbar.html partials)."""
    return sum(
        [
            date_filter != "all",
            status_filter != "all",
            importance_filter != "all",
            urgency_filter != "all",
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
    """Context keys every task view modal needs for its Relations card: the
    events already linked to this task. `None` task -> empty list, so
    templates never branch on the object existing.

    1.2 side work (Universal command surface step 3): this used to also
    precompute `linkable_events` -- every not-yet-linked event sharing a
    label with this task, the old `<select>`'s entire option pool. The
    picker overlay (static/command_palette.js) now asks `GET /api/search
    ?for_task=<uid>` for exactly the page of candidates it needs instead,
    so there's nothing left to precompute here."""
    if task is None:
        return {"related_events": []}
    related = db.related_events_for_task(conn, task["uid"])
    # Events fetched via db don't carry calendar_color (only the calendar
    # views' _annotate_calendar_colors sets it) -- annotate so the card's
    # identity dots follow each event's first-label color like everywhere
    # else in the app.
    related = calendar_router._annotate_calendar_colors(conn, related)
    return {"related_events": related}


def _work_allocation_context(conn, task: dict) -> dict:
    """Context keys every task view modal needs for its Work sessions card
    (1.4, plans/open-priority.md § Work allocations): the scheduled work
    blocks for this task plus the scheduled/completed/remaining hour totals
    they add up to. `None` task -> empty, same "templates never branch on
    the object existing" convention as _related_context above."""
    if task is None:
        return {"work_allocations": [], "work_hours": {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0}}
    allocations = db.list_work_allocations_for_task(conn, task["uid"])
    allocations = calendar_router._annotate_calendar_colors(conn, allocations)
    return {
        "work_allocations": allocations,
        "work_hours": db.task_work_hours(conn, task["uid"]),
    }


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
        "importance_labels": IMPORTANCE_LABELS,
        "importance_colors": IMPORTANCE_COLORS,
        "urgency_labels": URGENCY_LABELS,
        "urgency_colors": URGENCY_COLORS,
    }


def _sort_keys(label_rules: dict) -> dict:
    """Factory, not a plain module-level dict: the importance/urgency sort
    keys need `label_rules` to compute the effective value (side work,
    post-1.1 -- there's no stored column to sort by anymore, see
    src/derived_state.py). Every other key is unaffected by label rules,
    kept here rather than split out so `list_tasks` has one dict to look
    `sort` up in either way."""
    return {
        "title": lambda t: (t.get("title") or "").lower(),
        "due_at": lambda t: t.get("due_at") or "9999",
        "importance": lambda t: derived_state.effective_importance(t, label_rules),
        "urgency": lambda t: derived_state.effective_urgency(t, label_rules),
        "status": lambda t: STATUSES.index(t["status"]) if t["status"] in STATUSES else 99,
    }


def _group_tasks_by_project(conn, tasks: list[dict]) -> list[dict]:
    """1.5 slice ("Tasks page as a table groupable by project", see
    plans/open-priority.md § Task model): cluster an already-filtered/
    already-sorted task list under project headers, reusing
    db.project_label_for -- the same "which of this task's labels, if any,
    is the project" lookup the project detail page relies on -- rather
    than reimplementing that logic. Named groups are sorted alphabetically
    (case-insensitive); a task with no project label falls into a "No
    project" bucket rendered last (deliberate choice, not required by the
    spec: named projects are the primary organizing unit here, so they
    lead). Within each group, task order is preserved exactly as passed in
    -- callers sort *before* grouping so a group's own tasks keep the
    page's active `sort`/`dir`."""
    buckets: dict[str | None, list[dict]] = {}
    order: list[str | None] = []
    for t in tasks:
        proj = db.project_label_for(conn, "task", t["uid"])
        if proj not in buckets:
            buckets[proj] = []
            order.append(proj)
        buckets[proj].append(t)
    named = sorted((p for p in order if p is not None), key=str.lower)
    groups = [{"name": p, "tasks": buckets[p]} for p in named]
    if None in buckets:
        groups.append({"name": None, "tasks": buckets[None]})
    return groups


def _tasks_list_context(
    conn,
    request: Request,
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
    label: str | None = None,
    q: str | None = None,
    sort: str = "due_at",
    dir: str = "asc",
    group_by: str = "none",
    page: int = 1,
    limit: int = 50,
) -> dict:
    """Build the full render context for the Table view. Shared between the
    full page (list_tasks) and the async-CRUD region fragment
    (tasks_regions, GET /tasks/regions?region=table) so a mutation-triggered
    region refresh re-renders the exact same markup as the full page --
    _tasks_body.html is the single source of truth either way
    (features/async-crud.md)."""
    _auto_archive_if_configured(conn)
    label_rules = _task_label_rules(conn)
    tasks = db.list_tasks(conn, q=q)
    tasks = _apply_date_filter(tasks, date_filter, label_rules)
    tasks = _apply_status_filter(tasks, status_filter, label_rules)
    tasks = _apply_importance_filter(tasks, importance_filter, label_rules)
    tasks = _apply_urgency_filter(tasks, urgency_filter, label_rules)
    # Phase 9b toolbar rework: label filter, the real replacement for the
    # old dead Space/Project dropdowns (see routers/labels.py and
    # db.list_task_label_names) -- narrows by object_labels membership
    # (object_type='task'), same case-insensitive single-label match
    # Contacts' `?tag=` filter already uses.
    tasks = _apply_label_filter(tasks, label)
    sort_keys = _sort_keys(label_rules)
    key_fn = sort_keys.get(sort, sort_keys["due_at"])
    tasks.sort(key=key_fn, reverse=(dir == "desc"))

    # Completed tasks (done/archived) stay visible in every view -- Today,
    # This week, All -- rather than disappearing the moment they're
    # checked off, but are clearly separated and pushed below the open
    # ones (see tasks_list.html's two <tbody> sections) instead of
    # interleaved by date/importance/urgency with active work. If
    # status_filter
    # already narrows to a single status, "separating" a single-status
    # list from itself would just be a redundant empty section, so the
    # split only actually matters (and the template only shows a divider)
    # when both groups are non-empty.
    open_tasks = [t for t in tasks if t["status"] not in DONE_STATUSES]
    completed_tasks = [t for t in tasks if t["status"] in DONE_STATUSES]

    # 1.9 slice (Webapp usability Phase B, plans/open.md § Webapp usability +
    # DAVx5 mobile hosting): paginate the open section of the Table view --
    # the highest-traffic surface named in that doc as the first pagination
    # target. Applies only in the default ungrouped view (group_by=='none');
    # group_by=project clusters tasks under per-project header rows, and a
    # flat page boundary would split a project's own tasks arbitrarily
    # across pages, so grouped mode is left showing everything, same as
    # before this slice -- a deliberate, documented scope cut, not an
    # oversight. limit is clamped to a sane range so a stray ?limit=0 or
    # ?limit=100000 can't produce a zero-division or an effectively
    # unpaginated "page". Completed tasks are never paginated: they're
    # already visually separated below Open, and bounded in practice by the
    # "Auto-archive completed tasks" setting (_auto_archive_if_configured
    # above) -- if that turns out wrong at real volume, it's a follow-up,
    # not a blocker for this slice (open.md's own "live-volume verification
    # required" note).
    limit = min(max(limit, 1), 200)
    page = max(page, 1)
    paginated = group_by == "none"
    open_total = len(open_tasks)
    total_pages = max(1, -(-open_total // limit)) if paginated else 1
    if paginated:
        page = min(page, total_pages)
        open_tasks = open_tasks[(page - 1) * limit : page * limit]
    else:
        page = 1

    # 1.5 slice (the deadline-vs-work-allocation surfacing slice, see
    # plans/open-priority.md § Task model): attach each visible task's
    # scheduled/completed/remaining hours so _task_row.html can render a
    # "Scheduled" column distinct from "Due" -- one batched query
    # (db.task_work_hours_bulk) for the whole page instead of one query per
    # row. Scoped to open_tasks + completed_tasks (i.e. after the 1.9
    # pagination slice above) rather than the full filtered `tasks` list, so
    # a large filtered set only pays for the hours of rows it actually
    # renders.
    _rendered = open_tasks + completed_tasks
    _hours = db.task_work_hours_bulk(conn, [t["uid"] for t in _rendered])
    for t in _rendered:
        t["work_hours"] = _hours[t["uid"]]

    # 1.5 slice ("Tasks page as a table groupable by project"): grouping is
    # opt-in via ?group_by=project (default "none" is exactly today's
    # behavior, so a bookmarked/existing URL without the param is
    # unaffected). Groups are built *after* the open/completed split and
    # *after* sorting, so grouping composes with both the existing
    # completed-stays-visible-but-separated rule and the active sort/dir
    # instead of replacing either.
    open_groups = None
    completed_groups = None
    if group_by == "project":
        open_groups = _group_tasks_by_project(conn, open_tasks)
        completed_groups = _group_tasks_by_project(conn, completed_tasks)

    tag_names = db.list_tag_names_in_use(conn)
    ctx = _task_context(request)
    ctx.update(
        {
            "open_tasks": open_tasks,
            "completed_tasks": completed_tasks,
            "group_by": group_by,
            "open_groups": open_groups,
            "completed_groups": completed_groups,
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "status_filters": STATUS_FILTERS,
            "status_filter_labels": STATUS_FILTER_LABELS,
            "importance_filters": IMPORTANCE_FILTERS,
            "importance_filter_labels": IMPORTANCE_FILTER_LABELS,
            "urgency_filters": URGENCY_FILTERS,
            "urgency_filter_labels": URGENCY_FILTER_LABELS,
            "active_date_filter": date_filter,
            "active_status_filter": status_filter,
            "active_importance_filter": importance_filter,
            "active_urgency_filter": urgency_filter,
            "active_label": label or "",
            "task_label_names": db.list_task_label_names(conn),
            "active_filter_count": _active_filter_count(date_filter, status_filter, importance_filter, urgency_filter, label),
            "q": q or "",
            "sort": sort,
            "dir": dir,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "paginated": paginated,
            "page": page,
            "limit": limit,
            "open_total": open_total,
            "total_pages": total_pages,
            # The dead Space/Project filter helpers (_aguid/_apuid, see
            # tasks_list.html) are always empty today; the page sets them via
            # `default('')` at block scope, so the fragment route must supply
            # the same empty values for the shared _tasks_body.html partial.
            "_aguid": "",
            "_apuid": "",
        }
    )
    return ctx


@router.get("")
def list_tasks(
    request: Request,
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
    label: str | None = None,
    q: str | None = None,
    sort: str = "due_at",
    dir: str = "asc",
    group_by: str = "none",
    page: int = 1,
    limit: int = 50,
    conn=Depends(get_db),
):
    ctx = _tasks_list_context(
        conn, request, date_filter, status_filter, importance_filter,
        urgency_filter, label, q, sort, dir, group_by, page, limit,
    )
    return templates.TemplateResponse("tasks_list.html", ctx)


@router.get("/regions")
def tasks_regions(
    request: Request,
    region: str = "table",
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
    label: str | None = None,
    q: str | None = None,
    sort: str = "due_at",
    dir: str = "asc",
    group_by: str = "none",
    page: int = 1,
    limit: int = 50,
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md): renders a single
    named region of the Table view -- currently `region=table`, the
    #tasks-body div shared with tasks_list.html -- so static/async_crud.js's
    refreshRegion() can swap it in place after a mutation instead of a full
    page reload. Takes the same query params as list_tasks; the client
    forwards the page's own query string so the refreshed region honors the
    active filters/sort/page."""
    if region != "table":
        return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)
    ctx = _tasks_list_context(
        conn, request, date_filter, status_filter, importance_filter,
        urgency_filter, label, q, sort, dir, group_by, page, limit,
    )
    html = templates.env.get_template("_tasks_body.html").render(ctx)
    return HTMLResponse(html)


@router.get("/board")
def board_view(
    request: Request,
    date_filter: str = "all",
    status_filter: str = "all",
    importance_filter: str = "all",
    urgency_filter: str = "all",
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
    # Phase 9b toolbar rework: Board gains the same date/status/
    # importance/urgency/label filters Table already has. Board's whole
    # layout is already a status grouping, so `status_filter` here narrows
    # *which* tasks appear in their columns rather than removing columns --
    # e.g. "only Active tasks with importance High, still grouped by
    # status" is a meaningful, non-redundant combination.
    label_rules = _task_label_rules(conn)
    tasks = _apply_date_filter(tasks, date_filter, label_rules)
    tasks = _apply_status_filter(tasks, status_filter, label_rules)
    tasks = _apply_importance_filter(tasks, importance_filter, label_rules)
    tasks = _apply_urgency_filter(tasks, urgency_filter, label_rules)
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
            "importance_filters": IMPORTANCE_FILTERS,
            "importance_filter_labels": IMPORTANCE_FILTER_LABELS,
            "urgency_filters": URGENCY_FILTERS,
            "urgency_filter_labels": URGENCY_FILTER_LABELS,
            "active_date_filter": date_filter,
            "active_status_filter": status_filter,
            "active_importance_filter": importance_filter,
            "active_urgency_filter": urgency_filter,
            "active_label": label or "",
            "task_label_names": db.list_task_label_names(conn),
            "active_filter_count": _active_filter_count(date_filter, status_filter, importance_filter, urgency_filter, label),
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
def new_task_form(
    request: Request, habit: bool = False, project: str = "", title: str = "", conn=Depends(get_db)
):
    # 2026-08-08 follow-up: Tasks > Habits' own "New" button (?habit=1)
    # renders a real, separate, stripped-down form now -- not task_form.html
    # with a field pre-checked -- direct feedback that a habit doesn't need
    # (and shouldn't show) Start/Due date, Status, Importance/Urgency, or
    # Recurrence at all, and
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
    tag_names = db.list_tag_names_in_use(conn)
    # `project` may be a freshly-promoted label with no object_labels rows
    # yet (a brand-new, empty project's "+ New task" is exactly this case)
    # -- list_tag_names_in_use only returns labels already *in use*, so the
    # chip multiselect below would have nothing to pre-check without this.
    # Same "offer it even though nothing points at it yet" idea as
    # projects.html's promote-form datalist.
    if project and project not in tag_names:
        tag_names = sorted(tag_names + [project], key=str.lower)
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": None,
            # Command palette actions (open.md) -- the palette's "Create
            # task: '<query>'" row opens this form with ?title=<query> so
            # the typed text isn't lost; blank for every other caller of
            # this route, same as prefill_start/prefill_end below.
            "prefill_title": title,
            "statuses": STATUSES,
            "status_items": STATUS_ITEMS,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            # 2026-08-08: Start date is a real field on the new-task form
            # now (see task_form.html) -- prefilled to today so the field
            # reads as "defaults to today, override if you want" rather
            # than starting blank.
            "today": date.today().isoformat(),
            "habit_label": db.get_task_habit_settings(conn)["habit_label"],
            # 1.4 (Project pages & views: "newly created tasks automatically
            # receive the project's label") -- the project detail page's "+
            # New task" link opens this same form with ?project=<name>, which
            # only pre-checks the label chip (still removable, same as any
            # other prefill in this app) rather than silently forcing it.
            "prefill_tags": [project] if project else [],
        },
    )


@router.post("")
def create_task(
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    start_at: str = Form(""),
    status: str = Form("active"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    x_requested_with: str | None = Header(default=None),
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
        # start_at at all -- e.g. the relation picker's "＋ New task…" path
        # in routers/calendar.py -- keeps the old "starts today" behavior
        # unchanged).
        "start_at": start_at or date.today().isoformat(),
        "status": status,
        "progress": _progress_for_status(status),
        "tags": _tags_list(tags),
        "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
        "target_per_day": target_per_day_value,
        "created_at": now,
        "updated_at": now,
    }
    # Phase 1 (label-space rework): plain SQL write, no Radicale/bridge
    # call in this path anymore -- see db.py's Phase 1 comments and
    # features/architecture.md §1.
    # 1.5 (single-project-per-task, § Task model): db.upsert_task rejects a
    # `tags` list carrying more than one is_project=1 label -- surfaced here
    # as a plain 400 with the offending label names, same "raise, don't
    # silently 500" convention as this router's other Form-POST validation
    # (routers/banners.py's upload-type/size checks are the closest existing
    # precedent for a plain-form endpoint erroring this way).
    try:
        db.upsert_task(conn, row)
    except db.MultipleProjectLabelsError as exc:
        raise HTTPException(400, str(exc))
    return respond(x_requested_with, "/tasks", status_code=201, uid=row["uid"])


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
        # Tasks are flat (1.2, task-model decision) -- no subtask cascade.
        # The checklist-item cleanup below is kept for any rows a database
        # from before the checklist/subtask removal still physically has.
        for uid in uids:
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
        # 1.5 (single-project-per-task): bulk "Add label" is a real path to
        # putting a second project label on a task (tasks_list.html's
        # bulk-actions-bar Labels picker offers every project label just
        # like any other), so it needs the same db.upsert_task guard the
        # single-task create/edit forms get. Applied per-uid rather than
        # pre-validated as a batch since whether a given task ends up with
        # two project labels depends on that task's own existing tags, not
        # just the labels being added; tasks already updated earlier in the
        # loop keep their change (partial application, matching how "delete"
        # and "status" above have no all-or-nothing rollback either), and
        # the response reports which uids were rejected so the client can
        # surface a clear error instead of a silent partial success.
        failed: list[dict[str, str]] = []
        applied = 0
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
            try:
                db.upsert_task(conn, row)
            except db.MultipleProjectLabelsError as exc:
                failed.append({"uid": uid, "title": row.get("title") or uid, "error": str(exc)})
                continue
            applied += 1
        if failed:
            # A plain 400 (not a 200/207 "partial success") even though
            # `applied` tasks already got their change written -- the bulk
            # picker's own JS (static/tasks_table.js's bulkPost) only ever
            # branches on resp.ok, so a non-2xx is what actually surfaces the
            # toast; the client reloads on success, so any already-applied
            # rows are picked up correctly on the next bulk action or page
            # load regardless of this response's status code.
            return JSONResponse(
                {
                    "ok": False,
                    "count": applied,
                    "error": f"{len(failed)} task(s) already have a project label and can't take a second one.",
                    "failed": failed,
                },
                status_code=400,
            )
        return JSONResponse({"ok": True, "count": applied})

    return JSONResponse({"error": f"unknown action '{action}'"}, status_code=400)


@router.get("/{uid}/edit")
def edit_task_form(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "active_tab": "tasks",
            "task": task,
            "statuses": STATUSES,
            "status_items": STATUS_ITEMS,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            # Relations card (2026-08-09) -- see _related_context above.
            **_related_context(conn, task),
            # Work sessions card (1.4) -- see _work_allocation_context above.
            **_work_allocation_context(conn, task),
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
    ctx.update(
        {
            "task": task,
            # Relations card (2026-08-09) -- see _related_context above.
            **(_related_context(conn, task)),
            # Work sessions card (1.4) -- see _work_allocation_context above.
            **(_work_allocation_context(conn, task)),
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
    status: str = Form("active"),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    x_requested_with: str | None = Header(default=None),
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
            "status": status,
            "progress": _progress_for_status(status),
            "tags": _tags_list(tags),
            "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
            "target_per_day": target_per_day_value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    try:
        db.upsert_task(conn, row)
    except db.MultipleProjectLabelsError as exc:
        raise HTTPException(400, str(exc))
    return respond(x_requested_with, "/tasks")


_UPDATABLE_FIELDS = {"status", "due_at", "title"}


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
    if field == "due_at":
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
def complete_task(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
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
    return respond(x_requested_with, "/tasks")


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
def delete_task(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    # Tasks are flat (1.2, task-model decision) -- a task is an independent
    # unit of work, so this deletes exactly the one task (plus its labels
    # and relation links, via db.delete_task's own cleanup). The checklist-
    # item cleanup below is kept for any rows a database from before the
    # checklist/subtask removal still physically has.
    db.delete_task(conn, uid)
    db.delete_checklist_items_for_task(conn, uid)
    return respond(x_requested_with, "/tasks")


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
# Work allocations -- 1.4, plans/open-priority.md § Work allocations, §
# Task & calendar semantics. A work allocation is a calendar Event linked
# to this task via event_task_relations.is_work_allocation=1 (db.py's
# create_work_allocation) -- a scheduled block of work time, distinct from
# an ordinary Relations-card link. This is the task-detail form entry point
# for scheduling one directly (start/end datetime); the project's Week
# Calendar view (not yet built) will be the drag-and-drop surface for the
# same underlying operation.
# --------------------------------------------------------------------- #


def _safe_next(next_url: str) -> str | None:
    """A same-origin relative path safe for a RedirectResponse after a
    work-session action -- rejects open-redirect payloads (schemes,
    "//host", and so on) that a client-submitted `next` field could carry.
    The planning grids' "Unscheduled work" panel steppers pass one (the page
    to return to); the task modal's Work sessions card leaves it empty and
    falls back to /tasks/{uid}. The isinstance guard also covers direct
    router calls in tests that omit `next` (its Form default object)."""
    if isinstance(next_url, str) and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None


@router.post("/{uid}/work-allocations")
def add_work_allocation(
    uid: str,
    start_at: str = Form(""),
    end_at: str = Form(""),
    next: str = Form(""),
    conn=Depends(get_db),
):
    """The Work sessions card's "+" button and the planning panels' "+" --
    add a work session with NO date at all. A session added this way is an
    unscheduled placeholder (no start/end), so the task stays on the
    planning grids' "Unscheduled work" panel and is placed onto a real slot
    by dragging it there (the create endpoints'
    place-the-oldest-undated-session behavior). The old start/end datetime
    inputs are gone from the modal but still honored here if a caller posts
    them: a valid pair schedules the session directly, a malformed pair is
    rejected the same as before (no-op). The panel posts a same-origin
    `next` path to reload on the grid it was used from; the modal leaves it
    empty and returns to the task."""
    task = db.get_task(conn, uid)
    if task is not None:
        if start_at and end_at and end_at > start_at:
            db.create_work_allocation(conn, uid, start_at, end_at)
        elif not (start_at or end_at):
            db.create_work_allocation(conn, uid)  # undated session placeholder
    return RedirectResponse(url=_safe_next(next) or f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/work-allocations/remove-latest")
def remove_latest_work_allocation(uid: str, next: str = Form(""), conn=Depends(get_db)):
    """The planning grids' "Unscheduled work" panel "−" button -- remove the
    task's most recently added UNDATED work session, so it undoes the
    panel's own "+" without ever touching an already-scheduled block (see
    `db.remove_latest_work_allocation`'s own docstring). No-ops if the task
    has no undated sessions left to remove, even if it has dated ones; never
    touches the task. `next`, when present, is the planning page to return
    to (same-origin path only, see `_safe_next`)."""
    db.remove_latest_work_allocation(conn, uid)
    return RedirectResponse(url=_safe_next(next) or f"/tasks/{uid}", status_code=303)


@router.post("/{uid}/work-allocations/remove")
def remove_work_allocation(uid: str, event_uid: str = Form(...), conn=Depends(get_db)):
    """"Deleting a work allocation removes only that scheduled block -- not
    the task." db.delete_work_allocation is delete_event under a name that
    states that at the call site; `uid` (the task) isn't touched."""
    db.delete_work_allocation(conn, event_uid)
    return RedirectResponse(url=f"/tasks/{uid}", status_code=303)


# --------------------------------------------------------------------- #
# Checklist -- 2026-08-08 direct feedback ("merge checklists and subtasks
# into one feature") -- the add/toggle/delete-single-item routes that used
# to live here are gone; task_detail.html/task_form.html showed one list,
# backed entirely by real subtasks. The 1.2 task-model decision then
# removed subtasks outright, so the merged list is gone entirely.
# delete_checklist_items_for_task above is the one survivor -- cascade
# cleanup for any checklist rows a database from before this change still
# physically has (db.py's table itself is deliberately not dropped, same
# "don't force-drop old data" convention as every other removed-feature
# table in this app).
# --------------------------------------------------------------------- #
