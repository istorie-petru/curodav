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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db, derived_state, recurrence_expand
from ..deps import EDIT_MODE_KEY, PAGE_HEADER_BANNER_SCOPE, get_db, templates

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


# Sentinel stored in config["tags"]/submitted via the Labels chip
# multiselect's `tags_labels` field (2026-08-31, direct feedback: "add a
# way to not select any label to filter by") -- distinct from an *empty*
# tags_filter, which already means "All" (no filter at all, see
# _widget_list_multiselect.html's own "filter" mode comment). This is the
# opposite: an explicit filter for items that carry *no* label at all,
# which nothing could express before (every real label name in tag_names
# is a possible checkbox value; there was no checkbox for "none of the
# above"). Never a real label name itself -- `_widget_builder_fields.html`/
# `_widget_edit_form.html` prepend a synthetic "No label" option carrying
# this exact value ahead of the real tag_name_items list, only inside the
# widget builder's own Labels field (not the plain-assignment Labels
# picker task_form/event_form/etc. reuse the same partial for, which never
# sets this sentinel as one of its real options).
NO_LABEL_SENTINEL = "__no_label__"


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
    `_filtered_events` call rather than per item.

    NO_LABEL_SENTINEL (2026-08-31) is an OR'd-in alternative match, not a
    real tag: an item passes if it has no tags at all AND the sentinel is
    selected, *or* it shares a real tag with whatever else is selected --
    same "matches any selected option" semantics multi-select filtering
    already has elsewhere, just with "no label" as one more option instead
    of a separate exclusive mode. Selecting only "No label" (real_tags
    empty) means only unlabeled items pass."""
    if not tags_filter:
        return True
    item_tags_set = set(item_tags or [])
    real_tags = set(tags_filter) - {NO_LABEL_SENTINEL}
    if NO_LABEL_SENTINEL in tags_filter and not item_tags_set:
        return True
    return bool(real_tags and (item_tags_set & real_tags))


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


def _filtered_events_expanded(conn, config: dict, window_start: date, window_end: date) -> list[dict]:
    """Same pool `_filtered_events` returns, but with every recurring row
    expanded into its real occurrences inside [window_start, window_end]
    first (routers/calendar.py's month/week/day views already do this via
    `recurrence_expand.expand_events` -- the Agenda widget never did, so a
    recurring event only ever showed up on the literal day its master row
    happened to be created on, then vanished from Today/This week/All
    upcoming forever after that one date passed. `db.list_events`'s own
    bounds clause already lets every recurring master row through
    regardless of `start`/`end` -- see its own docstring -- so the pool
    passed to `expand_events` here already has every candidate recurring
    row in it; this just turns each one into 0+ real occurrence rows dated
    inside the window instead of leaving it as its own unexpanded anchor)."""
    events = _filtered_events(conn, config)
    return recurrence_expand.expand_events(
        events,
        window_start,
        window_end,
        db.list_holidays_by_calendar(conn),
        db.list_event_occurrence_overrides_by_master(conn),
    )


# --------------------------------------------------------------------- #
# Widget renderers -- each takes (conn, config) and returns a plain dict
# the widget's partial template renders. Registered below in WIDGET_TYPES.
# --------------------------------------------------------------------- #


AGENDA_RANGES: tuple[str, ...] = ("today", "next_7_days", "next_30_days", "all_upcoming")
AGENDA_SHOWS: tuple[str, ...] = ("overdue", "tasks", "events")
AGENDA_DEFAULT_SHOW: list[str] = ["overdue", "tasks", "events"]


def _agenda_show(config: dict) -> set[str]:
    show = config.get("show")
    return set(show) if show is not None else set(AGENDA_DEFAULT_SHOW)


def _agenda_range(config: dict) -> str:
    range_ = config.get("range")
    if range_ in AGENDA_RANGES:
        return range_
    # Tolerates a not-yet-migrated or hand-built config that only has the
    # legacy `range_days` key (e.g. a preview call built before the range
    # string is resolved) -- best-effort translation, "today" is the safe
    # fallback for anything else.
    range_days = config.get("range_days")
    if range_days == 7:
        return "next_7_days"
    if range_days == 30:
        return "next_30_days"
    if range_days is None and "range_days" in config:
        return "all_upcoming"
    return "today"


def _render_agenda(conn, config: dict, nav: dict | None = None) -> dict:
    """Consolidated Agenda widget (2026-08-15 widget consolidation,
    plans/open.md § Widget consolidation) -- replaces the four separate
    today_agenda/weekly_overview/upcoming_events/overdue_tasks types with
    one configurable widget: Range (today / next 7 days / next 30 days /
    all upcoming) picks how far out to look, Show (overdue / tasks /
    events, independent checkboxes) picks which sections render.

    "Overdue" is always every currently-open overdue task regardless of
    Range -- Range only bounds the forward-looking Tasks/Events sections.
    Today and Next 7 days are the only two ranges still shaped for their
    own old widget: Today renders a flat single-day list (`mode: "flat"`,
    same shape today_agenda used); Next 7 days renders day-by-day
    (`mode: "days"`, same shape weekly_overview used, plus an Overdue
    section ahead of the grid when that's shown too) -- 7 boxes is still
    small enough to read at a glance. Next 30 days and All upcoming both
    render the same flat, `limit`-capped chronological list (2026-08-31
    direct feedback: "next 30 days range css should look like all
    upcoming" -- a 30-cell day-by-day grid was mostly empty boxes and
    harder to scan than a flat list); Next 30 days bounds Tasks/Events to
    its own 30-day window, All upcoming leaves Tasks unbounded forward and
    only windows Events for recurrence-expansion purposes (every future
    event, unbounded -- upcoming_events' own semantics)."""
    show = _agenda_show(config)
    range_ = _agenda_range(config)
    today = date.today()
    today_iso = today.isoformat()
    # `0` means "unlimited" (2026-08-31 direct feedback) -- `config.get
    # ("limit")` can legitimately be the int `0` now (see _config_from_form,
    # which already stores it verbatim), so this can't collapse falsy-0
    # into the "not set" default the way `... or 10` used to; only an
    # absent/None config value falls back to 10.
    _raw_limit = config.get("limit")
    limit = int(_raw_limit) if _raw_limit is not None else 10

    overdue_tasks: list[dict] = []
    if "overdue" in show:
        overdue_tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and t["due_at"][:10] < today_iso]
        overdue_tasks.sort(key=lambda t: t["due_at"])

    if range_ == "today":
        tasks = []
        if "tasks" in show:
            tasks = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and t["due_at"][:10] == today_iso]
            tasks.sort(key=lambda t: t["due_at"])
        events = []
        if "events" in show:
            events = [e for e in _filtered_events_expanded(conn, config, today, today) if e.get("start_at") and e["start_at"][:10] == today_iso]
            events.sort(key=lambda e: e.get("start_at") or "")
        return {"mode": "flat", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "tasks": tasks, "events": events, "today": today_iso}

    if range_ == "next_7_days":
        end = today + timedelta(days=6)
        days = [(today + timedelta(days=i)) for i in range(7)]

        tasks_pool: list[dict] = []
        if "tasks" in show:
            tasks_pool = [t for t in _filtered_tasks(conn, config) if t.get("due_at") and today_iso <= t["due_at"][:10] <= end.isoformat()]
        events_pool: list[dict] = []
        if "events" in show:
            events_pool = _filtered_events_expanded(conn, config, today, end)

        by_day = []
        for d in days:
            iso = d.isoformat()
            day_tasks = sorted(
                [t for t in tasks_pool if t["due_at"][:10] == iso],
                key=lambda t: (t.get("title") or "").lower(),
            )
            day_events = sorted([e for e in events_pool if e.get("start_at") and e["start_at"][:10] == iso], key=lambda e: e.get("start_at") or "")
            by_day.append({"date": iso, "label": d.strftime("%a %b %d"), "is_today": iso == today_iso, "tasks": day_tasks, "events": day_events})
        return {"mode": "days", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "days": by_day, "today": today_iso}

    # next_30_days / all_upcoming -- same flat-list shape; only the window
    # each bounds Tasks/Events to differs (see this function's own
    # docstring).
    task_end_iso = None if range_ == "all_upcoming" else (today + timedelta(days=29)).isoformat()
    # A window end far enough out that even a yearly-recurring event still
    # produces its next occurrence (same generous cap
    # `_is_long_lived_recurrence` above uses for the same reason) --
    # Next 30 days windows Events to its own real 30-day span instead.
    event_window_end = (today + timedelta(days=730)) if range_ == "all_upcoming" else (today + timedelta(days=29))

    tasks = []
    if "tasks" in show:
        tasks = [
            t for t in _filtered_tasks(conn, config)
            if t.get("due_at") and t["due_at"][:10] >= today_iso and (task_end_iso is None or t["due_at"][:10] <= task_end_iso)
        ]
        tasks.sort(key=lambda t: t["due_at"])
        if limit:
            tasks = tasks[:limit]
    events = []
    if "events" in show:
        # Local naive "now" -- same convention `date.today()`/
        # `datetime.now().hour` already use everywhere else in this file
        # (see `_greeting_for_hour`'s own comment) for "no separate
        # timezone handling introduced here". `start_at` is stored exactly
        # as the event form's local `datetime-local` input sends it (see
        # routers/calendar.py's create_event) -- naive local wall-clock
        # text, not a UTC-aware ISO string. Comparing that against
        # `datetime.now(timezone.utc)` (this branch's old behavior) mixed
        # a UTC clock reading with locally-stored strings and mis-filtered
        # by exactly the server's UTC offset -- a recently-started local
        # event could still read as "upcoming" (or a genuinely upcoming
        # one as already past), depending on which side of midnight UTC
        # the comparison landed on.
        now_str = datetime.now().isoformat()
        # db.list_events' own `start` filter is "(end_at IS NULL OR end_at
        # >= start)" -- deliberately permissive so an ongoing/no-end-date
        # event doesn't disappear from a filtered range it's still
        # "within". That's the right behavior for a calendar view, but
        # wrong for "upcoming": an event that already started (no end
        # date) shouldn't count as upcoming just because it has no end.
        # Filter on start_at explicitly here rather than relying on
        # list_events' own start param alone.
        events = [e for e in _filtered_events_expanded(conn, config, today, event_window_end) if e.get("start_at") and e["start_at"] >= now_str]
        events.sort(key=lambda e: e.get("start_at") or "")
        if limit:
            events = events[:limit]
    return {"mode": "flat", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "tasks": tasks, "events": events, "today": today_iso}


