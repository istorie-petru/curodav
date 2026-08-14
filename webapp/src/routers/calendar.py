from __future__ import annotations

import calendar as py_calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, grid_layout, recurrence_expand, schedule
from ..deps import _four_week_position, _week_start, get_db, templates
from . import dashboard as dashboard_router

# Month-view per-day list: how many rows (all-day colored rows + timed
# events + tasks, all in ONE flat list per day cell -- no more separate
# bar lanes, see _month_grid) to show before the rest collapse into a
# "+N more" overflow link to the day view. 2026-08-08 direct feedback
# ("reduce the number of events/tasks shown in a cell", then "maximum of
# four before adding a label") -- this list was previously unbounded and
# could run a cell's content well past its own border, especially now
# that the month grid can shrink to fit the viewport (see style.css's
# .month-viewport height rule) instead of always having a full 90px+ of
# vertical room to spill into.
MONTH_MAX_VISIBLE_ITEMS = 4

# Free-text fields (Location / Meeting URL / Recurrence) once got the
# literal string "None" saved into them by a pre-2026-08-08 str(None) sync
# bug (see db.py's init_schema self-heal) -- `"" or None` treats a truly
# empty submission as empty, but "None" is a *truthy* string, so it sailed
# straight through `location or None` and kept persisting. Normalize those
# placeholder-ish values to a real None on the way in so they can't round-
# trip any more, same for the task/contact forms' recurrence/org/etc.
_NONE_LIKE = ("None", "Nothing", "none", "nothing")


def _clean_field(value: str) -> str | None:
    stripped = (value or "").strip()
    return None if stripped in _NONE_LIKE else (stripped or None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


router = APIRouter(prefix="/calendar", tags=["calendar"])
# Event CRUD is a separate, unprefixed router -- these are shared item
# endpoints (fetched by uid from Month/Week/Day/Agenda views, the modal
# system, etc.), not "the calendar page" itself, same as /tasks/... and
# /contacts/... aren't nested under their own view prefixes either.
events_router = APIRouter(tags=["events"])


def _week_bounds(d: date, week_start: str = "monday") -> tuple[date, date]:
    """First/last day of the calendar week `d` falls in. `date.weekday()`
    is always Monday=0..Sunday=6 regardless of preference -- `offset`
    below is how many days back from `d` its own week's first day is,
    computed against whichever day the "Week starts on" Settings >
    General preference (deps.py's week_start()) names as day 0."""
    first_weekday = 6 if week_start == "sunday" else 0  # Python's date.weekday(): Mon=0..Sun=6
    offset = (d.weekday() - first_weekday) % 7
    start = d - timedelta(days=offset)
    return start, start + timedelta(days=6)


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _weekday_names(week_start: str) -> list[str]:
    """The weekday header row (calendar_month.html / calendar_fourweek.html),
    rotated to start on whichever day "Week starts on" (Settings > General,
    deps.py's week_start()) names as day 0 so the header always matches the
    actual column order _month_grid/_four_week_grid built above. Shared by
    both views so the two can't drift on the rotation."""
    names = list(_WEEKDAY_NAMES)
    if week_start == "sunday":
        names = names[6:] + names[:6]
    return names


def _hhmm_to_minutes(t: str) -> int:
    """"HH:MM" -> minutes since midnight -- the Sleep/Leisure Time blocks'
    own start_time/end_time storage format (routers/settings.py's Time
    inputs), same idea as grid_layout._minutes but reading a bare time
    string instead of slicing an ISO datetime."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _time_block_overlays_for_day(blocks: list[dict], day: date) -> list[dict]:
    """Every Sleep/Leisure Time block (db.list_time_blocks) that applies to
    `day`'s weekday, turned into a top_px/height_px overlay the Week/Day
    grid can render directly behind its events -- same top/height math as
    grid_layout.position_event, just driven off a fixed weekly time range
    instead of one event's start_at/end_at. `date.strftime('%A')` gives the
    same full weekday name (e.g. "Monday") db.TIME_BLOCK_DAYS/time_blocks.days
    already store, so no separate lookup table is needed here."""
    weekday = day.strftime("%A")
    overlays = []
    for b in blocks:
        if weekday not in db.time_block_days(b):
            continue
        start_min = _hhmm_to_minutes(b["start_time"])
        end_min = _hhmm_to_minutes(b["end_time"])
        if end_min <= start_min:
            continue  # defensive -- create/update already reject this, but never trust storage alone
        overlays.append(
            {
                "kind": b["kind"],
                "top_px": round(start_min / 60 * grid_layout.PX_PER_HOUR, 1),
                "height_px": round((end_min - start_min) / 60 * grid_layout.PX_PER_HOUR, 1),
            }
        )
    return overlays


def _time_blocks_client_payload(blocks: list[dict]) -> str:
    """JSON for the Week/Day grid's client-side scheduling-warning check
    (static/time_blocks.js) -- {kind, label, days, start_min, end_min} per
    block, minutes-since-midnight so the client never has to re-parse
    "HH:MM" strings. Rendered into a page-local <script type="application/
    json"> tag rather than an inline JS literal so it round-trips through
    Jinja's HTML auto-escaping safely (json.dumps already produces valid,
    self-contained JSON text -- no `</script>`-breaking concerns here since
    every string value is a plain label/day name this app itself controls
    via Settings > Sleep & Leisure Time, never arbitrary user HTML)."""
    return json.dumps(
        [
            {
                "kind": b["kind"],
                "label": b.get("label") or "",
                "days": db.time_block_days(b),
                "start_min": _hhmm_to_minutes(b["start_time"]),
                "end_min": _hhmm_to_minutes(b["end_time"]),
            }
            for b in blocks
        ]
    )


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


_TASK_STATUS_DOT_COLORS = {
    "active": "blue",
    "in_progress": "orange",
    "waiting": "yellow",
    "done": "green",
    "archived": "gray",
}


def _shares_label(a_tags: list[str] | None, b_tags: list[str] | None) -> bool:
    """The defining rule of a relation (2026-08-09): an event and a task
    may only be linked when they carry at least one label in common --
    "both have at least one label in common." Enforced by the picker (it
    only offers already-shared candidates) and re-checked defensively by
    the add-relation routes, since labels can change between render and
    submit. Same helper as routers/tasks.py's, kept local like this
    router's own _tags_list."""
    return bool(set(a_tags or []) & set(b_tags or []))


