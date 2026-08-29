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

# 2026-08-28 follow-up ("direct number input" for the Habits group's
# check-in cell) -- server-side mirror of the input's `max="999999"`, see
# set_task_completion below. Shared with routers/habits.py's own copy
# (kept as a plain duplicated constant rather than a cross-router import,
# same "small enough to just repeat" call this app makes elsewhere for a
# one-line bound rather than adding an import edge between two routers).
_MAX_HABIT_VALUE = 999999


def _excluded_dates_for_row(conn, row: dict, entries_by_date: dict, today: date) -> set[str]:
    """2026-08-29 (STATE.md backlog item 3): the same holiday_calendar/
    exclude_saturday/exclude_sunday policy resolution as routers/habits.py's
    _excluded_dates_for_habit (kept as its own small copy here rather than
    a cross-router import -- same "small enough to just repeat" call this
    file already makes for _MAX_HABIT_VALUE above) -- `row` may be a
    recurring task or a standalone habit entity, both now carry the same
    three columns. Cheap no-op (no DB read) when the row has no policy set
    at all."""
    if not (row.get("holiday_calendar") or row.get("exclude_saturday") or row.get("exclude_sunday")):
        return set()
    logged = [date.fromisoformat(d) for d in entries_by_date if d]
    start = min(logged) if logged else today
    start = max(start, today - timedelta(days=730))
    holiday_calendars = db.list_holidays_by_calendar(conn)
    return habit_heatmap.excluded_dates_in_range(row, holiday_calendars, start, today)


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
#
# 2026-08-28 "major rework" session (plans/STATE.md, item 3): the Table
# view's Importance/Urgency *filter dropdowns and sort keys* are gone (see
# the removed IMPORTANCE_FILTERS/URGENCY_FILTERS/_apply_importance_filter/
# _apply_urgency_filter below, in a previous revision of this file) -- but
# these two label/color maps stay, since task_detail.html's read-only
# Importance/Urgency meta row (_task_context) still reads them, and that
# surface was never in scope for this session's cut (only the Table page's
# own filtering/columns were named in the request).
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


