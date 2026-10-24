"""Widget renderers and the filters they share.

Part of the package whose __init__ re-exports every name.
"""

from __future__ import annotations

import calendar as py_calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from ... import clock, db, derived_state, habit_view, recurrence_expand
from ...deps import EDIT_MODE_KEY, PAGE_HEADER_BANNER_SCOPE, get_db, templates

def _now() -> str:
    return clock.now().isoformat()


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
    """-- the widget builder/
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
        otherwise blow up every one of those pre-existing calls.
    """
    if not isinstance(tags_labels, list):
        tags_labels = []
    parts = _tags_list(tags) if tags else []
    parts.extend(t.strip() for t in tags_labels if t and t.strip())
    return ",".join(parts)


def _with_project(conn, tags: str, project, project_field) -> str:
    """The task/event forms' Project dropdown folded into the same comma-separated `tags` string
        _combine_tags produces, via db.apply_project_choice. Only applied when
        the form actually carried the dropdown (`project_field` == "1"), so
        every other writer (inline edits, bulk actions, quick capture, tests
        calling the route directly) keeps its tags exactly as posted. The
        isinstance guards cover direct calls, where an unset param is still
        FastAPI's Form marker object.
    """
    if not (isinstance(project_field, str) and project_field == "1"):
        return tags
    project = project if isinstance(project, str) else ""
    return ",".join(db.apply_project_choice(conn, _tags_list(tags) if tags else [], project))


def _greeting_for_hour(hour: int, display_name: str | None = None) -> str:
    """Time-of-day greeting.
        Takes the hour as a plain int rather than reading
        `clock.local_now()` itself so it's directly testable with fixed hour
        values, no time-freezing needed -- same "compute from an explicit
        param, not a hidden clock read" shape `_render_mini_month_calendar`'s
        `nav` param already uses for its own "what month" question. The real
        caller (dashboard_view below) passes `clock.local_now().hour` -- local
        server time, the same convention `clock.today()` already uses
        everywhere else in this app for "today" (no separate timezone
        handling introduced here).
    """
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


def _scope_child_names(conn, label_name: str | None) -> set[str] | None:
    """`None` means "no scope restriction" (Home, unscoped) -- NOT "matches
        nothing"; see `_passes_scope` below, the only thing that should ever
        interpret this return value.
    """
    if not label_name:
        return None
    group = db.group_from_page_key(label_name)
    if group is not None:
        return set(db.group_member_names(conn, group))
    return {label_name}


def _passes_scope(item_tags: list[str] | None, scope_names: set[str] | None) -> bool:
    """The hard top-level page-scope check every item-listing widget now
        goes through (`_filtered_tasks`/`_filtered_events`/`_render_contact_
        list`/`_render_habit_checkin`) -- `scope_names` is `_scope_child_names`'s
        return value, resolved once per call from `config["label_name"]`.
        `None` (Home, unscoped) always passes; otherwise an item must carry at
        least one of `scope_names`' tags.
    """
    if scope_names is None:
        return True
    return bool(set(item_tags or []) & scope_names)


def _effective_tags_filter(config: dict) -> list[str]:
    """A widget's own OPTIONAL extra tag narrowing -- just `config["tags"]`
        now. No longer takes `conn` -- nothing here touches the
        database anymore.
    """
    return list(config.get("tags") or [])


def _passes_filters(item_tags: list[str], tags_filter: list[str]) -> bool:
    """Phase 1 dropped `task_lists`/
        `calendars` -- the project/space/list filters below used to resolve
        through a task's/event's collection membership (`list_path`/
        `calendar_path`, both gone -- see db.py's Phase 1 comments), so only
        the tags filter still applies here. Project/space filtering returns
        in Phase 2/3 as a label filter once object_labels is backfilled and
        routers/labels.py exists; any `project_uid`/`group_uid`/`list_uids`
        already saved in an old widget's config is now silently ignored
        rather than excluding everything. `tags_filter` is `_effective_tags_
        filter`'s return value, computed once per `_filtered_tasks`/`_filtered_events` call
        rather than per item.

        NO_LABEL_SENTINEL is an OR'd-in alternative match, not a
        real tag: an item passes if it has no tags at all AND the sentinel is
        selected, *or* it shares a real tag with whatever else is selected --
        same "matches any selected option" semantics multi-select filtering
        already has elsewhere, just with "no label" as one more option instead
        of a separate exclusive mode. Selecting only "No label" (real_tags
        empty) means only unlabeled items pass.
    """
    from .views import NO_LABEL_SENTINEL
    if not tags_filter:
        return True
    item_tags_set = set(item_tags or [])
    real_tags = set(tags_filter) - {NO_LABEL_SENTINEL}
    if NO_LABEL_SENTINEL in tags_filter and not item_tags_set:
        return True
    return bool(real_tags and (item_tags_set & real_tags))


