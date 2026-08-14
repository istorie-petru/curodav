"""Dashboard (Phase 8 of the projects/tags rework): a customizable,
extensible, widget-based landing page. Each widget is a row in
`dashboard_widgets` (type + filters + position) rendered by looking its
`type` up in `WIDGET_TYPES` below -- adding a new widget type later means
adding a new registry entry and render function, not touching the
add/edit/reorder/delete machinery, the template dispatch, or any existing
widget's code. That's what "extensible" means concretely here, not just
an adjective.

Every widget type shares the same filter vocabulary (project, tags, task
lists, calendars), even though not every widget uses every filter --
`upcoming_events` ignores `task_list_uids`, for instance. Filtering is
applied by `_passes_filters` against the *list/calendar a task or event
belongs to* resolving to a project via the same `project_uid` columns
Phase 4 wired up -- there's no per-task/per-event project field, a task's
"project" is always inherited from its list.
"""

from __future__ import annotations

import calendar as py_calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, derived_state
from ..deps import get_db, templates

router = APIRouter(tags=["dashboard"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_between(start_at: str | None, end_at: str | None) -> float:
    """Local copy of db._hours_between's trivial duration math -- same
    "not worth exposing db's private helper across module boundaries for
    one two-line calculation" reasoning routers/today.py's own copy used
    (that module is retired -- 1.9 side work, "Today folded into the
    Dashboard" -- this is where the calculation now lives)."""
    if not start_at or not end_at:
        return 0.0
    try:
        start = datetime.fromisoformat(start_at)
        end = datetime.fromisoformat(end_at)
    except ValueError:
        return 0.0
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _combine_tags(tags: str, tags_labels: list[str]) -> str:
    """(2026-08-07, modal-input-design Phase A) -- the widget builder/
    Filters form's Labels field is now a chip multiselect (checkboxes
    named `tags_labels`, one per known label name -- see
    _widget_list_multiselect.html's reuse in _widget_builder_fields.html/
    _widget_edit_form.html) instead of a free-text `tags` input. Rather
    than reshape `_config_from_form`/`_tags_list`'s str-in contract (which
    every caller below still posts, including any stale/no-JS form and
    every existing test that calls add_widget/edit_widget directly with
    tags="a, b"), this folds the two sources back into that same
    comma-separated string before _config_from_form ever sees it -- the
    stored config["tags"] shape is completely unchanged. `tags` stays
    first so a hidden carry-forward value (e.g. _widget_edit_form.html's
    hidden `tags` field for a Project-filter uid that isn't a pickable
    label) keeps its relative position; duplicates are harmless, dedup
    already happens in _config_from_form's project_uid append and
    _passes_filters treats tags as a set. `tags_labels` is defensively
    coerced to a list -- every test in this suite that predates this
    field calls add_widget/edit_widget/preview_widget as a plain Python
    function (bypassing FastAPI's request parsing) without passing it, so
    the parameter's own `Form([])` default -- a FastAPI marker object, not
    an actual empty list, outside of real request handling -- would
    otherwise blow up every one of those pre-existing calls."""
    if not isinstance(tags_labels, list):
        tags_labels = []
    parts = _tags_list(tags) if tags else []
    parts.extend(t.strip() for t in tags_labels if t and t.strip())
    return ",".join(parts)


# One-time default for the optional "Your name" Settings field: absent =
# no name, greeting reads "Good evening" alone rather than "Good evening,
# None". App-meta-backed (see routers/settings.py's own field for this).
DISPLAY_NAME_KEY = "dashboard_display_name"


def _greeting_for_hour(hour: int, display_name: str | None = None) -> str:
    """Time-of-day greeting (dashboard usability rework, 2026-08-07 --
    "Make the header more dynamic like Hello x, Evening, like claude web
    has"). Takes the hour as a plain int rather than reading
    `datetime.now()` itself so it's directly testable with fixed hour
    values, no time-freezing needed -- same "compute from an explicit
    param, not a hidden clock read" shape `_render_mini_month_calendar`'s
    `nav` param already uses for its own "what month" question. The real
    caller (dashboard_view below) passes `datetime.now().hour` -- local
    server time, the same convention `date.today()` already uses
    everywhere else in this app for "today" (no separate timezone
    handling introduced here)."""
    if hour < 12:
        base = "Good morning"
    elif hour < 18:
        base = "Good afternoon"
    else:
        base = "Good evening"
    return f"{base}, {display_name}" if display_name else base


# --------------------------------------------------------------------- #
# Filtering -- shared by every widget type that reads tasks/events.
# --------------------------------------------------------------------- #


def _effective_tags_filter(conn, config: dict) -> list[str]:
    """The *actual* tag filter a widget's config resolves to, folding in
    `config["label_name"]` (a label page's own page-scope identity) the
    same way `_render_contact_list`/`_render_habit_checkin`/
    `_render_project_preview` already each did inline, independently, for
    their own item types -- a Space label pools its child labels' names in
    (db.list_child_labels, direct assignment only), a plain label folds
    itself in directly. This is the one shared place that translation now
    lives; every filterer below should go through this rather than reading
    `config["tags"]`/`config["label_name"]` separately.

    2026-08-07 bug fix: `_passes_filters` (used by `_filtered_tasks`/
    `_filtered_events`, which back `_render_today_agenda`,
    `_render_weekly_overview`, `_render_overdue_tasks`,
    `_render_upcoming_events`, `_render_mini_month_calendar`,
    `_render_calendar_agenda`) never called this translation at all before
    today -- it only ever looked at `config["tags"]`. A Space/Project
    page's widgets ARE seeded with `config["label_name"]` set (see
    `_ensure_default_label_widgets`), so every one of those widget types
    was silently unscoped on a label page: a Project's "Today's Agenda"
    showed every task due today across the *entire* app, not just that
    project's own tasks, because nothing ever translated `label_name` into
    a tag filter for the tasks/events path. Pre-existing bug, not
    introduced here -- see features/dashboard.md's follow-up
    notes for the finding."""
    tags_filter = list(config.get("tags") or [])
    label_name = config.get("label_name")
    if label_name:
        cfg = db.get_label_config(conn, label_name)
        if cfg and cfg.get("generate_space"):
            child_names = {c["name"] for c in db.list_child_labels(conn, label_name)}
            tags_filter = list(set(tags_filter) | child_names)
        else:
            tags_filter = list(set(tags_filter) | {label_name})
    return tags_filter


def _passes_filters(item_tags: list[str], tags_filter: list[str]) -> bool:
    """Phase 1 (label-space rework, 2026-08-06) dropped `task_lists`/
    `calendars` -- the project/space/list filters below used to resolve
    through a task's/event's collection membership (`list_path`/
    `calendar_path`, both gone -- see db.py's Phase 1 comments), so only
    the tags filter still applies here. Project/space filtering returns
    in Phase 2/3 as a label filter once object_labels is backfilled and
    routers/labels.py exists; any `project_uid`/`group_uid`/`list_uids`
    already saved in an old widget's config is now silently ignored
    rather than excluding everything. `tags_filter` is the already-
    resolved list from `_effective_tags_filter` (config["tags"] plus
    whatever `label_name` folds in), computed once per `_filtered_tasks`/
    `_filtered_events` call rather than per item."""
    if tags_filter and not (set(item_tags or []) & set(tags_filter)):
        return False
    return True


def _child_label_names(conn, config: dict) -> set[str] | None:
    """Phase 2 (label-space rework): the old `group_uid` config key pooled
    every project under a Space; a Space is just a label with
    generate_space=1 now, and its "projects" are labels whose parent_name
    points at it (db.list_child_labels) -- direct assignment only, same
    scoping list_child_labels already documents. `label_name` is the
    replacement config key (also doubles as the widget's own page-scope
    identity, see dashboard_widgets.label_name)."""
    label_name = config.get("label_name")
    if not label_name:
        return None
    return {c["name"] for c in db.list_child_labels(conn, label_name)}


def _filtered_tasks(conn, config: dict, open_only: bool = True) -> list[dict]:
    tags_filter = _effective_tags_filter(conn, config)
    tasks = db.list_tasks(conn)
    out = []
    for t in tasks:
        if open_only and t["status"] in ("done", "archived"):
            continue
        if not _passes_filters(t.get("tags"), tags_filter):
            continue
        out.append(t)
    return out


def _filtered_events(conn, config: dict, start: str | None = None, end: str | None = None) -> list[dict]:
    tags_filter = _effective_tags_filter(conn, config)
    events = db.list_events(conn, start=start, end=end)
    out = []
    for e in events:
        if not _passes_filters(e.get("tags"), tags_filter):
            continue
        out.append(e)
    return out


# --------------------------------------------------------------------- #
# Widget renderers -- each takes (conn, config) and returns a plain dict
# the widget's partial template renders. Registered below in WIDGET_TYPES.
# --------------------------------------------------------------------- #


def _render_today_agenda(conn, config: dict, nav: dict | None = None) -> dict:
    """Overdue + due-today tasks (open only), and today's events -- the
    single most common "what does today look like" view."""
    today = date.today().isoformat()
    tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and t["due_at"][:10] <= today]
    tasks.sort(key=lambda t: t["due_at"])
    events = [e for e in _filtered_events(conn, config) if e.get("start_at") and e["start_at"][:10] == today]
    events.sort(key=lambda e: e.get("start_at") or "")
    return {"tasks": tasks, "events": events, "today": today}


def _render_weekly_overview(conn, config: dict, nav: dict | None = None) -> dict:
    """The next N days (including today), tasks and events grouped by
    date -- a day-by-day breakdown rather than agenda's single-day focus
    or a flat list. N defaults to 7 (the original "weekly" overview) but
    is itself a config knob now (`range_days`, 2026-08-02's Source/View/
    Range rework -- see WIDGET_RANGES below) so the same day-grouped
    rendering serves both a "next 7 days" and a "next 30 days" widget."""
    range_days = int(config.get("range_days") or 7)
    today = date.today()
    end = today + timedelta(days=range_days - 1)
    days = [(today + timedelta(days=i)) for i in range(range_days)]

    tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and today.isoformat() <= t["due_at"][:10] <= end.isoformat()]
    events = _filtered_events(conn, config, start=f"{today.isoformat()}T00:00:00", end=f"{end.isoformat()}T23:59:59")

    by_day = []
    for d in days:
        iso = d.isoformat()
        day_tasks = sorted(
            [t for t in tasks if t["due_at"][:10] == iso],
            key=lambda t: (-(t.get("importance") or 0), -(t.get("urgency") or 0)),
        )
        day_events = sorted([e for e in events if e.get("start_at") and e["start_at"][:10] == iso], key=lambda e: e.get("start_at") or "")
        by_day.append({"date": iso, "label": d.strftime("%a %b %d"), "is_today": iso == today.isoformat(), "tasks": day_tasks, "events": day_events})
    return {"days": by_day}