def _apply_date_filter(tasks: list[dict], date_filter: str, label_rules: dict | None = None) -> list[dict]:
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
    "filtering reduced to date only"). `label_rules` is kept as a
    parameter (unused by the remaining, purely temporal buckets) rather
    than dropped, since derived_state.virtual_states' own signature takes
    it and other callers of that function still need it."""
    if date_filter == "all":
        return tasks
    states = {date_filter}
    return [t for t in tasks if states & derived_state.virtual_states(t, label_rules or {})]


def _task_label_rules(conn) -> dict[str, dict]:
    """{label name: effective label config} for every label -- the resolved
    rules the `important`/`urgent` derived-state filters feed to
    src/derived_state.py. Delegates to db.list_label_rules (one call, never
    per task) -- see that function's docstring. Kept as a thin alias so the
    router's call sites read naturally and so dashboard.py (which imports
    this helper for its aggregation-service widget) has one stable name."""
    return db.list_label_rules(conn)


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
        "importance_labels": IMPORTANCE_LABELS,
        "importance_colors": IMPORTANCE_COLORS,
        "urgency_labels": URGENCY_LABELS,
        "urgency_colors": URGENCY_COLORS,
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


def _habit_group_items(conn) -> list[dict]:
    """2026-08-28 "major rework" session (item 2, "merge Habits into the
    Tasks table"): the Habits group's rows are a merge of the two habit
    concepts this app has grown -- habit-*labeled tasks* (task_habit_
    settings, "Tasks > Habits" as it existed before this session, real
    `tasks` rows tracked via target_per_day/task_completions) and the
    separate, standalone Habit *entities* (routers/habits.py's `habits`/
    `habit_entries` tables, whose own dedicated list page is retired by
    this same session -- see routers/habits.py's module docstring). Both
    are normalized into one shared shape here so _habit_row.html only has
    to render one thing, not two -- `kind` ('task' | 'entity') is the only
    field that varies where the two check-in mechanics differ (the toggle/
    plus/delete URLs). Going forward, the group's own "+" add-row only
    creates NEW habit-tracked work via the task-habit flow (`/tasks/new?
    habit=1`, unchanged) -- routers/habits.py's create endpoints stay alive
    (a pre-existing standalone habit needs somewhere to keep living, and
    its edit/archive/delete/entries endpoints are still exactly how this
    group's "entity" rows are mutated), but there's deliberately only one
    *creation* entry point post-merge rather than two competing ones."""
    today = date.today()
    today_iso = today.isoformat()
    items: list[dict] = []
    for t in db.list_habit_tasks(conn):
        if t["status"] in DONE_STATUSES:
            continue
        entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, t["uid"])}
        target = t.get("target_per_day") or 1
        excluded = _excluded_dates_for_row(conn, t, entries_by_date, today)
        current_streak, _ = habit_heatmap.streaks(entries_by_date, excluded_dates=excluded)
        today_value = entries_by_date.get(today_iso, 0)
        items.append(
            {
                "kind": "task",
                "uid": t["uid"],
                "title": t["title"],
                "tags": t.get("tags") or [],
                "is_quantity": target > 1,
                "target": target,
                "today_value": today_value,
                "next_value": today_value + 1,
                "done_today": today_value > 0,
                "current_streak": current_streak,
                # 2026-08-29 direct feedback: the Due column shows this
                # habit's cadence ("Daily"/"Weekly"/...), not its streak --
                # habit_heatmap.recurrence_label never renders the raw
                # "FREQ=DAILY" the task's own `recurrence` column stores.
                "recurrence_label": habit_heatmap.recurrence_label(t.get("recurrence")),
                "detail_url": f"/tasks/{t['uid']}",
                "toggle_url": f"/tasks/{t['uid']}/completion/{today_iso}/toggle",
                "plus_url": f"/tasks/{t['uid']}/completions",
                "delete_url": f"/tasks/{t['uid']}/delete",
            }
        )
    for h in db.list_habits(conn):
        entries_by_date = db.habit_entries_by_date(conn, h["uid"])
        target = h.get("target_per_day") or 1
        excluded = _excluded_dates_for_row(conn, h, entries_by_date, today)
        current_streak, _ = habit_heatmap.streaks(entries_by_date, excluded_dates=excluded)
        today_value = entries_by_date.get(today_iso, 0)
        items.append(
            {
                "kind": "entity",
                "uid": h["uid"],
                "title": h["name"],
                "tags": [],
                "is_quantity": target > 1,
                "target": target,
                "today_value": today_value,
                "next_value": today_value + 1,
                "done_today": today_value > 0,
                "current_streak": current_streak,
                # A standalone Habit entity has no recurrence field at all
                # (habit_entries is inherently a per-day log) -- it's
                # implicitly daily, same as habit_task_form.html's "New
                # habit" flow defaults its own Recurrence field to.
                "recurrence_label": "Daily",
                "detail_url": f"/habits/{h['uid']}",
                "toggle_url": f"/habits/{h['uid']}/entries/{today_iso}/toggle",
                "plus_url": f"/habits/{h['uid']}/entries",
                "delete_url": f"/habits/{h['uid']}/delete",
            }
        )
    items.sort(key=lambda it: (it["title"] or "").lower())
    return items


def _build_task_groups(conn, open_tasks: list[dict], completed_tasks: list[dict]) -> list[dict]:
    """2026-08-28 "major rework" session (item 3): grouping is now always
    on, in one fixed order -- Project (one group per project label,
    alphabetical) -> Habits (its own group, see _habit_group_items) ->
    Unassigned (open tasks with no project label) -> Completed (every
    completed task regardless of project, most-recent-first, always last).
    `open_tasks` is expected pre-sorted by due date (_due_at_key) -- every
    group but Completed simply preserves that order, so a project/
    Unassigned group's own tasks read due-date-ascending for free without
    re-sorting per bucket. Completed intentionally does NOT nest under its
    task's project anymore (the pre-rework `group_by=project` grouping did)
    -- "completed always last" only holds if every completed task, from
    every project, lands in the one trailing group together."""
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
    # NOTE: the key is `habit_items`, not `items` -- Jinja's attribute
    # lookup falls back to `dict.items` (the bound method every plain dict
    # already carries) if a `grp.items` template expression is used, which
    # would silently shadow a real "items" dict key with the builtin
    # instead of erroring (the exact class of bug _render_important_urgent's
    # "rows, not items" comment elsewhere in this app already warns about).
    groups.append({"kind": "habits", "name": "Habits", "habit_items": _habit_group_items(conn)})
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
    label_rules = _task_label_rules(conn)
    tasks = db.list_tasks(conn, q=q)
    tasks = _apply_date_filter(tasks, date_filter, label_rules)
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
    has_any = bool(open_tasks or completed_tasks or groups[-3]["habit_items"])  # the Habits group

    tag_names = db.list_tag_names_in_use(conn)
    ctx = _task_context(request)
    ctx.update(
        {
            "groups": groups,
            "has_any": has_any,
            "date_filters": DATE_FILTERS,
            "date_filter_labels": DATE_FILTER_LABELS,
            "active_date_filter": date_filter,
            "q": q or "",
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            # _habit_row.html's check-in "+1" form needs today's date to
            # post as entry_date/completion_date -- same value
            # _habit_group_items already anchored its per-item today_value/
            # next_value computation to.
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
    """The dedicated Tasks > Habits view is retired (2026-08-28 "major
    rework" session, items 2+3) -- every habit-labeled task, and every
    standalone Habit entity, now renders as a row in the Table view's own
    Habits group instead (see _habit_group_items/_build_task_groups).
    Redirect, same precedent as board_view_redirect above."""
    return RedirectResponse(url="/tasks", status_code=302)


@router.post("/habits/settings")
def save_habit_settings(habit_label: str = Form("Habit"), conn=Depends(get_db)):
    """Which label marks a task as habit-tracked -- 2026-08-28: the
    dedicated Tasks > Habits page this used to live on (a collapsible
    Settings panel at the bottom) is gone, but the setting itself, and this
    endpoint, are left in place unchanged -- a future slice can surface it
    somewhere in the merged Table view's Habits group if that turns out to
    be needed; nothing currently reads this route's redirect target as a
    real page, so it just returns to the Table."""
    db.save_task_habit_settings(conn, habit_label)
    return RedirectResponse(url="/tasks", status_code=303)


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
        "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
        "target_per_day": target_per_day_value,
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
    # 2026-08-29 (STATE.md backlog item 1, "bulk actions... then Habits"):
    # a selection on the Tasks page may include Habits-group rows for the
    # standalone Habit entity kind (_habit_row.html's checkbox, kind=
    # "entity") alongside plain task uids -- only "delete" needs to know
    # the difference (see static/tasks_table.js's selectedByKind), since
    # a habit entity lives in `habits`, not `tasks`. Only meaningful for
    # `action == "delete"`; every other branch below is unchanged and
    # still only ever looks at `uids`.
    habit_uids = payload.get("habit_uids") or []
    if action != "delete" and not uids:
        return JSONResponse({"error": "no tasks selected"}, status_code=400)
    if action == "delete" and not uids and not habit_uids:
        return JSONResponse({"error": "no tasks selected"}, status_code=400)

    if action == "delete":
        # Tasks are flat (1.2, task-model decision) -- no subtask cascade.
        # The checklist-item cleanup below is kept for any rows a database
        # from before the checklist/subtask removal still physically has.
        for uid in uids:
            db.delete_task(conn, uid)
            db.delete_checklist_items_for_task(conn, uid)
        for uid in habit_uids:
            db.delete_habit(conn, uid)
        return JSONResponse({"ok": True, "count": len(uids) + len(habit_uids)})

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
def task_detail(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    ctx = _task_context(request)
    ctx.update(
        {
            "task": task,
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
        current_streak, longest_streak = _completion_streaks(completions, excluded_dates=excluded)
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
    if _is_habit_task(conn, task):
        # Dedicated view modal (2026-08-29) -- see habit_task_detail.html's
        # own docstring/_is_habit_task above. Every context key it needs
        # (task, completion_weeks, current_streak, work_allocations,
        # work_hours, habit_label) is already on `ctx`/available here.
        ctx["habit_label"] = db.get_task_habit_settings(conn)["habit_label"]
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
            "recurrence": recurrence if recurrence and recurrence.strip().lower() not in ("none", "nothing") else None,
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


def _completion_streaks(
    completions: dict[str, str], today: date | None = None, excluded_dates: set[str] | None = None
) -> tuple[int, int]:
    """(current_streak, longest_streak) in days for a recurring task's
    completion history (dict of {due_date: ...}). Any present date counts
    as done. The current streak tolerates today not being checked off yet
    (you haven't lost the streak because it's 9am) but breaks the moment a
    full calendar day is skipped -- same semantics as habits' _streaks.

    `excluded_dates` (2026-08-29, STATE.md backlog item 3): same meaning
    as habit_heatmap.streaks' own parameter -- a non-working day per this
    task's holiday_calendar/exclude_saturday/exclude_sunday policy is
    invisible to the walk below, neither done nor a break. This is a
    hand-rolled twin of habit_heatmap.streaks (presence-only `completions`
    keys instead of a {date: value} log) rather than a shared call --
    reworking `completions` into the value-shaped dict streaks() expects
    just to reuse it would be more churn than the ~20 lines duplicated
    here, same call this function's own pre-existing docstring note
    ("same semantics as habits' _streaks") already implied before this
    change."""
    excluded_dates = excluded_dates or set()
    today = today or date.today()
    done_dates = sorted(d for d in completions if d and d not in excluded_dates)
    if not done_dates:
        return 0, 0
    done_set = set(done_dates)

    def _all_excluded_between(a: date, b: date) -> bool:
        span = (b - a).days
        return all((a + timedelta(days=i)).isoformat() in excluded_dates for i in range(1, span))

    longest = current_run = 0
    prev: date | None = None
    for d_str in done_dates:
        d = date.fromisoformat(d_str)
        if prev is not None and ((d - prev).days == 1 or _all_excluded_between(prev, d)):
            current_run += 1
        else:
            current_run = 1
        longest = max(longest, current_run)
        prev = d

    cursor = today
    if cursor.isoformat() not in done_set and cursor.isoformat() not in excluded_dates:
        cursor -= timedelta(days=1)
    current = 0
    while True:
        iso = cursor.isoformat()
        if iso in done_set:
            current += 1
            cursor -= timedelta(days=1)
        elif iso in excluded_dates:
            cursor -= timedelta(days=1)
        else:
            break
    return current, longest


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
    x_requested_with: str | None = Header(default=None),
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
    route above.

    2026-08-28 follow-up fix: same always-redirects gap as the toggle route
    above -- now dual-mode (deps.respond) so the Habits group's "+1" button
    can succeed via fetch instead of a full native form submit."""
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
        db.upsert_task_completion(conn, uid, completion_date, datetime.now(timezone.utc).isoformat(), parsed_value)
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