def _agenda_with_grace(conn, config: dict, predicate) -> list[dict]:
    """`_filtered_tasks(conn, config)` (open_only=True) plus any task that
    would otherwise have just been excluded for being done/archived, but
    was completed within the last `TASK_GRACE_MINUTES` and still passes
    `predicate` (the same due-date/window test the open-task list already
    applies) -- so a task checked off from an Agenda widget row (Overdue,
    or the flat Tasks list in every Range) stays in that same list, shown
    checked and struck through, instead of disappearing the instant the
    widget re-fetches. Deliberately local to the Agenda widget's own task
    lists (see TASK_GRACE_MINUTES' own comment) rather than folded into
    `_filtered_tasks` itself."""
    from .views import TASK_GRACE_MINUTES
    open_tasks = _filtered_tasks(conn, config)
    cutoff_iso = (clock.now() - timedelta(minutes=TASK_GRACE_MINUTES)).isoformat()
    done_recent = [
        t for t in _filtered_tasks(conn, config, open_only=False)
        if t["status"] in ("done", "archived") and t.get("completed_at") and t["completed_at"] >= cutoff_iso
    ]
    return [t for t in (open_tasks + done_recent) if predicate(t)]


def _filtered_tasks(conn, config: dict, open_only: bool = True) -> list[dict]:
    tags_filter = _effective_tags_filter(config)
    scope_names = _scope_child_names(conn, config.get("label_name"))
    tasks = db.list_tasks(conn)
    out = []
    for t in tasks:
        if open_only and t["status"] in ("done", "archived"):
            continue
        if not _passes_scope(t.get("tags"), scope_names):
            continue
        if not _passes_filters(t.get("tags"), tags_filter):
            continue
        out.append(t)
    return out


def _filtered_events(conn, config: dict, start: str | None = None, end: str | None = None) -> list[dict]:
    tags_filter = _effective_tags_filter(config)
    scope_names = _scope_child_names(conn, config.get("label_name"))
    events = db.list_events(conn, start=start, end=end)
    out = []
    for e in events:
        if not _passes_scope(e.get("tags"), scope_names):
            continue
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
    expanded = recurrence_expand.expand_events(
        events,
        window_start,
        window_end,
        db.list_holidays_by_calendar(conn),
        db.list_event_occurrence_overrides_by_master(conn),
    )
    return db.annotate_item_colors(conn, expanded)


def _agenda_show(config: dict) -> set[str]:
    from .views import AGENDA_DEFAULT_SHOW
    show = config.get("show")
    return set(show) if show is not None else set(AGENDA_DEFAULT_SHOW)


def _agenda_range(config: dict) -> str:
    from .views import AGENDA_RANGES
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


def _agenda_habits(conn, config: dict, show: set[str]) -> list[dict]:
    """Habits H7: today's still-to-do build habits for the Agenda widget
    (habit_view.habit_items rows, page-scoped like every item widget)."""
    if "habits" not in show:
        return []
    scope_names = _scope_child_names(conn, config.get("label_name"))
    return [
        h for h in habit_view.habit_items(conn)
        if h["due_today"] and not h["is_avoid"] and _passes_scope(h["tags"], scope_names)
    ]