def _render_at_a_glance(conn, config: dict, nav: dict | None = None) -> dict:
    """At-a-glance stats strip (dashboard usability rework, 2026-08-07) --
    counts over the exact same open-tasks pool `_render_overdue_tasks`/
    `_render_today_agenda`/`_render_weekly_overview` already query (via
    `_filtered_tasks`, so this is correctly scoped to a label page now that
    the `_effective_tags_filter` fix applies there too): Overdue, Due
    today, Due this week. Every widget type here renders a *list*; this is
    the one that renders a *number*, so "how am I doing" is answerable in
    under two seconds without reading through any other widget's content.

    Zero counts still render (not hidden/suppressed) -- confirming
    "nothing's overdue" is itself useful information for an at-a-glance
    widget, not an empty state to hide.

    The counts come from src/derived_state.py's shared aggregation service
    (1.1, plans/open-priority.md § Virtual & derived states): ONE pass over
    the scoped pool computing every per-state count through `count_by_state`
    -- state names match `count_by_state`'s own keys, so "3 overdue" is a
    real, already-filtered destination, not a number you have to go
    re-derive yourself, and the count and the filter view can never
    disagree.

    Tasks page filter cleanup (2026-08-15, plans/open.md): `overdue` moved
    from a `date_filter` value to a `status_filter` value.

    2026-08-28 "major rework" session update: Status filtering is gone from
    the Tasks page entirely now (item 3, "filtering reduced to date only")
    -- there's no longer a filtered-view destination for overdue to link
    to, only Date's `today`/`this_week` survive. `overdue_link` now points
    at the plain Table view (still a real, useful destination -- the count
    itself, computed independently via count_by_state, is unaffected either
    way); `today_link`/`week_link` are unchanged since `date_filter` is
    still live. The Important/Urgent stat blocks this widget used to show
    (1.1) are removed along with the rest of that feature -- see
    src/derived_state.py's module docstring."""
    tasks = _filtered_tasks(conn, config)
    counts = derived_state.count_by_state(tasks)

    def _tasks_link(param: str | None = None, value: str | None = None) -> str:
        if not param:
            return "/tasks"
        return f"/tasks?{param}={value}"

    return {
        "overdue_count": counts["overdue"],
        "today_count": counts["today"],
        "week_count": counts["this_week"],
        "overdue_link": _tasks_link(),
        "today_link": _tasks_link("date_filter", "today"),
        "week_link": _tasks_link("date_filter", "this_week"),
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


def _render_spaces_projects(conn, config: dict, nav: dict | None = None) -> dict:
    """Consolidated Spaces & Projects widget (2026-08-15 widget
    consolidation, plans/open.md § Widget consolidation) -- replaces the
    two separate project_preview/filled_cards types with one, switched by
    `config["style"]` ("list", the default, or "cards"). List reuses
    project_preview's own rows (a project/label + progress bar); Cards
    reuses filled_cards' own Material-You-style filled squares (one per
    Space). Both styles honor `config["label_name"]` the same way
    project_preview always did -- scoped to that label's own children
    (projects AND sub-Spaces both, db.list_child_labels doesn't
    distinguish -- a Space's "children" were always both kinds structurally,
    nothing new needed there) on a Space/Project page, every top-level
    label/Space on Home.

    `config["scope"]` (2026-08-15, expanded scope) -- a Space/Project
    page's widget is auto-scoped to that page via `label_name`
    (widget_page_context/add_widget's own auto-scope), which used to be
    the only option: there was no way to place a "show literally
    everything, every Space/project app-wide" instance of this widget on
    a Space's own dashboard. `scope == "everything"` opts a single widget
    instance out of that auto-scoping and renders exactly like the Home/
    unscoped case instead -- a per-instance override, not a second widget
    type (per plans/open.md's own framing of this ask). Default ("space")
    preserves every existing/migrated widget's current behavior
    unchanged.

    2026-08-30 merge: the "cards" style now also includes every open
    (non-archived) project when unscoped -- direct request ("merge the
    quick links and spaces & projects into one data source"). The
    now-retired Quick Links widget rendered the exact same
    `.filled-cards-grid` tiles for "every Space + every open project"
    (Home-only, no config); this style already rendered a subset of that
    (Spaces only) when unscoped. Scoped instances (`label_name` set, a
    Space/Project page) are unaffected -- `db.list_child_labels` already
    pools both projects and sub-Spaces under that label, unlike this
    unscoped branch which otherwise only ever saw `list_space_labels`."""
    style = config.get("style") or "list"
    label_name = config.get("label_name") if config.get("scope") != "everything" else None
    if label_name:
        labels = db.list_child_labels(conn, label_name)
    elif style == "cards":
        labels = db.list_space_labels(conn)
    else:
        labels = [lbl for lbl in db.list_labels(conn) if not lbl.get("generate_space")]

    if style == "cards":
        cards = []
        for lbl in labels:
            children = db.list_child_labels(conn, lbl["name"])
            # `labels` here can be a Space's own children (label_name set),
            # which -- per this function's docstring -- pools BOTH
            # sub-Spaces and promoted projects; a project among them needs
            # its own page (routers/projects.py), not the /spaces/ URL a
            # sub-Space gets. When unscoped, `labels` is list_space_labels
            # (Spaces only), so this is a no-op fallthrough there.
            href = f"/spaces/{lbl['name']}" if lbl.get("generate_space") else (
                f"/projects/{lbl['name']}" if lbl.get("is_project") else f"/settings/labels/{lbl['name']}"
            )
            cards.append({
                "uid": lbl["name"],
                "name": lbl["name"],
                "href": href,
                "icon": lbl.get("icon") or "layers",
                "color": lbl.get("color") or "blue",
                "description": lbl.get("description") or "",
                "meta": f"{len(children)} project{'' if len(children) == 1 else 's'}",
            })
        if not label_name:
            # Unscoped (Home, or a scoped instance opted out via
            # scope=="everything") -- fold in every open project too, same
            # "every Space + every open project" set Quick Links used to
            # render on its own. Not reachable when label_name is set: that
            # branch already sourced `labels` from list_child_labels above,
            # which pools projects in directly -- adding them again here
            # would duplicate every project card on a Space/Project page.
            for lbl in db.list_project_labels(conn):
                if lbl.get("archived_at"):
                    continue
                cards.append({
                    "uid": lbl["name"],
                    "name": lbl["name"],
                    # 2026-08-30: /projects/{name} is real again (a Kanban
                    # board, routers/projects.py::project_detail) -- was
                    # "/tasks" while the page was a redirect stub
                    # (2026-08-15 through 2026-08-30, see that history in
                    # this file's git log).
                    "href": f"/projects/{lbl['name']}",
                    "icon": lbl.get("icon") or "folder",
                    "color": lbl.get("color") or "blue",
                    "description": "",
                    "meta": "Project",
                })
        return {"style": "cards", "cards": cards}

    # Progress is derived from direct object_labels membership (tasks
    # tagged with that label) -- direct assignment only, same "not
    # transitive through parent_name" rule every label-page query in this
    # app follows.
    previews = []
    for lbl in labels:
        tasks = [t for t in db.list_tasks(conn) if lbl["name"] in (t.get("tags") or [])]
        total = len(tasks)
        done = len([t for t in tasks if t["status"] in ("done", "archived")])
        progress = round(100 * done / total) if total else None
        previews.append({"project": lbl, "progress": progress, "tasks_done": done, "tasks_total": total})
    return {"style": "list", "previews": previews}


# _render_streak/_render_next_deadline/_render_organize_today (2026-08-15
# widget consolidation types) removed 2026-08-30, direct request ("maybe
# just remove the next deadline, what needs organizing and streak widgets
# - not really that useful"). See _migrate_widget_removal's own comment
# for how existing instances of these three types are cleaned up on a
# live dashboard.


# The 2026-08-15 "Weekly Schedule" widget's own threshold for "this
# recurring event is really a standing timetable pattern, not a short-
# lived recurring reminder" -- see _render_weekly_schedule's own
# docstring for how it's measured.
_WEEKLY_SCHEDULE_MIN_SPAN_DAYS = 30
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _minutes_of_day(iso_dt: str) -> int:
    """Minutes since midnight from an "...THH:MM..." string -- local copy
    of grid_layout._minutes' own trivial slice (that module's own function
    is private, and this is a one-line calculation, same "not worth
    exposing a private helper across a module boundary" reasoning
    _hours_between's own copy at the top of this file already used)."""
    return int(iso_dt[11:13]) * 60 + int(iso_dt[14:16])


def _is_long_lived_recurrence(event: dict) -> bool:
    """Whether `event`'s own recurrence rule spans at least
    `_WEEKLY_SCHEDULE_MIN_SPAN_DAYS` from its first to its last occurrence
    -- filters a short-lived recurring reminder (e.g. a 3-day daily pill
    reminder, COUNT=3) out of the Weekly Schedule widget, while keeping
    anything that reads as a real standing pattern (a semester's worth of
    twice-weekly lectures, or a literally open-ended recurring event).
    Expands the event on its own, from its own start date out to a
    generous 2-year cap (`recurrence_expand.expand_events` takes a shared
    window, not a per-event one, so this calls it once per candidate
    rather than trying to force every candidate through one shared window)
    -- an open-ended rule (no UNTIL/COUNT) naturally produces occurrences
    spanning nearly the whole 2-year window, so it qualifies without a
    separate "has no end condition" branch; a rule that legitimately ends
    within `_WEEKLY_SCHEDULE_MIN_SPAN_DAYS` of its own start is correctly
    excluded either way. Malformed/unparseable rules degrade to `False`
    (excluded, not crashed -- expand_events itself already degrades a
    malformed row to a single non-expanded occurrence, which is 1 row,
    below the "at least 2 occurrences" floor this function also checks)."""
    if not event.get("start_at"):
        return False
    try:
        start_date = date.fromisoformat(event["start_at"][:10])
    except ValueError:
        return False
    window_end = start_date + timedelta(days=730)
    occurrences = recurrence_expand.expand_events([event], start_date, window_end)
    occ_dates = sorted({o["start_at"][:10] for o in occurrences if o.get("start_at")})
    if len(occ_dates) < 2:
        return False
    span = (date.fromisoformat(occ_dates[-1]) - date.fromisoformat(occ_dates[0])).days
    return span >= _WEEKLY_SCHEDULE_MIN_SPAN_DAYS


def _render_weekly_schedule(conn, config: dict, nav: dict | None = None) -> dict:
    """Weekly Schedule widget (2026-08-15, new type, plans/open.md's
    "small schedule calendar... statically... a way to show the
    university schedule" ask) -- a compact, STATIC weekly-pattern view of
    a label's long-lived recurring events (see _is_long_lived_recurrence),
    deliberately lighter than the removed Schedule module (plans/
    abandoned.md, 2026-08-15): no new data model, no course/semester
    fields, purely a presentation over ordinary recurring Calendar events
    that already exist -- add a class as a normal weekly (optionally
    every-2-weeks) recurring event and it shows up here automatically.

    "Static" is the operative word: every qualifying event's grid slot
    comes straight from its own `start_at`/`end_at` time-of-day and
    `start_at`'s weekday, not from expanding any one real calendar week.
    This is correct, not a shortcut -- `FREQ=WEEKLY` (optionally
    `INTERVAL=2` for the odd/even-week presets, see recurrence_picker.js)
    always recurs on the exact weekday/time of its own anchor, so no
    occurrence expansion is needed for *display*, only for the long-lived
    *qualification* check. A real week's holidays/manual exceptions are
    deliberately not reflected -- this widget answers "what does my
    typical week look like," not "what's actually on the calendar this
    particular week" (that's Agenda's job).

    Grid geometry is computed here, not via grid_layout.py's 24-hour Week/
    Day grid math -- reusing that would render mostly empty space for a
    widget whose whole point is showing just a handful of class-shaped
    blocks; the grid's own vertical range is tightened to
    (earliest start - 30min) .. (latest end + 30min) across every
    qualifying event, and only weekdays that actually have a block become
    columns (no blank Saturday/Sunday column for a Mon/Wed/Fri course
    load). A companion agenda-style list (day + time + title, sorted by
    weekday then time) renders below the grid -- the grid's blocks
    necessarily truncate a longer title, and pairing it with a plain
    readable list is what makes a handful of narrow colored blocks not
    read as "a lot of dead space with three thin bars in it".

    Excludes `all_day` events (2026-08-30 bug fix) -- an all-day event has
    no time-of-day to place on this grid, and its `start_at` isn't even
    guaranteed to carry one: contact-birthday sync (db.sync_contact_
    birthday_event) writes a bare "1900-MM-DD" (no "THH:MM"), which
    crashed `_minutes_of_day`'s fixed-offset slice on any dashboard with a
    Weekly Schedule widget whose label matched a birthday'd contact --
    reachable by just adding a birthday, not an edge case. Same exclusion
    grid_layout.py's `layout_day` already applies before its own
    time-of-day math, for the same reason -- all-day events get their own
    separate strip there, and have no place in a purely time-slotted grid
    like this one either."""
    events = [
        e for e in _filtered_events(conn, config)
        if e.get("recurrence") and e.get("start_at") and not e.get("all_day")
    ]
    long_lived = [e for e in events if _is_long_lived_recurrence(e)]

    items = []
    for e in long_lived:
        start_min = _minutes_of_day(e["start_at"])
        end_min = _minutes_of_day(e["end_at"]) if e.get("end_at") else start_min + 60
        if end_min <= start_min:
            end_min = start_min + 60
        items.append({
            "event": e,
            "weekday": date.fromisoformat(e["start_at"][:10]).weekday(),
            "start_min": start_min,
            "end_min": end_min,
            "biweekly": "INTERVAL=2" in (e.get("recurrence") or ""),
        })

    if not items:
        return {"days": [], "agenda_rows": []}

    grid_start_min = max(0, min(i["start_min"] for i in items) - 30)
    grid_end_min = min(24 * 60, max(i["end_min"] for i in items) + 30)
    span_min = max(grid_end_min - grid_start_min, 60)

    days = []
    for wd in sorted({i["weekday"] for i in items}):
        blocks = []
        for i in sorted((i for i in items if i["weekday"] == wd), key=lambda i: i["start_min"]):
            top_pct = round((i["start_min"] - grid_start_min) / span_min * 100, 2)
            height_pct = max(round((i["end_min"] - i["start_min"]) / span_min * 100, 2), 4.0)
            blocks.append({"event": i["event"], "top_pct": top_pct, "height_pct": height_pct, "biweekly": i["biweekly"]})
        days.append({"weekday": wd, "label": _WEEKDAY_LABELS[wd], "blocks": blocks})

    agenda_rows = sorted(items, key=lambda i: (i["weekday"], i["start_min"]))

    return {"days": days, "agenda_rows": agenda_rows}


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
    # `0` means "unlimited" -- see _render_agenda's own comment on the same
    # `config.get("limit")` pattern for why `... or 20` can't be used here
    # any more now that `0` is a legitimate stored value, not "unset".
    _raw_limit = config.get("limit")
    limit = int(_raw_limit) if _raw_limit is not None else 20
    return {"contacts": contacts[:limit] if limit else contacts}


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


def _render_scheduled_work_today(conn, config: dict, nav: dict | None = None) -> dict:
    """Scheduled Work Hours Today -- today's work-allocation sessions plus a
    completed/total hours readout (1.9 side work, porting routers/today.py's
    own "scheduled hours today" computation, the other piece /today had that
    no existing widget covered -- see plans/STATE.md). Scoped like every
    other widget via `_filtered_events`.

    /today also had an "Important & urgent, not due today" section, ported
    to its own Dashboard widget type at the same time -- that widget type
    (and the whole Importance/Urgency feature behind it) is now removed;
    see src/derived_state.py's module docstring."""
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


# Grid width -- there used to be a manual width picker/drag-resize here
# (a "half"/"full" flag on WIDGET_TYPES, then from 2026-08-01 a per-
# widget-instance override living in config["width"], picked from the
# Filters panel or dragged from the card's own resize handle), removed
# 2026-08-07 alongside the manual height picker/drag-resize, per the same
# direct feedback: automatic, content-driven sizing, no manual override.
# `_widget_width` used to always return a widget's *type's* own
# `default_width` -- see WIDGET_TYPES -- the real "what does this content
# naturally need" signal (e.g. At a Glance is just three numbers, so it's
# a third; Weekly Overview is a 7-day-wide grid, so it's the full row).
#
# Manual per-instance width REINSTATED 2026-08-30 -- direct request after
# the automatic masonry layout (static/app.js) still produced an
# arrangement the user didn't want, even after a same-day best-fit
# packing pass: "can't we have a width setting in edit mode (100%,75%,
# 50%,25%), or maybe actually fix the automatic one." Given this
# environment has no browser to visually verify a layout-algorithm change
# against, and the automatic approach had already been iterated on twice
# in the same session without landing on something the user was happy
# with, manual control is the more reliable fix. This reverses the
# 2026-08-07 decision above for WIDTH specifically -- height's own
# removal (`.widget-content`'s single flat max-height) is untouched, no
# per-widget height concept came back.
#
# Grid widened from 6 to 12 virtual columns (static/app.js's `maxCols` --
# the grid is absolutely-positioned by JS, not a real CSS grid, so there's
# no grid-template-columns to also update) at the same time --
# 6 has no integer quarter/three-quarter, so a literal 25%/75% option
# needs a column count divisible by 4. Every existing span was simply
# doubled (third 2->4, half 3->6, two_thirds 4->8, full 6->12) --
# identical real-world widths, `span/cols` unchanged (2/6 == 4/12 etc.)
# -- with two new keys added at the now-exact quarter/three-quarters
# marks. `.widget-card[data-span="…"]` CSS (static/style.css, the At a
# Glance narrow-width font scaling) and every comment elsewhere in this
# file/style.css that said "out of 6"/"6 virtual columns" were updated to
# match. `_widget_width` below now checks a widget instance's own
# `config["width"]` first (if it's one of the four percentages the Width
# field offers, WIDGET_WIDTH_CHOICES) before falling back to its type's
# `default_width`, same as before this reversal.
WIDGET_WIDTHS: dict[str, dict] = {
    "quarter": {"label": "1/4 width", "span": 3},
    "third": {"label": "1/3 width", "span": 4},
    "half": {"label": "1/2 width", "span": 6},
    "two_thirds": {"label": "2/3 width", "span": 8},
    "three_quarters": {"label": "3/4 width", "span": 9},
    "full": {"label": "Full width", "span": 12},
}

# The four percentages actually offered by the Width field (2026-08-30) --
# "third"/"two_thirds" stay reachable only as a WIDGET_TYPES default
# (At a Glance, Contact List, etc.), not as something a user picks by
# hand; the field literally asked for was "100%,75%,50%,25%", not six
# choices, so the picker only exposes the four that map onto it.
WIDGET_WIDTH_CHOICES: tuple[str, ...] = ("quarter", "half", "three_quarters", "full")


def _widget_width(widget: dict, spec: dict | None) -> dict:
    """A widget's width: its own `config["width"]` if it's one of
    `WIDGET_WIDTH_CHOICES` (2026-08-30, reinstated manual override -- see
    this section's own header comment for why), else its type's
    `default_width` -- unchanged from the 2026-08-07 automatic-only
    behavior for any widget that never sets one.

    A stack (type="stack") has no WIDGET_TYPES entry -- it's not "content"
    of its own, just a container of 1+ other widgets grouped by a drag-
    onto-another-widget interaction -- so it has no `default_width` to
    fall back on. It keeps reading its own stored config["width"] instead,
    seeded once at creation time from whichever widget triggered the
    stack (stack_widget below) or from _DEFAULT_STACK_CONFIG for the
    seed-time Space/Project stack, and never edited after that (no Edit/
    Filters form renders for a stack's own top-level card, only for the
    member widgets inside it -- see _widget_workspace.html's stack
    header) -- this is what lets every member of a stack share one width
    so they visually align in a single card (only the stack's own
    top-level card carries `data-span`; see _widget_workspace.html).
    Falls back to "half" if that stored value isn't a real key (e.g.
    never set)."""
    config = widget.get("config") or {}
    if spec is not None and config.get("width") in WIDGET_WIDTH_CHOICES:
        key = config["width"]
    elif spec is None:
        key = config.get("width")
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
        # `.widget-card[data-span="3"|"4"|"6"]` font-scaling rule for this
        # widget written for exactly this narrower width (span numbers
        # doubled 2026-08-30, see WIDGET_WIDTHS' own comment), which was
        # otherwise unreachable dead CSS as long as this default was "full".
        "default_width": "third",
    },
    # "agenda" (2026-08-15 widget consolidation, plans/open.md § Widget
    # consolidation) -- replaces today_agenda/weekly_overview/
    # upcoming_events/overdue_tasks (4 types -> 1, Range + Show config
    # toggles instead of 4 separate names). "half" (today_agenda's own
    # old default) rather than weekly_overview's old "full" -- the
    # flat/today mode most widgets use (including the seeded default) is
    # the common case; a multi-day grouped Range still renders fine, just
    # a little tighter, with no manual per-instance width override to
    # reach for either way (see _widget_width's own docstring).
    "agenda": {
        "label": "Agenda",
        "template": "_widget_agenda.html",
        "render": _render_agenda,
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
    # "spaces_projects" (2026-08-15 widget consolidation) -- replaces
    # project_preview/filled_cards (2 types -> 1, a List/Cards style
    # toggle instead of 2 separate names).
    "spaces_projects": {
        "label": "Spaces & Projects",
        "template": "_widget_spaces_projects.html",
        "render": _render_spaces_projects,
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
    "contact_list": {
        "label": "Contact List",
        "template": "_widget_contact_list.html",
        "render": _render_contact_list,
        "uses": set(),
        "default_width": "third",
    },
    "scheduled_work_today": {
        "label": "Scheduled Work Hours Today",
        "template": "_widget_scheduled_work_today.html",
        "render": _render_scheduled_work_today,
        "uses": {"events"},
        "default_width": "third",
    },
    # "quick_links" (1.9 side work) retired 2026-08-30 -- merged into
    # "spaces_projects"'s own "cards" style (direct request, "merge the
    # quick links and spaces & projects into one data source"); see
    # _render_spaces_projects's own 2026-08-30 comment. "streak"/
    # "next_deadline"/"organize_today" (2026-08-15 widget consolidation)
    # removed the same day, direct request ("not really that useful") --
    # see the comment where their render functions used to be, above.
    # "weekly_schedule" (2026-08-15, new type) -- see
    # _render_weekly_schedule's own docstring. "half" width: a compact
    # grid + a short list, more content than a bare stat widget but not a
    # full 6-column-wide grid either.
    "weekly_schedule": {
        "label": "Weekly Schedule",
        "template": "_widget_weekly_schedule.html",
        "render": _render_weekly_schedule,
        "uses": {"events"},
        "default_width": "half",
    },
}

# --------------------------------------------------------------------- #
# Source / View / Range -- 2026-08-02 rework of how a widget gets picked.
# WIDGET_TYPES above is unchanged and still the actual storage/rendering
# mechanism -- what changed is the *picker* in front of it: three
# independent choices, what data (Source), how it's laid out (View), and
# how far out (Range, only where it means something) -- and
# _resolve_selection below maps that triple onto one of WIDGET_TYPES'
# `type` keys plus whatever extra config that type needs (e.g. Agenda's
# `range`/`show`). _selection_from_widget does the reverse, so the
# per-widget Filters form can show an existing widget's Source/View/Range
# pre-selected instead of just its opaque type name.
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
    "habits": {"label": "Habits", "icon": "activity"},
    "contacts": {"label": "Contacts", "icon": "users"},
    # "spaces_projects" (2026-08-15 widget consolidation) -- re-added to
    # the builder as its own source now that it's one clean List/Cards
    # widget instead of two ("projects" was purged from the picker
    # entirely 2026-08-07 while project_preview/filled_cards were still
    # two separate, harder-to-explain types; see that comment's own
    # history in this file's git log). Reads label_config directly, no
    # tasks/events at all (`"uses": set()` in WIDGET_TYPES).
    #
    # "quick_links" (1.9 side work, its own source for the same reason)
    # retired 2026-08-30 -- its "every Space + every open project" tile
    # grid merged into this source's own "cards" style (Style radio, see
    # WIDGET_VIEWS' spaces_projects_view/has_style below) rather than
    # staying a second, harder-to-explain source next to this one.
    "spaces_projects": {"label": "Spaces & Projects", "icon": "layers"},
}