def _related_context(conn, event: dict | None) -> dict:
    """Context keys every event view modal needs for its Relations card:
    the tasks already linked to this event. `None` event -> empty list, so
    templates never branch on the object existing.

    1.2 side work (Universal command surface step 3): this used to also
    precompute `linkable_tasks` -- every not-yet-linked task sharing a
    label with this event, the old `<select>`'s entire option pool. The
    picker overlay (static/command_palette.js) now asks `GET /api/search
    ?for_event=<uid>` for exactly the page of candidates it needs instead,
    so there's nothing left to precompute here."""
    if event is None:
        return {"related_tasks": []}
    related = db.related_tasks_for_event(conn, event["uid"])
    # The event card's relation rows use a status-colored identity dot, the
    # same mapping task views render task status with (routers/tasks.py's
    # STATUS_COLORS, duplicated here rather than imported -- the two
    # routers share helpers in only one direction, and this is a tiny,
    # table-driven lookup that never changes on its own).
    for t in related:
        t["status_color"] = _TASK_STATUS_DOT_COLORS.get(t["status"], "blue")
    return {"related_tasks": related}


def _group_education_next_lectures(conn, label: str | None) -> list[dict]:
    """Phase 6 -- the education "next lecture" badge strip for a Space-
    filtered calendar. Phase 2 (label-space rework) dropped project_groups'
    `kind='education'` column -- there's no dedicated "education space"
    flag anymore, so this now just checks whether the filtered Space
    (a generate_space=1 label) has any class events among its child
    labels' members at all; any other filter renders no badges. 1.6
    (Schedule & recurrence rework): a "class" is now a real recurring
    event carrying the Schedule system label plus a course label
    (db.list_schedule_class_events), not its own schedule_classes row --
    each entry's "class" key is that event dict now, and the next
    occurrence is read straight off the event's own RRULE/EXDATE
    (schedule.next_occurrence_for_event) instead of being re-derived from
    settings/holidays. Phase 9b toolbar rework: the calendar's filter is a
    plain event label filter (`label`, see month_view/week_view/day_view/
    agenda_view below), not a dedicated Space/Project picker -- this still
    works unchanged since a Space is just a label like any other, `label`
    here plays the same role `group_uid` used to. Each entry: {"class":
    <event row>, "date": <next date>, "label": "today"|"tomorrow"|"in N
    days"}."""
    from datetime import date as _date

    if not label:
        return []
    cfg = db.get_label_config(conn, label)
    if not cfg or not cfg.get("generate_space"):
        return []
    child_names = {c["name"] for c in db.list_child_labels(conn, label)}
    classes = [
        c for c in db.list_schedule_class_events(conn) if child_names & set(c.get("tags") or [])
    ]
    if not classes:
        return []
    today = _date.today()
    holiday_calendars = db.list_holidays_by_calendar(conn)
    badges = []
    for cl in classes:
        nxt = schedule.next_occurrence_for_event(cl, today, holiday_calendars=holiday_calendars)
        if not nxt:
            continue
        # The badge's acronym is the course's own label_config.course_acronym
        # now (see db.py's label_config CREATE TABLE comment) -- an event
        # itself has no acronym field, only its title.
        course_name = db.project_label_for(conn, "event", cl["uid"])
        course_cfg = db.get_label_config(conn, course_name) if course_name else None
        cl = dict(cl)
        cl["acronym"] = (course_cfg or {}).get("course_acronym")
        badges.append({"class": cl, "date": nxt, "label": schedule.next_label(nxt, today)})
    return badges


def _apply_event_label_filter(events: list[dict], label: str | None) -> list[dict]:
    """Phase 9b toolbar rework -- Calendar's new event label filter,
    replacing the dead Space/Project dropdowns (see _calendar_nav.html's
    former project_groups/projects form). Same case-insensitive
    single-label match every other label filter in this app uses."""
    if not label:
        return events
    wanted = label.lower()
    return [e for e in events if any((tg or "").lower() == wanted for tg in e.get("tags") or [])]


_DEFAULT_EVENT_COLOR = "blue"


def _annotate_calendar_colors(conn, events: list[dict]) -> list[dict]:
    """Fixes a real, pre-existing bug found 2026-08-07 while reworking
    Month view's multi-day bars: every calendar template (Month/Week/
    Day/Agenda) has always read `e.calendar_color` to color-code events
    (`cal-{{ e.calendar_color }}`, the same class convention labels use
    for their own color pills) -- but nothing anywhere in db.py has ever
    set that key on an event row. It's been silently undefined since the
    label-space rework removed the old `calendars` table (which used to
    be where an event's color genuinely lived, one color per calendar);
    every event has been rendering with the class `cal-` (empty suffix,
    no color) this whole time, on every calendar view, not just Month.

    Fix, consistent with how color already works everywhere else in this
    app post-rework (a label's own `color` field, e.g. `label_config`
    rows, `cell-tag cal-{{ l.color }}` in labels_manage.html): an event's
    color is its first label's color (alphabetical, for a stable pick
    when an event carries more than one label), falling back to a fixed
    neutral default for an unlabeled event. Mutates and returns the same
    list (matches _apply_event_label_filter's sibling functions' style
    of returning a list rather than annotating in place silently)."""
    color_by_label: dict[str, str] = {}
    for e in events:
        tags = sorted(e.get("tags") or [], key=str.lower)
        color = _DEFAULT_EVENT_COLOR
        for name in tags:
            if name not in color_by_label:
                # effective_label_config, not get_label_config -- fills in
                # the same 'blue' default a label with no config row would
                # show on its own manage page, so an event's color matches
                # what that label looks like everywhere else in the app.
                cfg = db.effective_label_config(conn, name)
                color_by_label[name] = cfg.get("color") or _DEFAULT_EVENT_COLOR
            color = color_by_label[name]
            break
        e["calendar_color"] = color
    return events


def _apply_task_label_filter(tasks: list[dict], label: str | None) -> list[dict]:
    """Same as _apply_event_label_filter, for the task chips Day/Week/
    Month/Agenda also show alongside events (object_type='task' labels)."""
    if not label:
        return tasks
    wanted = label.lower()
    return [t for t in tasks if any((tg or "").lower() == wanted for tg in t.get("tags") or [])]


