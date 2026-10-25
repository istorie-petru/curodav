from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import clock, db, derived_state, finance, finance_stats, habit_heatmap, habit_view, university_plan, work_sessions
from .. import tags as tag_store
from .. import validation
from ..deps import get_db, respond, templates, validation_response
from . import dashboard as dashboard_router
from . import calendar as calendar_router  # _annotate_calendar_colors, for related events' identity dots

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_AUTO_ARCHIVE_DAYS_KEY = "task_auto_archive_days"

_MAX_HABIT_VALUE = 999999


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

STATUS_ITEMS = [{"uid": s, "name": STATUS_LABELS[s]} for s in STATUSES]

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
    """
    if date_filter == "all":
        return tasks
    states = {date_filter}
    return [t for t in tasks if states & derived_state.virtual_states(t)]


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _work_allocation_context(conn, task: dict) -> dict:
    """Context keys every task view modal needs for its Work sessions card: the scheduled work
        blocks for this task plus the scheduled/completed/remaining hour totals
        they add up to. `None` task -> empty, so templates never have to branch
        on the object existing.
    """
    if task is None:
        return {"work_allocations": [], "work_hours": {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0},
                "linked_events": [], "link_candidates": [], "link_selected": []}
    allocations = db.list_work_allocations_for_task(conn, task["uid"])
    allocations = calendar_router._annotate_calendar_colors(conn, allocations)
    links = [link for link in db.links_for_task(conn, task["uid"]) if link["kind"] != "work_session"]
    since = (clock.today() - timedelta(days=14)).isoformat()
    return {
        "linked_events": links,
        "link_candidates": db.link_candidate_events(conn, task, since),
        "link_selected": [link["event"]["uid"] for link in links],
        "work_allocations": allocations,
        "work_hours": db.task_work_hours(conn, task["uid"]),
        "work_difficulty": work_sessions.average_difficulty([a.get("difficulty") for a in allocations]),
        "work_estimate_hours": work_sessions.estimated_hours(allocations),
        "work_difficulties": work_sessions.DIFFICULTIES,
    }


async def _pending_tag_values(request: Request) -> dict:
    """The Keywords dropdown of each Pending transactions row, posted as pt_tags__<row key>."""
    form = await request.form()
    return {k[len("pt_tags__"):]: form.getlist(k) for k in form.keys() if k.startswith("pt_tags__")}


def _pending_transaction_context(conn, task: dict | None) -> dict:
    """What the task edit form's Pending transactions rows need: the task's scheduled rows and the account names."""
    accounts = finance.list_accounts(conn)
    rows = finance.list_scheduled(conn, task_uid=task["uid"]) if task else []
    return {
        "pending_tag_items": tag_store.picker(conn, "scheduled", "", [t for r in rows for t in r["tags"]])["items"],
        "pending_transactions": rows,
        "pending_account_names": [a["name"] for a in accounts],
        "pending_type_names": [n for _, n in finance_stats.TRANSACTION_TYPES],
        "pending_amount_text": finance_stats.amount_input,
    }


def _pending_transaction_rows(conn, keys, uids, types, amounts, descriptions, accounts, to_accounts, dates, tags) -> list[dict]:
    """Zip the form's parallel pt_* arrays into rows, turning type and account names into the ids the model uses.
    `tags` maps a row's key to its Keywords selection."""
    by_name = {a["name"].lower(): a["uid"] for a in finance.list_accounts(conn)}
    rows = []
    for key, uid, kind, amount, description, account, to_account, day in zip(keys, uids, types, amounts, descriptions, accounts, to_accounts, dates):
        picked = tags.get(key, [])
        if not any((kind, amount, description, account, to_account, day, picked)):
            continue
        rows.append({"uid": uid, "type": kind.lower(), "amount": amount, "description": description, "date": day,
                     "account_uid": by_name.get(account.lower(), ""), "to_account_uid": by_name.get(to_account.lower(), ""),
                     "tags": picked})
    return rows


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
    """A task with no due date sorts last within its group
        (the same '9999' sentinel the old due_at sort key already used).
    """
    return t.get("due_at") or "9999"