# Which views exist per source, and which of those views take a Range.
# `has_show` (2026-08-15) marks the one view (Agenda) whose builder form
# also exposes the Show checkboxes (tasks/events/overdue); absent/False
# everywhere else, read via `.get("has_show")` so existing entries don't
# all need the key added.
WIDGET_VIEWS: dict[str, dict] = {
    # "agenda_view" (2026-08-15 widget consolidation) -- replaces the
    # three separate "agenda"/"upcoming_list"/"overdue_list" views; which
    # of those three the old picker offered is now the Show checkboxes
    # inside this one view instead (see _widget_builder_fields.html).
    "agenda_view": {"label": "Agenda", "source": "calendar_tasks", "has_range": True, "has_show": True, "has_limit": True},
    "at_a_glance_view": {"label": "At a glance (stats)", "source": "calendar_tasks", "has_range": False},
    "mini_calendar": {"label": "Mini calendar", "source": "calendar_tasks", "has_range": False},
    "checklist": {"label": "Checklist", "source": "habits", "has_range": False},
    # `has_limit` (2026-08-15, expanded scope: "widgets should be more
    # customizable") -- contact_list's own render function already reads
    # `config["limit"]` (`_render_contact_list`), but the builder never
    # offered a way to set it -- a real, narrow customizability gap, not
    # the "Range/Show/Style toggles already cover it" case. Fixed by
    # generalizing the Limit field's gate from a single hardcoded view name
    # to this flag, same `has_range`/`has_show`/`has_style` pattern.
    "contact_list_view": {"label": "Contact list", "source": "contacts", "has_range": False, "has_limit": True},
    "scheduled_work_view": {"label": "Scheduled work hours today", "source": "calendar_tasks", "has_range": False},
    # "spaces_projects_view" (2026-08-15 widget consolidation) -- exposes
    # the List/Cards Style radio (see _widget_builder_fields.html), same
    # gating idea as Agenda's has_show. "quick_links_view"/"streak_view"/
    # "next_deadline_view"/"organize_today_view" retired 2026-08-30 along
    # with their widget types -- see WIDGET_TYPES' own comment.
    "spaces_projects_view": {"label": "Spaces & Projects", "source": "spaces_projects", "has_range": False, "has_style": True},
    "weekly_schedule_view": {"label": "Weekly schedule", "source": "calendar_tasks", "has_range": False},
}