def _render_upcoming_events(conn, config: dict, nav: dict | None = None) -> dict:
    """The next events from right now onward, chronological, optionally
    bounded to `range_days` out (2026-08-02's Source/View/Range rework --
    unset/None means the original unbounded "just take the next `limit`
    events, however far out" behavior). `limit` still caps the list
    either way, so a widget can be a short "what's next" strip or a
    longer look-ahead within whatever range it's scoped to."""
    limit = int(config.get("limit") or 10)
    range_days = config.get("range_days")
    now_iso = datetime.now(timezone.utc).isoformat()
    end_iso = None
    if range_days:
        end_iso = f"{(date.today() + timedelta(days=int(range_days))).isoformat()}T23:59:59"
    # db.list_events' own `start` filter is "(end_at IS NULL OR end_at >=
    # start)" -- deliberately permissive so an ongoing/no-end-date event
    # doesn't disappear from a filtered range it's still "within". That's
    # the right behavior for a calendar view, but wrong for "upcoming":
    # an event that already started (no end date) shouldn't count as
    # upcoming just because it has no end. Filter on start_at explicitly
    # here rather than relying on list_events' own start param alone.
    events = [
        e
        for e in _filtered_events(conn, config, start=now_iso, end=end_iso)
        if e.get("start_at") and e["start_at"] >= now_iso
    ]
    events.sort(key=lambda e: e.get("start_at") or "")
    return {"events": events[:limit]}


def _render_overdue_tasks(conn, config: dict, nav: dict | None = None) -> dict:
    """Bonus widget beyond the three explicitly named ones, proving the
    registry is genuinely extensible and not just three hardcoded
    branches -- open tasks whose due date has passed, most-overdue first."""
    today = date.today().isoformat()
    tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and t["due_at"][:10] < today]
    tasks.sort(key=lambda t: t["due_at"])
    return {"tasks": tasks, "today": today}


def _render_at_a_glance(conn, config: dict, nav: dict | None = None) -> dict:
    """At-a-glance stats strip (dashboard usability rework, 2026-08-07) --
    counts over the exact same open-tasks pool `_render_overdue_tasks`/
    `_render_today_agenda`/`_render_weekly_overview` already query (via
    `_filtered_tasks`, so this is correctly scoped to a label page now that
    the `_effective_tags_filter` fix applies there too): Overdue, Due
    today, Due this week, plus (1.1) Important and Urgent. Every widget
    type here renders a *list*; this is the one that renders a *number*, so
    "how am I doing" is answerable in under two seconds without reading
    through any other widget's content.

    Zero counts still render (not hidden/suppressed) -- confirming
    "nothing's overdue" is itself useful information for an at-a-glance
    widget, not an empty state to hide.

    The counts come from src/derived_state.py's shared aggregation service
    (1.1, plans/open-priority.md § Virtual & derived states): ONE pass over
    the scoped pool computing every per-state count through `count_by_state`
    -- state names match routers/tasks.py's DATE_FILTERS, so "3 overdue" is
    a real, already-filtered destination (`?date_filter=overdue`, plus
    `&label={label_name}` when scoped to a label page), not a number you
    have to go re-derive yourself, and the count and the filter view can
    never disagree."""
    tasks = _filtered_tasks(conn, config)
    label_rules = db.list_label_rules(conn)
    counts = derived_state.count_by_state(tasks, label_rules)

    label_name = config.get("label_name")

    def _tasks_link(date_filter: str) -> str:
        url = f"/tasks?date_filter={date_filter}"
        if label_name:
            url += f"&label={label_name}"
        return url

    return {
        "overdue_count": counts["overdue"],
        "today_count": counts["today"],
        "week_count": counts["this_week"],
        "important_count": counts["important"],
        "urgent_count": counts["urgent"],
        "overdue_link": _tasks_link("overdue"),
        "today_link": _tasks_link("today"),
        "week_link": _tasks_link("this_week"),
        "important_link": _tasks_link("important"),
        "urgent_link": _tasks_link("urgent"),
    }


def _render_mini_month_calendar(conn, config: dict, nav: dict | None = None) -> dict:
    """Small month-at-a-glance -- day numbers and a plain busy/not-busy
    dot, current day highlighted, no drag-create or event chips (that's
    what the real Calendar page is for). Same Monday-first grid math as
    routers/calendar.py's month view (`py_calendar.Calendar
    (firstweekday=0)`), so it reads as the same calendar, just smaller.
    Defaults to half-width (see WIDGET_TYPES/WIDGET_WIDTHS below) so it
    sits next to Today's Agenda out of the box, but that's just a
    starting point -- each widget's own width is user-editable now, not
    hardcoded per type.

    `nav` (year/month) lets the Dashboard's own ?cal_year=&cal_month=
    query params (dashboard_view below) page this forward/back, same
    prev/next convention routers/calendar.py's month_view already uses --
    plain full-page links, no JS required. Defaults to the real today's
    month when nav is absent (first load, or any other widget type)."""
    today = date.today()
    year = (nav or {}).get("year") or today.year
    month = (nav or {}).get("month") or today.month
    cal = py_calendar.Calendar(firstweekday=0)
    weeks_raw = cal.monthdatescalendar(year, month)
    month_start = weeks_raw[0][0].isoformat()
    month_end = weeks_raw[-1][-1].isoformat()

    tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and month_start <= t["due_at"][:10] <= month_end]
    events = _filtered_events(conn, config, start=f"{month_start}T00:00:00", end=f"{month_end}T23:59:59")
    busy_days = {t["due_at"][:10] for t in tasks} | {e["start_at"][:10] for e in events if e.get("start_at")}

    today_iso = today.isoformat()
    weeks = [
        [
            {
                "date": d.isoformat(),
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d.isoformat() == today_iso,
                "has_activity": d.isoformat() in busy_days,
            }
            for d in week
        ]
        for week in weeks_raw
    ]
    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)
    return {
        "weeks": weeks,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    }


def _render_project_preview(conn, config: dict, nav: dict | None = None) -> dict:
    """Quick links/progress for one label's page's child labels
    (config["label_name"] set and that label has children -- the former
    "a Space's own projects" preview) or every plain (non-Space) label
    (unset) -- the Dashboard-side half of Projects' management living in
    Settings: the *content* still belongs on the Dashboard, as a
    lighter-weight preview. Progress is derived from direct object_labels
    membership (tasks tagged with that label) -- direct assignment only,
    same "not transitive through parent_name" rule every label-page query
    in this app follows."""
    label_name = config.get("label_name")
    if label_name:
        labels = db.list_child_labels(conn, label_name)
    else:
        labels = [lbl for lbl in db.list_labels(conn) if not lbl.get("generate_space")]

    previews = []
    for lbl in labels:
        tasks = [t for t in db.list_tasks(conn) if lbl["name"] in (t.get("tags") or [])]
        total = len(tasks)
        done = len([t for t in tasks if t["status"] in ("done", "archived")])
        progress = round(100 * done / total) if total else None
        previews.append({"project": lbl, "progress": progress, "tasks_done": done, "tasks_total": total})
    return {"previews": previews}


def _render_filled_cards(conn, config: dict, nav: dict | None = None) -> dict:
    """Filled cards widget -- Material You style filled rounded squares
    for each Space (a label with generate_space=1), with the Space's
    color as the fill, showing the name and description. Each card is a
    link to the Space's generated page (/labels/{name})."""
    cards = []
    for lbl in db.list_space_labels(conn):
        children = db.list_child_labels(conn, lbl["name"])
        cards.append({
            "uid": lbl["name"],
            "name": lbl["name"],
            "color": lbl.get("color") or "blue",
            "description": lbl.get("description") or "",
            "project_count": len(children),
        })
    return {"cards": cards}


def _render_calendar_agenda(conn, config: dict, nav: dict | None = None) -> dict:
    """Combined Calendar+Agenda widget -- the mini month calendar on top
    and a 7-day day-by-day agenda below it, both scoped by the same config
    (group_uid, project_uid, tags, etc.). Designed to sit at a third width
    (2 of 6 columns) next to a Today's Agenda at two-thirds, giving a
    compact "where am I this month / what's this week" panel without
    needing two separate widgets stacked. The two sub-renders share the
    same config (filters apply to both calendar and tasks), same nav (month
    arrow links work the same way they do on the standalone mini calendar),
    and the same data shape as their standalone counterparts so the
    template can just delegate to the same rendering logic.

    2026-08-03 (§1 Dashboard / §2 Spaces v2 rework): new type added to
    the registry as "calendar_agenda", source "calendar_tasks", view
    "calendar_agenda_view", has_range False -- it doesn't expose a Range
    picker because the month is always the current month (nav-able via
    prev/next) and the agenda is always 7 days from today, same as the
    standalone weekly_overview default."""
    calendar_data = _render_mini_month_calendar(conn, config, nav)
    agenda_data = _render_weekly_overview(conn, {**config, "range_days": 7}, nav)
    return {"calendar": calendar_data, "agenda": agenda_data}


def _render_contact_list(conn, config: dict, nav: dict | None = None) -> dict:
    """Contacts filtered by tags -- tags that match project names in the
    space's group (or any tags explicitly set in config["tags"]). Designed
    for the Space widget grid where contacts are often tagged by project/
    course/organisation name (via the addressbook migration that tags every
    contact in a non-default book with that book's name).

    2026-08-03 (§2 Spaces v2): new widget type. Filtering is simpler than
    tasks/events because contacts don't belong to lists/calendars and have
    no project_uid path -- we filter on tags_json directly. With group_uid
    set (the default for Space widgets), we resolve the group's project
    names and treat them as extra tag filters, so a University space
    automatically shows contacts tagged "CS101", "MATH201", etc. Explicit
    config["tags"] filters stack on top of this (intersection, not union)
    if the user added their own tag filter via the Filters panel.

    Phase 2 (label-space rework): `group_uid`/`project_uid` collapsed to
    one `label_name` config key. With `label_name` set to a Space label,
    its child labels' names (db.list_child_labels) are folded in as
    implicit tag filters, same as before. With `label_name` set to a
    plain (non-Space) label, that label itself is the implicit filter --
    a Project page shows contacts tagged with its own label directly,
    the same "direct object_labels membership only" rule every label page
    in this app follows.

    2026-08-07: this inline label_name -> tags translation moved into the
    shared `_effective_tags_filter` (see its own docstring for why -- the
    same logic used to be duplicated here, in `_render_habit_checkin`, and
    in `_render_project_preview`, and was missing entirely from the
    tasks/events path). Behavior here is unchanged, just de-duplicated."""
    tags_filter = _effective_tags_filter(conn, config)

    contacts = db.list_contacts(conn)

    if tags_filter:
        tags_lower = {t.lower() for t in tags_filter}
        contacts = [
            c for c in contacts
            if any(tag.lower() in tags_lower for tag in (c.get("tags") or []))
        ]
    limit = int(config.get("limit") or 20)
    return {"contacts": contacts[:limit]}


def _render_habit_checkin(conn, config: dict, nav: dict | None = None) -> dict:
    """Check-off-today for every active habit, right on the Dashboard --
    the point of pulling Habits off the main topbar (2026-08-01): daily
    use ("did I do X today / how much of X today") shouldn't require a
    whole page, only editing/adding a habit's definition should (now in
    Settings). `target_per_day == 1` habits (the common case -- "did I
    read today") render as a plain checkbox via the existing toggle
    endpoint; `target_per_day > 1` ("8 glasses of water") render as a
    count + a "+1" button instead, since a checkbox can't express a
    partial amount. `next_value` is pre-computed here (not left to
    client-side JS) so the "+1" button is a plain no-JS form post to the
    existing /habits/{uid}/entries endpoint, same no-JS-required
    philosophy as the heatmap toggle cells it sits next to conceptually."""
    label_name = config.get("label_name")
    if label_name:
        cfg = db.get_label_config(conn, label_name)
        if cfg and cfg.get("generate_space"):
            # A Space's habits widget pools every habit under any of the
            # Space's child (project) labels -- same "pool every project
            # under it" behavior as _render_project_preview.
            child_names = _child_label_names(conn, config) or set()
            habits = [h for h in db.list_habits(conn) if h.get("project_uid") in child_names]
        else:
            habits = db.list_habits(conn, project_uid=label_name)
    else:
        habits = db.list_habits(conn)
    today_iso = date.today().isoformat()
    rows = []
    for h in habits:
        entry = db.get_habit_entry(conn, h["uid"], today_iso)
        current_value = entry["value"] if entry else 0
        rows.append(
            {
                "habit": h,
                "today": today_iso,
                "is_quantity": h["target_per_day"] > 1,
                "current_value": current_value,
                "done_today": current_value > 0,
                "next_value": current_value + 1,
            }
        )
    return {"rows": rows}