def _is_bar_worthy(e: dict) -> bool:
    """2026-08-07 follow-up to the Month-view bar rework: not every event
    belongs in the bar system. Apple/Google both draw a hard line here --
    an all-day event or a genuine multi-day span gets a colored bar; a
    plain timed event on a single day (a 2-hour meeting) renders as
    compact text with a time + color dot instead, the same visual weight
    this app's tasks already have. The first version of this rework put
    *every* event through the old bar-lane layout regardless, which is
    why a single "9am" timed event was showing up as a full-width filled
    pill getting its title truncated to "9" -- there was no length/weight
    distinction between a week-long trip and an hour-long call.

    Bar-worthy: `all_day` is set. Full stop -- a *timed* event that
    happens to span multiple days (e.g. an overnight flight, or a
    conference with specific 9am-5pm times across three days) is still
    text, not a bar, matching direct feedback: "color background should
    be only all day and multi day all day. The rest are text only."
    2026-08-07's first version of this function also treated any multi-
    day date range as bar-worthy regardless of the all_day flag -- that
    was wrong per this feedback and has been narrowed to just the
    all_day check."""
    return bool(e.get("all_day"))


def _event_date_range(e: dict) -> tuple[date, date] | None:
    """(start_date, end_date), both inclusive, for laying an event out on
    the Month grid -- `end_at` is stored inclusive-of-last-day here (see
    `new_event_form`'s all-day prefill: `f"{end_date}T23:59"`, not next-day
    midnight), so no exclusive/inclusive adjustment is needed beyond
    slicing the date portion off each timestamp. Falls back to a same-day
    range when `end_at` is missing or (defensively) earlier than
    `start_at`."""
    start_raw = e.get("start_at")
    if not start_raw:
        return None
    start_d = date.fromisoformat(start_raw[:10])
    end_raw = e.get("end_at")
    end_d = date.fromisoformat(end_raw[:10]) if end_raw else start_d
    if end_d < start_d:
        end_d = start_d
    return start_d, end_d


def _bucket_month_items(events: list[dict], tasks: list[dict]) -> tuple[dict, dict, dict]:
    """Buckets events/tasks into per-date maps for the Month and 4-Week
    grids -- the three dicts _month_grid used to build inline, extracted
    so the new 4-Week view (_four_week_grid, 2026-08-11) builds identical
    day cells from a continuous 28-day window without duplicating the
    all-day/multi-day repeat-per-day + timed-sort logic. Returns
    (all_day_by_date, timed_by_date, tasks_by_date).

    Multi-day events (all-day or timed) repeat on every day they touch,
    not just their start date -- same "repeated entry per day" behavior
    Apple/Google use, and the fix for the original "event only showed on
    its start day" bug this view's rework started from."""
    all_day_events = [e for e in events if _is_bar_worthy(e)]
    timed_events = [e for e in events if not _is_bar_worthy(e)]

    all_day_by_date: dict[str, list[dict]] = {}
    for e in all_day_events:
        rng = _event_date_range(e)
        if rng is None:
            continue
        start_d, end_d = rng
        d = start_d
        while d <= end_d:
            all_day_by_date.setdefault(d.isoformat(), []).append(e)
            d += timedelta(days=1)

    timed_by_date: dict[str, list[dict]] = {}
    for e in timed_events:
        rng = _event_date_range(e)
        if rng is None:
            continue
        start_d, end_d = rng
        d = start_d
        while d <= end_d:
            timed_by_date.setdefault(d.isoformat(), []).append(e)
            d += timedelta(days=1)
    for day_events in timed_by_date.values():
        day_events.sort(key=lambda e: e.get("start_at") or "")

    tasks_by_date: dict[str, list[dict]] = {}
    for t in tasks:
        if not t.get("due_at"):
            continue
        tasks_by_date.setdefault(t["due_at"][:10], []).append(t)

    return all_day_by_date, timed_by_date, tasks_by_date


def _month_day_cells(
    dates: list[date],
    all_day_by_date: dict,
    timed_by_date: dict,
    tasks_by_date: dict,
    today: date,
    is_window_day,
) -> list[dict]:
    """Build one week's day cells -- the shared core of the Month and
    4-Week grids (2026-08-11). `dates` is a single week's 7 days;
    `is_window_day(date) -> bool` marks a cell in-window (Month:
    day.month == month, which grays out the leading/trailing adjacent-month
    days; 4-Week: always True, since its window is exactly 4 weeks and
    never bleeds into surrounding weeks/months).

    Each cell is ONE flat list of rows: all-day colored rows first, then
    timed events by time, then tasks -- same visual priority the cell
    shows top-to-bottom, and the count that feeds the "+N more" link. The
    key is `rows`, NOT `items` -- a dict key named `items` would collide
    with Python's own `dict.items` method in Jinja (a template's `day.items`
    would resolve to the bound method and crash iterating over it)."""
    week_days = []
    for day in dates:
        key = day.isoformat()
        rows = []
        for e in all_day_by_date.get(key, []):
            rows.append({"kind": "all_day", "event": e})
        for e in timed_by_date.get(key, []):
            rows.append({"kind": "event", "event": e})
        for t in tasks_by_date.get(key, []):
            rows.append({"kind": "task", "task": t})
        visible = rows[:MONTH_MAX_VISIBLE_ITEMS]
        week_days.append(
            {
                "date": day,
                "iso": key,
                "in_month": is_window_day(day),
                "is_today": day == today,
                "rows": visible,
                "overflow_count": len(rows) - len(visible),
            }
        )
    return week_days


def _month_grid(year: int, month: int, events: list[dict], tasks: list[dict], week_start: str = "monday") -> list[dict]:
    # 2026-08-08 rework: every day cell is a single flat list, no more
    # lane-packed bars layered on top of a separate quiet-text list --
    # that layering is exactly what let the colored all-day rows overlap
    # the text events/tasks. Now all three types live in one list where
    # each item is tagged with its `kind` so the template can render
    # all-day events as colored rows, timed events as time+dot text, and
    # tasks as square+title text, with no overlap between them.
    # Everything past MONTH_MAX_VISIBLE_ITEMS folds into the "+N more"
    # overflow link that directs to the day view. The per-day cell work
    # lives in _bucket_month_items/_month_day_cells so the 4-Week view
    # (_four_week_grid) can reuse it over a continuous 28-day window.
    all_day_by_date, timed_by_date, tasks_by_date = _bucket_month_items(events, tasks)

    # Python's calendar module: firstweekday=0 is Monday, 6 is Sunday --
    # same "Week starts on" preference _week_bounds above reads.
    cal = py_calendar.Calendar(firstweekday=6 if week_start == "sunday" else 0)
    today = date.today()
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        weeks.append(
            {
                "days": _month_day_cells(
                    week, all_day_by_date, timed_by_date, tasks_by_date, today, lambda d: d.month == month
                )
            }
        )
    return weeks


