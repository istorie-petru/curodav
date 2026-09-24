from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db, derived_state, habit_heatmap, habit_view
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

# 2026-08-28 follow-up ("direct number input" for the Habits group's
# check-in cell) -- server-side mirror of the input's `max="999999"`, see
# set_task_completion below.
_MAX_HABIT_VALUE = 999999


# Moved to habit_view.py (2026-09-24) -- shared with the Dashboard's
# Habit Check-in widget; kept under its old name for this file's callers.
_excluded_dates_for_row = habit_view.excluded_dates_for_row


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
# states) introduced two independent 1-3 axes -- Importance and Urgency --
# replacing the single 1-4 WebDAV `priority` axis. That whole feature (the
# axes, their filters/sort keys, the task detail meta row, the Dashboard
# widgets that read them, and the export columns) is removed outright --
# no longer a feature this app offers. The old `tasks.priority` column
# stays physically on disk, unused, same "never force-drop old data"
# convention as every other removed column in db.py.

# 2026-08-08 direct feedback ("rework Priority/Status/Recurrence to look
# the same as Range/View/Labels") -- task_form.html's Status field moved
# from a plain `<select>` (a browser's own unstyleable open-dropdown
# chrome, the same problem View/Range had before their 2026-08-07 rework
# -- see _widget_list_multiselect.html's header comment) to the same
# single-mode multiselect panel View/Range/Labels already share. {uid,
# name} pairs, the same shape that partial expects everywhere else.
# Importance/Urgency used to have their own *_ITEMS lists here too (the
# 1.1 manual multiselect fields); removed along with the rest of that
# feature -- see this module's other Importance/Urgency comments.
STATUS_ITEMS = [{"uid": s, "name": STATUS_LABELS[s]} for s in STATUSES]

# 2026-08-28 "major rework" session (item 3, "filtering reduced to date
# only"): Status/Importance/Urgency/label filtering and the group-by toggle
# are gone from the Table view entirely -- DATE_FILTERS is the one filter
# axis left. Reworked 2026-08-01: the old single "smart filter" dropdown
# (Today / Overdue / High Priority / Waiting / Completed / Archived / All
# Open / All) conflated several independent questions into one flat preset
# list; that history is why this stayed a real date-bucket list rather than
# a boolean "today only" toggle even after the other axes were cut.
DATE_FILTERS = ["all", "today", "tomorrow", "this_week", "this_month"]
DATE_FILTER_LABELS = {
    "all": "All dates",
    "today": "Today",
    "tomorrow": "Tomorrow",
    "this_week": "This week",
    "this_month": "This month",
}

DONE_STATUSES = ("done", "archived")


def _apply_date_filter(tasks: list[dict], date_filter: str) -> list[dict]:
    """Filters tasks by the real date buckets (today/tomorrow/this_week/
    this_month). Delegates to src/derived_state.py's `virtual_states`
    predicate -- the single place per-state membership is computed -- so
    this filter, the Dashboard's aggregation service, and any future
    surface agree by construction rather than by each re-implementing the
    date math.

    Tasks page filter cleanup (2026-08-15, plans/open.md): `overdue`/
    `important`/`urgent` used to live here too (1.1) but moved to
    Status/Importance/Urgency filters instead -- all of which are gone
    entirely as of the 2026-08-28 "major rework" session (item 3,
    "filtering reduced to date only"), and Importance/Urgency itself is now
    gone as a feature -- `virtual_states` no longer takes a `label_rules`
    argument at all."""
    if date_filter == "all":
        return tasks
    states = {date_filter}
    return [t for t in tasks if states & derived_state.virtual_states(t)]


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _work_allocation_context(conn, task: dict) -> dict:
    """Context keys every task view modal needs for its Work sessions card
    (1.4, plans/open-priority.md § Work allocations): the scheduled work
    blocks for this task plus the scheduled/completed/remaining hour totals
    they add up to. `None` task -> empty, so templates never have to branch
    on the object existing."""
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
    }