def _render_agenda(conn, config: dict, nav: dict | None = None) -> dict:
    """Consolidated Agenda widget -- replaces the four separate
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
        render the same flat, `limit`-capped chronological list; Next 30 days bounds Tasks/Events to
        its own 30-day window, All upcoming bounds Tasks/Events to 364 days
        out.
    """
    show = _agenda_show(config)
    range_ = _agenda_range(config)
    today = clock.today()
    today_iso = today.isoformat()
    _raw_limit = config.get("limit")
    limit = int(_raw_limit) if _raw_limit is not None else 8
    if not limit:
        limit = 8

    overdue_tasks: list[dict] = []
    if "overdue" in show:
        overdue_tasks = _agenda_with_grace(conn, config, lambda t: t.get("due_at") and t["due_at"][:10] < today_iso)
        overdue_tasks.sort(key=lambda t: t["due_at"])

    if range_ == "today":
        tasks = []
        if "tasks" in show:
            tasks = [
                t for t in _filtered_tasks(conn, config, open_only=False)
                if t.get("due_at") and t["due_at"][:10] == today_iso and t["status"] != "archived"
            ]
            tasks.sort(key=lambda t: (t["status"] == "done", t["due_at"]))
        events = []
        if "events" in show:
            events = [e for e in _filtered_events_expanded(conn, config, today, today) if e.get("start_at") and e["start_at"][:10] == today_iso]
            events.sort(key=lambda e: e.get("start_at") or "")
        return {"mode": "flat", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "tasks": tasks, "events": events, "today": today_iso, "habits": _agenda_habits(conn, config, show)}

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
        return {"mode": "days", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "days": by_day, "today": today_iso, "habits": _agenda_habits(conn, config, show)}

    task_end_iso = (today + timedelta(days=364)).isoformat() if range_ == "all_upcoming" else (today + timedelta(days=29)).isoformat()
    event_window_end = (today + timedelta(days=364)) if range_ == "all_upcoming" else (today + timedelta(days=29))

    tasks = []
    if "tasks" in show:
        tasks = _agenda_with_grace(
            conn, config,
            lambda t: t.get("due_at") and t["due_at"][:10] >= today_iso and (task_end_iso is None or t["due_at"][:10] <= task_end_iso),
        )
        tasks.sort(key=lambda t: t["due_at"])
        if limit:
            tasks = tasks[:limit]
    events = []
    if "events" in show:
        event_window_end_iso = event_window_end.isoformat()
        events = [
            e for e in _filtered_events_expanded(conn, config, today, event_window_end)
            if e.get("start_at") and today_iso <= e["start_at"][:10] <= event_window_end_iso
        ]
        events.sort(key=lambda e: e.get("start_at") or "")
        events = recurrence_expand.collapse_recurring(events)
        if limit:
            events = events[:limit]
    return {"mode": "flat", "range": range_, "show": show, "overdue_tasks": overdue_tasks, "tasks": tasks, "events": events, "today": today_iso,
            "recurring_window": "in the next year" if range_ == "all_upcoming" else "in the next 30 days"}


def _render_at_a_glance(conn, config: dict, nav: dict | None = None) -> dict:
    """At-a-glance stats strip --
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

        The counts come from src/derived_state.py's shared aggregation service: ONE pass over
        the scoped pool computing every per-state count through `count_by_state`
        -- state names match `count_by_state`'s own keys, so "3 overdue" is a
        real, already-filtered destination, not a number you have to go
        re-derive yourself, and the count and the filter view can never
        disagree.

        Tasks page filter cleanup: `overdue` moved
        from a `date_filter` value to a `status_filter` value.
    """
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
    from ...deps import WEEK_START_KEY

    week_start = db.get_app_meta(conn, WEEK_START_KEY) or "monday"
    today = clock.today()
    year = (nav or {}).get("year") or today.year
    month = (nav or {}).get("month") or today.month
    cal = py_calendar.Calendar(firstweekday=6 if week_start == "sunday" else 0)
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
    weekday_initials = ["M", "T", "W", "T", "F", "S", "S"]
    if week_start == "sunday":
        weekday_initials = weekday_initials[6:] + weekday_initials[:6]
    return {
        "weeks": weeks,
        "weekday_initials": weekday_initials,
        "month_label": date(year, month, 1).strftime("%B %Y"),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    }