def _render_important_urgent(conn, config: dict, nav: dict | None = None) -> dict:
    """Important & Urgent -- open tasks whose derived_state.virtual_states
    includes "important"/"urgent" that aren't already overdue or due today
    (1.9 side work, porting routers/today.py's own "Important & urgent, not
    due today" section into the Dashboard's widget registry ahead of that
    page's retirement -- see plans/STATE.md). Reuses the exact same shared
    aggregation service (src/derived_state.py) /today already used, so this
    widget can never disagree with what /tasks?date_filter=important/urgent
    shows. Scoped like every other widget via `_filtered_tasks` (a Space/
    Project page's Important & Urgent widget only considers that page's own
    tasks), which /today itself never needed since it was always a whole-app
    view."""
    today = date.today()
    today_iso = today.isoformat()
    tasks = _filtered_tasks(conn, config)
    overdue_or_due_today = {
        t["uid"] for t in tasks if t.get("due_at") and t["due_at"][:10] <= today_iso
    }
    label_rules = db.list_label_rules(conn)
    # "rows", not "items" -- data is a plain dict, and Jinja's attribute-then-
    # item lookup (`data.items`) would silently resolve to dict.items (the
    # builtin method) instead of this key, since attribute lookup is tried
    # first. Found live while rendering this exact widget the first time.
    rows = []
    for t in tasks:
        if t["uid"] in overdue_or_due_today:
            continue
        states = derived_state.virtual_states(t, label_rules, today)
        if "important" in states or "urgent" in states:
            rows.append((t, states))
    rows.sort(
        key=lambda pair: (
            -derived_state.effective_importance(pair[0], label_rules),
            -derived_state.effective_urgency(pair[0], label_rules, today),
            pair[0].get("due_at") or "9999-99-99",
        )
    )
    limit = int(config.get("limit") or 8)
    return {"rows": rows[:limit]}


def _render_scheduled_work_today(conn, config: dict, nav: dict | None = None) -> dict:
    """Scheduled Work Hours Today -- today's work-allocation sessions plus a
    completed/total hours readout (1.9 side work, porting routers/today.py's
    own "scheduled hours today" computation, the other piece /today had that
    no existing widget covered -- see plans/STATE.md). Scoped like every
    other widget via `_filtered_events`."""
    today_iso = date.today().isoformat()
    events = _filtered_events(conn, config, start=f"{today_iso}T00:00:00", end=f"{today_iso}T23:59:59")
    events = [e for e in events if e.get("start_at") and e["start_at"][:10] == today_iso]
    sessions = []
    total_hours = 0.0
    for e in events:
        task_uid = db.work_allocation_task_uid(conn, e["uid"])
        if not task_uid:
            continue
        task = db.get_task(conn, task_uid)
        hours = _hours_between(e.get("start_at"), e.get("end_at"))
        sessions.append({"event": e, "task": task, "hours": hours})
        total_hours += hours
    sessions.sort(key=lambda w: w["event"].get("start_at") or "")
    return {"sessions": sessions, "total_hours": round(total_hours, 1), "today": today_iso}


def _render_quick_links(conn, config: dict, nav: dict | None = None) -> dict:
    """Quick Links -- a visual tile grid of every Space (generate_space=1)
    and every open (non-archived) project (is_project=1), each linking to
    its own page. The Dashboard's "more visual, less data-heavy" side work
    (1.9): the app has no separate "pinned"/"favorite" concept (label_config
    dropped `pinned` outright, see db.py's own SCHEMA_SQL comment) -- a
    curated-by-nature set of "every Space + every open project" is the v1,
    per plans/STATE.md's own note, no new schema needed. Uses each label's
    own `icon`/`color` (label_config.icon, the same `icon()` Jinja helper
    and `--cal-bg-<hue>` vars every other colored tile in this app already
    uses -- filled_cards/project_preview) rather than inventing a new visual
    language. Home-only (excluded on Space/Project pages, same as
    filled_cards/project_preview -- see _SCOPE_EXCLUDED_TYPES): "every Space
    + every project" is meaningless once you're already inside one of them."""
    # "tiles", not "items" -- see _render_important_urgent's own comment on
    # why a plain dict key named "items" is unsafe with Jinja's attribute
    # lookup.
    tiles = []
    for lbl in db.list_space_labels(conn):
        tiles.append({
            "name": lbl["name"], "href": f"/labels/{lbl['name']}",
            "icon": lbl.get("icon") or "layers", "color": lbl.get("color") or "blue",
            "kind": "Space",
        })
    for lbl in db.list_project_labels(conn):
        if lbl.get("archived_at"):
            continue
        tiles.append({
            "name": lbl["name"], "href": f"/projects/{lbl['name']}",
            "icon": lbl.get("icon") or "folder", "color": lbl.get("color") or "blue",
            "kind": "Project",
        })
    return {"tiles": tiles}


# Grid width -- there used to be a manual width picker/drag-resize here
# (a "half"/"full" flag on WIDGET_TYPES, then from 2026-08-01 a per-
# widget-instance override living in config["width"], picked from the
# Filters panel or dragged from the card's own resize handle), removed
# 2026-08-07 alongside the manual height picker/drag-resize, per the same
# direct feedback: automatic, content-driven sizing, no manual override.
# `_widget_width` below now always returns a widget's *type's* own
# `default_width` -- see WIDGET_TYPES -- which is the real "what does
# this content naturally need" signal (e.g. At a Glance is just three
# numbers, so it's a third; Weekly Overview is a 7-day-wide grid, so it's
# the full row). `span` is out of 6 (dashboard.html's grid-template-
# columns), chosen as the smallest common denominator for thirds AND
# halves without fractional spans; "two_thirds" is kept as a valid preset
# even though no WIDGET_TYPES entry currently defaults to it, since a
# stack's own config["width"] can still be any of these four keys.
WIDGET_WIDTHS: dict[str, dict] = {
    "third": {"label": "1/3 width", "span": 2},
    "half": {"label": "1/2 width", "span": 3},
    "two_thirds": {"label": "2/3 width", "span": 4},
    "full": {"label": "Full width", "span": 6},
}


def _widget_width(widget: dict, spec: dict | None) -> dict:
    """A widget's width is now always just its type's own `default_width`
    -- no per-instance override (removed 2026-08-07, same day and same
    reasoning as the manual height picker/drag-resize's removal above:
    "auto-fit by content", no manual third/half/two-thirds/full picker).
    The width dropdown on the widget builder form, the drag-to-resize
    handle, and edit_widget's width carry-through are all gone; creating
    or editing a widget can no longer set config["width"] at all.

    A stack (type="stack") has no WIDGET_TYPES entry -- it's not "content"
    of its own, just a container of 1+ other widgets grouped by a drag-
    onto-another-widget interaction -- so it has no `default_width` to
    fall back on. It keeps reading its own stored config["width"] instead,
    seeded once at creation time from whichever widget triggered the
    stack (stack_widget below) or from _DEFAULT_STACK_CONFIG for the
    seed-time Space/Project stack, and never written to again -- this is
    what lets every member of a stack share one width so they visually
    align in a single card (only the stack's own top-level card carries
    `data-span`; see _widget_workspace.html).

    Existing dashboards may still have a stale config["width"] sitting in
    a *non-stack* widget's config from before this change -- harmless,
    simply never read any more, same convention as other deprecated
    config fields elsewhere in this codebase (e.g. the old per-widget
    `height`)."""
    if spec is None:
        key = (widget.get("config") or {}).get("width")
        if key not in WIDGET_WIDTHS:
            key = "half"
    else:
        key = spec.get("default_width", "full")
    return {"key": key, **WIDGET_WIDTHS[key]}


# Grid height -- there used to be a manual height picker/drag-resize here
# (WIDGET_HEIGHTS/_widget_height, four fixed presets, mirroring
# WIDGET_WIDTHS/_widget_width's drag-to-resize model), removed 2026-08-07
# per direct feedback: a widget's height should just be "how much content
# it is", no scrollbar, unless it goes over a max height. There's no
# per-widget height concept left at all now -- `.widget-content` (see
# _widget_workspace.html's widget_inner macro) just sizes to its own
# content, capped by one flat CSS max-height shared by every widget type
# (static/style.css) as a backstop; each widget's own item-count limit
# (e.g. _render_contact_list's `limit`) is what normally keeps content
# within bounds. Existing dashboards may still have a stale `height` key
# sitting unused in a widget's stored `config` JSON -- harmless, not
# migrated away, same convention as other deprecated config fields
# elsewhere in this codebase.
WIDGET_TYPES: dict[str, dict] = {
    "at_a_glance": {
        "label": "At a Glance",
        "template": "_widget_at_a_glance.html",
        "render": _render_at_a_glance,
        "uses": {"tasks"},
        # Corrected from "full" to "third" (2026-08-07, automatic-width
        # pass) -- it's just three number+label stat blocks, not content
        # that needs a full row; static/style.css already has a
        # `.widget-card[data-span="2"|"3"]` font-scaling rule for this
        # widget written for exactly this narrower width, which was
        # otherwise unreachable dead CSS as long as this default was "full".
        "default_width": "third",
    },
    "today_agenda": {
        "label": "Today's Agenda",
        "template": "_widget_today_agenda.html",
        "render": _render_today_agenda,
        "uses": {"tasks", "events"},
        "default_width": "half",
    },
    "mini_month_calendar": {
        "label": "Mini Calendar",
        "template": "_widget_mini_month_calendar.html",
        "render": _render_mini_month_calendar,
        "uses": {"tasks", "events"},
        "default_width": "half",
    },
    "weekly_overview": {
        "label": "Weekly Overview",
        "template": "_widget_weekly_overview.html",
        "render": _render_weekly_overview,
        "uses": {"tasks", "events"},
        "default_width": "full",
    },
    "upcoming_events": {
        "label": "Upcoming Events",
        "template": "_widget_upcoming_events.html",
        "render": _render_upcoming_events,
        "uses": {"events"},
        "default_width": "third",
    },
    "overdue_tasks": {
        "label": "Overdue Tasks",
        "template": "_widget_overdue_tasks.html",
        "render": _render_overdue_tasks,
        "uses": {"tasks"},
        "default_width": "third",
    },
    "project_preview": {
        "label": "Project Preview",
        "template": "_widget_project_preview.html",
        "render": _render_project_preview,
        "uses": set(),
        "default_width": "third",
    },
    "habit_checkin": {
        "label": "Habit Check-in",
        "template": "_widget_habit_checkin.html",
        "render": _render_habit_checkin,
        "uses": set(),
        "default_width": "half",
    },
    "calendar_agenda": {
        "label": "Calendar + Agenda",
        "template": "_widget_calendar_agenda.html",
        "render": _render_calendar_agenda,
        "uses": {"tasks", "events"},
        "default_width": "third",
    },
    "contact_list": {
        "label": "Contact List",
        "template": "_widget_contact_list.html",
        "render": _render_contact_list,
        "uses": set(),
        "default_width": "third",
    },
    "filled_cards": {
        "label": "Filled Cards",
        "template": "_widget_filled_cards.html",
        "render": _render_filled_cards,
        "uses": set(),
        "default_width": "full",
    },
    "important_urgent": {
        "label": "Important & Urgent",
        "template": "_widget_important_urgent.html",
        "render": _render_important_urgent,
        "uses": {"tasks"},
        "default_width": "half",
    },
    "scheduled_work_today": {
        "label": "Scheduled Work Hours Today",
        "template": "_widget_scheduled_work_today.html",
        "render": _render_scheduled_work_today,
        "uses": {"events"},
        "default_width": "third",
    },
    "quick_links": {
        "label": "Quick Links",
        "template": "_widget_quick_links.html",
        "render": _render_quick_links,
        "uses": set(),
        "default_width": "full",
    },
}

