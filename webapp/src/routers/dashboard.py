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

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..deps import get_db, templates

router = APIRouter(tags=["dashboard"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


# --------------------------------------------------------------------- #
# Filtering -- shared by every widget type that reads tasks/events.
# --------------------------------------------------------------------- #


def _passes_filters(
    item_tags: list[str],
    list_uid: str | None,
    config: dict,
    project_by_list: dict[str, str | None],
    group_project_uids: set[str] | None = None,
) -> bool:
    tags_filter = config.get("tags") or []
    if tags_filter and not (set(item_tags or []) & set(tags_filter)):
        return False
    list_uids_filter = config.get("list_uids") or []
    if list_uids_filter and list_uid not in list_uids_filter:
        return False
    project_filter = config.get("project_uid")
    if project_filter and project_by_list.get(list_uid) != project_filter:
        return False
    # group_uid (spaces-home-pipeline, 2026-08-02) -- resolved once by the
    # caller (_filtered_tasks/_filtered_events below) to the set of project
    # uids under that group, since this function only ever sees one item at
    # a time and has no conn to resolve it itself. None (every existing
    # widget config, which never sets group_uid) means "no group filter",
    # not "empty group" -- backward compatible with every config that
    # predates this.
    if group_project_uids is not None and project_by_list.get(list_uid) not in group_project_uids:
        return False
    return True


def _group_project_uids(conn, config: dict) -> set[str] | None:
    group_uid = config.get("group_uid")
    if not group_uid:
        return None
    return {p["uid"] for p in db.list_projects(conn) if p.get("group_uid") == group_uid}


def _filtered_tasks(conn, config: dict, open_only: bool = True) -> list[dict]:
    project_by_list = {l["uid"]: l.get("project_uid") for l in db.list_task_lists(conn)}
    group_project_uids = _group_project_uids(conn, config)
    tasks = db.list_tasks(conn)
    out = []
    for t in tasks:
        if open_only and t["status"] in ("done", "archived"):
            continue
        if not _passes_filters(t.get("tags"), t.get("list_path"), config, project_by_list, group_project_uids):
            continue
        out.append(t)
    return out


def _filtered_events(conn, config: dict, start: str | None = None, end: str | None = None) -> list[dict]:
    project_by_calendar = {c["uid"]: c.get("project_uid") for c in db.list_calendars(conn)}
    group_project_uids = _group_project_uids(conn, config)
    events = db.list_events(conn, start=start, end=end)
    out = []
    for e in events:
        if not _passes_filters(e.get("tags"), e.get("calendar_path"), config, project_by_calendar, group_project_uids):
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
        day_tasks = sorted([t for t in tasks if t["due_at"][:10] == iso], key=lambda t: t.get("priority") or 9)
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
    """Quick links/progress for one project (config['project_uid'] set,
    same filter every widget already has) or every active project
    (unset) -- the Dashboard-side half of moving Projects' own add/
    rename/archive management into Settings (2026-08-01): the *content*
    (which projects exist, how far along they are) still belongs on the
    Dashboard, just as a lighter-weight preview instead of a full
    management page. Progress is a simplified version of projects.py's
    own _project_scope (task-list tasks only, no calendars/contacts/
    classes) -- enough for a glance card, not a full project page."""
    project_uid = config.get("project_uid")
    projects = db.list_projects(conn)
    if project_uid:
        projects = [p for p in projects if p["uid"] == project_uid]
    else:
        # group_uid (2026-08-02, per-space widgets) -- a Space's default
        # Project Cards widget is seeded with this instead of project_uid,
        # same "pool every project under the group" resolution
        # _group_project_uids already does for tasks/events.
        group_project_uids = _group_project_uids(conn, config)
        if group_project_uids is not None:
            projects = [p for p in projects if p["uid"] in group_project_uids]
    task_lists = db.list_task_lists(conn)
    lists_by_project: dict[str, list[str]] = {}
    for l in task_lists:
        if l.get("project_uid"):
            lists_by_project.setdefault(l["project_uid"], []).append(l["uid"])

    previews = []
    for p in projects:
        list_uids = set(lists_by_project.get(p["uid"], []))
        tasks = [t for t in db.list_tasks(conn) if t.get("list_path") in list_uids]
        total = len(tasks)
        done = len([t for t in tasks if t["status"] in ("done", "archived")])
        progress = round(100 * done / total) if total else None
        previews.append({"project": p, "progress": progress, "tasks_done": done, "tasks_total": total})
    return {"previews": previews}


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
    if the user added their own tag filter via the Filters panel."""
    tags_filter: list[str] = list(config.get("tags") or [])

    group_uid = config.get("group_uid")
    if group_uid:
        # Resolve project names under the group and treat them as implicit
        # tag filters (union with the explicit tags filter).
        projects = [p for p in db.list_projects(conn) if p.get("group_uid") == group_uid]
        project_names = [p["name"] for p in projects]
        tags_filter = list(set(tags_filter) | set(project_names))

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
    project_uid = config.get("project_uid")
    if project_uid:
        habits = db.list_habits(conn, project_uid=project_uid)
    else:
        # group_uid (2026-08-02, per-space widgets) -- habits.project_uid
        # is the only link a habit has to a project (no group_uid column
        # of its own), so scoping by group means pooling every project
        # under it, same as _render_project_preview above.
        group_project_uids = _group_project_uids(conn, config)
        if group_project_uids is not None:
            habits = [h for h in db.list_habits(conn) if h.get("project_uid") in group_project_uids]
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


# Grid width, 2026-08-01 -- previously a fixed "half"/"full" flag baked
# into WIDGET_TYPES (so every Today's Agenda was always half-width,
# period). That's a type-level default now (see "default_width" below),
# but the *actual* width lives per widget INSTANCE, in its own config
# (same config dict the project/tags/list filters already live in) --
# picked from the Filters panel, same as every other per-widget setting.
# That's what makes this a real grid layout instead of an implicit
# pairing: any widget can be a third, half, two-thirds, or the full row,
# independent of its type, and independent of what's next to it. `span`
# is out of 6 (dashboard.html's grid-template-columns), chosen as the
# smallest common denominator for thirds AND halves without fractional
# spans.
WIDGET_WIDTHS: dict[str, dict] = {
    "third": {"label": "1/3 width", "span": 2},
    "half": {"label": "1/2 width", "span": 3},
    "two_thirds": {"label": "2/3 width", "span": 4},
    "full": {"label": "Full width", "span": 6},
}


def _widget_width(widget: dict, spec: dict | None) -> dict:
    key = widget.get("config", {}).get("width")
    if key not in WIDGET_WIDTHS:
        key = (spec or {}).get("default_width", "full")
    return {"key": key, **WIDGET_WIDTHS[key]}


# Grid height (2026-08-02 -- "a way to resize them vertically and all the
# widgets having a specific values for their width and height, not any
# height"). Same "drag the card's own edge, snapped to one of a fixed set
# of presets" model width already uses (see WIDGET_WIDTHS/_widget_width
# above and static/app.js's drag-to-resize handler) -- deliberately not a
# pixel-precise free resize, so every widget's height is always one of
# these four values, never "whatever you happened to drag it to." Applied
# to the widget's own *content* area only (a `.widget-content` wrapper
# around `{% include spec.template %}` in _widget_workspace.html's
# widget_inner macro), not the card as a whole -- the header and (in edit
# mode) the Filters panel stay their own natural height regardless, only
# the actual data below them is clamped/scrollable at this height.
WIDGET_HEIGHTS: dict[str, dict] = {
    "short": {"label": "Short", "px": 180},
    "medium": {"label": "Medium", "px": 320},
    "tall": {"label": "Tall", "px": 480},
    "xl": {"label": "Extra tall", "px": 680},
}


def _widget_height(widget: dict, spec: dict | None) -> dict:
    key = widget.get("config", {}).get("height")
    if key not in WIDGET_HEIGHTS:
        key = (spec or {}).get("default_height", "medium")
    return {"key": key, **WIDGET_HEIGHTS[key]}


WIDGET_TYPES: dict[str, dict] = {
    "today_agenda": {
        "label": "Today's Agenda",
        "template": "_widget_today_agenda.html",
        "render": _render_today_agenda,
        "uses": {"tasks", "events"},
        "default_width": "half",
        "default_height": "medium",
    },
    "mini_month_calendar": {
        "label": "Mini Calendar",
        "template": "_widget_mini_month_calendar.html",
        "render": _render_mini_month_calendar,
        "uses": {"tasks", "events"},
        "default_width": "half",
        "default_height": "tall",
    },
    "weekly_overview": {
        "label": "Weekly Overview",
        "template": "_widget_weekly_overview.html",
        "render": _render_weekly_overview,
        "uses": {"tasks", "events"},
        "default_width": "full",
        "default_height": "tall",
    },
    "upcoming_events": {
        "label": "Upcoming Events",
        "template": "_widget_upcoming_events.html",
        "render": _render_upcoming_events,
        "uses": {"events"},
        "default_width": "third",
        "default_height": "short",
    },
    "overdue_tasks": {
        "label": "Overdue Tasks",
        "template": "_widget_overdue_tasks.html",
        "render": _render_overdue_tasks,
        "uses": {"tasks"},
        "default_width": "third",
        "default_height": "medium",
    },
    "project_preview": {
        "label": "Project Preview",
        "template": "_widget_project_preview.html",
        "render": _render_project_preview,
        "uses": set(),
        "default_width": "third",
        "default_height": "medium",
    },
    "habit_checkin": {
        "label": "Habit Check-in",
        "template": "_widget_habit_checkin.html",
        "render": _render_habit_checkin,
        "uses": set(),
        "default_height": "medium",
        "default_width": "half",
    },
    "calendar_agenda": {
        "label": "Calendar + Agenda",
        "template": "_widget_calendar_agenda.html",
        "render": _render_calendar_agenda,
        "uses": {"tasks", "events"},
        "default_width": "third",
        "default_height": "xl",
    },
    "contact_list": {
        "label": "Contact List",
        "template": "_widget_contact_list.html",
        "render": _render_contact_list,
        "uses": set(),
        "default_width": "third",
        "default_height": "medium",
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
    "calendar_tasks": {"label": "Calendar & Tasks"},
    "projects": {"label": "Projects"},
    "habits": {"label": "Habits"},
    "contacts": {"label": "Contacts"},
}

# Which views exist per source, and which of those views take a Range.
WIDGET_VIEWS: dict[str, dict] = {
    "agenda": {"label": "Agenda (grouped by day)", "source": "calendar_tasks", "has_range": True},
    "upcoming_list": {"label": "Upcoming list", "source": "calendar_tasks", "has_range": True},
    "overdue_list": {"label": "Overdue list", "source": "calendar_tasks", "has_range": False},
    "mini_calendar": {"label": "Mini calendar", "source": "calendar_tasks", "has_range": False},
    "cards": {"label": "Cards", "source": "projects", "has_range": False},
    "checklist": {"label": "Checklist", "source": "habits", "has_range": False},
    "calendar_agenda_view": {"label": "Calendar + Agenda", "source": "calendar_tasks", "has_range": False},
    "contact_list_view": {"label": "Contact list", "source": "contacts", "has_range": False},
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
_SELECTION_TO_TYPE: dict[tuple[str, str | None], tuple[str, int | None]] = {
    ("agenda", "today"): ("today_agenda", None),
    ("agenda", "next_7_days"): ("weekly_overview", 7),
    ("agenda", "next_30_days"): ("weekly_overview", 30),
    ("upcoming_list", "next_7_days"): ("upcoming_events", 7),
    ("upcoming_list", "next_30_days"): ("upcoming_events", 30),
    ("upcoming_list", "all_upcoming"): ("upcoming_events", None),
    ("overdue_list", None): ("overdue_tasks", None),
    ("mini_calendar", None): ("mini_month_calendar", None),
    ("cards", None): ("project_preview", None),
    ("checklist", None): ("habit_checkin", None),
    ("calendar_agenda_view", None): ("calendar_agenda", None),
    ("contact_list_view", None): ("contact_list", None),
}

# Reverse of the above, for pre-filling the edit form from an existing
# widget's stored `type` + `config.range_days`.
_TYPE_TO_SELECTION: dict[tuple[str, int | None], tuple[str, str | None]] = {
    ("today_agenda", None): ("agenda", "today"),
    # weekly_overview's own render function defaults range_days to 7 when
    # config doesn't have one at all (_render_weekly_overview) -- true for
    # every dashboard that had this widget seeded before 2026-08-02, back
    # when config was just `{}`. (weekly_overview, None) has to reverse-
    # map to the *same* selection as (weekly_overview, 7), or every
    # pre-existing Weekly Overview widget would show as "next_7_days"
    # when you look at it but silently jump to the generic
    # calendar_tasks/agenda/today fallback the moment you opened its
    # Filters panel, changing its actual behavior the instant you saved.
    ("weekly_overview", None): ("agenda", "next_7_days"),
    ("weekly_overview", 7): ("agenda", "next_7_days"),
    ("weekly_overview", 30): ("agenda", "next_30_days"),
    ("upcoming_events", 7): ("upcoming_list", "next_7_days"),
    ("upcoming_events", 30): ("upcoming_list", "next_30_days"),
    ("upcoming_events", None): ("upcoming_list", "all_upcoming"),
    ("overdue_tasks", None): ("overdue_list", None),
    ("mini_month_calendar", None): ("mini_calendar", None),
    ("project_preview", None): ("cards", None),
    ("habit_checkin", None): ("checklist", None),
    ("calendar_agenda", None): ("calendar_agenda_view", None),
    ("contact_list", None): ("contact_list_view", None),
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
    the first source/view rather than crashing the edit form."""
    range_days = (widget.get("config") or {}).get("range_days")
    key = (widget["type"], int(range_days) if range_days else None)
    if key not in _TYPE_TO_SELECTION:
        return "calendar_tasks", "agenda", "today"
    view, range_ = _TYPE_TO_SELECTION[key]
    return WIDGET_VIEWS[view]["source"], view, range_


_DEFAULT_WIDGETS = ["calendar_agenda", "today_agenda", "weekly_overview", "upcoming_events"]

# Per-widget configs for the default seed -- width/height are set here so
# the first-load layout is immediately the intended 30/70 side-by-side pair
# (calendar+agenda at third width, today's agenda at two-thirds) rather than
# defaulting to each type's own default_width and looking like four separate
# full-width blocks until the user resizes them.
_DEFAULT_WIDGET_CONFIGS: dict[str, dict] = {
    "calendar_agenda": {"width": "third", "height": "xl"},
    "today_agenda": {"width": "two_thirds", "height": "xl"},
    "weekly_overview": {},
    "upcoming_events": {},
}

_MINI_CALENDAR_BACKFILL_KEY = "dashboard_mini_calendar_backfilled_v1"


def _ensure_default_widgets(conn) -> None:
    """A brand-new install gets a working dashboard out of the box
    (unfiltered today/week/upcoming) -- "customizable" means you can
    reshape it from there, not that you start from a blank page. A no-op
    once any widget exists, same convention as ensure_default_calendar/
    ensure_default_task_list/ensure_default_addressbook (db.py).

    2026-08-03 (§1 Dashboard rework): first two defaults are now
    calendar_agenda (third/30%) and today_agenda (two_thirds/70%) side by
    side, replacing the old mini_month_calendar + today_agenda pairing.
    Width configs are set on the seeded widgets so the out-of-the-box
    layout is already the intended 30/70 split, not each type's own
    default_width."""
    if db.list_dashboard_widgets(conn):
        return
    now = _now()
    for i, wtype in enumerate(_DEFAULT_WIDGETS):
        config = dict(_DEFAULT_WIDGET_CONFIGS.get(wtype) or {})
        db.upsert_dashboard_widget(
            conn, {"uid": str(uuid.uuid4()), "type": wtype, "title": None, "config": config, "position": float(i), "created_at": now}
        )


# Space widget grid (2026-08-02 follow-up to spaces-home-pipeline) -- a
# Space page gets the exact same widget system as Home (WIDGET_TYPES,
# add/edit/resize/stack/reorder, all below), just scoped to its own
# dashboard_widgets rows via space_uid instead of the default NULL
# ("Home"). Every widget seeded here is pre-configured with
# config["group_uid"] = this space's uid so it's useful immediately with
# no setup -- see _group_project_uids/_render_project_preview/
# _render_habit_checkin, which all already know how to resolve that key.
_DEFAULT_SPACE_WIDGETS: list[tuple[str, dict]] = [
    # Calendar+Agenda at third width sits alongside the weekly overview
    # (two_thirds) -- same 30/70 pattern as the Home default (§2 Spaces v2,
    # 2026-08-03). Project cards and habit check-in follow as the next row.
    ("calendar_agenda", {"width": "third", "height": "xl"}),
    ("weekly_overview", {"width": "two_thirds", "height": "xl", "range_days": 7}),
    ("project_preview", {}),
    ("habit_checkin", {}),
]


def _ensure_default_space_widgets(conn, space_uid: str) -> None:
    """Same idempotent-once-ever seeding as _ensure_default_widgets, scoped
    to one Space -- a no-op once *that space* has any widget of its own,
    checked independently of every other space's/Home's own widgets.

    The weekly_overview's `range_days` is sourced from the Space's own
    `default_range_days` column (§2 Spaces v2: "Personal: ~90 days;
    University: upcoming week/month — a plain setting on the space")
    rather than always being 7; falls back to 7 when the setting isn't
    set, matching the original default."""
    if db.list_dashboard_widgets(conn, space_uid=space_uid):
        return
    group = db.get_project_group(conn, space_uid)
    space_range = (group or {}).get("default_range_days") or 7
    now = _now()
    for i, (wtype, extra_config) in enumerate(_DEFAULT_SPACE_WIDGETS):
        config = {"group_uid": space_uid, **extra_config}
        # Override the weekly_overview's range_days with the space's own
        # default_range_days so a Personal space can default to 90 days
        # while a University space defaults to 7.
        if wtype == "weekly_overview":
            config["range_days"] = space_range
        db.upsert_dashboard_widget(
            conn,
            {
                "uid": str(uuid.uuid4()),
                "type": wtype,
                "title": None,
                "config": config,
                "position": float(i),
                "created_at": now,
                "space_uid": space_uid,
            },
        )


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
    height = _widget_height(widget, spec)
    source, view, range_ = _selection_from_widget(widget)
    selection = {"source": source, "view": view, "range": range_}
    if spec is None:
        return {"widget": widget, "spec": None, "data": None, "width": width, "height": height, "selection": selection, "is_stack": False}
    data = spec["render"](conn, widget["config"], nav)
    return {"widget": widget, "spec": spec, "data": data, "width": width, "height": height, "selection": selection, "is_stack": False}


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
            height = _widget_height(w, None)
            children = [_widget_context(conn, c, nav) for c in children_by_group.get(w["uid"], [])]
            contexts.append({"widget": w, "spec": None, "data": None, "width": width, "height": height, "selection": None, "is_stack": True, "children": children})
        else:
            contexts.append(_widget_context(conn, w, nav))
    return contexts


def _return_url(space_uid: str | None) -> str:
    """Where a widget-mutating POST should redirect back to -- Home ("/")
    when the acted-on widget has no space_uid, or that Space's own page
    otherwise. Derived from the widget itself wherever one already exists
    (edit/resize/stack/unstack/delete/move/reorder below); only add_widget
    has no existing widget to derive it from, so it takes space_uid as a
    hidden form field instead (see _widget_workspace.html)."""
    return f"/projects/groups/{space_uid}" if space_uid else "/"


def widget_page_context(conn, space_uid: str | None = None, edit: bool = False, nav: dict | None = None) -> dict:
    """Every piece of context _widget_workspace.html needs to render one
    page's widget grid (Add-widget form, live preview pane, the grid
    itself, each widget's own Filters panel) -- shared by dashboard_view
    (space_uid=None, below) and routers/projects.py's space_detail
    (space_uid set) so both pages run through the exact same widget
    machinery -- add/edit/resize/stack/reorder, all further below -- rather
    than a second, parallel implementation living on the Space route."""
    widgets = db.list_dashboard_widgets(conn, space_uid=space_uid)
    widget_contexts = _build_widget_contexts(conn, widgets, nav)
    return {
        "space_uid": space_uid or "",
        "page_url": _return_url(space_uid),
        "edit_mode": edit,
        "widget_contexts": widget_contexts,
        "widget_types": WIDGET_TYPES,
        "widget_widths": WIDGET_WIDTHS,
        "widget_heights": WIDGET_HEIGHTS,
        "widget_sources": WIDGET_SOURCES,
        "widget_views": WIDGET_VIEWS,
        "widget_ranges": WIDGET_RANGES,
        "projects": db.list_projects(conn),
        "task_lists": db.list_task_lists(conn),
        "calendars": db.list_calendars(conn),
        "tag_names": db.list_tag_names_in_use(conn),
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
    ctx.update(
        {
            "request": request,
            "active_tab": "dashboard",
            # Space cards (spaces-home-pipeline, 2026-08-02) -- Home is the
            # only way to reach a Space page, deliberately not a tabbar
            # entry (see the plan doc's scope guardrails).
            "project_groups": db.list_project_groups(conn),
        }
    )
    return templates.TemplateResponse("dashboard.html", ctx)


def _config_from_form(
    project_uid: str,
    tags: str,
    task_list_uids: list[str],
    calendar_uids: list[str],
    limit: str,
    width: str = "",
    range_days: int | None = None,
) -> dict:
    config: dict = {}
    if project_uid:
        config["project_uid"] = project_uid
    tag_list = _tags_list(tags)
    if tag_list:
        config["tags"] = tag_list
    # Both task-list and calendar selections land in the same "list_uids"
    # filter key (_passes_filters doesn't care which kind of list a uid
    # came from, only whether the item's own list_uid is in the set) --
    # a widget that reads both tasks and events can therefore accept a
    # mixed selection naturally, without two separate filter keys to keep
    # in sync.
    list_uids = list(task_list_uids or []) + list(calendar_uids or [])
    if list_uids:
        config["list_uids"] = list_uids
    if limit:
        try:
            config["limit"] = int(limit)
        except ValueError:
            pass
    # Grid width (2026-08-01) -- validated against WIDGET_WIDTHS rather
    # than trusted as-is, since this is user-submitted form data; an
    # unrecognized/missing value just falls back to the widget type's own
    # default_width at render time (_widget_width), not stored at all.
    if width in WIDGET_WIDTHS:
        config["width"] = width
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
    space widgets) is only ever present when previewing from a Space
    page's own Add-widget form -- see add_widget below for why the
    preview has to auto-scope the same way the real save does."""
    if source not in WIDGET_SOURCES:
        return templates.TemplateResponse(
            "_dashboard_widget_preview.html",
            {"request": request, "widget": {"uid": "preview", "title": title}, "spec": None, "data": None},
        )
    wtype, range_days = _resolve_selection(source, view, range or None)
    spec = WIDGET_TYPES[wtype]
    config = _config_from_form(project_uid, tags, task_list_uids, calendar_uids, limit, range_days=range_days)
    if space_uid:
        config["group_uid"] = space_uid
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
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    width: str = Form(""),
    space_uid: str = Form(""),
    conn=Depends(get_db),
):
    """`space_uid` (2026-08-02, per-space widgets) -- a hidden field on
    _widget_workspace.html's Add-widget form, empty on Home and set to the
    Space's own uid on a Space page. This is the one mutating route that
    can't derive its page from an existing widget (there isn't one yet),
    so it's the one place space is threaded through the form instead of
    read back off a row. Every widget added from a Space auto-scopes to
    it via config["group_uid"] (the answered "auto-scope" design question,
    2026-08-02) -- the user never has to pick a Project filter just to
    keep a widget from leaking other spaces' data."""
    if source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(space_uid or None), status_code=303)
    wtype, range_days = _resolve_selection(source, view, range or None)
    config = _config_from_form(project_uid, tags, task_list_uids, calendar_uids, limit, width, range_days)
    if space_uid:
        config["group_uid"] = space_uid
    db.upsert_dashboard_widget(
        conn,
        {
            "uid": str(uuid.uuid4()),
            "type": wtype,
            "title": title.strip() or None,
            "config": config,
            "position": db.next_dashboard_widget_position(conn, space_uid or None),
            "created_at": _now(),
            "space_uid": space_uid or None,
        },
    )
    return RedirectResponse(url=_return_url(space_uid or None), status_code=303)