def _due_at_key(t: dict) -> str:
    """The one sort key the reworked Table view still needs -- 2026-08-28
    "major rework" session (item 3): sorting is no longer user-choosable
    (the old Title/Status/Due column-header sort links and the `sort`/`dir`
    query params are gone, along with the importance/urgency sort keys they
    used to sit next to), every non-Completed group is simply due-date
    ascending, always. A task with no due date sorts last within its group
    (the same '9999' sentinel the old due_at sort key already used)."""
    return t.get("due_at") or "9999"


def _build_task_groups(conn, open_tasks: list[dict], completed_tasks: list[dict]) -> list[dict]:
    """2026-08-28 "major rework" session (item 3): grouping is now always
    on, in one fixed order -- Project (one group per project label,
    alphabetical) -> Unassigned (open tasks with no project label) -> Completed (every
    completed task regardless of project, most-recent-first, always last).
    `open_tasks` is expected pre-sorted by due date (_due_at_key) -- every
    group but Completed simply preserves that order, so a project/
    Unassigned group's own tasks read due-date-ascending for free without
    re-sorting per bucket. Completed intentionally does NOT nest under its
    task's project anymore (the pre-rework `group_by=project` grouping did)
    -- "completed always last" only holds if every completed task, from
    every project, lands in the one trailing group together.

    Habits H2 (2026-09-24): the Habits group that used to sit between
    Project and Unassigned is gone -- habits live on /habits now."""
    buckets: dict[str | None, list[dict]] = {}
    order: list[str | None] = []
    for t in open_tasks:
        proj = db.project_label_for(conn, "task", t["uid"])
        if proj not in buckets:
            buckets[proj] = []
            order.append(proj)
        buckets[proj].append(t)
    named = sorted((p for p in order if p is not None), key=str.lower)

    groups = [{"kind": "project", "name": p, "tasks": buckets[p]} for p in named]
    groups.append({"kind": "unassigned", "name": "Unassigned", "tasks": buckets.get(None, [])})
    completed_sorted = sorted(completed_tasks, key=lambda t: t.get("updated_at") or "", reverse=True)
    groups.append({"kind": "completed", "name": "Completed", "tasks": completed_sorted})
    return groups


def _tasks_list_context(
    conn,
    request: Request,
    date_filter: str = "all",
    q: str | None = None,
) -> dict:
    """Build the full render context for the Table view -- now the *only*
    Tasks view (2026-08-28 "major rework" session, item 4). Shared between
    the full page (list_tasks) and the async-CRUD region fragment
    (tasks_regions, GET /tasks/regions?region=table) so a mutation-triggered
    region refresh re-renders the exact same markup as the full page --
    _tasks_body.html is the single source of truth either way
    (features/async-crud.md).

    Filtering is date-only now (item 3) -- Status/Importance/Urgency/label
    filtering, the group-by toggle, sorting-by-column, and pagination are
    all gone (see this module's other 2026-08-28 comments for why each one
    went). No pagination in particular: the 1.9 pagination slice already
    special-cased "grouped mode shows everything, don't paginate it" --
    grouping is unconditional now, so that's simply the whole page's
    behavior, not a narrower special case anymore."""
    _auto_archive_if_configured(conn)
    tasks = db.list_tasks(conn, q=q)
    tasks = _apply_date_filter(tasks, date_filter)
    tasks.sort(key=_due_at_key)

    # Completed tasks (done/archived) stay visible in every view -- Today,
    # This week, All -- rather than disappearing the moment they're
    # checked off, but are pulled into their own trailing "Completed" group
    # (_build_task_groups) instead of interleaved with open work.
    open_tasks = [t for t in tasks if t["status"] not in DONE_STATUSES]
    completed_tasks = [t for t in tasks if t["status"] in DONE_STATUSES]

    # 1.5 slice (the deadline-vs-work-allocation surfacing slice, see
    # plans/open-priority.md § Task model): attach each visible task's
    # scheduled/completed/remaining hours so _task_row.html can render a
    # "Scheduled" column distinct from "Due" -- one batched query
    # (db.task_work_hours_bulk) for the whole page instead of one query per
    # row.
    _rendered = open_tasks + completed_tasks
    _hours = db.task_work_hours_bulk(conn, [t["uid"] for t in _rendered])
    for t in _rendered:
        t["work_hours"] = _hours[t["uid"]]

    groups = _build_task_groups(conn, open_tasks, completed_tasks)
    # Habits H2 (2026-09-24): habits have their own page (/habits) now --
    # the Habits group this table used to carry is gone, so "anything to
    # show" is just "any regular task".
    has_main_tasks = bool(open_tasks or completed_tasks)
    has_any = has_main_tasks

    tag_names = db.list_tag_names_in_use(conn)
    ctx = _task_context(request)
    ctx.update(
        {
            "groups": groups,
            "has_any": has_any,
            "has_main_tasks": has_main_tasks,
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "active_date_filter": date_filter,
            "q": q or "",
            "tag_names": tag_names,
            # audit-fixes-2.1.md (2026-09-13): tasks_list.html's own
            # tag_name_items -- fed the now-removed bulk-tag-picker
            # (#bulk-tag-picker, trimmed away along with bulk status-set
            # when the bulk-actions-bar shrank to Delete+Clear) -- is gone.
            # `tag_names` itself stays -- _task_row.html's per-row inline
            # Labels picker still reads it directly.
            "today_iso": date.today().isoformat(),
        }
    )
    return ctx