def _four_week_window(anchor: date, week_start: str, position: int) -> tuple[date, date]:
    """(view_start, view_end) for the 4-Week view (2026-08-11): a
    continuous 28-day window whose `position`-th week (1-4) is the anchor
    week -- the week `anchor` falls in, per the "Week starts on"
    preference. Position 1 puts the anchor week on the first row (the
    window starts at the anchor week itself), position 2 on the second
    (starts one week earlier), 3 on the third, 4 on the fourth -- i.e.
    the window starts `(position - 1) * 7` days before the anchor week.
    Extracted from four_week_view so the math is unit-testable independent
    of request/settings plumbing."""
    anchor_week_start, _ = _week_bounds(anchor, week_start)
    view_start = anchor_week_start - timedelta(days=(position - 1) * 7)
    return view_start, view_start + timedelta(days=27)


def _four_week_grid(view_start: date, events: list[dict], tasks: list[dict], week_start: str = "monday") -> list[dict]:
    """4-Week view's day grid (2026-08-11) -- the Month grid's own day-cell
    layout (_month_day_cells) laid out over a continuous 28-day window
    instead of a calendar month: exactly four week rows, every cell always
    in-window (no grayed-out .not-in-month adjacent-month days at all,
    since the window never bleeds into surrounding weeks/months). `view_start`
    is the window's first day (a week start, already shifted back by the
    current-week-position preference -- see four_week_view below). Keeps
    the same interaction surface as Month: each cell's data-date + DOM
    order feed static/calendar_month.js's click-and-hold drag-to-create
    unchanged."""
    all_day_by_date, timed_by_date, tasks_by_date = _bucket_month_items(events, tasks)
    today = date.today()
    weeks = []
    for week_index in range(4):
        dates = [view_start + timedelta(days=week_index * 7 + i) for i in range(7)]
        weeks.append(
            {
                "days": _month_day_cells(
                    dates, all_day_by_date, timed_by_date, tasks_by_date, today, lambda d: True
                )
            }
        )
    return weeks


@router.get("")
def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    label: str | None = None,
    conn=Depends(get_db),
):
    today = date.today()
    year = year or today.year
    month = month or today.month
    week_start = _week_start(request)

    # Expand across the visible 6-week grid, not just the calendar month,
    # so recurring events show correctly on the leading/trailing days from
    # the adjacent months that the grid always displays a few of.
    grid_start = date(year, month, 1) - timedelta(days=6)
    grid_end = date(year, month, 28) + timedelta(days=13)
    events = db.list_events(conn, start=grid_start.isoformat(), end=grid_end.isoformat() + "T23:59:59")
    events = recurrence_expand.expand_events(events, grid_start, grid_end, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn))
    events = _apply_event_label_filter(events, label)
    events = _annotate_calendar_colors(conn, events)

    # Timetabled tasks (work-allocation events, scheduled from a project's
    # Week/Timetable planning grids) are scheduling placeholders, not
    # ordinary events -- they're deliberately prominent on the Week grid
    # (see week_view's own docstring) but would just be noise duplicating
    # the task's own due-date chip here, so Month excludes them entirely
    # rather than rendering them as a third kind of item.
    allocation_uids = db.work_allocation_event_uids(conn)
    events = [e for e in events if e["uid"] not in allocation_uids]

    # Phase 9b toolbar rework: the dead Space/Project dropdowns
    # (project_uid/group_uid) are gone -- `label` is the one real filter
    # now, applied to both events and the all-day task chips this page
    # also shows (see db.py's Phase 1 comments for why there's only ever
    # one universal pool of each to filter in the first place).
    tasks = db.list_tasks(conn)
    tasks = _apply_task_label_filter(tasks, label)

    weeks = _month_grid(year, month, events, tasks, week_start)

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    # Weekday header row (calendar_month.html) -- 2026-08-08: was
    # hardcoded Mon..Sun; now rotated to start on whichever day "Week
    # starts on" (Settings > General) preference names, so the header always
    # matches the actual column order _month_grid just built above. Shared
    # with the 4-Week view via _weekday_names (2026-08-11).
    weekday_names = _weekday_names(week_start)

    return templates.TemplateResponse(
        "calendar_month.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "month",
            "today_iso": today.isoformat(),
            "weeks": weeks,
            "weekday_names": weekday_names,
            "year": year,
            "month": month,
            "month_name": py_calendar.month_name[month],
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "event_label_names": db.list_event_label_names(conn),
            "active_label": label or "",
            "schedule_next_lectures": _group_education_next_lectures(conn, label),
        },
    )


@router.get("/fourweek")
def four_week_view(
    request: Request,
    date_: str | None = None,
    label: str | None = None,
    conn=Depends(get_db),
):
    """4-Week view (2026-08-11) -- Month's day-grid layout (_four_week_grid)
    over a rolling, continuous 28-day window instead of calendar-month
    boundaries. The anchor (default: today, like Month's year/month default)
    falls in the anchor week; that week occupies whichever of the four rows
    Settings > General's "4-Week view: current week" preference names
    (deps.py's _four_week_position: 1-4), so the window starts
    `(position - 1) * 7` days before the anchor week's start -- e.g.
    position 1 shows [this week, +1, +2, +3], position 2 shows
    [-1, this week, +1, +2]. Prev/next move the whole window by one week
    at a time (the anchor shifts by 7 days, so the window slides by a week
    while the anchor week keeps its configured row -- direct feedback
    2026-08-11, "move by 1 week, not 4"); the `date_` param is the anchor
    (a bare date inside whatever window is shown)."""
    today = date.today()
    anchor = date.fromisoformat(date_) if date_ else today
    week_start = _week_start(request)
    position = _four_week_position(request)
    view_start, view_end = _four_week_window(anchor, week_start, position)

    # Same `end` end-of-day-timestamp requirement as week_view below --
    # db.list_events compares these as plain strings, and a bare end-date
    # would silently exclude every timed event on the window's last day.
    events = db.list_events(conn, start=view_start.isoformat(), end=view_end.isoformat() + "T23:59:59")
    events = recurrence_expand.expand_events(events, view_start, view_end, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn))
    events = _apply_event_label_filter(events, label)
    events = _annotate_calendar_colors(conn, events)

    tasks = db.list_tasks(conn)
    tasks = _apply_task_label_filter(tasks, label)

    weeks = _four_week_grid(view_start, events, tasks, week_start)

    return templates.TemplateResponse(
        "calendar_fourweek.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "fourweek",
            "today_iso": today.isoformat(),
            "weeks": weeks,
            "weekday_names": _weekday_names(week_start),
            "view_start": view_start,
            "view_end": view_end,
            "anchor_iso": anchor.isoformat(),
            "prev_start": (view_start - timedelta(days=7)).isoformat(),
            "next_start": (view_start + timedelta(days=7)).isoformat(),
            "event_label_names": db.list_event_label_names(conn),
            "active_label": label or "",
            "schedule_next_lectures": _group_education_next_lectures(conn, label),
        },
    )