def _build_task_groups(conn, open_tasks: list[dict], completed_tasks: list[dict]) -> list[dict]:
    """The list's sections: one per shelf (alphabetical), then tasks with no tag, then Completed last.

    A shelf section holds a sub-group per tag; a task sits under every tag it carries. `tasks` is the section's
    tasks without repeats. `open_tasks` is pre-sorted by due date and each group keeps that order. Completed
    tasks stay together in the one trailing group, newest change first."""
    shelves: dict[str, dict[str, list[dict]]] = {}
    loose: list[dict] = []
    for t in open_tasks:
        items = t.get("tag_items") or []
        for item in items:
            shelves.setdefault(item["label"], {}).setdefault(item["name"], []).append(t)
        if not items:
            loose.append(t)
    groups = []
    for shelf, by_tag in sorted(shelves.items(), key=lambda kv: kv[0].lower()):
        subgroups = []
        for name, members in sorted(by_tag.items(), key=lambda kv: kv[0].lower()):
            look = next(i for i in members[0]["tag_items"] if i["name"] == name)
            subgroups.append({"name": name, "color": look["color"], "icon": look["icon"], "tasks": members})
        unique = {t["uid"]: t for sub in subgroups for t in sub["tasks"]}
        groups.append({"kind": "label", "name": shelf, "subgroups": subgroups,
                       "tasks": sorted(unique.values(), key=_due_at_key)})
    if loose:
        groups.append({"kind": "unassigned", "name": "No tag", "subgroups": [], "tasks": loose})
    completed_sorted = sorted(completed_tasks, key=lambda t: t.get("updated_at") or "", reverse=True)
    if completed_sorted:
        groups.append({"kind": "completed", "name": "Completed", "subgroups": [], "tasks": completed_sorted})
    return groups


def _tasks_list_context(
    conn,
    request: Request,
    date_filter: str = "all",
    q: str | None = None,
) -> dict:
    """Build the full render context for the Table view -- now the *only*
        Tasks view. Shared between
        the full page (list_tasks) and the async-CRUD region fragment
        (tasks_regions, GET /tasks/regions?region=table) so a mutation-triggered
        region refresh re-renders the exact same markup as the full page --
        _tasks_body.html is the single source of truth either way
        (features/async-crud.md).

        Filtering is date-only now (item 3) -- Status/Importance/Urgency/label
        filtering, the group-by toggle, sorting-by-column, and pagination are
        all gone. No pagination in particular: the 1.9 pagination slice already
        special-cased "grouped mode shows everything, don't paginate it" --
        grouping is unconditional now, so that's simply the whole page's
        behavior, not a narrower special case anymore.
    """
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

    _rendered = open_tasks + completed_tasks
    _hours = db.task_work_hours_bulk(conn, [t["uid"] for t in _rendered])
    for t in _rendered:
        t["work_hours"] = _hours[t["uid"]]

    groups = _build_task_groups(conn, open_tasks, completed_tasks)
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
            "today_iso": clock.today().isoformat(),
            "soon_iso": (clock.today() + timedelta(days=2)).isoformat(),
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
def board_view(request: Request, conn=Depends(get_db)):
    """Every open task on one status board; done tasks show the most recent few."""
    board_statuses = [s for s in STATUSES if s != "archived"]
    columns: dict[str, list] = {s: [] for s in board_statuses}
    tasks = [t for t in db.list_tasks(conn) if t["status"] != "archived"]
    tasks.sort(key=_due_at_key)
    for t in tasks:
        t["strip"] = db.card_strip(conn, t)
        if t["status"] in columns:
            columns[t["status"]].append(t)
    columns["done"] = sorted(columns["done"], key=lambda t: t.get("completed_at") or "", reverse=True)[:20]
    ctx = _task_context(request)
    ctx.update({"columns": columns, "board_statuses": board_statuses, "label": None, "active_tab": "tasks"})
    return templates.TemplateResponse("tasks_board.html", ctx)


@router.get("/habits")
def habits_view_redirect():
    """Old Tasks > Habits URL -- habits have their own page since habits
        H2. Redirect, same precedent as
        board_view_redirect above.
    """
    return RedirectResponse(url="/habits", status_code=302)