# --------------------------------------------------------------------- #
# Source / View / Range -- 2026-08-02 rework of how a widget gets picked.
# WIDGET_TYPES above is unchanged and still the actual storage/rendering
# mechanism (every widget row's `type` column is still one of its 7 keys,
# no migration needed for existing dashboards) -- what changed is the
# *picker* in front of it. Choosing a widget used to be one flat list
# ("Today's Agenda", "Weekly Overview", "Upcoming Events", ... -- seven
# names that don't obviously relate to each other even though four of
# them are really the same underlying data, tasks+events, just sliced
# differently). Now it's three independent choices -- what data
# (Source), how far out (Range, only where it means something), and how
# it's laid out (View) -- and _resolve_selection below maps that triple
# onto one of the existing seven `type` keys plus a `range_days` config
# value where relevant. _selection_from_widget does the reverse, so the
# per-widget Filters form can show an existing widget's Source/View/Range
# pre-selected instead of just its opaque legacy type name.
# --------------------------------------------------------------------- #

WIDGET_SOURCES: dict[str, dict] = {
    # `icon` (2026-08-07, modal-input-design Phase A) -- the Data source
    # tile picker in _widget_builder_fields.html/_widget_edit_form.html
    # renders one of these per tile via {{ icon(spec.icon, 'icon-lg') }};
    # picked from the existing sprite (templates/_icons_sprite.html), no
    # new icons drawn.
    # "calendar_tasks" (2026-08-07 rename) -- label is now "WebDAV" (the
    # underlying source is a CalDAV/CardDAV-style server either way); the
    # dict key stays as-is since it's an internal id threaded through
    # _SELECTION_TO_TYPE/config, not user-facing.
    "calendar_tasks": {"label": "WebDAV", "icon": "calendar"},
    # "projects" removed entirely (2026-08-07, "purge all remains of
    # projects" from this modal) -- no Projects tile in the Data source
    # picker any more. The underlying widget types (project_preview/
    # filled_cards) and their render functions are NOT deleted -- an
    # already-placed widget of either type keeps rendering via WIDGET_TYPES
    # exactly as before; this only stops the builder from offering a new
    # one. See _TYPE_TO_SELECTION/_selection_from_widget below and
    # edit_widget's own comment for how an already-placed widget's Filters
    # form still saves safely despite its source no longer being a valid
    # picker option.
    "habits": {"label": "Habits", "icon": "activity"},
    "contacts": {"label": "Contacts", "icon": "users"},
    # "quick_links" (1.9 side work) -- its own source rather than folded
    # under "calendar_tasks", since it reads label_config directly (no
    # tasks/events at all, same "uses: set()" shape project_preview/
    # filled_cards already have) -- see _render_quick_links.
    "quick_links": {"label": "Quick Links", "icon": "link"},
}

# Which views exist per source, and which of those views take a Range.
WIDGET_VIEWS: dict[str, dict] = {
    "agenda": {"label": "Agenda (grouped by day)", "source": "calendar_tasks", "has_range": True},
    "upcoming_list": {"label": "Upcoming list", "source": "calendar_tasks", "has_range": True},
    "overdue_list": {"label": "Overdue list", "source": "calendar_tasks", "has_range": False},
    "at_a_glance_view": {"label": "At a glance (stats)", "source": "calendar_tasks", "has_range": False},
    "mini_calendar": {"label": "Mini calendar", "source": "calendar_tasks", "has_range": False},
    # "cards"/"filled_cards_view" removed with the "projects" source above
    # -- neither is offered in the View picker any more.
    "checklist": {"label": "Checklist", "source": "habits", "has_range": False},
    "calendar_agenda_view": {"label": "Calendar + Agenda", "source": "calendar_tasks", "has_range": False},
    "contact_list_view": {"label": "Contact list", "source": "contacts", "has_range": False},
    # 1.9 side work -- porting /today's two sections into the Dashboard
    # registry (see _render_important_urgent/_render_scheduled_work_today)
    # and a new visual "Quick Links" tile grid (see _render_quick_links),
    # each offered through the same Source/View picker every other widget
    # type is, not just registered in WIDGET_TYPES with no way to add one.
    "important_urgent_view": {"label": "Important & urgent", "source": "calendar_tasks", "has_range": False},
    "scheduled_work_view": {"label": "Scheduled work hours today", "source": "calendar_tasks", "has_range": False},
    "quick_links_view": {"label": "Quick links (tiles)", "source": "quick_links", "has_range": False},
}

WIDGET_RANGES: dict[str, dict] = {
    "today": {"label": "Today", "views": {"agenda"}},
    "next_7_days": {"label": "Next 7 days", "views": {"agenda", "upcoming_list"}},
    "next_30_days": {"label": "Next 30 days", "views": {"agenda", "upcoming_list"}},
    "all_upcoming": {"label": "All upcoming", "views": {"upcoming_list"}},
}

# (view, range) -> (type, range_days). `range` is only ever looked up for
# views where WIDGET_VIEWS[view]["has_range"] is True; the other views
# have exactly one valid mapping regardless of whatever range came in.
# "cards"/"filled_cards_view" stay in this dict even though WIDGET_VIEWS no
# longer offers them (2026-08-07 Projects purge) -- harmless dead forward-
# lookup data; nothing ever submits those view values any more except
# _widget_edit_form.html's own hidden-field fallback for an already-placed
# Projects-sourced widget (see edit_widget's own comment), which needs
# _resolve_selection to keep resolving them correctly rather than 404ing.
_SELECTION_TO_TYPE: dict[tuple[str, str | None], tuple[str, int | None]] = {
    ("agenda", "today"): ("today_agenda", None),
    ("agenda", "next_7_days"): ("weekly_overview", 7),
    ("agenda", "next_30_days"): ("weekly_overview", 30),
    ("upcoming_list", "next_7_days"): ("upcoming_events", 7),
    ("upcoming_list", "next_30_days"): ("upcoming_events", 30),
    ("upcoming_list", "all_upcoming"): ("upcoming_events", None),
    ("overdue_list", None): ("overdue_tasks", None),
    ("at_a_glance_view", None): ("at_a_glance", None),
    ("mini_calendar", None): ("mini_month_calendar", None),
    ("cards", None): ("project_preview", None),
    ("filled_cards_view", None): ("filled_cards", None),
    ("checklist", None): ("habit_checkin", None),
    ("calendar_agenda_view", None): ("calendar_agenda", None),
    ("contact_list_view", None): ("contact_list", None),
    ("important_urgent_view", None): ("important_urgent", None),
    ("scheduled_work_view", None): ("scheduled_work_today", None),
    ("quick_links_view", None): ("quick_links", None),
}

# Reverse of the above, for pre-filling the edit form from an existing
# widget's stored `type` + `config.range_days`. Stores the full (source,
# view, range) triple directly (2026-08-07 Projects purge) rather than just
# (view, range) + a WIDGET_VIEWS[view]["source"] lookup -- "cards"/
# "filled_cards_view" no longer exist as WIDGET_VIEWS keys, so that lookup
# would KeyError the moment an already-placed Projects-sourced widget's
# Filters panel was opened. Kept as harmless dead reverse-lookup data for
# exactly that case; see _selection_from_widget and edit_widget's own
# comments for how the rest of the round-trip stays safe.
_TYPE_TO_SELECTION: dict[tuple[str, int | None], tuple[str, str, str | None]] = {
    ("today_agenda", None): ("calendar_tasks", "agenda", "today"),
    # weekly_overview's own render function defaults range_days to 7 when
    # config doesn't have one at all (_render_weekly_overview) -- true for
    # every dashboard that had this widget seeded before 2026-08-02, back
    # when config was just `{}`. (weekly_overview, None) has to reverse-
    # map to the *same* selection as (weekly_overview, 7), or every
    # pre-existing Weekly Overview widget would show as "next_7_days"
    # when you look at it but silently jump to the generic
    # calendar_tasks/agenda/today fallback the moment you opened its
    # Filters panel, changing its actual behavior the instant you saved.
    ("weekly_overview", None): ("calendar_tasks", "agenda", "next_7_days"),
    ("weekly_overview", 7): ("calendar_tasks", "agenda", "next_7_days"),
    ("weekly_overview", 30): ("calendar_tasks", "agenda", "next_30_days"),
    ("upcoming_events", 7): ("calendar_tasks", "upcoming_list", "next_7_days"),
    ("upcoming_events", 30): ("calendar_tasks", "upcoming_list", "next_30_days"),
    ("upcoming_events", None): ("calendar_tasks", "upcoming_list", "all_upcoming"),
    ("overdue_tasks", None): ("calendar_tasks", "overdue_list", None),
    ("at_a_glance", None): ("calendar_tasks", "at_a_glance_view", None),
    ("mini_month_calendar", None): ("calendar_tasks", "mini_calendar", None),
    ("project_preview", None): ("projects", "cards", None),
    ("filled_cards", None): ("projects", "filled_cards_view", None),
    ("habit_checkin", None): ("habits", "checklist", None),
    ("calendar_agenda", None): ("calendar_tasks", "calendar_agenda_view", None),
    ("contact_list", None): ("contacts", "contact_list_view", None),
    ("important_urgent", None): ("calendar_tasks", "important_urgent_view", None),
    ("scheduled_work_today", None): ("calendar_tasks", "scheduled_work_view", None),
    ("quick_links", None): ("quick_links", "quick_links_view", None),
}


def _resolve_selection(source: str, view: str, range_: str | None) -> tuple[str, int | None]:
    """(source, view, range) from the form -> (type, range_days) to
    actually store/render. Falls back to the first valid view for the
    source (and drops an inapplicable range) on anything malformed or
    stale rather than erroring -- a selector that's out of sync with its
    own source (e.g. JS hasn't filtered it yet, or a no-JS submission
    sent a range that view doesn't use) should still produce *a* working
    widget, not a 400."""
    if view not in WIDGET_VIEWS or WIDGET_VIEWS[view]["source"] != source:
        view = next(v for v, spec in WIDGET_VIEWS.items() if spec["source"] == source)
    if not WIDGET_VIEWS[view]["has_range"]:
        range_ = None
    elif range_ not in WIDGET_RANGES or view not in WIDGET_RANGES[range_]["views"]:
        range_ = next(r for r, spec in WIDGET_RANGES.items() if view in spec["views"])
    return _SELECTION_TO_TYPE[(view, range_)]