@router.get("")
def list_tasks(
    request: Request,
    date_filter: str = "all",
    q: str | None = None,
    conn=Depends(get_db),
):
    ctx = _tasks_list_context(conn, request, date_filter, q)
    return templates.TemplateResponse("tasks_list.html", ctx)


@router.get("/regions")
def tasks_regions(
    request: Request,
    region: str = "table",
    date_filter: str = "all",
    q: str | None = None,
    conn=Depends(get_db),
):
    """Async-CRUD region fragment (features/async-crud.md): renders a single
    named region of the Table view -- currently `region=table`, the
    #tasks-body div shared with tasks_list.html -- so static/async_crud.js's
    refreshRegion() can swap it in place after a mutation instead of a full
    page reload. Takes the same query params as list_tasks; the client
    forwards the page's own query string so the refreshed region honors the
    active date filter."""
    if region != "table":
        return JSONResponse({"error": f"unknown region '{region}'"}, status_code=400)
    ctx = _tasks_list_context(conn, request, date_filter, q)
    html = templates.env.get_template("_tasks_body.html").render(ctx)
    return HTMLResponse(html)


@router.get("/board")
def board_view_redirect():
    """Kanban is retired (2026-08-28 "major rework" session, item 4) --
    Table is now the only Tasks view. Redirect rather than a bare 404, same
    "any bookmark still lands somewhere real" precedent `/projects`'s own
    retirement established (routers/projects.py). tasks_board.html and this
    route's old filter-driven column logic are gone; `_apply_status_filter`
    et al died with them (see this module's other 2026-08-28 comments)."""
    return RedirectResponse(url="/tasks", status_code=302)


@router.get("/habits")
def habits_view_redirect():
    """Old Tasks > Habits URL -- habits have their own page since habits
    H2 (2026-09-24, routers/habits.py). Redirect, same precedent as
    board_view_redirect above."""
    return RedirectResponse(url="/habits", status_code=302)


@router.post("/habits/settings")
def save_habit_settings(habit_label: str = Form("Habit"), conn=Depends(get_db)):
    """Which label marks a task as habit-tracked -- 2026-08-28: the
    dedicated Tasks > Habits page this used to live on (a collapsible
    Settings panel at the bottom) is gone, but the setting itself, and this
    endpoint, are left in place unchanged -- a future slice can surface it
    somewhere in the merged Table view's Habits group if that turns out to
    be needed; nothing currently reads this route's redirect target as a
    real page. Returns to /habits since habits H2."""
    db.save_task_habit_settings(conn, habit_label)
    return RedirectResponse(url="/habits", status_code=303)


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
                "task": None,
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
            # 2026-08-29 (STATE.md backlog item 3) -- feeds the same
            # holiday-calendar dropdown _event_form_fields.html uses.
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


