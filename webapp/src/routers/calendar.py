from __future__ import annotations

import calendar as py_calendar
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, grid_layout, habit_heatmap, recurrence_expand
from ..deps import _four_week_position, _week_start, get_db, respond, templates, wants_json
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
                "is_past": day < today,
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


def _month_view_context(conn, request: Request, year: int | None, month: int | None, label: str | None) -> dict:
    """Shared computation for the Month view (calendar_month.html) and its
    async-CRUD region fragment (_calendar_month_grid.html) -- one source of
    truth so a region refresh can never drift from a fresh full render."""
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

    return {
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
    }


@router.get("")
def calendar_root_redirect(label: str | None = None):
    """The "Calendar" tabbar destination is the 4-Week view now, not Month
    (2026-08-28 follow-up to "Calendar split into two pages" -- direct
    feedback: "in the month view it should be the 4 week view, not actually
    the month view"). Registered at the bare `/calendar` root (same URL
    base.html's "Calendar" tab links to and every event-mutation redirect
    already targets, e.g. create_event's `respond(x_requested_with,
    "/calendar", ...)`), so this is a plain retire-to-redirect, same
    precedent as week_redirect/timetable_view_redirect below -- any old
    `/calendar?year=&month=` bookmark still lands somewhere real, just on
    4-Week instead of Month.

    `month_view` itself (and everything it renders -- calendar_month.html,
    _calendar_month_grid.html, _month_view_context/_month_grid) is
    deliberately NOT deleted, just un-routed: it's still exercised directly
    by test_calendar_month_bars.py and several other test files (this app's
    router-function-call convention), and `_month_day_cells`/
    `_bucket_month_items` underneath it are shared with the 4-Week grid, so
    there's no dead-weight cost to keeping it importable."""
    url = "/calendar/fourweek"
    if label:
        url += f"?label={label}"
    return RedirectResponse(url=url, status_code=302)


def month_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    label: str | None = None,
    conn=Depends(get_db),
):
    """No longer routed (see calendar_root_redirect above) -- kept as a
    plain callable for its own tests and as the 'month' region's renderer
    below."""
    return templates.TemplateResponse("calendar_month.html", _month_view_context(conn, request, year, month, label))


@router.get("/regions")
def calendar_regions(
    request: Request,
    region: str,
    year: int | None = None,
    month: int | None = None,
    date_: str | None = None,
    label: str | None = None,
    conn=Depends(get_db),
):
    """async-CRUD region fragments (features/async-crud.md): GET endpoints
    rendering one named region so a mutation's change event can re-render
    just that slice of the calendar instead of a full reload."""
    if region == "month":
        return templates.TemplateResponse(
            "_calendar_month_grid.html", _month_view_context(conn, request, year, month, label)
        )
    if region == "week":
        return templates.TemplateResponse(
            "_calendar_week_grid.html", _week_view_context(conn, request, date_, label)
        )
    return JSONResponse({"error": f"unknown calendar region: {region}"}, status_code=400)


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
            # "calendar" (not "calendar_fourweek"): 4-Week IS what the
            # "Calendar" tabbar destination opens now (see
            # calendar_root_redirect's docstring above).
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
    return templates.TemplateResponse(
        "calendar_week.html", _week_view_context(conn, request, date_, label)
    )