WIDGET_RANGES: dict[str, dict] = {
    "today": {"label": "Today", "views": {"agenda_view"}},
    "next_7_days": {"label": "Next 7 days", "views": {"agenda_view"}},
    "next_30_days": {"label": "Next 30 days", "views": {"agenda_view"}},
    "all_upcoming": {"label": "All upcoming", "views": {"agenda_view"}},
}

# (view, range) -> (type, extra_config). `range` is only ever looked up
# for views where WIDGET_VIEWS[view]["has_range"] is True; the other
# views have exactly one valid mapping regardless of whatever range came
# in. `extra_config` is merged into the widget's stored config on top of
# whatever _config_from_form already built from Title/Labels/Limit/Style/
# Show -- Agenda's own `range`/(default) `show` land here so a fresh
# widget starts with sane defaults even before any Show checkbox is
# touched.
#
# The pre-consolidation (view, range) keys ("agenda"/"upcoming_list"/
# "overdue_list"/"cards"/"filled_cards_view"/"calendar_agenda_view") are
# NOT kept as dead entries here (unlike the 2026-08-07 Projects-purge
# precedent) -- every dashboard row using them is rewritten in place by
# `_migrate_widget_consolidation` the moment this version runs, so no
# live widget can still be carrying one; _resolve_selection's own
# fallback (an unrecognized view resolves to the first valid view for
# the source) covers any stale/forged submission just as safely.
_SELECTION_TO_TYPE: dict[tuple[str, str | None], tuple[str, dict]] = {
    ("agenda_view", "today"): ("agenda", {"range": "today"}),
    ("agenda_view", "next_7_days"): ("agenda", {"range": "next_7_days"}),
    ("agenda_view", "next_30_days"): ("agenda", {"range": "next_30_days"}),
    ("agenda_view", "all_upcoming"): ("agenda", {"range": "all_upcoming"}),
    ("at_a_glance_view", None): ("at_a_glance", {}),
    ("mini_calendar", None): ("mini_month_calendar", {}),
    ("checklist", None): ("habit_checkin", {}),
    ("contact_list_view", None): ("contact_list", {}),
    ("scheduled_work_view", None): ("scheduled_work_today", {}),
    ("spaces_projects_view", None): ("spaces_projects", {}),
    ("weekly_schedule_view", None): ("weekly_schedule", {}),
}