@router.post("/dashboard/widgets/{uid}/edit")
def edit_widget(
    uid: str,
    source: str = Form(...),
    view: str = Form(...),
    range: str = Form(""),
    title: str = Form(""),
    project_uid: str = Form(""),
    tags: str = Form(""),
    task_list_uids: list[str] = Form([]),
    calendar_uids: list[str] = Form([]),
    limit: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return RedirectResponse(url="/", status_code=303)
    space_uid = existing.get("space_uid")
    if source not in WIDGET_SOURCES:
        return RedirectResponse(url=_return_url(space_uid), status_code=303)
    wtype, range_days = _resolve_selection(source, view, range or None)
    row = dict(existing)
    new_config = _config_from_form(project_uid, tags, task_list_uids, calendar_uids, limit, range_days=range_days)
    # Width isn't a field on this form (2026-08-01) -- it's set by
    # dragging the card's own resize handle instead, a separate action
    # against a separate endpoint (/resize below). Preserve whatever
    # width the widget already had rather than rebuilding config from
    # scratch and silently dropping it back to the type's default the
    # next time someone just changes, say, the Project filter or the
    # Source/View/Range itself.
    existing_width = (existing.get("config") or {}).get("width")
    if existing_width in WIDGET_WIDTHS:
        new_config["width"] = existing_width
    # Same preservation for height (2026-08-02) -- also drag-only, also
    # not a field on this form, same "don't silently reset it back to the
    # type's default" reasoning as width just above.
    existing_height = (existing.get("config") or {}).get("height")
    if existing_height in WIDGET_HEIGHTS:
        new_config["height"] = existing_height
    # Re-scope to whichever page this widget already belongs to
    # (2026-08-02) -- a Space widget's group_uid filter isn't a field on
    # this form either, same reasoning as width: editing Title/Source/
    # Project/Tags must never silently un-scope a widget from its Space.
    if space_uid:
        new_config["group_uid"] = space_uid
    row.update({"type": wtype, "title": title.strip() or None, "config": new_config})
    db.upsert_dashboard_widget(conn, row)
    return RedirectResponse(url=_return_url(space_uid), status_code=303)


@router.post("/dashboard/widgets/{uid}/resize")
def resize_widget(uid: str, width: str = Form(...), conn=Depends(get_db)):
    """Drag-to-resize (static/app.js, edit mode's .widget-resize-handle) --
    a dedicated endpoint rather than routing through edit_widget above,
    because that one rebuilds the *entire* config from a full form
    submission; a resize is a one-field change and should only ever touch
    that one field, never risk clobbering Project/Tags/List filters that
    happen not to be present in whatever request triggered it."""
    if width not in WIDGET_WIDTHS:
        return JSONResponse({"error": f"invalid width '{width}'"}, status_code=400)
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["config"] = dict(row.get("config") or {})
    row["config"]["width"] = width
    db.upsert_dashboard_widget(conn, row)
    return JSONResponse({"ok": True})


@router.post("/dashboard/widgets/{uid}/resize-height")
def resize_widget_height(uid: str, height: str = Form(...), conn=Depends(get_db)):
    """Drag-to-resize, vertical axis (2026-08-02 -- "a way to resize them
    vertically") -- exact mirror of resize_widget above, just the other
    dimension and its own config key, so a height change never risks
    touching width/Project/Tags/List filters the way a full edit_widget
    submission would."""
    if height not in WIDGET_HEIGHTS:
        return JSONResponse({"error": f"invalid height '{height}'"}, status_code=400)
    existing = db.get_dashboard_widget(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["config"] = dict(row.get("config") or {})
    row["config"]["height"] = height
    db.upsert_dashboard_widget(conn, row)
    return JSONResponse({"ok": True})


def _dissolve_stack(conn, stack: dict) -> None:
    """Ungroups every member of `stack` back to the top level, in their
    existing relative order, landing at the stack's own old position and
    inheriting its shared width -- used both when a stack is explicitly
    deleted (dissolve, don't destroy -- see delete_widget below) and when
    unstacking a widget leaves a stack with fewer than 2 members (a
    "stack" of one thing isn't a stack, it's just that widget). Height is
    deliberately NOT shared/propagated here the way width is (2026-08-02)
    -- stack members render one above another in a single card, each
    keeping its own independently-resizable content height (see
    widget_inner's own resize handle in _widget_workspace.html), not one
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
    if moved.get("space_uid") != target.get("space_uid"):
        # A stack's members share one width/position range scoped to a
        # single page's grid (2026-08-02) -- stacking across Home and a
        # Space, or across two different Spaces, would leave the stack
        # only correctly orderable on whichever page rendered it last.
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
                # equal by the space_uid check above).
                "space_uid": target.get("space_uid"),
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
    stack_uid = widget["group_uid"]
    stack = db.get_dashboard_widget(conn, stack_uid)
    widget = dict(widget)
    widget["group_uid"] = None
    widget["position"] = db.next_dashboard_widget_position(conn, space_uid)
    if stack:
        widget_config = dict(widget.get("config") or {})
        widget_config["width"] = (stack.get("config") or {}).get("width", widget_config.get("width"))
        widget["config"] = widget_config
    db.upsert_dashboard_widget(conn, widget)
    _dissolve_if_singleton(conn, stack_uid)
    return RedirectResponse(url=_return_url(space_uid), status_code=303)


@router.post("/dashboard/widgets/{uid}/delete")
def delete_widget(uid: str, conn=Depends(get_db)):
    widget = db.get_dashboard_widget(conn, uid)
    if widget is not None:
        space_uid = widget.get("space_uid")
        if widget["type"] == "stack":
            # Dissolve, don't destroy -- a stack is a layout grouping, not
            # a real owner of the widgets inside it, so removing it should
            # never take your Filters config for those widgets with it.
            _dissolve_stack(conn, widget)
            return RedirectResponse(url=_return_url(space_uid), status_code=303)
        stack_uid = widget.get("group_uid")
        db.delete_dashboard_widget(conn, uid)
        if stack_uid:
            _dissolve_if_singleton(conn, stack_uid)
        return RedirectResponse(url=_return_url(space_uid), status_code=303)
    db.delete_dashboard_widget(conn, uid)
    return RedirectResponse(url="/", status_code=303)


@router.post("/dashboard/widgets/{uid}/move")
def move_widget(uid: str, direction: str = Form(...), conn=Depends(get_db)):
    target_widget = db.get_dashboard_widget(conn, uid)
    if target_widget is None:
        return RedirectResponse(url="/", status_code=303)
    space_uid = target_widget.get("space_uid")
    widgets = db.list_dashboard_widgets(conn, space_uid=space_uid)
    idx = next((i for i, w in enumerate(widgets) if w["uid"] == uid), None)
    if idx is None:
        return RedirectResponse(url=_return_url(space_uid), status_code=303)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(widgets):
        db.swap_dashboard_widget_positions(conn, widgets[idx]["uid"], widgets[swap_idx]["uid"])
    return RedirectResponse(url=_return_url(space_uid), status_code=303)


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
    # Scoped to `moved`'s own page (space_uid) as well as its stack
    # membership (group_uid, pre-existing) -- otherwise every page's
    # top-level widgets (group_uid IS NULL on all of them) would end up
    # compared against each other (2026-08-02, per-space widgets).
    all_widgets = db.list_dashboard_widgets(conn, space_uid=moved.get("space_uid"))
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