@router.get("/week")
def week_view(
    request: Request,
    date_: str | None = None,
    label: str | None = None,
    conn=Depends(get_db),
):
    """Week -- the ordinary Week grid (Month/4-Week/Week/Day) MERGED with the
    former "Timetable" sub-view (1.9 side work, direct feedback: "merge the
    calendar's week view with the timetable view"). One grid, both
    capabilities at once: ordinary calendar events stay fully interactive
    (drag-to-move/resize via `static/calendar.js`, click to open), empty grid
    space still drag-creates a new event (`.calendar-create-col`), AND every
    work-allocation event renders prominently as a draggable `.work-allocation`
    block (`static/project_calendar.js`) with its own move/resize/delete
    (block only, never the task) plus the "Unscheduled work" sidebar that
    drags a task onto the grid to schedule it. Both scripts load on this page
    now; calendar.js's own `.time-event` selector explicitly excludes
    `.work-allocation` so the two scripts never double-attach a pointerdown
    handler to the same block (see calendar.js's own comment). The sidebar is
    collapsible via a header button (static/unscheduled_panel_toggle.js,
    per-device localStorage, no server state).

    This reuses what the old timetable_view (folded in here) computed: the
    per-event `is_allocation`/`task_uid` annotation and the unscheduled-work
    list (`db.work_allocation_panel_info`), on top of the plain Week grid's
    own geometry (`grid_layout.layout_day`) and color annotation."""
    anchor = date.fromisoformat(date_) if date_ else date.today()
    week_start_date, week_end_date = _week_bounds(anchor, _week_start(request))

    # `end` must be an end-of-day timestamp, not a bare date -- db.list_events
    # compares these as plain strings, and "2026-09-02T09:00:00" sorts
    # *after* "2026-09-02" lexicographically, so a bare end-date would
    # silently exclude every timed event on the range's last calendar day.
    events = db.list_events(conn, start=week_start_date.isoformat(), end=week_end_date.isoformat() + "T23:59:59")
    events = recurrence_expand.expand_events(events, week_start_date, week_end_date, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn))
    events = _apply_event_label_filter(events, label)
    events = _annotate_calendar_colors(conn, events)

    # Every work-allocation event is schedulable-work-made-visible, prominent
    # regardless of task/project -- same annotation the old timetable_view
    # (and routers/week.py::week_view) did.
    for e in events:
        task_uid = db.work_allocation_task_uid(conn, e["uid"])
        e["is_allocation"] = bool(task_uid)
        e["task_uid"] = task_uid

    tasks = db.list_tasks(conn)
    tasks = _apply_task_label_filter(tasks, label)
    open_tasks = [t for t in db.list_tasks(conn) if t.get("status") not in ("done", "archived")]

    # Sleep/Leisure Time hatching (1.9 side work) -- fetched once for the
    # whole week, then resolved per day by weekday name (_time_block_overlays_
    # for_day), same "compute once, slice per day" shape day_all_day above
    # already uses.
    time_blocks = db.list_time_blocks(conn)

    days = []
    for i in range(7):
        d = week_start_date + timedelta(days=i)
        key = d.isoformat()
        day_events = [e for e in events if e.get("start_at", "").startswith(key)]
        timed = grid_layout.layout_day(day_events)
        day_tasks = [t for t in tasks if (t.get("due_at") or "").startswith(key)]
        time_block_overlays = _time_block_overlays_for_day(time_blocks, d)
        # All-day events repeat on every day they span, not just their
        # start date -- the same "repeated entry per day" behavior Month's
        # _month_grid already has (a multi-day all-day trip should fill
        # every day's strip, not just the first), so the strip and the
        # month view agree on which days an all-day event touches.
        day_all_day = []
        for e in events:
            if not e.get("all_day"):
                continue
            rng = _event_date_range(e)
            if rng and rng[0] <= d <= rng[1]:
                day_all_day.append(e)
        days.append(
            {
                "date": d,
                "iso": key,
                "is_today": d == date.today(),
                "all_day": day_all_day,
                "timed": timed,
                "tasks": day_tasks,
                "time_block_overlays": time_block_overlays,
            }
        )

    # Unscheduled work (the drag source): every open task with no work
    # allocation yet, across every project or none -- sorted by due date
    # (earliest first, no-due-date tasks last). Each item carries its
    # db.work_allocation_panel_info summary (session count still needing
    # placement) for the stepper the shared _unscheduled_task_item.html
    # partial renders.
    unscheduled_tasks = []
    for t in open_tasks:
        # Unscheduled = no work session at all, OR any session still has no
        # date (a "+"-added placeholder from the task modal's Work sessions
        # card awaiting placement on a grid -- see db.create_work_allocation's
        # undated form). Only a task whose every session is dated has nothing
        # left to place, so only those drop off the panel.
        info = db.work_allocation_panel_info(conn, t["uid"])
        if info["count"] and not info["undated_count"]:
            continue
        project = db.project_label_config_for(conn, "task", t["uid"])
        unscheduled_tasks.append({"task": t, "project": project, "sessions": info})
    unscheduled_tasks.sort(key=lambda item: item["task"].get("due_at") or "9999-99-99")

    return templates.TemplateResponse(
        "calendar_week.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "week",
            "today_iso": date.today().isoformat(),
            "days": days,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            # Context keys kept as "monday"/"sunday" for calendar_week.html
            # (unchanged template contract) even though the actual first
            # day of the displayed week is now whichever "Week starts on"
            # (Settings > General) names -- these are just "first/last
            # displayed day of the week," same as before this preference
            # existed.
            "monday": week_start_date,
            "sunday": week_end_date,
            "prev_week": (week_start_date - timedelta(days=7)).isoformat(),
            "next_week": (week_start_date + timedelta(days=7)).isoformat(),
            "unscheduled_tasks": unscheduled_tasks,
            "unscheduled_next": f"/calendar/week?date_={week_start_date.isoformat()}",
            "event_label_names": db.list_event_label_names(conn),
            "active_label": label or "",
            "schedule_next_lectures": _group_education_next_lectures(conn, label),
            "time_blocks_json": _time_blocks_client_payload(time_blocks),
        },
    )