# Reverse of the above, for pre-filling the edit form from an existing
# widget's stored `type` (+ `config.range` for Agenda). See
# _selection_from_widget for the type-aware key it builds.
_TYPE_TO_SELECTION: dict[tuple[str, str | None], tuple[str, str, str | None]] = {
    ("agenda", "today"): ("calendar_tasks", "agenda_view", "today"),
    ("agenda", "next_7_days"): ("calendar_tasks", "agenda_view", "next_7_days"),
    ("agenda", "next_30_days"): ("calendar_tasks", "agenda_view", "next_30_days"),
    ("agenda", "all_upcoming"): ("calendar_tasks", "agenda_view", "all_upcoming"),
    ("at_a_glance", None): ("calendar_tasks", "at_a_glance_view", None),
    ("mini_month_calendar", None): ("calendar_tasks", "mini_calendar", None),
    ("spaces_projects", None): ("spaces_projects", "spaces_projects_view", None),
    ("habit_checkin", None): ("habits", "checklist", None),
    ("contact_list", None): ("contacts", "contact_list_view", None),
    ("scheduled_work_today", None): ("calendar_tasks", "scheduled_work_view", None),
    ("weekly_schedule", None): ("calendar_tasks", "weekly_schedule_view", None),
}


def _resolve_selection(source: str, view: str, range_: str | None) -> tuple[str, dict]:
    """(source, view, range) from the form -> (type, extra_config) to
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
    """Stored widget -> (source, view, range) to pre-select in the form.
    Agenda is keyed on its own `config["range"]` string (defaulting to
    "today" for a not-yet-migrated/hand-built config, via `_agenda_range`
    -- same tolerant fallback the render function itself uses); every
    other type has exactly one selection regardless of config. Unknown/
    legacy types (shouldn't happen once `_migrate_widget_consolidation`
    has run, but _widget_context already tolerates a None spec for
    exactly this kind of "the type on disk doesn't match anything live"
    case) fall back to the first source/view rather than crashing the
    edit form."""
    wtype = widget["type"]
    if wtype == "agenda":
        key = (wtype, _agenda_range(widget.get("config") or {}))
    else:
        key = (wtype, None)
    if key not in _TYPE_TO_SELECTION:
        return "calendar_tasks", "agenda_view", "today"
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

# "quick_links" dropped from both sets 2026-08-30 -- retired outright
# (merged into "spaces_projects"), nothing left to exclude it as. Space
# pages have no exclusions left at all now (no "space" key -- same
# `.get(scope) or set()` fallback _excluded_widget_types already uses for
# Home's "" scope handles the now-absent key identically).
_SCOPE_EXCLUDED_TYPES: dict[str, set[str]] = {
    "project": {"spaces_projects"},
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
_DEFAULT_TODAY_AGENDA_CONFIG: dict = {"width": "half", "range": "today"}
_DEFAULT_STACK_CONFIG: dict = {"width": "half"}
# (2026-08-15 widget consolidation) -- upcoming_events/overdue_tasks no
# longer exist as their own types; the stacked card's other two members
# are now Agenda widgets configured to show just one Show section each
# (Events-only/all-upcoming, Overdue-only), reproducing the exact same
# two panes the old seed showed.
_DEFAULT_STACK_MEMBER_TYPES: list[tuple[str, dict]] = [
    ("at_a_glance", {}),
    ("agenda", {"range": "all_upcoming", "show": ["events"]}),
    ("agenda", {"range": "today", "show": ["overdue"]}),
]

_MINI_CALENDAR_BACKFILL_KEY = "dashboard_mini_calendar_backfilled_v1"
_HOME_SEEDED_KEY = "dashboard_home_seeded_v1"


def _seed_agenda_stack_layout(conn, label_name: str | None, now: str) -> None:
    """Writes the default layout for one page's grid -- Home when
    `label_name` is None, otherwise that label's generated Space/Project
    page -- shared by _ensure_default_widgets and
    _ensure_default_label_widgets so both seed with the identical
    screenshot-driven look: Today's Agenda beside a stack of At a
    Glance / Upcoming events / Overdue. Building the stack this way (a
    `type="stack"` row + group_uid members) mirrors stack_widget()'s own
    shape exactly, not a new mechanism.

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
            "uid": str(uuid.uuid4()), "type": "agenda", "title": None,
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
    for i, (wtype, extra_config) in enumerate(_DEFAULT_STACK_MEMBER_TYPES):
        member_config = dict(extra_config)
        if label_name:
            member_config["label_name"] = label_name
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