def _selection_from_widget(widget: dict) -> tuple[str, str, str | None]:
    """(type, range_days) stored on a widget -> (source, view, range) to
    pre-select in the form. Unknown/legacy types (shouldn't happen, but
    _widget_context already tolerates a None spec for exactly this kind
    of "the type on disk doesn't match anything live" case) fall back to
    the first source/view rather than crashing the edit form. Returns the
    (source, view, range) triple straight from _TYPE_TO_SELECTION -- for a
    type whose source/view are no longer offered by the builder (Projects,
    2026-08-07 purge), this still returns "projects"/"cards" (or
    "filled_cards_view") correctly instead of KeyError-ing on a
    WIDGET_VIEWS lookup that key no longer has; _widget_edit_form.html
    checks whether the returned source is still in `widget_sources` before
    deciding whether to render it as a picker or fall back to read-only
    hidden fields (see that template's own comment)."""
    range_days = (widget.get("config") or {}).get("range_days")
    key = (widget["type"], int(range_days) if range_days else None)
    if key not in _TYPE_TO_SELECTION:
        return "calendar_tasks", "agenda", "today"
    return _TYPE_TO_SELECTION[key]


# --------------------------------------------------------------------- #
# Per-page scope (2026-08-05, "Dashboard customization copied to the
# Space/Project dashboard, widget options limited to fit the page") --
# the same widget registry serves three pages now (Home, a Space's grid,
# a project's grid), and not every widget type makes sense on every page.
# `filled_cards` is a whole-app "every space" overview -- meaningless
# inside the one Space it's already showing, and doubly meaningless on a
# single project page. `project_preview` is "pick one project / every
# active project" -- pointless on the one project page it's already
# showing. Home offers the full registry; each narrower page only drops
# the types that can't mean anything there. Existing widgets of a now-
# excluded type are NOT deleted or hidden (a user-configured Space card
# keeps rendering via the global WIDGET_TYPES lookup) -- this only stops
# the *builder/editor* from offering them fresh. The project/task-list/
# calendar collections offered by the Advanced filters are scoped the
# same way (_scoped_collections below): a Space only lists its own
# projects and their lists/calendars; a project only lists itself and its
# own linked lists/calendars.
# --------------------------------------------------------------------- #

_SCOPE_EXCLUDED_TYPES: dict[str, set[str]] = {
    "space": {"filled_cards", "quick_links"},
    "project": {"filled_cards", "project_preview", "quick_links"},
}


def _page_scope(conn, label_name: str | None) -> str:
    """The scope name for a page identity -- "project" / "space" / "" (Home).
    Phase 2 (label-space rework) collapsed space_uid/project_uid into one
    `label_name` column -- which kind of page it is (Space vs. plain
    label/"project" page) is derived here from label_config.generate_space
    rather than which of two columns was set."""
    if not label_name:
        return ""
    cfg = db.get_label_config(conn, label_name)
    return "space" if (cfg and cfg.get("generate_space")) else "project"


def _excluded_widget_types(scope: str) -> set[str]:
    return _SCOPE_EXCLUDED_TYPES.get(scope) or set()


def _type_for_view(view: str) -> str | None:
    """The widget `type` a view maps to (any range) -- for scoping the View
    picker to views whose type is allowed on the page. Views map to exactly
    one type per range, but the type is the same for every range a view
    supports (agenda -> today_agenda/weekly_overview depending on range),
    so just return the first mapping found."""
    for (v, _r), (t, _d) in _SELECTION_TO_TYPE.items():
        if v == view:
            return t
    return None


def _widget_types_for_scope(scope: str) -> dict[str, dict]:
    excluded = _excluded_widget_types(scope)
    return {k: v for k, v in WIDGET_TYPES.items() if k not in excluded}


def _widget_views_for_scope(scope: str) -> dict[str, dict]:
    excluded = _excluded_widget_types(scope)
    return {k: v for k, v in WIDGET_VIEWS.items() if _type_for_view(k) not in excluded}


def _widget_sources_for_scope(scope: str) -> dict[str, dict]:
    """Sources that still have at least one allowed view -- a source whose
    every view is excluded (e.g. Projects on a project page, once both
    `cards` and `filled_cards_view` are gone) disappears from the picker
    entirely rather than showing a dead Source with no View choices."""
    allowed_sources = {v["source"] for v in _widget_views_for_scope(scope).values()}
    return {k: v for k, v in WIDGET_SOURCES.items() if k in allowed_sources}


def _scoped_collections(conn, label_name: str | None) -> tuple[list[dict], list[dict], list[dict]]:
    """(projects, task_lists, calendars) the Customize/Filter forms may
    offer for one page's grid -- Home offers every plain label; a Space's
    page only its own child labels; a plain label's own page just itself.
    Phase 1 (label-space rework, 2026-08-06) dropped `task_lists`/
    `calendars` -- those two elements of the tuple are always empty now;
    kept as an empty list, not removed from the return shape, so every
    existing caller (widget_page_context below) keeps unpacking a 3-tuple
    unchanged. "projects" here means "labels" -- kept as the historical
    name templates already read (`projects` context key)."""
    if label_name is not None:
        cfg = db.get_label_config(conn, label_name)
        if cfg and cfg.get("generate_space"):
            projects = db.list_child_labels(conn, label_name)
        else:
            projects = [db.effective_label_config(conn, label_name)]
    else:
        projects = [lbl for lbl in db.list_labels(conn) if not lbl.get("generate_space")]
    return projects, [], []


# 2026-08-07 (screenshot-driven default-layout rework): the default seed
# is now exactly what the target screenshot shows -- Today's Agenda on the
# left, and one stacked card of At a Glance / Upcoming Events / Overdue
# Tasks on the right. calendar_agenda/weekly_overview/mini_month_calendar
# are no longer pre-seeded (still available to add manually via "New
# widget" -- this only changes what's pre-populated on a brand-new page).
# The stack is built with the exact same data shape stack_widget() itself
# produces below (a `type="stack"` dashboard_widgets row + members pointed
# at it via group_uid), not a bespoke seed-only mechanism, so a seeded
# stack is indistinguishable at render time from one a user built by
# dragging one widget onto another.
_DEFAULT_TODAY_AGENDA_CONFIG: dict = {"width": "half"}
_DEFAULT_STACK_CONFIG: dict = {"width": "half"}
_DEFAULT_STACK_MEMBER_TYPES: list[str] = ["at_a_glance", "upcoming_events", "overdue_tasks"]

_MINI_CALENDAR_BACKFILL_KEY = "dashboard_mini_calendar_backfilled_v1"
_HOME_SEEDED_KEY = "dashboard_home_seeded_v1"


def _seed_agenda_stack_layout(conn, label_name: str | None, now: str) -> None:
    """Writes the default layout for one page's grid -- Home when
    `label_name` is None, otherwise that label's generated Space/Project
    page -- shared by _ensure_default_widgets and
    _ensure_default_label_widgets so both seed with the identical
    screenshot-driven look: Today's Agenda beside a stack of At a
    Glance / Upcoming Events / Overdue Tasks. Building the stack this way
    (a `type="stack"` row + group_uid members) mirrors stack_widget()'s
    own shape exactly, not a new mechanism.

    Every widget/stack row is scoped to this page via the `label_name`
    column (None means Home -- see db.upsert_dashboard_widget), and each
    *widget's own config* additionally gets `label_name` set (label pages
    only) so its data query is filtered to this label, same as every
    other label-page widget (see _effective_tags_filter)."""
    agenda_config = dict(_DEFAULT_TODAY_AGENDA_CONFIG)
    if label_name:
        agenda_config["label_name"] = label_name
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": str(uuid.uuid4()), "type": "today_agenda", "title": None,
            "config": agenda_config, "position": 0.0, "created_at": now, "label_name": label_name,
        },
    )
    stack_uid = str(uuid.uuid4())
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": stack_uid, "type": "stack", "title": None,
            "config": dict(_DEFAULT_STACK_CONFIG), "position": 1.0, "created_at": now, "label_name": label_name,
        },
    )
    for i, wtype in enumerate(_DEFAULT_STACK_MEMBER_TYPES):
        member_config = {"label_name": label_name} if label_name else {}
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()), "type": wtype, "title": None, "config": member_config,
                "position": float(i), "created_at": now, "group_uid": stack_uid, "label_name": label_name,
            },
        )


def _ensure_default_widgets(conn) -> None:
    """A brand-new install gets a working dashboard out of the box
    (unfiltered today/week/upcoming) -- "customizable" means you can
    reshape it from there, not that you start from a blank page.

    A one-time-only seed: once seeded (tracked via app_meta), it never
    re-seeds -- even if the user deletes every widget. This honors the
    "No widgets yet" empty state instead of silently re-creating defaults
    on every reload after a full clear. Same convention as the existing
    _backfill_mini_calendar_widget one-time migration and
    ensure_default_calendar/ensure_default_task_list/ensure_default_addressbook
    (db.py), but scoped per-page.

    2026-08-07 (screenshot-driven default-layout rework): see
    _seed_agenda_stack_layout -- Today's Agenda + a stacked At a
    Glance/Upcoming Events/Overdue Tasks card, replacing the previous
    six-widget seed."""
    if db.get_app_meta(conn, _HOME_SEEDED_KEY):
        return
    if db.list_dashboard_widgets(conn):
        db.set_app_meta(conn, _HOME_SEEDED_KEY, "1")
        return
    _seed_agenda_stack_layout(conn, None, _now())
    # Found during this pass, not anticipated going in: _backfill_mini_
    # calendar_widget (below) is a one-time *migration* for dashboards
    # that already existed before mini_month_calendar/calendar_agenda
    # were invented -- it injects a standalone mini_month_calendar when
    # neither type is present. Since this fresh seed no longer includes
    # calendar_agenda either, a truly brand-new install would otherwise
    # trip that same "neither present" condition and get an uninvited
    # mini_month_calendar widget nobody asked for. Marking the backfill
    # done here (this dashboard has no history to migrate) is the fix --
    # genuinely pre-existing installs (the `list_dashboard_widgets(conn)`
    # branch above) are untouched and still get the real migration.
    db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")
    # Found during Phase 1 implementation, not in this phase's original
    # scope: this branch never marked itself seeded after actually
    # writing the fresh defaults (only the "widgets already existed"
    # branch above did), so every subsequent call re-seeded on top of a
    # full delete instead of respecting the "no widgets yet" empty state
    # the function's own docstring promises. Fixed here since it blocks
    # the full suite going green, not because it's part of the
    # label-space rework.
    db.set_app_meta(conn, _HOME_SEEDED_KEY, "1")


# Label page widget grid (2026-08-02 follow-up to spaces-home-pipeline,
# collapsed 2026-08-06 -- label-space rework Phase 2): a label's generated
# page gets the exact same widget system as Home (WIDGET_TYPES, add/edit/
# resize/stack/reorder, all below), just scoped to its own
# dashboard_widgets rows via `label_name` instead of the default NULL
# ("Home"). Every widget seeded here is pre-configured with
# config["label_name"] = this label's own name so it's useful immediately
# with no setup -- see _child_label_names/_render_project_preview/
# _render_habit_checkin, which all already know how to resolve that key.
# A Space label (generate_space=1) gets the "overview of my projects"
# defaults; a plain label gets the "this label's own items" defaults --
# same split _SCOPE_EXCLUDED_TYPES already draws for which widget types
# are offered on each.
# 2026-08-07 (screenshot-driven default-layout rework, "feature parity
# with the main home dashboard"): a Space/Project page now gets the exact
# same default layout as Home (see _seed_agenda_stack_layout) -- Today's
# Agenda beside a stacked At a Glance/Upcoming Events/Overdue Tasks card,
# each widget's data scoped to this label via config["label_name"].
# project_preview/habit_checkin/contact_list/calendar_agenda/
# weekly_overview are no longer pre-seeded on either Space or Project
# pages -- still available to add manually via "New widget", same as on
# Home. Space and Project no longer need their own distinct default
# lists since the layout is now identical between them; a future
# divergence here would reintroduce separate default lists.