@router.get("/timetable")
def timetable_view_redirect(date_: str | None = None, label: str | None = None):
    """The former standalone "Timetable" sub-view is now just Week (see
    week_view's own docstring) -- kept as a redirect so any old bookmark/link
    to /calendar/timetable still lands somewhere real."""
    url = "/calendar/week"
    params = []
    if date_:
        params.append(f"date_={date_}")
    if label:
        params.append(f"label={label}")
    if params:
        url += "?" + "&".join(params)
    return RedirectResponse(url=url, status_code=303)


def _week_redirect(date_: str) -> RedirectResponse:
    url = "/calendar/week"
    if date_:
        url += f"?date_={date_}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/week/allocations")
def create_week_allocation(
    task_uid: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag a task from the "Unscheduled work" list onto the Week grid to
    create a work allocation -- same shape/validation as routers/week.py::
    create_allocation (any open task is a valid drop target here, no project
    re-check), just redirecting back to this page instead of /week. The
    block-level create/move/delete trio is deliberately duplicated from
    week.py with this page's own redirect because routers/week.py imports this
    router (calendar) and so this router cannot import week back -- the repo's
    established "duplicate the small thing, with a cross-reference comment"
    pattern for exactly this one-directional-import constraint."""
    task = db.get_task(conn, task_uid)
    if task is not None and task.get("status") not in ("done", "archived") and start_at and end_at and end_at > start_at:
        # A task with an undated session placeholder (added via the task
        # modal's Work sessions "+" button) gets THAT session placed onto
        # the dropped slot instead of creating yet another block; a task
        # with no sessions yet creates its first dated block, as before.
        undated = db.first_undated_work_allocation_for_task(conn, task_uid)
        if undated:
            db.set_work_allocation_times(conn, undated["uid"], start_at, end_at)
        else:
            db.create_work_allocation(conn, task_uid, start_at, end_at)
    return _week_redirect(date_)


@router.post("/week/allocations/{event_uid}/move")
def move_week_allocation(
    event_uid: str,
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    conn=Depends(get_db),
):
    """Drag-to-move / drag-to-resize a work-allocation block on Week -- only
    a real work-allocation event may be moved (re-checked via
    db.work_allocation_task_uid), same as routers/week.py::move_allocation."""
    task_uid = db.work_allocation_task_uid(conn, event_uid)
    if task_uid and start_at and end_at and end_at > start_at:
        existing = db.get_event(conn, event_uid)
        if existing is not None:
            row = dict(existing)
            row["start_at"] = start_at
            row["end_at"] = end_at
            row["updated_at"] = _now()
            db.upsert_event(conn, row)
    return _week_redirect(date_)


@router.post("/week/allocations/{event_uid}/delete")
def delete_week_allocation(event_uid: str, date_: str = Form(""), conn=Depends(get_db)):
    """Unschedule a block -- clears this ONE session back to undated
    (`db.unschedule_work_allocation`) instead of deleting it; the task's
    total session count never changes just from unscheduling. Same fixed
    semantics as routers/week.py::delete_allocation -- see that function's
    docstring for the two earlier same-day designs this replaced (collapse-
    to-one, then a hard delete, both wrong)."""
    if not db.unschedule_work_allocation(conn, event_uid):
        db.delete_work_allocation(conn, event_uid)
    return _week_redirect(date_)


@router.get("/day/{day}")
def day_view(
    day: str,
    request: Request,
    label: str | None = None,
    conn=Depends(get_db),
):
    """2026-08-08: Day's 24-hour grid now fills the whole viewport and
    scrolls internally, the same single-pane layout Week uses (direct
    feedback: "make day-agenda-split calendar-viewport scrollable like the
    calendar week view. Remove the agenda at the bottom of the calendar
    day view") -- the old Day+Agenda side-by-side split is gone along with
    _build_agenda_days (the separate rolling-30-day list that used to sit
    beside it). GET /calendar/agenda (agenda_view, below) still redirects
    here."""
    d = date.fromisoformat(day)
    events = db.list_events(conn, start=day, end=day + "T23:59:59")
    events = recurrence_expand.expand_events(events, d, d, db.list_holidays_by_calendar(conn), db.list_event_occurrence_overrides_by_master(conn))
    events = _apply_event_label_filter(events, label)
    events = _annotate_calendar_colors(conn, events)

    all_tasks = db.list_tasks(conn)
    tasks = [t for t in all_tasks if (t.get("due_at") or "").startswith(day)]
    tasks = _apply_task_label_filter(tasks, label)

    # All-day events repeat on every day they span (same as _month_grid) --
    # a multi-day all-day event that started yesterday must still fill
    # today's strip, so this runs over the full overlap set BEFORE the
    # start-day filter below (which is fine to keep for the hour grid:
    # timed events are positioned off their own start_at, so a timed event
    # that merely overlaps today without starting today has no grid slot).
    all_day = [
        e for e in events
        if e.get("all_day") and (rng := _event_date_range(e)) and rng[0] <= d <= rng[1]
    ]
    day_events = [e for e in events if e.get("start_at", "").startswith(day)]
    timed = grid_layout.layout_day(day_events)
    day_time_blocks = db.list_time_blocks(conn)
    time_block_overlays = _time_block_overlays_for_day(day_time_blocks, d)

    return templates.TemplateResponse(
        "calendar_day.html",
        {
            "request": request,
            "active_tab": "calendar",
            "calendar_view": "day",
            "today_iso": date.today().isoformat(),
            "day": day,
            "prev_day": (d - timedelta(days=1)).isoformat(),
            "next_day": (d + timedelta(days=1)).isoformat(),
            "all_day": all_day,
            "timed": timed,
            "tasks": tasks,
            "time_block_overlays": time_block_overlays,
            "hours": list(range(grid_layout.GRID_HOURS)),
            "px_per_hour": grid_layout.PX_PER_HOUR,
            "event_label_names": db.list_event_label_names(conn),
            "active_label": label or "",
            "schedule_next_lectures": _group_education_next_lectures(conn, label),
            "time_blocks_json": _time_blocks_client_payload(day_time_blocks),
        },
    )


@router.get("/agenda")
def agenda_view(label: str | None = None):
    """2026-08-08: Agenda is no longer its own page -- Day and Agenda were
    merged into one view, and then (direct feedback) Day became the sole
    single-pane grid and the merged Agenda list was removed entirely (see
    day_view above, calendar_day.html). This route stays registered as a
    redirect (matching the same pattern GET /export uses after Export &
    backup was inlined into Settings > Advanced) so an old bookmark/link
    to /calendar/agenda still lands somewhere real."""
    today_iso = date.today().isoformat()
    url = f"/calendar/day/{today_iso}"
    if label:
        url += f"?label={label}"
    return RedirectResponse(url=url, status_code=303)


@events_router.get("/events/new")
def new_event_form(
    request: Request,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    end_date: str | None = None,
    conn=Depends(get_db),
):
    # `end_date` (no start_time/end_time) is the month-view click-and-hold
    # drag-to-create path (static/calendar_month.js) -- a day-granularity
    # range with no time-of-day at all, prefilled as an all-day event
    # spanning midnight-to-midnight. The existing `start_time`/`end_time`
    # path (Week/Day view's drag-to-create, static/calendar.js) still
    # takes priority when present, since that one's a same-day, specific
    # time range.
    prefill_all_day = False
    if date and end_date and not start_time and not end_time:
        prefill_start = f"{date}T00:00"
        prefill_end = f"{end_date}T23:59"
        prefill_all_day = True
    else:
        prefill_start = f"{date}T{start_time}" if date and start_time else (f"{date}T09:00" if date else None)
        prefill_end = f"{date}T{end_time}" if date and end_time else None
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "active_tab": "calendar",
            "event": None,
            "prefill_start": prefill_start,
            "prefill_end": prefill_end,
            "prefill_all_day": prefill_all_day,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
        },
    )


@events_router.post("/events")
def create_event(
    title: str = Form(...),
    description: str = Form(""),
    start_at: str = Form(...),
    end_at: str = Form(""),
    all_day: str = Form(""),
    location: str = Form(""),
    meeting_url: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    reminders: str = Form(""),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at or None,
        "all_day": bool(all_day),
        "location": _clean_field(location),
        "meeting_url": _clean_field(meeting_url),
        "status": "active",
        "tags": _tags_list(tags),
        "recurrence": _clean_field(recurrence),
        "reminders": [int(m) for m in reminders.split(",") if m.strip().isdigit()],
        # 1.6 ("Generalized recurrence and the non-working-day policy") --
        # see _event_form_fields.html's own comment on these three fields.
        "holiday_calendar": _clean_field(holiday_calendar),
        "exclude_saturday": bool(exclude_saturday),
        "exclude_sunday": bool(exclude_sunday),
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_event(conn, row)
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.get("/events/{uid}")
def event_detail(uid: str, request: Request, occurrence_date: str | None = None, conn=Depends(get_db)):
    """2026-08-08 direct feedback ("add for events a way like for tasks to
    only view the event before editing it") -- events previously had no
    read-only view at all, every event link (Calendar's own Month/Week/
    Day/Agenda grids, every dashboard widget that lists events) went
    straight to /events/{uid}/edit. Mirrors task_detail.html's shape:
    #modal-target wrapper (same "modal is progressive enhancement over a
    real page" pattern), a compact meta grid, an Edit button leading to
    the real edit form, Delete at the bottom -- see event_detail.html.
    /events/{uid}/edit itself is unchanged, still reachable directly (a
    bookmark, or this page's own Edit button).

    1.6 ("Manual recurrence exceptions"): `occurrence_date` (the RECURRENCE-
    ID every expanded occurrence carries, see ical_rows.py's
    ical_to_event_row) identifies which specific occurrence the user
    clicked, when it's a recurring event -- calendar_month/week/day.html
    append it to every occurrence's own link. Its presence gates the "This
    occurrence" card (event_detail.html) offering Cancel/Move/Restore for
    just that one instance, never the whole series."""
    event = db.get_event(conn, uid)
    if event:
        _annotate_calendar_colors(conn, [event])
    occurrence_override = None
    if occurrence_date and event and event.get("recurrence"):
        occurrence_override = next(
            (o for o in db.list_event_occurrence_overrides(conn, uid) if o["occurrence_date"] == occurrence_date),
            None,
        )
    return templates.TemplateResponse(
        "event_detail.html",
        {
            "request": request,
            "active_tab": "calendar",
            "event": event,
            "occurrence_date": occurrence_date,
            "occurrence_override": occurrence_override,
            # Relations card (2026-08-09) -- see _related_context above.
            **_related_context(conn, event),
        },
    )


@events_router.get("/events/{uid}/edit")
def edit_event_form(uid: str, request: Request, conn=Depends(get_db)):
    event = db.get_event(conn, uid)
    tag_names = db.list_tag_names_in_use(conn)
    return templates.TemplateResponse(
        "event_form.html",
        {
            "request": request,
            "active_tab": "calendar",
            "event": event,
            "tag_names": tag_names,
            "tag_name_items": [{"uid": n, "name": n} for n in tag_names],
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
            # Relations card (2026-08-09) -- see _related_context above.
            **_related_context(conn, event),
        },
    )


@events_router.post("/events/{uid}")
def update_event(
    uid: str,
    title: str = Form(...),
    description: str = Form(""),
    start_at: str = Form(...),
    end_at: str = Form(""),
    all_day: str = Form(""),
    location: str = Form(""),
    meeting_url: str = Form(""),
    tags: str = Form(""),
    tags_labels: list[str] = Form([]),
    recurrence: str = Form(""),
    reminders: str = Form(""),
    holiday_calendar: str = Form(""),
    exclude_saturday: str = Form(""),
    exclude_sunday: str = Form(""),
    conn=Depends(get_db),
):
    tags = dashboard_router._combine_tags(tags, tags_labels)
    existing = db.get_event(conn, uid) or {}
    # 1.4 (§ Task & calendar semantics): "changing the title of a
    # work-allocation event changes the associated task rather than
    # creating an independent event with a conflicting name." A
    # work-allocation event's title is owned by its task -- write the new
    # title there (upsert_task's title-sync then writes it back onto this
    # event, and every other allocation of the same task) instead of onto
    # this row directly.
    work_task_uid = db.work_allocation_task_uid(conn, uid)
    row = dict(existing)
    row.update(
        {
            "uid": uid,
            "title": existing.get("title", title) if work_task_uid else title,
            "description": description,
            "start_at": start_at,
            "end_at": end_at or None,
            "all_day": bool(all_day),
            "location": _clean_field(location),
            "meeting_url": _clean_field(meeting_url),
            "tags": _tags_list(tags),
            "recurrence": _clean_field(recurrence),
            "reminders": [int(m) for m in reminders.split(",") if m.strip().isdigit()],
            "holiday_calendar": _clean_field(holiday_calendar),
            "exclude_saturday": bool(exclude_saturday),
            "exclude_sunday": bool(exclude_sunday),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    db.upsert_event(conn, row)
    if work_task_uid:
        task = db.get_task(conn, work_task_uid)
        if task and task.get("title") != title:
            task_row = dict(task)
            task_row["title"] = title
            task_row["updated_at"] = datetime.now(timezone.utc).isoformat()
            db.upsert_task(conn, task_row)
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.post("/events/{uid}/delete")
def delete_event(uid: str, conn=Depends(get_db)):
    db.delete_event(conn, uid)
    return RedirectResponse(url="/calendar", status_code=303)


# --------------------------------------------------------------------- #
# Manual recurrence exceptions (1.6, "Manual recurrence exceptions") -- a
# specific occurrence of a recurring event can be cancelled or moved
# without touching the master's own recurrence rule (db.py's
# event_occurrence_overrides CREATE TABLE comment has the full model).
# Reached from event_detail.html's "This occurrence" card, itself only
# shown when the page was opened with ?occurrence_date=... (calendar_
# month/week/day.html append it to every occurrence's own link).
# --------------------------------------------------------------------- #


@events_router.post("/events/{uid}/occurrences/cancel")
def cancel_occurrence(uid: str, occurrence_date: str = Form(...), conn=Depends(get_db)):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_event_occurrence_override(
        conn,
        {"master_uid": uid, "occurrence_date": occurrence_date, "cancelled": True, "created_at": now, "updated_at": now},
    )
    return RedirectResponse(url="/calendar", status_code=303)


@events_router.post("/events/{uid}/occurrences/move")
def move_occurrence(
    uid: str,
    occurrence_date: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(""),
    title: str = Form(""),
    location: str = Form(""),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_event_occurrence_override(
        conn,
        {
            "master_uid": uid, "occurrence_date": occurrence_date, "cancelled": False,
            "start_at": start_at, "end_at": end_at or None,
            "title": _clean_field(title), "location": _clean_field(location),
            "created_at": now, "updated_at": now,
        },
    )
    return RedirectResponse(url=f"/events/{uid}?occurrence_date={start_at}", status_code=303)


@events_router.post("/events/{uid}/occurrences/restore")
def restore_occurrence(uid: str, occurrence_date: str = Form(...), conn=Depends(get_db)):
    """Undoes a cancel or a move -- the occurrence goes back to whatever
    the recurrence rule alone generates."""
    db.delete_event_occurrence_override(conn, uid, occurrence_date)
    return RedirectResponse(url=f"/events/{uid}?occurrence_date={occurrence_date}", status_code=303)


# --------------------------------------------------------------------- #
# Relations -- 2026-08-09, event<->task associative links ("a relation can
# link an event with existing/new tasks that both have at least one label
# in common"; see the event_task_relations comment in db.py). The event
# side of the feature: an event's Relations card links it to tasks -- either
# an existing task (the picker only offers ones already sharing a label,
# and _shares_label re-checks defensively) or a brand-new task created
# inline that inherits this event's labels, which guarantees the rule. Both
# routes redirect back to the event's own detail page so the card's
# data-modal-keep-open forms re-render in place (modal.js).
# --------------------------------------------------------------------- #


def _create_related_task(conn, event: dict, title: str) -> str | None:
    """Create a new task related to `event` from the Relations card's
    "＋ New task…" path. Inherits the event's labels (guaranteeing the
    shared-label rule), starts today (the same default create_task applies
    when a task form leaves start_at blank), status active -- the user
    edits due date/importance/urgency/labels later. Returns None (no task
    created) when the event has no labels at all, since no shared-label
    link could ever hold."""
    event_tags = event.get("tags") or []
    if not event_tags:
        return None
    title = (title or "").strip()
    if not title:
        return None
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "uid": str(uuid.uuid4()),
        "title": title,
        "description": "",
        "start_at": date.today().isoformat(),
        "due_at": None,
        "importance": None,
        "urgency": None,
        "status": "active",
        "progress": 0.0,
        "recurrence": None,
        "tags": event_tags,
        "target_per_day": 1.0,
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_task(conn, task)
    return task["uid"]


@events_router.post("/events/{uid}/relations")
def add_event_relation(
    uid: str,
    target_uid: str = Form(""),
    new_title: str = Form(""),
    conn=Depends(get_db),
):
    event = db.get_event(conn, uid)
    if event is None:
        return RedirectResponse(url="/calendar", status_code=303)
    task_uid = None
    if target_uid == "__new__":
        task_uid = _create_related_task(conn, event, new_title)
    elif target_uid:
        task = db.get_task(conn, target_uid)
        if task and _shares_label(event.get("tags") or [], task.get("tags") or []):
            task_uid = task["uid"]
    if task_uid:
        db.add_event_task_relation(conn, uid, task_uid)
    return RedirectResponse(url=f"/events/{uid}", status_code=303)


@events_router.post("/events/{uid}/relations/remove")
def remove_event_relation(uid: str, task_uid: str = Form(...), conn=Depends(get_db)):
    """Unlink a task from an event's Relations card. Graph link only -- the
    task itself is left entirely alone (relations are associative, not
    ownership; no cascade, matching delete_event/delete_task's cleanup)."""
    db.remove_event_task_relation(conn, uid, task_uid)
    return RedirectResponse(url=f"/events/{uid}", status_code=303)


@events_router.post("/events/{uid}/reschedule")
async def reschedule_event(uid: str, request: Request, conn=Depends(get_db)):
    """JSON endpoint for the Week/Day grid's drag-to-move / drag-to-resize
    (see static/calendar.js) -- only touches start_at/end_at, leaves every
    other field alone. A plain form POST to /events/{uid} would also work
    but means round-tripping every field through JS for no reason; this is
    the minimal surface the drag interaction actually needs."""
    payload = await request.json()
    existing = db.get_event(conn, uid)
    if existing is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    row = dict(existing)
    row["start_at"] = payload["start_at"]
    row["end_at"] = payload.get("end_at")
    row["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.upsert_event(conn, row)
    return JSONResponse({"ok": True, "start_at": row.get("start_at"), "end_at": row.get("end_at")})