_WIDGET_CONSOLIDATION_KEY = "dashboard_widget_consolidation_v1"


def _migrate_widget_consolidation(conn) -> None:
    """One-time migration (2026-08-15 widget consolidation, plans/open.md
    § Widget consolidation) -- rewrites every existing dashboard_widgets
    row still carrying one of the seven now-removed types in place, so no
    existing dashboard silently loses a widget just because this version
    is running. Runs exactly once (tracked in app_meta), same
    non-idempotent-forever pattern _backfill_mini_calendar_widget uses
    below (this only ever needs to run once, not "until the condition is
    no longer true").

    - today_agenda/weekly_overview/upcoming_events/overdue_tasks all
      become "agenda", each config translated to the exact Range/Show
      combination that reproduces its old content -- every one of these
      four preserves the underlying task/event set unchanged, just under
      the new registry (see AGENDA_RANGES/AGENDA_SHOWS and _render_agenda's
      own docstring for what each combination renders).
    - project_preview/filled_cards become "spaces_projects" with
      style="list"/"cards" respectively.
    - calendar_agenda splits into two widgets in its old row's place: the
      row itself becomes an "agenda" (range=next_7_days,
      show=[tasks, events], matching the old embedded 7-day agenda), and
      a brand-new "mini_month_calendar" row is inserted right beside it,
      sharing the same group_uid -- a calendar_agenda that was already
      inside a stack keeps both halves stacked together; a standalone one
      gets two standalone widgets at (roughly) the same position. Doesn't
      nest a new stack around them -- stacks aren't nestable (see
      stack_widget's own comment), and reusing calendar_agenda's existing
      group_uid (None or a real stack) sidesteps that restriction
      entirely."""
    if db.get_app_meta(conn, _WIDGET_CONSOLIDATION_KEY):
        return
    now = _now()
    for w in db.list_all_dashboard_widgets(conn):
        wtype = w["type"]
        cfg = dict(w.get("config") or {})
        if wtype in ("today_agenda", "weekly_overview", "upcoming_events", "overdue_tasks"):
            range_days = cfg.pop("range_days", None)
            if wtype == "today_agenda":
                cfg.update({"range": "today", "show": ["overdue", "tasks", "events"]})
            elif wtype == "weekly_overview":
                cfg.update({"range": "next_30_days" if range_days == 30 else "next_7_days", "show": ["tasks", "events"]})
            elif wtype == "upcoming_events":
                if range_days == 7:
                    cfg["range"] = "next_7_days"
                elif range_days == 30:
                    cfg["range"] = "next_30_days"
                else:
                    cfg["range"] = "all_upcoming"
                cfg["show"] = ["events"]
            else:  # overdue_tasks
                cfg.update({"range": "today", "show": ["overdue"]})
            row = dict(w)
            row["type"], row["config"] = "agenda", cfg
            db.upsert_dashboard_widget(conn, row)
        elif wtype in ("project_preview", "filled_cards"):
            cfg["style"] = "list" if wtype == "project_preview" else "cards"
            row = dict(w)
            row["type"], row["config"] = "spaces_projects", cfg
            db.upsert_dashboard_widget(conn, row)
        elif wtype == "calendar_agenda":
            agenda_cfg = dict(cfg)
            agenda_cfg.update({"range": "next_7_days", "show": ["tasks", "events"]})
            row = dict(w)
            row["type"], row["config"] = "agenda", agenda_cfg
            db.upsert_dashboard_widget(conn, row)
            cal_cfg = {}
            if cfg.get("tags"):
                cal_cfg["tags"] = cfg["tags"]
            if cfg.get("label_name"):
                cal_cfg["label_name"] = cfg["label_name"]
            db.upsert_dashboard_widget(
                conn,
                {
                    "uid": str(uuid.uuid4()),
                    "type": "mini_month_calendar",
                    "title": None,
                    "config": cal_cfg,
                    "position": w["position"] - 0.001,
                    "created_at": now,
                    "group_uid": w.get("group_uid"),
                    "label_name": w.get("label_name"),
                },
            )
    db.set_app_meta(conn, _WIDGET_CONSOLIDATION_KEY, "1")


_WIDGET_REMOVAL_2026_08_30_KEY = "dashboard_widget_removal_2026_08_30"


def _migrate_widget_removal_2026_08_30(conn) -> None:
    """One-time migration (2026-08-30, direct requests: "merge the quick
    links and spaces & projects into one data source" / "maybe just remove
    the next deadline, what needs organizing and streak widgets") -- same
    non-idempotent-forever pattern as `_migrate_widget_consolidation`
    above (runs exactly once, tracked in its own app_meta key so it
    doesn't re-run and doesn't collide with that migration's own guard).

    - Every existing "quick_links" row becomes "spaces_projects" with
      `style="cards"` in place (same rewrite-in-place approach
      `_migrate_widget_consolidation` already uses for project_preview/
      filled_cards) -- `_render_spaces_projects`'s own cards branch now
      renders the identical "every Space + every open project" tile set
      Quick Links used to when unscoped, so nothing is lost, just
      relabeled onto the surviving type.
    - Every existing "next_deadline"/"organize_today"/"streak" row is
      deleted outright -- there's no replacement type to rewrite onto (a
      straight removal, not a merge), and leaving the row in place would
      otherwise render as `_widget_inner.html`'s generic "Unknown widget
      type" empty state forever (`_widget_context` already degrades a
      row whose `type` isn't in `WIDGET_TYPES` that way -- harmless, but
      not what "remove" means here). `db.delete_dashboard_widget` is a
      plain row delete; a removed widget that happened to be inside a
      stack just stops appearing among that stack's children (nothing
      else references it back)."""
    if db.get_app_meta(conn, _WIDGET_REMOVAL_2026_08_30_KEY):
        return
    for w in db.list_all_dashboard_widgets(conn):
        wtype = w["type"]
        if wtype == "quick_links":
            row = dict(w)
            row["type"] = "spaces_projects"
            row["config"] = {**(w.get("config") or {}), "style": "cards"}
            db.upsert_dashboard_widget(conn, row)
        elif wtype in ("next_deadline", "organize_today", "streak"):
            db.delete_dashboard_widget(conn, w["uid"])
    db.set_app_meta(conn, _WIDGET_REMOVAL_2026_08_30_KEY, "1")


# "Bare" tile-grid widgets (2026-08-30, direct feedback: "i like the quick
# links grid but i'd like to not have them inside a div card") -- Spaces &
# Projects' own "cards" style renders `.filled-cards-grid`/`.filled-card`
# tiles that already carry their own visual weight (saturated fills, MD3
# "elevation-1" shadow per tile) -- wrapping that grid a second time in the
# .card chrome (border + shadow + padded box) was redundant framing, not
# information. Originally also covered the standalone "quick_links" widget
# type, which rendered the identical tile grid -- retired the same day,
# merged into this style (see _render_spaces_projects's own comment), so
# only the one condition below remains. `bare` opts a widget INSTANCE's
# card wrapper out of that chrome (border/shadow/background/padding -- see
# .widget-card--bare, static/style.css) while keeping the same
# `.widget-card` class/id/data-* attributes the masonry layout (static/
# app.js) and the async-CRUD single-widget refresh (_widget_card.html's
# `#widget-<uid>` match) both still key off of -- structural role
# unchanged, only the visual box around it is gone.
def _is_bare_tile_widget(widget: dict) -> bool:
    return widget["type"] == "spaces_projects" and (widget.get("config") or {}).get("style") == "cards"


def _widget_context(conn, widget: dict, nav: dict | None = None) -> dict:
    spec = WIDGET_TYPES.get(widget["type"])
    width = _widget_width(widget, spec)
    source, view, range_ = _selection_from_widget(widget)
    selection = {"source": source, "view": view, "range": range_}
    bare = _is_bare_tile_widget(widget)
    if spec is None:
        return {"widget": widget, "spec": None, "data": None, "width": width, "selection": selection, "is_stack": False, "bare": bare}
    data = spec["render"](conn, widget["config"], nav)
    return {"widget": widget, "spec": spec, "data": data, "width": width, "selection": selection, "is_stack": False, "bare": bare}


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