_WEEKDAY_ORDER = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _apply_habit_days(recurrence: str | None, habit_days, present) -> str | None:
    """habit_task_form.html's "Only on" day chips (habits H2): any day
    checked makes the habit a fixed-days one, `FREQ=WEEKLY;BYDAY=...`,
    overriding the Recurrence preset (the preset picker can't express
    weekdays). All unchecked on a form that carries the chips strips a
    previous BYDAY back to plain weekly. Forms without the chips (the plain
    task form, direct callers) leave `recurrence` untouched."""
    if not (isinstance(present, str) and present):
        return recurrence
    days = [d for d in _WEEKDAY_ORDER if isinstance(habit_days, list) and d in habit_days]
    if days:
        return "FREQ=WEEKLY;BYDAY=" + ",".join(days)
    if recurrence and "BYDAY=" in recurrence.upper():
        kept = [p for p in recurrence.split(";") if not p.upper().startswith("BYDAY=")]
        return ";".join(kept) or "FREQ=WEEKLY"
    return recurrence


def _habit_kind_value(raw) -> str | None:
    """Habits H5: "avoid" or None (a normal, build-it habit)."""
    return "avoid" if isinstance(raw, str) and raw.strip().lower() == "avoid" else None


def _habit_unit_value(raw) -> str | None:
    """Habits H5: short free-text unit for an amount habit ("glasses")."""
    if not isinstance(raw, str):
        return None
    return raw.strip()[:24] or None