def _ensure_default_label_widgets(conn, label_name: str) -> None:
    """Same one-time-only seeding as _ensure_default_widgets, scoped to
    one label's page -- never re-seeds once _that label_ has been seeded,
    even if the user later deletes every widget from it (honors the empty
    state instead of silently re-creating defaults). Checked independently
    of every other label's/Home's own widgets.

    2026-08-07 (screenshot-driven default-layout rework): both a Space
    page and a plain Project/label page now get the identical layout Home
    does -- see _seed_agenda_stack_layout. (Previously Space and Project
    pages seeded different widget sets; that distinction is gone now that
    the target layout is the same everywhere.)"""
    seeded_key = f"dashboard_label_{label_name}_seeded_v1"
    if db.get_app_meta(conn, seeded_key):
        return
    if db.list_dashboard_widgets(conn, label_name=label_name):
        db.set_app_meta(conn, seeded_key, "1")
        return
    _seed_agenda_stack_layout(conn, label_name, _now())
    db.set_app_meta(conn, seeded_key, "1")


def _backfill_mini_calendar_widget(conn) -> None:
    """One-time migration, NOT the same idempotent-forever pattern
    _ensure_default_widgets uses. mini_month_calendar was added to
    _DEFAULT_WIDGETS after real dashboards already existed -- Widget
    seeding only runs on a completely empty dashboard, so anyone who'd
    already visited before this change never got it. Runs exactly once
    (tracked in app_meta), inserting it right after Today's Agenda if
    that widget exists, so deleting it afterward sticks instead of it
    reappearing on the next load like a true default would.

    2026-08-03 (§1 Dashboard rework): calendar_agenda replaces the
    standalone mini_month_calendar in the defaults -- dashboards that
    already have a calendar_agenda widget don't need a bare
    mini_month_calendar too. The backfill marks itself done immediately
    in that case instead of inserting the now-redundant widget."""
    if db.get_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY):
        return
    widgets = db.list_dashboard_widgets(conn)
    has_mini_cal = any(w["type"] == "mini_month_calendar" for w in widgets)
    has_cal_agenda = any(w["type"] == "calendar_agenda" for w in widgets)
    # New installs (§1, 2026-08-03) get calendar_agenda instead -- no need
    # to also inject the old standalone mini calendar.
    if has_cal_agenda:
        db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")
        return
    if widgets and not has_mini_cal:
        today_idx = next((i for i, w in enumerate(widgets) if w["type"] == "today_agenda"), None)
        if today_idx is not None and today_idx + 1 < len(widgets):
            position = (widgets[today_idx]["position"] + widgets[today_idx + 1]["position"]) / 2
        elif today_idx is not None:
            position = widgets[today_idx]["position"] + 0.5
        else:
            position = db.next_dashboard_widget_position(conn)
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "type": "mini_month_calendar",
                "title": None,
                "config": {},
                "position": position,
                "created_at": _now(),
            },
        )
    db.set_app_meta(conn, _MINI_CALENDAR_BACKFILL_KEY, "1")


def _widget_context(conn, widget: dict, nav: dict | None = None) -> dict:
    spec = WIDGET_TYPES.get(widget["type"])
    width = _widget_width(widget, spec)
    source, view, range_ = _selection_from_widget(widget)
    selection = {"source": source, "view": view, "range": range_}
    if spec is None:
        return {"widget": widget, "spec": None, "data": None, "width": width, "selection": selection, "is_stack": False}
    data = spec["render"](conn, widget["config"], nav)
    return {"widget": widget, "spec": spec, "data": data, "width": width, "selection": selection, "is_stack": False}


def _build_widget_contexts(conn, widgets: list[dict], nav: dict | None = None) -> list[dict]:
    """Top-level render list -- plain widgets via _widget_context as
    before, plus stacks (2026-08-02): a stack is just another
    dashboard_widgets row (type="stack", no spec/render of its own,
    _widget_context already treats an unrecognized type as "no spec"),
    grouping whatever other widgets have `group_uid` pointing at it. Its
    members are excluded from this top-level list entirely -- they only
    ever get rendered nested inside their stack's own `children`, in
    `position` order among just that stack's members (not comparable to
    any other widget's position, same as this file's docstring on
    group_uid already explains)."""
    children_by_group: dict[str, list[dict]] = {}
    for w in widgets:
        gid = w.get("group_uid")
        if gid:
            children_by_group.setdefault(gid, []).append(w)
    for kids in children_by_group.values():
        kids.sort(key=lambda w: w["position"])

    contexts = []
    for w in widgets:
        if w.get("group_uid"):
            continue  # rendered nested under its stack instead
        if w["type"] == "stack":
            width = _widget_width(w, None)
            children = [_widget_context(conn, c, nav) for c in children_by_group.get(w["uid"], [])]
            contexts.append({"widget": w, "spec": None, "data": None, "width": width, "selection": None, "is_stack": True, "children": children})
        else:
            contexts.append(_widget_context(conn, w, nav))
    return contexts


def _return_url(label_name: str | None, _legacy: str | None = None, edit: bool = False) -> str:
    """Where a widget-mutating POST should redirect back to -- Home ("/")
    when the acted-on widget has no page identity, or that label's
    generated page (/labels/{name}) otherwise. Derived from the widget
    itself wherever one already exists (edit/resize/stack/unstack/delete/
    move/reorder below); only add_widget has no existing widget to derive
    it from, so it takes `label_name` as a hidden form field instead (see
    _widget_builder_fields.html). `_legacy` accepts a second positional
    arg so every pre-Phase-2 call site passing (space_uid, project_uid)
    -- both now the same value, see _widget_row_to_dict's aliasing --
    keeps working unchanged; only the first non-empty of the two is used."""
    label_name = label_name or _legacy
    base = f"/labels/{label_name}" if label_name else "/"
    return f"{base}?edit=1" if edit else base


def widget_page_context(conn, space_uid: str | None = None, project_uid: str | None = None, edit: bool = False, nav: dict | None = None) -> dict:
    """Every piece of context _widget_workspace.html needs to render one
    page's widget grid (Add-widget form, live preview pane, the grid
    itself, each widget's own Filters panel) -- shared by dashboard_view
    (label_name=None, below) and routers/labels.py's label_detail (a
    label's generated page) so both pages run through the exact same
    widget machinery -- add/edit/resize/stack/reorder, all further below
    -- rather than a second parallel implementation living on the label
    route. `space_uid`/`project_uid` (kept as this function's own
    parameter names -- both now the same value, Phase 2 label-space
    rework) are the label whose page this is; only one is ever passed by
    any real caller. The widget *options* offered to each page are scoped
    by _widget_types_for_scope/_widget_views_for_scope/
    _widget_sources_for_scope and the collection dropdowns by
    _scoped_collections, so a label page never offers widgets or filters
    that can't mean anything there."""
    label_name = project_uid or space_uid
    widgets = db.list_dashboard_widgets(conn, label_name=label_name)
    widget_contexts = _build_widget_contexts(conn, widgets, nav)
    scope = _page_scope(conn, label_name)
    projects, task_lists, calendars = _scoped_collections(conn, label_name)
    tag_names = db.list_tag_names_in_use(conn)
    return {
        "space_uid": label_name or "",
        "project_uid": label_name or "",
        "label_name": label_name or "",
        "page_scope": scope,
        "page_url": _return_url(label_name),
        "edit_mode": edit,
        "widget_contexts": widget_contexts,
        "widget_types": _widget_types_for_scope(scope),
        "widget_sources": _widget_sources_for_scope(scope),
        "widget_views": _widget_views_for_scope(scope),
        "widget_ranges": WIDGET_RANGES,
        "projects": projects,
        "task_lists": task_lists,
        "calendars": calendars,
        "tag_names": tag_names,
        # (2026-08-07) reshaped for the Labels chip multiselect, which
        # reuses _widget_list_multiselect.html's {uid, name} item contract
        # -- a label's own name IS its identity, so uid == name here.
        "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
    }


@router.get("/")
def dashboard_view(
    request: Request,
    edit: bool = False,
    cal_year: int | None = None,
    cal_month: int | None = None,
    conn=Depends(get_db),
):
    _ensure_default_widgets(conn)
    _backfill_mini_calendar_widget(conn)
    # Month nav (cal_year/cal_month) is a plain query param on this same
    # route, not a per-widget one -- same "prev/next just re-requests the
    # page with different params" convention routers/calendar.py's month
    # view already uses, no JS required. Applies to every
    # mini_month_calendar widget on the page (there's normally just one);
    # a second instance would page together rather than independently,
    # which is an acceptable shared tradeoff for how much simpler it
    # keeps this than per-widget-uid params.
    nav = {"year": cal_year, "month": cal_month} if (cal_year and cal_month) else None
    ctx = widget_page_context(conn, space_uid=None, edit=edit, nav=nav)
    display_name = db.get_app_meta(conn, DISPLAY_NAME_KEY)
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            "greeting": _greeting_for_hour(datetime.now().hour, display_name),
            # Page banner (2026-08-09, routers/banners.py) -- Home's
            # banner + the page key ("" = Home) the banner editor's hidden
            # scope field and _page_banner.html's edit-mode button read.
            "banner": db.get_page_banner(conn, ""),
            "banner_scope": "",
        }
    )
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/quick/add")
def quick_add_form(request: Request, conn=Depends(get_db)):
    # Merged task/event quick-add (2026-08-10) -- the dashboard's and
    # label-page's single "+" button opens this instead of two separate
    # New task / New event forms. Renders BOTH create-forms in one modal
    # (quick_add.html); the client just flips between them. The task and
    # event option lists are imported lazily from .tasks so this module
    # (which .tasks itself imports at load time) doesn't create a
    # circular import.
    from .tasks import IMPORTANCE_ITEMS, URGENCY_ITEMS, STATUS_ITEMS, STATUSES

    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "quick_add.html",
        {
            "request": request,
            "active_tab": "dashboard",
            # Task-side context -- the shared field-grid partial
            # (_task_form_fields.html) needs the same items new_task_form
            # passes; task is None, so the edit-only branches don't render.
            "task": None,
            "statuses": STATUSES,
            "importance_items": IMPORTANCE_ITEMS,
            "urgency_items": URGENCY_ITEMS,
            "status_items": STATUS_ITEMS,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "today": date.today().isoformat(),
            "habit_label": db.get_task_habit_settings(conn)["habit_label"],
            # Event-side context -- same union new_event_form passes, all
            # blank so the event form starts empty.
            "event": None,
            "prefill_start": None,
            "prefill_end": None,
            "prefill_all_day": False,
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


def _reset_dashboard(conn, label_name: str | None) -> None:
    """"Have a clear default dashboard that the user could revert back to
    anytime, via settings." -- deletes every widget for one page's scope
    (Home when `label_name` is None, that label's own page otherwise) and
    clears the matching one-time "seeded" app_meta flag, then immediately
    re-seeds so the user lands back on a populated default layout, not a
    blank grid. Doesn't touch `_ensure_default_widgets`/
    `_ensure_default_label_widgets`'s own "seed once, never again"
    contract -- clearing the flag here is exactly what makes them willing
    to seed again, same as if this page had never been visited."""
    for w in db.list_dashboard_widgets(conn, label_name=label_name):
        db.delete_dashboard_widget(conn, w["uid"])
    if label_name:
        db.set_app_meta(conn, f"dashboard_label_{label_name}_seeded_v1", "")
        _ensure_default_label_widgets(conn, label_name)
    else:
        db.set_app_meta(conn, _HOME_SEEDED_KEY, "")
        _ensure_default_widgets(conn)


@router.post("/dashboard/reset")
def reset_dashboard(label_name: str = Form(""), edit: bool = Form(False), conn=Depends(get_db)):
    """Reset-to-default-layout -- one generic route for both Home
    (`label_name` omitted/empty) and a label page (`label_name` set),
    rather than a second `/labels/{name}/dashboard/reset` route in
    routers/labels.py, since the only thing that differs is which scope's
    widgets get cleared and which seed function runs, both already
    handled by `_reset_dashboard`. Surfaced as a button in Settings'
    Widgets group (Home) and in a label page's own edit-mode toolbar
    (Settings has no per-space subpage to host that one) -- both go
    through a `data-confirm-sheet` form (static/app.js's confirm-sheet
    pattern), same mechanism every other destructive action in this app
    already uses, not a second confirmation UI."""
    _reset_dashboard(conn, label_name or None)
    return RedirectResponse(url=_return_url(label_name or None, edit=edit), status_code=303)


def _flatten_customize(contexts: list[dict]) -> list[dict]:
    """Flattens the (possibly stacked) widget-context list into the one
    list the Customize modal renders: each top-level widget becomes one
    row, a stack container becomes one group header row (its /delete
    dissolves, not destroys), and each stack member becomes an indented
    child row of that container."""
    flat: list[dict] = []
    for wc in contexts:
        if wc["is_stack"]:
            flat.append({"is_stack_header": True, "wc": wc, "widget": wc["widget"]})
            for child in wc["children"]:
                flat.append({
                    "is_stack_header": False, "wc": child,
                    "widget": child.get("widget", {}), "in_stack": True,
                })
        else:
            flat.append({"is_stack_header": False, "wc": wc, "widget": wc["widget"], "in_stack": False})
    return flat


@router.get("/dashboard/customize")
def dashboard_customize(request: Request, space_uid: str = "", project_uid: str = "", conn=Depends(get_db)):
    """The Customize modal -- a friendly surface for adding widgets. Shows
     the two-pane Widget Builder with configuration form + always-live
     preview -- always available (2026-08-08: the "Custom widgets" toggle
     that used to gate it is removed, see _modal_widget_customize.html's
     own comment). Reuses widget_page_context for source/view/range/
     project/tag/calendar data needed by _widget_builder_fields.html.
     `space_uid`/`project_uid` (2026-08-05) scope it exactly like the grid
     it manages -- Home has neither, a Space page passes space_uid, a
     Project page project_uid."""
    ctx = widget_page_context(conn, space_uid or None, project_uid or None, edit=True)
    page_label = "Space dashboard" if space_uid else ("Project dashboard" if project_uid else "dashboard")
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            "space_uid": space_uid,
            "project_uid": project_uid,
            "page_label": page_label,
        }
    )
    return templates.TemplateResponse("dashboard_customize.html", ctx)