def _week_view_context(conn, request, date_, label):
    """Everything the Week view needs, in one dict -- shared by week_view
    (full page) and the async `#week-grid` region (features/async-crud.md),
    which re-renders just the `.project-calendar-layout` grid after a
    work-allocation create/move/delete or an event change on the week page."""
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
                "is_past": d < date.today(),
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

    # 2026-08-29 ("habit work sessions" slice, direct feedback): a
    # habit-tracked task is deliberately excluded from `db.list_tasks`'
    # default query (it's meant to live only on Tasks > Habits) so
    # `open_tasks` above never contains one -- fetched separately here so
    # this week's grid can still offer "schedule this habit's work" the
    # same way it does for any other task. Follows a different "am I
    # still unscheduled" rule than the loop above: see
    # db.habit_work_sessions_status's own docstring for why "every
    # session has a date" isn't the right test for a recurring habit.
    for t in db.list_habit_tasks(conn):
        if t.get("status") in ("done", "archived") or not t.get("recurrence"):
            continue
        if habit_heatmap.recurrence_frequency(t.get("recurrence")) == "monthly":
            period_start = week_start_date.replace(day=1).isoformat()
            next_month = (week_start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            period_end = (next_month - timedelta(days=1)).isoformat()
        else:
            period_start, period_end = week_start_date.isoformat(), week_end_date.isoformat()
        info = db.habit_work_sessions_status(conn, t["uid"], t.get("recurrence"), period_start, period_end)
        if info["needed"] <= 0:
            continue
        project = db.project_label_config_for(conn, "task", t["uid"])
        unscheduled_tasks.append(
            {
                "task": t,
                "project": project,
                "sessions": {"undated_count": info["undated_count"]},
                "is_habit": True,
                "habit_sessions": info,
            }
        )
    unscheduled_tasks.sort(key=lambda item: item["task"].get("due_at") or "9999-99-99")

    return {
        "request": request,
        "active_tab": "calendar_week",
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
        "time_blocks_json": _time_blocks_client_payload(time_blocks),
    }


@events_router.get("/week")
def week_redirect(date_: str | None = None):
    """The former standalone /week page ("Week -- planning", 1.7 slice 2,
    routers/week.py) is retired (1.9 side work) -- its cross-project
    scheduling surface (Unscheduled work sidebar, drag-drop, the grid
    itself) is now identically present at /calendar/week (see this file's
    own week_view docstring: the "Calendar Week + Timetable merged" side
    work already folded Timetable's planning capability into the ordinary
    Week grid, confirmed by reading both routers/templates directly before
    this retirement, not assumed). Registered on `events_router` (this
    module's unprefixed router) rather than `router` (prefix="/calendar")
    since the redirect's own path has to be the bare "/week", not
    "/calendar/week" -- same "any bookmark still lands somewhere real"
    precedent `timetable_view_redirect` right below already set."""
    url = "/calendar/week"
    if date_:
        url += f"?date_={date_}"
    return RedirectResponse(url=url, status_code=302)


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


def _week_respond(x_requested_with: str | None, date_: str):
    """Dual-mode return for the work-allocation create/move/delete trio:
    plain 303 redirect to the Week view without the fetch header, JSON when
    the async drag path (project_calendar.js -> ccApi.post) is driving."""
    url = "/calendar/week"
    if date_:
        url += f"?date_={date_}"
    return respond(x_requested_with, url, ok=True)


@router.post("/week/allocations")
def create_week_allocation(
    task_uid: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    x_requested_with: str | None = Header(default=None),
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
    return _week_respond(x_requested_with, date_)


@router.post("/week/allocations/{event_uid}/move")
def move_week_allocation(
    event_uid: str,
    start_at: str = Form(...),
    end_at: str = Form(...),
    date_: str = Form(""),
    x_requested_with: str | None = Header(default=None),
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
    return _week_respond(x_requested_with, date_)


@router.post("/week/allocations/{event_uid}/delete")
def delete_week_allocation(
    event_uid: str,
    date_: str = Form(""),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Unschedule a block -- clears this ONE session back to undated
    (`db.unschedule_work_allocation`) instead of deleting it; the task's
    total session count never changes just from unscheduling. Same fixed
    semantics as routers/week.py::delete_allocation -- see that function's
    docstring for the two earlier same-day designs this replaced (collapse-
    to-one, then a hard delete, both wrong)."""
    if not db.unschedule_work_allocation(conn, event_uid):
        db.delete_work_allocation(conn, event_uid)
    return _week_respond(x_requested_with, date_)


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
    title: str = "",
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
            # Command palette actions (open.md) -- see new_task_form's
            # identical prefill_title comment; blank for every other caller.
            "prefill_title": title,
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
    x_requested_with: str | None = Header(default=None),
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
    return respond(x_requested_with, "/calendar", status_code=201, ok=True, uid=row["uid"])


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
    x_requested_with: str | None = Header(default=None),
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
    return respond(x_requested_with, "/calendar", ok=True)


@events_router.post("/events/{uid}/delete")
def delete_event(uid: str, x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    db.delete_event(conn, uid)
    return respond(x_requested_with, "/calendar", ok=True)


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
def cancel_occurrence(
    uid: str,
    occurrence_date: str = Form(...),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_event_occurrence_override(
        conn,
        {"master_uid": uid, "occurrence_date": occurrence_date, "cancelled": True, "created_at": now, "updated_at": now},
    )
    return respond(x_requested_with, "/calendar", ok=True)


@events_router.post("/events/{uid}/occurrences/move")
def move_occurrence(
    uid: str,
    occurrence_date: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(""),
    title: str = Form(""),
    location: str = Form(""),
    x_requested_with: str | None = Header(default=None),
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
    return respond(x_requested_with, f"/events/{uid}?occurrence_date={start_at}", ok=True)


@events_router.post("/events/{uid}/occurrences/restore")
def restore_occurrence(uid: str, occurrence_date: str = Form(...), x_requested_with: str | None = Header(default=None), conn=Depends(get_db)):
    """Undoes a cancel or a move -- the occurrence goes back to whatever
    the recurrence rule alone generates."""
    db.delete_event_occurrence_override(conn, uid, occurrence_date)
    return respond(x_requested_with, f"/events/{uid}?occurrence_date={occurrence_date}", ok=True)


# --------------------------------------------------------------------- #
# Relations -- fully removed 2026-08-29 (STATE.md backlog item 4, direct
# request). This used to be the event side of an event<->task associative
# links feature: POST /events/{uid}/relations and /relations/remove,
# backed by the Relations card in event_form.html/event_detail.html
# (_event_relations.html, now unreferenced). See routers/tasks.py's own
# "Relations -- fully removed" comment for the task side and the same
# "db.py's CRUD stays, other things still read it" note.
# --------------------------------------------------------------------- #


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