def _render_spaces_projects(conn, config: dict, nav: dict | None = None) -> dict:
    """Consolidated Spaces & Projects widget -- replaces the
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

        `config["scope"]` -- a Space/Project
        page's widget is auto-scoped to that page via `label_name`
        (widget_page_context/add_widget's own auto-scope), which used to be
        the only option: there was no way to place a "show literally
        everything, every Space/project app-wide" instance of this widget on
        a Space's own dashboard. `scope == "everything"` opts a single widget
        instance out of that auto-scoping and renders exactly like the Home/
        unscoped case instead -- a per-instance override, not a second widget
        type. Default ("space")
        preserves every existing/migrated widget's current behavior
        unchanged.
    """
    from ..label_pages import deadline_info

    style = config.get("style") or "list"
    label_name = config.get("label_name") if config.get("scope") != "everything" else None
    group = db.group_from_page_key(label_name) if label_name else None
    if group is not None:
        labels = [lbl for lbl in (db.effective_label_config(conn, name) for name in db.group_member_names(conn, group)) if not lbl.get("archived_at")]
    elif label_name:
        labels = []  # a plain label page (not a group) has no sub-labels
    else:
        labels = [lbl for lbl in db.list_labels(conn) if lbl.get("widget_pin") and not lbl.get("archived_at")]

    if style == "cards":
        cards = []
        if not label_name:
            for g in db.list_groups(conn):
                n = len(g["labels"])
                cards.append({
                    "uid": db.group_page_key(g["name"]),
                    "name": g["name"],
                    "href": f"/groups/{g['name']}",
                    "icon": g.get("icon") or "layers",
                    "color": g.get("color") or "gray",
                    "description": "",
                    "meta": f"{n} label{'' if n == 1 else 's'}",
                })
        for lbl in labels:
            if not label_name and lbl.get("label_group"):
                continue  # already reachable through its group's card
            cards.append({
                "uid": lbl["name"],
                "name": lbl["name"],
                "href": f"/labels/{lbl['name']}",
                "icon": lbl.get("icon") or ("folder" if lbl.get("is_project") else "tag"),
                "color": lbl.get("color") or "blue",
                "description": lbl.get("description") or "",
                "meta": "Project" if lbl.get("is_project") else "Shelf",
            })
        return {"style": "cards", "cards": cards, "scoped": group is not None}

    previews = []
    all_tasks = db.list_tasks(conn)
    for lbl in labels:
        previews.append({"project": lbl, "attention": _label_attention(all_tasks, lbl["name"])})
    return {"style": "list", "previews": previews, "scoped": group is not None}


def _label_attention(tasks: list[dict], name: str) -> str | None:
    """"overdue" (red) or "soon" (yellow) when an open task under the label is due this month, else None."""
    today = clock.today().isoformat()
    state = None
    for t in tasks:
        due = (t.get("due_at") or "")[:10]
        if name not in (t.get("tags") or []) or t.get("status") in ("done", "archived") or due[:7] != today[:7]:
            continue
        if due < today:
            return "overdue"
        state = "soon"
    return state