def _return_url(label_name: str | None, _legacy: str | None = None, conn=None) -> str:
    """Where a widget-mutating POST should redirect back to -- Home ("/")
    when the acted-on widget has no page identity, or that label's
    generated page otherwise: `/spaces/{name}` directly for a Space
    (`conn` passed -- avoids bouncing through label_detail's own 301,
     2026-08-28 fix, see plans/STATE.md), `/settings/labels/{name}`
    (labels.py's label_detail, which itself 301s on to /spaces/{name}
    for a Space) when no `conn` is available to check. Derived from the
    widget itself wherever one already exists (edit/resize/stack/unstack/
    delete/move/reorder below); only add_widget has no existing widget to
    derive it from, so it takes `label_name` as a hidden form field
    instead (see _widget_builder_fields.html). `_legacy` accepts a second
    positional arg so every pre-Phase-2 call site passing (space_uid,
    project_uid) -- both now the same value, see _widget_row_to_dict's
    aliasing -- keeps working unchanged; only the first non-empty of the
    two is used.

    No longer takes an `edit` flag (2026-08-29, sidebar redesign item
    13d) -- edit mode is a persistent, app-wide Settings > Appearance
    toggle (EDIT_MODE_KEY) now, not a per-page `?edit=1` query param a
    redirect needed to preserve, so every caller lands on the plain page
    URL regardless of whether edit mode is on."""
    label_name = label_name or _legacy
    if not label_name:
        return "/"
    if conn is not None and db.effective_label_config(conn, label_name).get("generate_space"):
        return f"/spaces/{label_name}"
    return f"/settings/labels/{label_name}"


def widget_page_context(conn, space_uid: str | None = None, project_uid: str | None = None, nav: dict | None = None) -> dict:
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
    that can't mean anything there. `edit_mode` in the returned context is
    read straight off EDIT_MODE_KEY (2026-08-29, sidebar redesign item
    13d) -- no longer a caller-supplied `edit` flag threaded through from
    a `?edit=1` query param, since edit mode is now a persistent, app-wide
    Settings > Appearance toggle rather than a per-page one."""
    _migrate_widget_consolidation(conn)
    _migrate_widget_removal_2026_08_30(conn)
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
        "page_url": _return_url(label_name, conn=conn),
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
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


def _page_banner_context(conn, scope: str) -> dict:
    """Every piece of context _page_banner.html needs to render one page's
    banner -- Home ("" scope) and every Space/Project page
    (routers/labels.py::label_detail, routers/spaces.py::space_detail)
    all call this the same way. 2026-08-29 (direct request): a page with
    no banner of its own now falls back to the single default set in
    Settings > Appearance (deps.py's PAGE_HEADER_BANNER_SCOPE) instead of
    showing no banner at all -- the same "one default image everywhere,
    overridable per page" model the narrow header (Tasks/Calendar/...)
    already uses, extended to the big banner too.

    `has_own_banner` (not `banner`) is what the "Add banner"/"Change
    banner" edit-mode button's label reads: it's about whether THIS page
    has its own override, not whether a banner happens to be showing at
    all (the default rendering through doesn't mean this page has "added"
    one). `banner_image_scope` is which banner is actually being
    rendered (this page's own scope, or the sentinel default scope) --
    kept separate from `banner_scope` (this page's own identity, always
    used by the edit button/upload/remove forms regardless of which image
    is currently showing) so _page_banner.html's `/banners/image` URL
    points at the right stored image rather than looking up this page's
    own (unset) scope with the default banner's version hash."""
    own_banner = db.get_page_banner(conn, scope)
    if own_banner:
        return {"banner": own_banner, "has_own_banner": True, "banner_scope": scope, "banner_image_scope": scope}
    return {
        "banner": db.get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE),
        "has_own_banner": False,
        "banner_scope": scope,
        "banner_image_scope": PAGE_HEADER_BANNER_SCOPE,
    }


@router.get("/")
def dashboard_view(
    request: Request,
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
    ctx = widget_page_context(conn, space_uid=None, nav=nav)
    display_name = db.get_app_meta(conn, DISPLAY_NAME_KEY)
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            "greeting": _greeting_for_hour(datetime.now().hour, display_name),
            # Dashboard Header (Expanded) avatar (2026-08-29, sidebar
            # redesign follow-up, direct request, plans/sidebar-redesign
            # .md § "The Standard Header") -- the large circular avatar
            # overlapping the banner's bottom-left, _page_banner.html's
            # own addition. Reuses the exact same profile-photo feature
            # Settings > General's own avatar row already has (deps.py's
            # avatar() global, same {photo_b64, photo_type, full_name}
            # dict shape) -- no new storage. display_name is already
            # computed above for the greeting; profile_photo is new here.
            "profile_photo": db.get_profile_photo(conn),
            "display_name": display_name,
        }
    )
    ctx.update(_page_banner_context(conn, ""))
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/today")
def today_redirect():
    """The standalone /today page (1.7 slice 1, "Today -- execution") is
    retired (1.9 side work) -- its two sections that no existing Dashboard
    widget covered (Important & urgent, Scheduled work hours today) became
    the important_urgent/scheduled_work_today widget types; everything else
    it showed (Due & overdue, today's calendar events) already had a direct
    Dashboard equivalent (today_agenda). important_urgent has since been
    removed outright along with the rest of the Importance/Urgency feature
    -- see src/derived_state.py's module docstring. Kept as a redirect
    rather than a bare 404, same "any bookmark still lands somewhere real"
    precedent `routers/calendar.py::week_redirect`/`timetable_view_redirect`
    already established for the analogous /calendar/timetable retirement --
    see plans/STATE.md."""
    return RedirectResponse(url="/", status_code=302)