def _habits_per_period_value(raw) -> int | None:
    """habit_task_form.html's "Times per period" field (habits H1): blank,
    missing, or anything below 2 means "once per period" (NULL); capped
    at 31 (every day of a month)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        n = int(float(raw))
    except ValueError:
        return None
    return min(n, 31) if n >= 2 else None


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
    habits_per_period: str | None = Form(None),
    habit_days: list[str] = Form([]),
    habit_days_present: str = Form(""),
    habit_kind: str | None = Form(None),
    habit_unit: str | None = Form(None),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
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
    # Same coercion for the three new holiday-policy fields (2026-08-29,
    # STATE.md backlog item 3) -- see the comment just above.
    if not isinstance(holiday_calendar, str):
        holiday_calendar = ""
    if not isinstance(exclude_saturday, str):
        exclude_saturday = ""
    if not isinstance(exclude_sunday, str):
        exclude_sunday = ""
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
        "recurrence": _apply_habit_days(
            recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
            habit_days,
            habit_days_present,
        ),
        "target_per_day": target_per_day_value,
        "habits_per_period": _habits_per_period_value(habits_per_period),
        "habit_kind": _habit_kind_value(habit_kind),
        "habit_unit": _habit_unit_value(habit_unit),
        # 2026-08-29 (STATE.md backlog item 3) -- see the `tasks` CREATE
        # TABLE comment; only meaningful once `recurrence` above is set.
        "holiday_calendar": holiday_calendar or None,
        "exclude_saturday": exclude_saturday in ("1", "true", "on"),
        "exclude_sunday": exclude_sunday in ("1", "true", "on"),
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


def _is_habit_task(conn, task: dict | None) -> bool:
    """True if `task` carries the configured habit label -- the same test
    `db.list_habit_tasks`' own filter applies, done directly against a
    single already-fetched task instead of a second query. Used to route
    a habit-tracked task's edit/view to the dedicated habit_task_form.html/
    habit_task_detail.html templates (2026-08-29 direct feedback: "habits
    should not have in their edit modal a label dropdown, a status
    dropdown, a due or a start date") instead of the generic task_form.
    html/task_detail.html every other task uses."""
    if not task:
        return False
    habit_label = db.get_task_habit_settings(conn)["habit_label"]
    return habit_label in (task.get("tags") or [])


@router.get("/{uid}/edit")
def edit_task_form(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    if _is_habit_task(conn, task):
        # Dedicated stripped-down edit form (2026-08-29) -- see
        # habit_task_form.html's own docstring for why the generic
        # task_form.html (label dropdown, status dropdown, due/start date)
        # is wrong for a habit-tracked task, and _is_habit_task above.
        return templates.TemplateResponse(
            "habit_task_form.html",
            {
                "request": request,
                "active_tab": "tasks",
                "task": task,
                "habit_label": db.get_task_habit_settings(conn)["habit_label"],
                # Work sessions card (2026-08-29 addition to this form) --
                # see _work_allocation_context above.
                **_work_allocation_context(conn, task),
            },
        )
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
            # 2026-08-29 (STATE.md backlog item 3) -- see new_task_form.
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


@router.get("/{uid}")
def task_detail(uid: str, request: Request, month: str | None = None, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    ctx = _task_context(request)
    ctx.update(
        {
            "task": task,
            # 2026-08-30 (direct request): the resolved label/project/Space
            # banner (db.banner_for_task), if any -- rendered as a hero
            # strip above the modal header, same "identity" role the app's
            # dashboard-page banners already play, just scoped to one task
            # instead of a whole page.
            "banner": db.banner_for_task(conn, task) if task else None,
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
        excluded = _excluded_dates_for_row(conn, task, completions, date.today())
        # Habits H1 (2026-09-24): schedule-aware -- a weekly or Mon/Wed/Fri
        # task no longer "breaks" on the days it isn't due.
        stats = habit_view.stats_for_task(task, {d: 1 for d in completions}, excluded)
        ctx.update(
            {
                "completions": completions,
                "completion_weeks": _completion_heatmap_weeks(completions),
                "current_streak": stats["current"],
                "longest_streak": stats["longest"],
                "habit_stats": stats,
            }
        )
    else:
        ctx.update(
            {
                "completions": {},
                "completion_weeks": [],
                "current_streak": 0,
                "longest_streak": 0,
                "habit_stats": None,
            }
        )
    if _is_habit_task(conn, task):
        # Dedicated view modal (2026-08-29) -- see habit_task_detail.html's
        # own docstring/_is_habit_task above. Every context key it needs
        # (task, completion_weeks, current_streak, work_allocations,
        # work_hours, habit_label) is already on `ctx`/available here.
        ctx["habit_label"] = db.get_task_habit_settings(conn)["habit_label"]
        # Habits H3 (2026-09-24): month calendar + day notes + "Log a day".
        rows = db.list_task_completions(conn, uid)
        ctx["habit_month"] = habit_view.month_calendar(uid, rows, month if isinstance(month, str) else None)
        ctx["habit_notes"] = habit_view.recent_notes(rows)
        ctx["today_iso"] = date.today().isoformat()
        return templates.TemplateResponse("habit_task_detail.html", ctx)
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
    habits_per_period: str | None = Form(None),
    habit_days: list[str] = Form([]),
    habit_days_present: str = Form(""),
    habit_kind: str | None = Form(None),
    habit_unit: str | None = Form(None),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
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
    # Defensively coerced -- same reasoning as create_task's own comment;
    # every pre-existing direct caller of update_task (this suite's tests)
    # predates these three fields entirely.
    if not isinstance(holiday_calendar, str):
        holiday_calendar = ""
    if not isinstance(exclude_saturday, str):
        exclude_saturday = ""
    if not isinstance(exclude_sunday, str):
        exclude_sunday = ""
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
            "recurrence": _apply_habit_days(
                recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
                habit_days,
                habit_days_present,
            ),
            "target_per_day": target_per_day_value,
            # 2026-08-29 (STATE.md backlog item 3) -- always overwritten by
            # whatever this form submits, same convention as recurrence/tags
            # just above; habit_task_form.html has no such fields and so
            # always submits the Form(...) defaults here, same as it
            # already does for due_at/start_at/status (see that template's
            # own comment).
            "holiday_calendar": holiday_calendar or None,
            "exclude_saturday": exclude_saturday in ("1", "true", "on"),
            "exclude_sunday": exclude_sunday in ("1", "true", "on"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    # Only habit_task_form.html sends this field -- a plain task form
    # leaves whatever the row already had.
    if isinstance(habits_per_period, str):
        row["habits_per_period"] = _habits_per_period_value(habits_per_period)
    # Habits H5 -- same "only the habit form sends these" rule.
    if isinstance(habit_kind, str):
        row["habit_kind"] = _habit_kind_value(habit_kind)
    if isinstance(habit_unit, str):
        row["habit_unit"] = _habit_unit_value(habit_unit)
    try:
        db.upsert_task(conn, row)
    except db.MultipleProjectLabelsError as exc:
        raise HTTPException(400, str(exc))
    return respond(x_requested_with, "/tasks")


_UPDATABLE_FIELDS = {"status", "due_at", "title", "tags"}


@router.post("/{uid}/update-field")
async def update_field(uid: str, request: Request, conn=Depends(get_db)):
    """Single-field inline edit, used by the Table view's click-to-edit
    pills/date/labels cells. Deliberately a JSON body, not a Form -- this is
    only ever called from tasks_table.js via fetch(), never from a plain
    HTML form/no-JS fallback, unlike every other route in this router. (The
    Projects page's Kanban board used to call this too for its own per-card
    status dropdown -- removed 2026-09-02, "no inline editing"; a status
    change there now happens by opening the task's own edit form instead,
    which POSTs through the normal `/tasks/{uid}` route, not this one.)

    `tags` (2026-08-29, STATE.md backlog item 9, "Labels ... become
    always-clickable checkbox dropdown menus") -- the Table view's Labels
    cell is now an editable checkbox dropdown (static/tasks_table.js), same
    "no separate Save step" convention as status/due_at above: every
    checkbox toggle re-posts the row's *complete* new tag list (a replace,
    not an add/remove delta -- simpler than diffing, and the client already
    has the full checked set at hand from the panel's own checkboxes)."""
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
    elif field == "tags":
        if not isinstance(value, list):
            return JSONResponse({"error": "tags value must be a list"}, status_code=400)
        row["tags"] = sorted({t.strip() for t in value if isinstance(t, str) and t.strip()})
    else:  # title
        if not isinstance(value, str) or not value.strip():
            return JSONResponse({"error": "title cannot be blank"}, status_code=400)
        row["title"] = value.strip()
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    # 1.5 (single-project-per-task): the tags path can put a second project
    # label on a task same as the create/edit forms/bulk "Add label" can --
    # surfaced the same way, a plain 400 rather than a silent 500/partial
    # write (db.upsert_task raises before writing anything).
    try:
        db.upsert_task(conn, row)
    except db.MultipleProjectLabelsError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
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



def _completion_heatmap_weeks(
    completions: dict[str, str], weeks: int = habit_heatmap.DETAIL_WEEKS, today: date | None = None
) -> list[list[dict]]:
    """Monday-aligned grid of `weeks` columns x 7 rows ending on `today`,
    same shape habits' _heatmap_weeks produces (so the shared
    _habit_heatmap.html macro can paint it). A present date is "full"
    (level 4 -- there's no target-per-day concept for task check-offs);
    future days render blank/non-interactive (level -1).

    Default was 12 weeks until 2026-08-29 direct feedback ("the heatmap
    graph should not have empty space... prefer to show more months, empty
    cells, but not empty space"): at the heatmap's fixed 11px cell size, 12
    weeks (~168px) was far narrower than the ~660px modal body
    habit_task_detail.html renders it in, leaving a large blank gap.
    Reusing habit_heatmap.DETAIL_WEEKS (53 weeks, "a bit over a year") both
    fills that width with real grid (extra future days render as blank
    *cells* within the grid, not blank space around it) and keeps this
    heatmap visually consistent with the standalone habit detail modal's."""
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
    uid: str,
    completion_date: str,
    request: Request,
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """The heatmap/list toggle for a recurring task's daily check-off: no
    completion for that date -> record one; already logged -> remove it
    (back to true "not done", not a hidden zero row). Redirects back to the
    referer (the tasks list's Today column), falling back to the task's own
    detail page when there's no referer -- same pattern as the habits
    toggle.

    2026-08-28 follow-up fix: this endpoint always redirected regardless of
    `X-Requested-With`, so the Habits group's checkbox (_habit_row.html,
    posts here for a plain kind='task' habit) never had a JSON success path
    to key off of -- it fell back to a plain, unenhanced native form submit
    (no `data-cc-change` was even set), causing a full-page reload/re-
    navigate on every check-in. Now dual-mode like every other mutation
    endpoint in this router (deps.respond)."""
    # Habits H3 (2026-09-24): every day cell (Habits page strip, detail
    # year grid, month calendar) posts here -- reject a malformed or
    # future date instead of storing it.
    try:
        if date.fromisoformat(completion_date) > date.today():
            return JSONResponse({"error": "Can't log a day in the future."}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid date."}, status_code=400)
    if db.get_task_completion(conn, uid, completion_date) is not None:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(
            conn, uid, completion_date, datetime.now(timezone.utc).isoformat()
        )
    referer = request.headers.get("referer")
    return respond(x_requested_with, referer or f"/tasks/{uid}")


@router.post("/{uid}/completions")
def set_task_completion(
    uid: str,
    request: Request,
    completion_date: str = Form(...),
    value: str = Form("1"),
    note: str | None = Form(None),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Explicit-value counterpart to toggle_task_completion above (a >target_per_day
    "+1" quick check-in button on Tasks > Habits posts today's date and
    the pre-computed next value here; referer-aware redirect is what lets
    that work from the check-in row without bouncing to the task's own
    detail page). Only relevant for a habit-labeled task with
    target_per_day > 1 -- a plain checkbox habit (or an ordinary recurring
    task) never has anything that posts here, it just uses the toggle
    route above.

    2026-08-28 follow-up fix: same always-redirects gap as the toggle route
    above -- now dual-mode (deps.respond) so the Habits group's "+1" button
    can succeed via fetch instead of a full native form submit."""
    # Habits H3 (2026-09-24): the detail modal's "Log a day" form lets a
    # user pick the date, so validate it -- a real ISO date, not in the
    # future (backfilling the past is the point; logging tomorrow isn't).
    try:
        if date.fromisoformat(completion_date) > date.today():
            return JSONResponse({"error": "Can't log a day in the future."}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid date."}, status_code=400)
    if not isinstance(note, str):
        note = None
    elif note is not None:
        note = note.strip()[:500]
    try:
        parsed_value = float(value) if value else 1.0
    except ValueError:
        parsed_value = 1.0
    # 2026-08-28 follow-up (direct number input replacing the "+1"/reset
    # buttons): the input's own `max="999999"` is advisory only -- an HTML
    # `max` doesn't stop a hand-crafted request, so clamp here too. Keeps
    # a typo or scroll-wheel nudge from writing an arbitrarily large value.
    if parsed_value > _MAX_HABIT_VALUE:
        parsed_value = _MAX_HABIT_VALUE
    if parsed_value <= 0:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(
            conn, uid, completion_date, datetime.now(timezone.utc).isoformat(), parsed_value, note
        )
    referer = request.headers.get("referer")
    return respond(x_requested_with, referer or f"/tasks/{uid}")


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
# Relations -- fully removed 2026-08-29 (STATE.md backlog item 4, direct
# request). This used to be the task side of an event<->task associative
# links feature ("a relation can link an event with existing/new tasks
# that both have at least one label in common"): POST /{uid}/relations and
# /{uid}/relations/remove, backed by the Relations card in task_form.html/
# task_detail.html (_task_relations.html, now unreferenced). Not the same
# thing as Work allocations right below, which is a distinct feature built
# on the same event_task_relations table (is_work_allocation=1 rows) and
# is untouched. db.py's underlying CRUD (add_event_task_relation/
# remove_event_task_relation/related_events_for_task/related_tasks_for_
# event) is left in place -- other things still read it (routers/export.py's
# backup/restore, the offline-sync tests) -- there's just no UI path left
# that calls it for an ordinary (non-work-allocation) relation anymore.
# --------------------------------------------------------------------- #


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


@router.post("/{uid}/work-allocations/{event_uid}/set-times")
def set_work_allocation_times(uid: str, event_uid: str, start_at: str = Form(""), end_at: str = Form(""), conn=Depends(get_db)):
    """The Work sessions card's per-session picker (2026-08-17): give one
    session its scheduled start/end right from the card instead of only by
    drag. The shared datetime picker's hidden start_at/end_at inputs post
    here (data-modal-keep-open refreshes the card in place). db.
    set_work_allocation_times guards the same contract the drag endpoints
    use -- the event must actually be one of this task's work allocations
    and end_at must follow start_at -- and returns False (no-op) otherwise,
    never an error page, so a cancelled/invalid Apply just leaves the
    session untouched."""
    db.set_work_allocation_times(conn, event_uid, start_at, end_at)
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