def _render_group_members(conn, config: dict, nav: dict | None = None) -> dict:
    """Item 20: redesigns
        the group page's old always-visible "group-labels" toolbar
        (label_detail.html used to render a plain row of pill links
        unconditionally -- "the collapsed sidebar can't expand a group, so
        this is the always-available way in") as a real dashboard widget. Each
        member label/project is now a row card, not a bare pill, showing its
        own related data -- open task count, upcoming event count, and the
        nearest upcoming due date/event start across both -- "in the same
        spirit as the Unscheduled Work mockup" per the item's own wording.

        Auto-scoped to the group page it's seeded on via `config["label_name"]`
        (the normal per-page auto-scope every widget type gets -- see
        `add_widget`/`widget_page_context`); `db.group_from_page_key` recovers
        the group name from that key. Deliberately renders an empty row list
        rather than raising if it's ever placed somewhere that isn't a group
        page (label_name unset, or a plain label's key, which has no group) --
        `_SCOPE_EXCLUDED_TYPES` already keeps the picker from offering it
        there, this is just defense in depth for a manually-forged config.

        Deliberately independent of `_render_spaces_projects`'s own
        `widget_pin` filtering just above -- item 20 wants EVERY member
        visible, the same guarantee the toolbar it replaces gave, not just the
        ones a user has separately opted into showing on Home.
    """
    group = db.group_from_page_key(config.get("label_name"))
    if not group:
        return {"rows": []}
    now = clock.now().isoformat()
    all_tasks = db.list_tasks(conn)
    all_events = db.list_events(conn)
    rows = []
    for name in db.group_member_names(conn, group):
        lbl = db.effective_label_config(conn, name)
        open_tasks = [
            t for t in all_tasks
            if name in (t.get("tags") or []) and t.get("status") not in ("done", "archived")
        ]
        upcoming_events = [
            e for e in all_events
            if name in (e.get("tags") or []) and e.get("start_at") and e["start_at"] >= now
        ]
        due_candidates = [t["due_at"] for t in open_tasks if t.get("due_at")]
        due_candidates += [e["start_at"] for e in upcoming_events]
        rows.append({
            "label": lbl,
            "open_task_count": len(open_tasks),
            "upcoming_event_count": len(upcoming_events),
            "next_due": min(due_candidates) if due_candidates else None,
        })
    return {"rows": rows}


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
    from .views import _WEEKLY_SCHEDULE_MIN_SPAN_DAYS
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
    """Weekly Schedule widget -- a compact, STATIC weekly-pattern view of
        a label's long-lived recurring events (see _is_long_lived_recurrence),
        deliberately lighter than the removed Schedule module: no new data model, no course/semester
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

        Excludes `all_day` events -- an all-day event has
        no time-of-day to place on this grid, and its `start_at` isn't even
        guaranteed to carry one: contact-birthday sync (db.sync_contact_
        birthday_event) writes a bare "1900-MM-DD" (no "THH:MM"), which
        crashed `_minutes_of_day`'s fixed-offset slice on any dashboard with a
        Weekly Schedule widget whose label matched a birthday'd contact --
        reachable by just adding a birthday, not an edge case. Same exclusion
        grid_layout.py's `layout_day` already applies before its own
        time-of-day math, for the same reason -- all-day events get their own
        separate strip there, and have no place in a purely time-slotted grid
        like this one either.
    """
    from .views import _WEEKDAY_LABELS
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

        Phase 2 (label-space rework): `group_uid`/`project_uid` collapsed to
        one `label_name` config key. With `label_name` set to a Space label,
        its child labels' names (db.list_child_labels) are folded in as
        implicit tag filters, same as before. With `label_name` set to a
        plain (non-Space) label, that label itself is the implicit filter --
        a Project page shows contacts tagged with its own label directly,
        the same "direct object_labels membership only" rule every label page
        in this app follows.
    """
    scope_names = _scope_child_names(conn, config.get("label_name"))
    tags_filter = _effective_tags_filter(config)

    contacts = db.list_contacts(conn)
    contacts = [c for c in contacts if _passes_scope(c.get("tags"), scope_names)]

    if tags_filter:
        tags_lower = {t.lower() for t in tags_filter}
        contacts = [
            c for c in contacts
            if any(tag.lower() in tags_lower for tag in (c.get("tags") or []))
        ]
    _raw_limit = config.get("limit")
    limit = int(_raw_limit) if _raw_limit is not None else 8
    if not limit:
        limit = 8
    return {"contacts": contacts[:limit]}


def _render_notebook_list(conn, config: dict, nav: dict | None = None) -> dict:
    """Notebook documents tagged with this page's label/group scope --
        same shape as `_render_contact_list` immediately above (direct
        object_labels membership, no tasks/events involved, same hard-scope-
        then-optional-tags-filter-then-limit pipeline).
    """
    scope_names = _scope_child_names(conn, config.get("label_name"))
    tags_filter = _effective_tags_filter(config)

    documents = db.list_notebook_documents(conn)
    documents = [d for d in documents if _passes_scope(d.get("tags"), scope_names)]

    if tags_filter:
        tags_lower = {t.lower() for t in tags_filter}
        documents = [
            d for d in documents
            if any(tag.lower() in tags_lower for tag in (d.get("tags") or []))
        ]
    _raw_limit = config.get("limit")
    limit = int(_raw_limit) if _raw_limit is not None else 8
    if not limit:
        limit = 8
    # "New note" pre-attaching this page's label (roadmap Phase 3) only
    # makes sense on a plain label's own page, where there's exactly one
    # unambiguous label to attach -- a group page aggregates several
    # member labels (db.group_from_page_key returns non-None), so there's
    # no single correct label to pre-attach there; the widget template
    # omits its own "+ New document" action whenever this is None (Home
    # included, since label_name is None there too).
    label_name = config.get("label_name")
    create_label = label_name if label_name and db.group_from_page_key(label_name) is None else None
    # Already newest-updated-first (db.list_notebook_documents' own
    # ORDER BY) -- the right default for a "recent documents" widget,
    # same as every other list-shaped widget here.
    documents = documents[:limit]
    type_looks = db.notebook_note_type_looks(conn)
    for d in documents:
        look = type_looks.get(d.get("note_type") or "", db.NOTEBOOK_TYPE_LOOK_FALLBACK)
        d["type_icon"] = look["icon"]
        d["type_color"] = look["color"]
    return {"documents": documents, "create_label": create_label}


def _render_habit_checkin(conn, config: dict, nav: dict | None = None) -> dict:
    """Check-off-today for every active habit, right on the Dashboard.
        `target_per_day == 1` habits render as a plain checkbox (the toggle
        endpoint); `target_per_day > 1` ("8 glasses of water") as a count + a
        "+1" button posting the pre-computed `next_value`, so it works as a
        plain no-JS form.
    """
    scope_names = _scope_child_names(conn, config.get("label_name"))
    rows = [h for h in habit_view.habit_items(conn) if _passes_scope(h["tags"], scope_names)]
    todo = [h for h in rows if h["due_today"]]
    rest = [h for h in rows if not h["due_today"]]
    countable = [h for h in rows if not h.get("is_avoid") and not h.get("paused_today")]
    open_count = sum(1 for h in countable if h["due_today"])
    return {
        "rows": todo + rest,
        "todo_count": open_count,
        "total": len(countable),
        "done_count": len(countable) - open_count,
        "all_done": bool(countable) and not open_count,
    }


def _render_scheduled_work_today(conn, config: dict, nav: dict | None = None) -> dict:
    """Scheduled Work Hours Today -- today's work-allocation sessions plus a
        completed/total hours readout. Scoped like every
        other widget via `_filtered_events`.

        /today also had an "Important & urgent, not due today" section, ported
        to its own Dashboard widget type at the same time -- that widget type
        (and the whole Importance/Urgency feature behind it) is now removed;
        see src/derived_state.py's module docstring.
    """
    today_iso = clock.today().isoformat()
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


def _widget_width(widget: dict, spec: dict | None) -> dict:
    """A stack (type="stack") has no WIDGET_TYPES entry -- it's not "content"
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
        never set).
    """
    from .views import WIDGET_WIDTHS, WIDGET_WIDTH_CHOICES
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


def _agenda_show_from_form(show: list[str] | None) -> list[str]:
    """Always
        returned in AGENDA_SHOWS' own canonical order regardless of the
        submitted order, and silently drops anything that isn't a real Show
        value -- same "not our job to validate a forged/stale value here"
        convention `_config_from_form`'s width handling already follows. `show` is defensively coerced to a list -- same reason
        `_combine_tags`'s own `tags_labels` coercion exists (see its own
        comment): a test that calls add_widget/edit_widget/preview_widget as a
        plain Python function without passing `show` gets this parameter's own
        `Form([])` default, a FastAPI marker object rather than an actual
        empty list outside of real request handling, which isn't iterable.
    """
    from .views import AGENDA_SHOWS
    if not isinstance(show, list):
        show = []
    return [name for name in AGENDA_SHOWS if name in set(show)]