@router.get("/quick/add")
def quick_add_form(request: Request, conn=Depends(get_db)):
    # Merged task/event quick-add (2026-08-10) -- the dashboard's and
    # label-page's single "+" button opens this instead of two separate
    # New task / New event forms. Renders BOTH create-forms in one modal
    # (quick_add.html); the client just flips between them. The task and
    # event option lists are imported lazily from .tasks so this module
    # (which .tasks itself imports at load time) doesn't create a
    # circular import.
    from .tasks import STATUS_ITEMS, STATUSES

    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "quick_add.html",
        {
            "request": request,
            "active_tab": "dashboard",
            # Task-side context -- the shared field-grid partial
            # (_task_form_fields.html) needs the same items new_task_form
            # passes; task is None, so the edit-only branches don't render.
            # (Importance/Urgency have no items here anymore -- side work,
            # post-1.1, both are computed, not manually set.)
            "task": None,
            "statuses": STATUSES,
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
def reset_dashboard(label_name: str = Form(""), conn=Depends(get_db)):
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
    return RedirectResponse(url=_return_url(label_name or None, conn=conn), status_code=303)


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
    ctx = widget_page_context(conn, space_uid or None, project_uid or None)
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


@router.get("/dashboard/widgets/{uid}")
def widget_card_region(request: Request, uid: str, conn=Depends(get_db)):
    """Async-CRUD single-widget region fragment (features/async-crud.md) --
    re-renders one plain widget's card (the .widget-card with
    id="widget-{uid}") so static/async_crud.js's refreshRegion() can swap
    it in place after a task change instead of reloading the whole page.
    Shares _widget_card.html/_widget_inner.html with the full grid, so the
    fragment is pixel-identical to what widget_page_context renders (one
    source of truth). A stack (or stack child) returns the same card
    markup, but a stack child has no #widget-<uid> container on the page,
    so refreshRegion() no-ops for those -- documented scope cut, see
    _widget_card.html's own comment.

    `edit_mode` (2026-08-30 bug fix, direct report -- "saving a widget...
    not seeing the change only after a hard refresh") used to be
    hardcoded False here, which was harmless for the one caller that
    existed at the time (a *task* change refreshing a task-using widget,
    always skipped in edit mode -- see async_crud.js's cc-entity-changed
    listener, which never calls this route while editing at all). It
    stopped being harmless once a widget's OWN Filters/Width edit needed
    to refresh its own card live (dashboard_widget_preview.js's
    autosave() below) -- that only ever happens *while* in edit mode (the
    Filters form only opens there), and a hardcoded False would silently
    render the refreshed card without its drag handle/Edit/Delete chrome,
    which is exactly what the old task-change listener's own comment
    warned against doing. Reads the real, current edit_mode the same way
    widget_page_context already does, rather than assuming a caller-
    specific constant."""
    widget = db.get_dashboard_widget(conn, uid)
    if widget is None:
        raise HTTPException(status_code=404, detail=f"widget not found: {uid}")
    wc = _widget_context(conn, widget, None)
    label_name = widget.get("label_name") or ""
    ctx = {
        "request": request,
        "edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
        "space_uid": label_name,
        "project_uid": label_name,
        "label_name": label_name,
        "wc": wc,
    }
    html = templates.env.get_template("_widget_card.html").render(ctx)
    return HTMLResponse(html)


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
    page_ctx = widget_page_context(conn, space_uid or None, project_uid or None, nav=nav)
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
    extra: dict | None = None,
    style: str = "",
    show: list[str] | None = None,
    scope: str = "",
    width: str = "",
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
    # `extra` (2026-08-15 widget consolidation) -- whatever
    # _resolve_selection decided a fresh Agenda widget's `range` (and, by
    # omission, its default `show`) should be; merged in before `style`/
    # `show` below so an explicit Style/Show submission still wins.
    if extra:
        config.update(extra)
    # `style` (2026-08-15, Spaces & Projects) / `show` (2026-08-15, Agenda)
    # -- only ever passed by callers that already know the resolved type
    # is spaces_projects/agenda respectively, so these never pollute any
    # other type's stored config.
    if style:
        config["style"] = style
    # `scope` (2026-08-15, expanded scope) -- Spaces & Projects' "This
    # Space" (default, omitted) / "Everything" per-instance override; see
    # _render_spaces_projects' own docstring.
    if scope:
        config["scope"] = scope
    if show is not None:
        config["show"] = show
    # `width` (2026-08-30, reinstated manual per-instance override -- see
    # WIDGET_WIDTHS/_widget_width's own comment) -- only ever one of
    # WIDGET_WIDTH_CHOICES from a real submission of the Width field
    # (blank/"Auto" -> omitted entirely, same "don't store a no-op key"
    # convention `style`/`scope` above already follow); a stale/forged
    # value that isn't a real key is silently dropped here too, same
    # "not our job to validate here" reasoning _widget_width's own
    # fallback already covers on the read side.
    if width in WIDGET_WIDTH_CHOICES:
        config["width"] = width
    return config


def _agenda_show_from_form(show: list[str] | None) -> list[str]:
    """2026-08-31 direct feedback ("show should be another checkbox
    dropdown") -- the Show field used to submit as three independent
    `show_overdue`/`show_tasks`/`show_events` booleans (one `<input
    type="checkbox">` each, always visible); now a single `name="show"`
    field submitting 0+ values, same shared-checkbox-list-in-a-dropdown
    shape Labels/Task lists/Calendars already use
    (_widget_list_multiselect.html, ms_mode="select" since an empty
    selection here is a real "show nothing" state, not "no filter/show
    everything" the way Labels' own empty selection means). Always
    returned in AGENDA_SHOWS' own canonical order regardless of the
    submitted order, and silently drops anything that isn't a real Show
    value -- same "not our job to validate a forged/stale value here"
    convention `_config_from_form`'s width handling already follows.
    `show` is defensively coerced to a list -- same reason
    `_combine_tags`'s own `tags_labels` coercion exists (see its own
    comment): a test that calls add_widget/edit_widget/preview_widget as a
    plain Python function without passing `show` gets this parameter's own
    `Form([])` default, a FastAPI marker object rather than an actual
    empty list outside of real request handling, which isn't iterable."""
    if not isinstance(show, list):
        show = []
    return [name for name in AGENDA_SHOWS if name in set(show)]


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
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
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
    is the Labels chip multiselect's checkboxes -- see _combine_tags.
    `style`/`show` (2026-08-15 widget consolidation; `show` reworked
    2026-08-31 into a single multi-value field, see
    _agenda_show_from_form) are Spaces & Projects' Style radio and
    Agenda's Show checkboxes; `width` (2026-08-30, reinstated) is the
    Width radio -- see _config_from_form. The preview
    card itself ignores width visually either way (`.widget-preview-card`
    is reset to `position:static; width:auto`, static/style.css), but it's
    threaded through anyway so the previewed widget's data/behavior stays
    consistent with what a real save would produce."""
    if source not in WIDGET_SOURCES:
        return templates.TemplateResponse(
            "_dashboard_widget_preview.html",
            {"request": request, "widget": {"uid": "preview", "title": title}, "spec": None, "data": None},
        )
    wtype, extra = _resolve_selection(source, view, range or None)
    spec = WIDGET_TYPES[wtype]
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
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
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
    space_uid: str = Form(""),
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
    excluded for the page's scope (e.g. Spaces & Projects on a project
    page) are rejected as a no-op the same way an unknown source is, so a
    stale/excluded combo never silently creates a widget that can't mean
    anything on the page. `width` (2026-08-30, reinstated manual
    override) -- see WIDGET_WIDTHS/_widget_width's own comment."""
    page_label = space_uid or project_uid or None
    if source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    wtype, extra = _resolve_selection(source, view, range or None)
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
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
    return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)


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
    style: str = Form(""),
    scope: str = Form(""),
    width: str = Form(""),
    show: list[str] = Form([]),
    conn=Depends(get_db),
):
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return RedirectResponse(url="/", status_code=303)
    page_label = existing.get("label_name")
    # Already-placed widget of a source/view no longer offered by the
    # builder (2026-08-07 Projects purge) -- _widget_edit_form.html can't
    # render a picker for a source that isn't in `widget_sources` any
    # more, so it falls back to submitting the widget's own current
    # selection unchanged via hidden fields (see that template's own
    # comment). Recognize that exact "nothing about Source/View/Range
    # actually changed" case here and keep the widget's existing type/
    # extra config as-is, *before* the `source not in WIDGET_SOURCES`
    # guard below would otherwise reject the whole save -- without this,
    # simply editing the Title or Labels on such a widget would silently
    # fail to save anything.
    orig_source, orig_view, orig_range = _selection_from_widget(existing)
    if source == orig_source and view == orig_view and (range or None) == orig_range and source not in WIDGET_SOURCES:
        wtype = existing["type"]
        extra = {}
    elif source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    else:
        wtype, extra = _resolve_selection(source, view, range or None)
    # Scope guard (2026-08-05) -- an excluded type can only arrive from a
    # stale/forged submission (the builder no longer offers it), so refuse
    # it the same way an unknown source is refused rather than silently
    # turning a project widget into something that can't mean anything
    # there.
    if wtype in _excluded_widget_types(_page_scope(conn, page_label)):
        return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)
    row = dict(existing)
    show = _agenda_show_from_form(show) if wtype == "agenda" else None
    new_config = _config_from_form(
        project_uid, _combine_tags(tags, tags_labels), task_list_uids, calendar_uids, limit,
        extra=extra, style=style if wtype == "spaces_projects" else "",
        scope=scope if wtype == "spaces_projects" else "", show=show, width=width,
    )
    # Width (2026-08-30, reinstated -- see WIDGET_WIDTHS/_widget_width's
    # own comment) is a real field on this form now, handled the same way
    # every other _config_from_form kwarg above already is -- no special
    # casing needed here (a blank/"Auto" submission is simply omitted from
    # new_config by _config_from_form itself, same as an unset Style).
    # Re-scope to whichever page this widget already belongs to
    # (2026-08-02) -- a label page's `label_name` filter isn't a field on
    # this form either, same reasoning as width: editing Title/Source/
    # Project/Tags must never silently un-scope a widget from its page.
    if page_label:
        new_config["label_name"] = page_label
    row.update({"type": wtype, "title": title.strip() or None, "config": new_config})
    db.upsert_dashboard_widget(conn, row)
    return RedirectResponse(url=_return_url(page_label, conn=conn), status_code=303)


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
def unstack_widget(uid: str, conn=Depends(get_db)):
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
    return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)


@router.post("/dashboard/widgets/{uid}/delete")
def delete_widget(uid: str, conn=Depends(get_db)):
    widget = db.get_dashboard_widget(conn, uid)
    if widget is not None:
        space_uid = widget.get("space_uid")
        project_uid = widget.get("project_uid")
        if widget["type"] == "stack":
            # Dissolve, don't destroy -- a stack is a layout grouping, not
            # a real owner of the widgets inside it, so removing it should
            # never take your Filters config for those widgets with it.
            _dissolve_stack(conn, widget)
            return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
        stack_uid = widget.get("group_uid")
        db.delete_dashboard_widget(conn, uid)
        if stack_uid:
            _dissolve_if_singleton(conn, stack_uid)
        return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
    db.delete_dashboard_widget(conn, uid)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/widgets/{uid}/move")
def move_widget(uid: str, direction: str = Form(...), conn=Depends(get_db)):
    target_widget = db.get_dashboard_widget(conn, uid)
    if target_widget is None:
        return RedirectResponse(url="/", status_code=303)
    space_uid = target_widget.get("space_uid")
    project_uid = target_widget.get("project_uid")
    widgets = db.list_dashboard_widgets(conn, space_uid=space_uid, project_uid=project_uid)
    idx = next((i for i, w in enumerate(widgets) if w["uid"] == uid), None)
    if idx is None:
        return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(widgets):
        db.swap_dashboard_widget_positions(conn, widgets[idx]["uid"], widgets[swap_idx]["uid"])
    return RedirectResponse(url=_return_url(space_uid, project_uid, conn=conn), status_code=303)


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

# /dashboard/widgets/{uid}/resize (a drag-to-resize-width endpoint) briefly
# existed here, 2026-08-30 -- reinstated the same day as the Filters
# panel's own Width field, direct request ("i don't really like the
# settings width settings and much rather would mouse resize them"), then
# removed again just as quickly, direct follow-up that it still didn't
# drag correctly even after a first attempted fix ("remove it... the
# dashboard customise is fine"). WIDGET_WIDTHS/_widget_width and the
# Filters panel's Width field are unaffected -- that's still the only way
# to set a widget's width.