@router.get("/dashboard/widgets/{uid}/edit")
def widget_edit_form(request: Request, uid: str, space_uid: str = "", conn=Depends(get_db)):
    """Per-widget Filters editor as a modal (edit mode only) -- opened via the
    Filters button on each widget card. Returns a modal target fragment that
    static/modal.js shows as a dialog instead of an inline <details>.
    Gated behind edit_mode on the caller (the button only renders in edit mode)."""
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"widget not found: {uid}")
    wc = _widget_context(conn, widget)
    space_uid = widget.get("space_uid") or ""
    project_uid = widget.get("project_uid") or ""
    nav = {"year": 0, "month": 0}
    page_ctx = widget_page_context(conn, space_uid or None, project_uid or None, edit=True, nav=nav)
    page_ctx.update({
        "request": request,
        "widget": wc["widget"],
        "wc": wc,
        "spec": wc["spec"],
        "space_uid": space_uid,
        "project_uid": project_uid,
    })
    return templates.TemplateResponse("_widget_edit_modal.html", page_ctx)


def _config_from_form(
    project_uid: str,
    tags: str,
    task_list_uids: list[str],
    calendar_uids: list[str],
    limit: str,
    range_days: int | None = None,
) -> dict:
    config: dict = {}
    tag_list = _tags_list(tags)
    if project_uid:
        # Phase 2 (label-space rework): the widget builder's "Project"
        # picker filters content by one label now -- folded straight into
        # the tags filter (a label IS a tag, see _passes_filters) rather
        # than a separate config["project_uid"] key, which is reserved for
        # the widget's own page-scope identity now (see
        # dashboard_widgets.label_name / config["label_name"]).
        if project_uid not in tag_list:
            tag_list.append(project_uid)
    if tag_list:
        config["tags"] = tag_list
    # Phase 1 (label-space rework, 2026-08-06) dropped `task_lists`/
    # `calendars` -- `task_list_uids`/`calendar_uids` are still accepted
    # as form params (so old form markup that still submits them doesn't
    # 422) but are no longer stored into config; _passes_filters no
    # longer has a `list_uids` filter to apply (see its own comment).
    if limit:
        try:
            config["limit"] = int(limit)
        except ValueError:
            pass
    # Range (2026-08-02's Source/View/Range rework) -- resolved server-side
    # by _resolve_selection before this is ever called, never trusted
    # as-is from the client.
    if range_days:
        config["range_days"] = range_days
    return config


@router.post("/dashboard/widgets/preview")
def preview_widget(
    request: Request,
    source: str = Form(...),
    view: str = Form(""),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    space_uid: str = Form(""),
    conn=Depends(get_db),
):
    """Live preview (2026-08-02) -- Source/View/Range/filter changes in the
    Add-widget or per-widget Filters form fetch this on every change
    (static/dashboard_widget_preview.js) and swap the result into a
    preview pane, so you see the *actual* widget -- real data, real
    render function, same partial template -- before committing to it,
    not a mockup. `widget.uid` is a placeholder ("preview") since nothing
    has been saved; the only template that reads it (Mini Calendar's
    prev/next links) just gets a link that doesn't scroll anywhere
    meaningful, harmless in a preview pane. `space_uid` (2026-08-02, per-
    space widgets) and `project_uid` (2026-08-05, per-project widgets) are
    only ever present when previewing from a Space/Project page's own
    Customize form -- see add_widget below for why the preview has to
    auto-scope the same way the real save does. `tags_labels` (2026-08-07)
    is the Labels chip multiselect's checkboxes -- see _combine_tags."""
    if source not in WIDGET_SOURCES:
        return templates.TemplateResponse(
            "_dashboard_widget_preview.html",
            {"request": request, "widget": {"uid": "preview", "title": title}, "spec": None, "data": None},
        )
    wtype, range_days = _resolve_selection(source, view, range or None)
    spec = WIDGET_TYPES[wtype]
    config = _config_from_form(project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit, range_days=range_days)
    page_label = space_uid or project_uid
    if page_label:
        config["label_name"] = page_label
    data = spec["render"](conn, config, None)
    return templates.TemplateResponse(
        "_dashboard_widget_preview.html",
        {"request": request, "widget": {"uid": "preview", "title": title.strip() or None}, "spec": spec, "data": data},
    )


@router.post("/dashboard/widgets")
def add_widget(
    source: str = Form(...),
    view: str = Form(...),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    space_uid: str = Form(""),
    edit: bool = Form(False),
    conn=Depends(get_db),
):
    """`space_uid` (2026-08-02, per-space widgets) and `project_uid`
    (2026-08-05, per-project widgets) -- hidden fields on the Customize
    form's widget builder, empty on Home, set to the Space's/Project's own
    uid on their pages. This is the one mutating route that can't derive
    its page from an existing widget (there isn't one yet), so it's the
    one place the page identity is threaded through the form instead of
    read back off a row. Every widget added from a Space auto-scopes to it
    via config["group_uid"]; every widget added from a project via
    config["project_uid"] (the answered "auto-scope" design question,
    2026-08-02) -- the user never has to pick a Project filter just to
    keep a widget from leaking other spaces'/projects' data. Widget types
    excluded for the page's scope (e.g. Filled Cards on a Space, Project
    Preview on a project page) are rejected as a no-op the same way an
    unknown source is, so a stale/excluded combo never silently creates a
    widget that can't mean anything on the page."""
    page_label = space_uid or project_uid or None
    if source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)
    wtype, range_days = _resolve_selection(source, view, range or None)
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)
    config = _config_from_form(project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit, range_days)
    if page_label:
        config["label_name"] = page_label
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": str(uuid.uuid4()),
            "type": wtype,
            "title": title.strip() or None,
            "config": config,
            "position": db.next_dashboard_widget_position(conn, page_label),
            "created_at": _now(),
            "label_name": page_label,
        },
    )
    return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)


@router.post("/dashboard/widgets/{uid}/edit")
def edit_widget(
    uid: str,
    source: str = Form(...),
    view: str = Form(...),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    edit: bool = Form(False),
    conn=Depends(get_db),
):
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return RedirectResponse(url="/", status_code=303)
    page_label = existing.get("label_name")
    # Already-placed widget of a source/view no longer offered by the
    # builder (2026-08-07 Projects purge -- "projects"/"cards"/
    # "filled_cards_view") -- _widget_edit_form.html can't render a picker
    # for a source that isn't in `widget_sources` any more, so it falls
    # back to submitting the widget's own current selection unchanged via
    # hidden fields (see that template's own comment). Recognize that
    # exact "nothing about Source/View/Range actually changed" case here
    # and keep the widget's existing type/range_days as-is, *before* the
    # `source not in WIDGET_SOURCES` guard below would otherwise reject
    # the whole save -- without this, simply editing the Title or Labels
    # on an old Projects widget would silently fail to save anything.
    orig_source, orig_view, orig_range = _selection_from_widget(existing)
    if source == orig_source and view == orig_view and (range or None) == orig_range and source not in WIDGET_SOURCES:
        wtype = existing["type"]
        range_days = (existing.get("config") or {}).get("range_days")
    elif source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)
    else:
        wtype, range_days = _resolve_selection(source, view, range or None)
    # Scope guard (2026-08-05) -- an excluded type can only arrive from a
    # stale/forged submission (the builder no longer offers it), so refuse
    # it the same way an unknown source is refused rather than silently
    # turning a project widget into something that can't mean anything
    # there.
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)
    row = dict(existing)
    new_config = _config_from_form(project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit, range_days=range_days)
    # Width isn't a field on this form (2026-08-07 removal of the manual
    # width picker/drag-resize) -- there's no per-widget-instance width
    # left to carry over at all any more; a widget's width is always just
    # its type's own default_width (_widget_width), recomputed fresh at
    # render time regardless of what's in config.
    # Re-scope to whichever page this widget already belongs to
    # (2026-08-02) -- a label page's `label_name` filter isn't a field on
    # this form either, same reasoning as width: editing Title/Source/
    # Project/Tags must never silently un-scope a widget from its page.
    if page_label:
        new_config["label_name"] = page_label
    row.update({"type": wtype, "title": title.strip() or None, "config": new_config})
    db.upsert_dashboard_widget(conn, row)
    return RedirectResponse(url=_return_url(page_label, edit=edit), status_code=303)