@router.get("/new")
def new_task_form(
    request: Request, habit: bool = False, project: str = "", title: str = "", conn=Depends(get_db)
):
    if habit:
        return templates.TemplateResponse(
            "habit_task_form.html",
            {"request": request, "active_tab": "tasks", "task": None},
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
            **db.project_picker_context(conn),
            "today": clock.today().isoformat(),
            # 1.4 (Project pages & views: "newly created tasks automatically
            # receive the project's label") -- the project detail page's "+
            # New task" link opens this same form with ?project=<name>, which
            # only pre-checks the label chip (still removable, same as any
            # other prefill in this app) rather than silently forcing it.
            "prefill_tags": [project] if project else [],
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


def _apply_habit_repeat(repeat, recurrence, habit_days, habits_per_period, times_week=None, times_month=None):
    """habit_task_form.html's "How often" choice: daily /
        days (the Days dropdown) / week / month (the "N times a week/month"
        dropdown next to it) / keep (the stored rule, sent back as the hidden
        `recurrence`). Returns (recurrence, habits_per_period); forms without
        the field get their own values back unchanged, and _apply_habit_days
        still runs after.
    """
    if not isinstance(repeat, str) or not repeat:
        return recurrence, habits_per_period
    if repeat == "daily":
        return "FREQ=DAILY", ""
    if repeat == "days":
        days = [d for d in _WEEKDAY_ORDER if isinstance(habit_days, list) and d in habit_days]
        return ("FREQ=WEEKLY;BYDAY=" + ",".join(days)) if days else "FREQ=DAILY", ""
    if repeat == "week":
        return "FREQ=WEEKLY", times_week if isinstance(times_week, str) else habits_per_period
    if repeat == "month":
        return "FREQ=MONTHLY", times_month if isinstance(times_month, str) else habits_per_period
    return recurrence, habits_per_period


def _apply_habit_goal(goal, target_per_day):
    """The form's "Daily goal": "once" is a plain check-off
        (target 1) whatever the hidden Amount box holds; "amount" keeps the
        typed number (1 or blank falls back to 1 downstream).
    """
    if isinstance(goal, str) and goal == "once":
        return "1"
    return target_per_day


def _save_habit_look(conn, uid: str, icon, color) -> None:
    icon = icon if isinstance(icon, str) and icon in habit_view.habit_icon_choices() else None
    color = color if isinstance(color, str) and color in habit_view.HABIT_COLORS else None
    db.set_task_habit_look(conn, uid, icon, color)


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
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    habits_per_period: str | None = Form(None),
    habit_days: list[str] = Form([]),
    habit_days_present: str = Form(""),
    habit_repeat: str | None = Form(None),
    habit_times_week: str | None = Form(None),
    habit_times_month: str | None = Form(None),
    habit_goal: str | None = Form(None),
    habit_kind: str | None = Form(None),
    habit_unit: str | None = Form(None),
    is_habit: str = Form(""),
    reminder_time: str | None = Form(None),
    habit_icon: str | None = Form(None),
    habit_color: str | None = Form(None),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    contacts: list[str] = Form([]),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    error = validation.task_error(title, start_at, due_at, status, STATUSES)
    if error:
        return validation_response(error, x_requested_with, "/tasks")
    if item_tags_field == "1":
        tags_labels = tag_store.labels_of(conn, item_tags)
    tags = dashboard_router._combine_tags(tags, tags_labels)
    tags = dashboard_router._with_project(conn, tags, project, project_field)
    recurrence, habits_per_period = _apply_habit_repeat(
        habit_repeat, recurrence, habit_days, habits_per_period, habit_times_week, habit_times_month
    )
    target_per_day = _apply_habit_goal(habit_goal, target_per_day)
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
    if not isinstance(holiday_calendar, str):
        holiday_calendar = ""
    if not isinstance(exclude_saturday, str):
        exclude_saturday = ""
    if not isinstance(exclude_sunday, str):
        exclude_sunday = ""
    now = clock.now().isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "due_at": due_at or None,
        "start_at": start_at or clock.today().isoformat(),
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
        "is_habit": is_habit in ("1", "true", "on"),
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
    if item_tags_field == "1":
        tag_store.record(conn, "task", row["uid"], item_tags)
    if isinstance(reminder_time, str):
        db.set_task_reminder_time(conn, row["uid"], reminder_time)
    if isinstance(habit_icon, str) or isinstance(habit_color, str):
        _save_habit_look(conn, row["uid"], habit_icon, habit_color)
    if isinstance(contacts, list):
        db.set_object_contacts(conn, "task", row["uid"], db.resolve_contact_entries(conn, contacts))
    return respond(x_requested_with, "/tasks", status_code=201, uid=row["uid"])


BULK_RECURRENCE = {
    "none": "Does not repeat",
    "FREQ=DAILY": "Daily",
    "FREQ=WEEKLY": "Weekly",
    "FREQ=MONTHLY": "Monthly",
    "FREQ=YEARLY": "Yearly",
}


def _label_options(conn):
    return [(i["name"], i["name"]) for i in tag_store.picker(conn, "task", "", [])["items"]]


@router.get("/bulk-edit-modal")
def bulk_edit_modal(uids: str, request: Request, conn=Depends(get_db)):
    """Bulk-select "Edit": one modal that sets the same value on every selected task."""
    labels = _label_options(conn)
    fields = [
        {"name": "status", "label": "Status", "kind": "select", "options": [(k, STATUS_LABELS[k]) for k in STATUSES]},
        {"name": "start_at", "label": "Start date", "kind": "date"},
        {"name": "due_at", "label": "Due date", "kind": "date"},
        {"name": "recurrence", "label": "Repeats", "kind": "select", "options": list(BULK_RECURRENCE.items())},
        {"name": "add_tag", "label": "Add tag", "kind": "select", "options": labels},
        {"name": "remove_tag", "label": "Remove tag", "kind": "select", "options": labels},
    ]
    return templates.TemplateResponse(
        "bulk_edit_modal.html",
        {"request": request, "uids": [u for u in uids.split(",") if u], "noun": "task", "fields": fields,
         "post_url": "/tasks/bulk-edit", "change_type": "task", "back_url": "/tasks"},
    )


@router.post("/bulk-edit")
def bulk_edit(
    uids: list[str] = Form([]),
    status: str = Form(""),
    start_at: str = Form(""),
    due_at: str = Form(""),
    recurrence: str = Form(""),
    add_tag: str = Form(""),
    remove_tag: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    if status and status not in STATUSES:
        raise HTTPException(400, f"invalid status '{status}'")
    for uid in uids:
        row = db.get_task(conn, uid)
        if row is None:
            continue
        if status:
            row["status"] = status
            row["progress"] = _progress_for_status(status)
        if start_at:
            row["start_at"] = start_at
        if due_at:
            row["due_at"] = due_at
        if recurrence in BULK_RECURRENCE:
            row["recurrence"] = None if recurrence == "none" else recurrence
        if add_tag or remove_tag:
            row["tags"] = sorted(tag_store.bulk_change(conn, "task", uid, row.get("tags") or [], [add_tag], [remove_tag]))
        row["updated_at"] = clock.now().isoformat()
        try:
            db.upsert_task(conn, row)
        except db.MultipleProjectLabelsError as exc:
            raise HTTPException(400, f"{row.get('title') or uid}: {exc}")
    return respond(x_requested_with, "/tasks", count=len(uids))


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
            row["updated_at"] = clock.now().isoformat()
            db.upsert_task(conn, row)
        return JSONResponse({"ok": True, "count": len(uids)})

    if action == "tag":
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
            row["tags"] = sorted(tag_store.bulk_change(
                conn, "task", uid, row.get("tags") or [],
                tags_to_apply if mode == "add" else [], tags_to_apply if mode == "remove" else []))
            row["updated_at"] = clock.now().isoformat()
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
        habit_task_detail.html templates instead of the generic task_form.
        html/task_detail.html every other task uses.
    """
    if not task:
        return False
    return bool(task.get("is_habit"))


@router.get("/{uid}/edit")
def edit_task_form(uid: str, request: Request, conn=Depends(get_db)):
    task = db.get_task(conn, uid)
    if _is_habit_task(conn, task):
        return templates.TemplateResponse(
            "habit_task_form.html",
            {
                "request": request,
                "active_tab": "tasks",
                "task": task,
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
            **db.project_picker_context(conn),
            # Work sessions card (1.4) -- see _work_allocation_context above.
            **_work_allocation_context(conn, task),
            **_pending_transaction_context(conn, task),
            # Fallback only -- every task has a real start_at since
            # create_task always sets one now, this just covers a legacy
            # row from before that was true.
            "today": clock.today().isoformat(),
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
        completion_rows = db.list_task_completions(conn, uid)
        completions = {c["due_date"]: "x" for c in completion_rows}
        excluded = _excluded_dates_for_row(conn, task, completions, clock.today())
        pinfo = habit_view.pause_info(db.list_habit_pauses(conn), uid, clock.today())
        stats = habit_view.stats_for_task(
            task, {c["due_date"]: c.get("value") or 1 for c in completion_rows}, excluded, paused=pinfo["dates"]
        )
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
        rows = db.list_task_completions(conn, uid)
        week_start = db.get_app_meta(conn, habit_view.WEEK_START_KEY) or "monday"
        ctx["completion_weeks"] = habit_heatmap.heatmap_weeks(
            {r["due_date"]: r.get("value") or 0 for r in rows},
            task.get("target_per_day") or 1,
            habit_heatmap.DETAIL_WEEKS,
            week_start=week_start,
        )
        ctx["habit_periods"] = habit_view.history(conn, task, week_start=week_start)["periods"]
        ctx["habit_look"] = habit_view.habit_look(task)
        ctx["habit_notes"] = habit_view.recent_notes(rows)
        return templates.TemplateResponse("habit_task_detail.html", ctx)
    return templates.TemplateResponse("task_detail.html", ctx)


@router.post("/{uid}")
def update_task(
    uid: str,
    title: str = Form(...),
    description: str = Form(""),
    due_at: str = Form(""),
    start_at: str = Form(""),
    status: str | None = Form(None),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    item_tags: list[str] = Form([]),
    item_tags_field: str = Form(""),
    project: str = Form(""),
    project_field: str = Form(""),
    recurrence: str = Form(""),
    target_per_day: str = Form("1"),
    habits_per_period: str | None = Form(None),
    habit_days: list[str] = Form([]),
    habit_days_present: str = Form(""),
    habit_repeat: str | None = Form(None),
    habit_times_week: str | None = Form(None),
    habit_times_month: str | None = Form(None),
    habit_goal: str | None = Form(None),
    habit_kind: str | None = Form(None),
    habit_unit: str | None = Form(None),
    is_habit: str = Form(""),
    reminder_time: str | None = Form(None),
    habit_icon: str | None = Form(None),
    habit_color: str | None = Form(None),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    contacts: list[str] = Form([]),
    contacts_present: str = Form(""),
    work_sessions_present: str = Form(""),
    links_present: str = Form(""),
    linked_event_uids: list[str] = Form([]),
    ws_uid: list[str] = Form([]),
    ws_title: list[str] = Form([]),
    ws_hours: list[str] = Form([]),
    ws_difficulty: list[str] = Form([]),
    ws_start: list[str] = Form([]),
    ws_end: list[str] = Form([]),
    pending_tx_present: str = Form(""),
    pt_key: list[str] = Form([]),
    pt_uid: list[str] = Form([]),
    pt_type: list[str] = Form([]),
    pt_amount: list[str] = Form([]),
    pt_description: list[str] = Form([]),
    pt_account: list[str] = Form([]),
    pt_to_account: list[str] = Form([]),
    pt_date: list[str] = Form([]),
    pending_tags=Depends(_pending_tag_values),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    error = validation.task_error(title, start_at, due_at, status, STATUSES)
    if error:
        return validation_response(error, x_requested_with, f"/tasks/{uid}/edit")
    pending_rows = None
    if pending_tx_present == "1":
        pending_rows = _pending_transaction_rows(
            conn, pt_key, pt_uid, pt_type, pt_amount, pt_description, pt_account, pt_to_account, pt_date,
            pending_tags if isinstance(pending_tags, dict) else {})
        for pending in pending_rows:
            _, error = finance.validate_scheduled(conn, {**pending, "task_uid": uid})
            if error:
                if x_requested_with == "fetch":
                    return JSONResponse({"detail": [{"loc": ["body", error["field"]], "msg": error["message"]}]}, status_code=422)
                return RedirectResponse(url=f"/tasks/{uid}/edit?error={quote(error['message'])}", status_code=303)
    if item_tags_field == "1":
        tags_labels = tag_store.labels_of(conn, item_tags)
    tags = dashboard_router._combine_tags(tags, tags_labels)
    tags = dashboard_router._with_project(conn, tags, project, project_field)
    recurrence, habits_per_period = _apply_habit_repeat(
        habit_repeat, recurrence, habit_days, habits_per_period, habit_times_week, habit_times_month
    )
    target_per_day = _apply_habit_goal(habit_goal, target_per_day)
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
    if existing and university_plan.is_locked(conn, "task", uid):  # an exam: title and description are the module's
        title, description = existing.get("title") or title, existing.get("description") or ""
    # `isinstance`, not `is None` -- a direct (non-HTTP) router call in a
    # test that omits `status` entirely gets FastAPI's raw `Form(None)`
    # marker object here, not a literal `None` (same guard shape
    # `_safe_next`'s own docstring documents for an omitted `next`).
    if not isinstance(status, str):
        status = existing.get("status") or "active"
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
            "holiday_calendar": holiday_calendar or None,
            "exclude_saturday": exclude_saturday in ("1", "true", "on"),
            "exclude_sunday": exclude_sunday in ("1", "true", "on"),
            "updated_at": clock.now().isoformat(),
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
    if is_habit in ("1", "true", "on"):
        row["is_habit"] = 1
    try:
        db.upsert_task(conn, row)
    except db.MultipleProjectLabelsError as exc:
        raise HTTPException(400, str(exc))
    if item_tags_field == "1":
        tag_store.record(conn, "task", row["uid"], item_tags)
    # Per-habit reminder time -- same "only the habit form sends it" rule.
    if isinstance(reminder_time, str):
        db.set_task_reminder_time(conn, row["uid"], reminder_time)
    if isinstance(habit_icon, str) or isinstance(habit_color, str):
        _save_habit_look(conn, row["uid"], habit_icon, habit_color)
    if contacts_present == "1" and isinstance(contacts, list):
        db.set_object_contacts(conn, "task", row["uid"], db.resolve_contact_entries(conn, contacts))
    if links_present == "1":
        db.sync_task_links(conn, row["uid"], linked_event_uids)
    if work_sessions_present == "1":
        db.sync_work_sessions(conn, row["uid"], _work_session_rows(ws_uid, ws_title, ws_hours, ws_difficulty, ws_start, ws_end))
    if pending_rows is not None:
        finance.sync_task_rows(conn, row["uid"], pending_rows)
    return respond(x_requested_with, "/tasks")


def _work_session_rows(uids, titles, hours, difficulties, starts, ends) -> list[dict]:
    """Zip the edit form's parallel ws_* arrays back into one dict per session row."""
    columns = [list(c) for c in (uids, titles, hours, difficulties, starts, ends)]
    rows = []
    for uid, title, hrs, difficulty, start, end in zip(*columns):
        rows.append(
            {"uid": uid, "title": title, "hours": hrs, "difficulty": difficulty.lower(), "start": start, "end": end}
        )
    return rows


_UPDATABLE_FIELDS = {"status", "due_at", "title"}


@router.post("/{uid}/update-field")
async def update_field(uid: str, request: Request, conn=Depends(get_db)):
    """Single-field inline edit, used by the Table view's click-to-edit
        pills/date cells. Deliberately a JSON body, not a Form -- this is
        only ever called from tasks_table.js via fetch(), never from a plain
        HTML form/no-JS fallback, unlike every other route in this router.
    """
    payload = await request.json()
    field = payload.get("field")
    value = payload.get("value")
    if field not in _UPDATABLE_FIELDS:
        return JSONResponse({"error": f"field '{field}' is not inline-editable"}, status_code=400)
    existing = db.get_task(conn, uid)
    if existing is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    if field in ("title", "description") and university_plan.is_locked(conn, "task", uid):
        return JSONResponse({"error": "This exam is edited in the University settings"}, status_code=400)
    error = validation.task_error(
        value if field == "title" else "x", existing.get("start_at"), value if field == "due_at" else None,
        value if field == "status" else None, STATUSES,
    )
    if error:
        return JSONResponse({"error": error["message"]}, status_code=400)
    row = dict(existing)
    if field == "due_at":
        row["due_at"] = value or None
    elif field == "status":
        row["status"] = value
        row["progress"] = _progress_for_status(value)
    else:  # title
        if not isinstance(value, str) or not value.strip():
            return JSONResponse({"error": "title cannot be blank"}, status_code=400)
        row["title"] = value.strip()
    row["updated_at"] = clock.now().isoformat()
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
            db.upsert_task_completion(conn, uid, clock.today().isoformat(), clock.now().isoformat())
    return respond(x_requested_with, "/tasks")


@router.post("/{uid}/archive")
def archive_task(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """Item 19: a plain task can
        already reach "archived" through its own Status dropdown
        (STATUSES/status_labels above already list it) -- this is a dedicated
        action for the one caller that has NO status dropdown at all,
        habit_task_form.html's Archive button ("habits should not have in
        their edit modal... a status dropdown" -- see that template's own
        header comment on why this exists as a separate button instead). Same
        `dict(existing) + one field + upsert_task` shape complete_task above
        already uses. update_task's own `status` default now falls back to
        whatever's already on the row (see that route's own comment) instead
        of hardcoding "active", so a later plain Save on this same habit
        doesn't silently undo this.
    """
    row = db.get_task(conn, uid)
    if row:
        row["status"] = "archived"
        row["progress"] = _progress_for_status("archived")
        db.upsert_task(conn, row)
    return respond(x_requested_with, "/tasks")


@router.post("/{uid}/unarchive")
def unarchive_task(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """The Restore counterpart -- routers/habits.py's Archived habits
    modal is the one place this is reachable from today (an archived
    habit drops off the main Habits list entirely, habit_view.habit_
    items' own `_INACTIVE_STATUSES` filter, so there's nothing on the
    normal page to click Restore from)."""
    row = db.get_task(conn, uid)
    if row:
        row["status"] = "active"
        row["progress"] = _progress_for_status("active")
        db.upsert_task(conn, row)
    return respond(x_requested_with, "/tasks")


def _completion_heatmap_weeks(
    completions: dict[str, str], weeks: int = habit_heatmap.DETAIL_WEEKS, today: date | None = None
) -> list[list[dict]]:
    """Monday-aligned grid of `weeks` columns x 7 rows ending on `today`,
        same shape habits' _heatmap_weeks produces (so the shared
        _habit_heatmap.html macro can paint it). A present date is "full"
        (level 4 -- there's no target-per-day concept for task check-offs);
        future days render blank/non-interactive (level -1).
    """
    today = today or clock.today()
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
    """
    try:
        if date.fromisoformat(completion_date) > clock.today():
            return JSONResponse({"error": "Can't log a day in the future."}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid date."}, status_code=400)
    if db.get_task_completion(conn, uid, completion_date) is not None:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(
            conn, uid, completion_date, clock.now().isoformat()
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
    """
    try:
        if date.fromisoformat(completion_date) > clock.today():
            return JSONResponse({"error": "Can't log a day in the future."}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid date."}, status_code=400)
    if not isinstance(note, str):
        note = None
    elif note is not None:
        note = note.strip()[:500]
    try:
        parsed_value = float(value) if value else None
    except ValueError:
        parsed_value = 1.0
    if parsed_value is None:
        existing = db.get_task_completion(conn, uid, completion_date)
        if existing and (existing.get("value") or 0) > 0:
            parsed_value = float(existing["value"])
        else:
            task_row = db.get_task(conn, uid) or {}
            parsed_value = float(task_row.get("target_per_day") or 1)
    if parsed_value > _MAX_HABIT_VALUE:
        parsed_value = _MAX_HABIT_VALUE
    if parsed_value <= 0:
        db.delete_task_completion(conn, uid, completion_date)
    else:
        db.upsert_task_completion(
            conn, uid, completion_date, clock.now().isoformat(), parsed_value, note
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
    x_requested_with: str | None = Header(default=None),
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
        empty and returns to the task.
    """
    task = db.get_task(conn, uid)
    if task is not None:
        if start_at and end_at and end_at > start_at:
            db.create_work_allocation(conn, uid, start_at, end_at)
        elif not (start_at or end_at):
            db.create_work_allocation(conn, uid)  # undated session placeholder
    return respond(x_requested_with, _safe_next(next) or f"/tasks/{uid}")


@router.post("/{uid}/work-allocations/remove-latest")
def remove_latest_work_allocation(
    uid: str,
    next: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """The planning grids' "Unscheduled work" panel "−" button -- remove the
        task's most recently added UNDATED work session, so it undoes the
        panel's own "+" without ever touching an already-scheduled block (see
        `db.remove_latest_work_allocation`'s own docstring). No-ops if the task
        has no undated sessions left to remove, even if it has dated ones; never
        touches the task. `next`, when present, is the planning page to return
        to (same-origin path only, see `_safe_next`).
    """
    db.remove_latest_work_allocation(conn, uid)
    return respond(x_requested_with, _safe_next(next) or f"/tasks/{uid}")