def _dissolve_stack(conn, stack: dict) -> None:
    """Ungroups every member of `stack` back to the top level, in their
    existing relative order, landing at the stack's own old position and
    inheriting its shared width -- used both when a stack is explicitly
    deleted (dissolve, don't destroy -- see delete_widget below) and when
    unstacking a widget leaves a stack with fewer than 2 members (a
    "stack" of one thing isn't a stack, it's just that widget). Height is
    not shared/propagated here the way width is -- stack members render
    one above another in a single card, each just sizing to its own
    content (see .widget-content in _widget_workspace.html), not one
    height split across all of them the way "same width, side by side"
    makes sense for width."""
    stack_uid = stack["uid"]
    stack_width = (stack.get("config") or {}).get("width")
    # list_all_dashboard_widgets, not list_dashboard_widgets (2026-08-02) --
    # a stack's uid is globally unique regardless of which page's grid
    # (Home or a Space) it's in, and this helper is called from both.
    children = sorted(
        (w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid),
        key=lambda w: w["position"],
    )
    for i, child in enumerate(children):
        child = dict(child)
        child["group_uid"] = None
        # Small offsets keep them in the same relative order rather than
        # colliding on one exact position value; landing at the stack's
        # own position keeps them roughly where the stack used to sit in
        # the overall top-level order instead of jumping to the end.
        child["position"] = stack["position"] + (i * 0.001)
        if stack_width:
            child_config = dict(child.get("config") or {})
            child_config["width"] = stack_width
            child["config"] = child_config
        db.upsert_dashboard_widget(conn, child)
    db.delete_dashboard_widget(conn, stack_uid)


def _dissolve_if_singleton(conn, stack_uid: str) -> None:
    """After a widget leaves a stack (via /unstack, or via plain delete of
    one member), a stack with 0 or 1 members left doesn't make sense as
    its own container any more -- pop the last one back to the top level
    and remove the now-empty/pointless stack row."""
    stack = db.get_dashboard_widget(conn, stack_uid)
    if not stack or stack["type"] != "stack":
        return
    remaining = [w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid]
    if len(remaining) <= 1:
        _dissolve_stack(conn, stack)


@router.post("/dashboard/widgets/{uid}/stack-onto")
def stack_widget(uid: str, target_uid: str = Form(...), conn=Depends(get_db)):
    """Drag-onto-another-card target (static/app.js's dashboard drag
    handler posts here instead of /reorder when the drop lands in a
    card's center "stack" zone, not its top/bottom "reorder" edges) --
    merges `uid` into whatever stack `target_uid` belongs to, creating a
    new one first if target isn't already grouped. This is the actual
    fix for "small calendar on top, today's events directly under it,
    same width, and it stays that way" -- a plain auto-flow grid can't
    guarantee that pairing once anything else on the page changes size,
    but two widgets sharing one group_uid always render together in one
    card regardless of what else is on the dashboard."""
    if uid == target_uid:
        return JSONResponse({"error": "cannot stack a widget onto itself"}, status_code=400)
    moved = db.get_dashboard_widget(conn, uid)
    target = db.get_dashboard_widget(conn, target_uid)
    if moved is None or target is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if moved["type"] == "stack":
        # Stacks aren't nestable -- keeping this to one level deep avoids
        # a whole extra class of "what does resizing a stack-in-a-stack
        # even mean" questions for a feature whose whole point is "two
        # widgets, same width, stacked."
        return JSONResponse({"error": "a stack can't be stacked onto something else"}, status_code=400)
    if moved.get("space_uid") != target.get("space_uid") or moved.get("project_uid") != target.get("project_uid"):
        # A stack's members share one width/position range scoped to a
        # single page's grid (2026-08-02) -- stacking across Home and a
        # Space, or across two different Spaces/Projects, would leave the
        # stack only correctly orderable on whichever page rendered it
        # last. project_uid (2026-08-05) joins the identity check so a
        # project widget can't stack onto a Home/Space/other-project one.
        return JSONResponse({"error": "cannot stack widgets from different pages together"}, status_code=400)

    old_group = moved.get("group_uid")

    if target["type"] == "stack":
        stack_uid = target["uid"]
        after_position = None  # append at the end
    elif target.get("group_uid"):
        stack_uid = target["group_uid"]
        after_position = target["position"]  # land right after target within its stack
    else:
        # Target is an ordinary top-level widget, not yet grouped with
        # anything -- create the stack now, at target's own old position
        # and width, with target as its first member.
        stack_uid = str(uuid.uuid4())
        target_width = _widget_width(target, WIDGET_TYPES.get(target["type"]))["key"]
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": stack_uid,
                "type": "stack",
                "title": None,
                "config": {"width": target_width},
                "position": target["position"],
                "created_at": _now(),
                # Same page as the two widgets being merged (guaranteed
                # equal by the space_uid/project_uid check above).
                "space_uid": target.get("space_uid"),
                "project_uid": target.get("project_uid"),
            },
        )
        target = dict(target)
        target["group_uid"] = stack_uid
        target["position"] = 0.0
        db.upsert_dashboard_widget(conn, target)
        after_position = 0.0

    siblings = [w for w in db.list_all_dashboard_widgets(conn) if w.get("group_uid") == stack_uid and w["uid"] != uid]
    if after_position is None:
        new_position = (max((s["position"] for s in siblings), default=-1.0) + 1.0)
    else:
        later = [s["position"] for s in siblings if s["position"] > after_position]
        new_position = (after_position + min(later)) / 2.0 if later else after_position + 1.0

    moved["group_uid"] = stack_uid
    moved["position"] = new_position
    db.upsert_dashboard_widget(conn, moved)

    # If `moved` was itself the last widget holding some *other* stack
    # together, that stack no longer has enough members to justify
    # existing.
    if old_group and old_group != stack_uid:
        _dissolve_if_singleton(conn, old_group)

    return JSONResponse({"ok": True, "stack_uid": stack_uid})


@router.post("/dashboard/widgets/{uid}/unstack")
def unstack_widget(uid: str, edit: bool = Form(False), conn=Depends(get_db)):
    """The explicit "pop this one back out to the top level" control on
    each widget inside a stack -- the counterpart to stack-onto above.
    Plain redirecting POST like the rest of this router's non-drag
    actions (delete, edit), not a fetch target, since there's no
    optimistic client-side state worth preserving across it."""
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None or not widget.get("group_uid"):
        return RedirectResponse(url="/", status_code=303)
    space_uid = widget.get("space_uid")
    project_uid = widget.get("project_uid")
    stack_uid = widget["group_uid"]
    stack = db.get_dashboard_widget(conn, stack_uid)
    widget = dict(widget)
    widget["group_uid"] = None
    widget["position"] = db.next_dashboard_widget_position(conn, space_uid, project_uid)
    if stack:
        widget_config = dict(widget.get("config") or {})
        widget_config["width"] = (stack.get("config") or {}).get("width", widget_config.get("width"))
        widget["config"] = widget_config
    db.upsert_dashboard_widget(conn, widget)
    _dissolve_if_singleton(conn, stack_uid)
    return RedirectResponse(url=_return_url(space_uid, project_uid, edit), status_code=303)


@router.post("/dashboard/widgets/{uid}/delete")
def delete_widget(uid: str, edit: bool = Form(False), conn=Depends(get_db)):
    widget = db.get_dashboard_widget(conn, uid)
    if widget is not None:
        space_uid = widget.get("space_uid")
        project_uid = widget.get("project_uid")
        if widget["type"] == "stack":
            # Dissolve, don't destroy -- a stack is a layout grouping, not
            # a real owner of the widgets inside it, so removing it should
            # never take your Filters config for those widgets with it.
            _dissolve_stack(conn, widget)
            return RedirectResponse(url=_return_url(space_uid, project_uid, edit), status_code=303)
        stack_uid = widget.get("group_uid")
        db.delete_dashboard_widget(conn, uid)
        if stack_uid:
            _dissolve_if_singleton(conn, stack_uid)
        return RedirectResponse(url=_return_url(space_uid, project_uid, edit), status_code=303)
    db.delete_dashboard_widget(conn, uid)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/widgets/{uid}/move")
def move_widget(uid: str, direction: str = Form(...), edit: bool = Form(False), conn=Depends(get_db)):
    target_widget = db.get_dashboard_widget(conn, uid)
    if target_widget is None:
        return RedirectResponse(url="/", status_code=303)
    space_uid = target_widget.get("space_uid")
    project_uid = target_widget.get("project_uid")
    widgets = db.list_dashboard_widgets(conn, space_uid=space_uid, project_uid=project_uid)
    idx = next((i for i, w in enumerate(widgets) if w["uid"] == uid), None)
    if idx is None:
        return RedirectResponse(url=_return_url(space_uid, project_uid, edit), status_code=303)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(widgets):
        db.swap_dashboard_widget_positions(conn, widgets[idx]["uid"], widgets[swap_idx]["uid"])
    return RedirectResponse(url=_return_url(space_uid, project_uid, edit), status_code=303)


@router.post("/dashboard/widgets/{uid}/reorder")
def reorder_widget(uid: str, after_uid: str = Form(""), conn=Depends(get_db)):
    """JSON-free but still a POST (form body, not JSON, to match the rest
    of this router) drag-and-drop reorder target -- static/app.js's
    dashboard drag handler (edit-mode only) posts here after a drop
    instead of the old move-one-step-at-a-time /move endpoint above
    (still there, still tested, just no longer the UI's own path -- see
    plans/webapp-action-pipelines-audit.md's "reload per click" finding).
    `after_uid` is the uid of the widget this one should land immediately
    after in the new order, or "" to become the first widget -- computed
    client-side from wherever the card was dropped, same "read the final
    DOM order, tell the server where it landed" contract Kanban's own
    drag-and-drop uses for task status.

    Scoped to whichever collection `uid` itself already belongs to
    (2026-08-02) -- top-level widgets (group_uid IS NULL) if it's a plain
    widget or a stack container, or that stack's own members if it's
    inside one (static/app.js's intra-stack drag handler posts here too,
    not just the top-level one). `after_uid` has to belong to that same
    collection -- position values aren't comparable across a stack's
    members and the rest of the dashboard (see the group_uid migration
    comment in db.py), so an after_uid from the wrong collection is
    rejected rather than silently doing the wrong math."""
    moved = db.get_dashboard_widget(conn, uid)
    if moved is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Scoped to `moved`'s own page (space_uid/project_uid) as well as its
    # stack membership (group_uid, pre-existing) -- otherwise every page's
    # top-level widgets (group_uid IS NULL on all of them) would end up
    # compared against each other (2026-08-02, per-space widgets;
    # project_uid joined 2026-08-05 for per-project widgets).
    all_widgets = db.list_dashboard_widgets(conn, space_uid=moved.get("space_uid"), project_uid=moved.get("project_uid"))
    scope = moved.get("group_uid")
    others = [w for w in all_widgets if w["uid"] != uid and w.get("group_uid") == scope]

    if not after_uid:
        new_position = (others[0]["position"] - 1.0) if others else 0.0
    else:
        idx = next((i for i, w in enumerate(others) if w["uid"] == after_uid), None)
        if idx is None:
            return JSONResponse({"error": "after_uid not found in the same collection"}, status_code=400)
        if idx == len(others) - 1:
            new_position = others[idx]["position"] + 1.0
        else:
            new_position = (others[idx]["position"] + others[idx + 1]["position"]) / 2.0

    moved["position"] = new_position
    db.upsert_dashboard_widget(conn, moved)
    return JSONResponse({"ok": True})
