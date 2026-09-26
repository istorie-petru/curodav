"""The one frontend habit shape (2026-09-24, plans/ui-cleanup-2026-09.md
item 14, slice 1).

A habit is a habit-labeled task in the backend (task_habit_settings'
label + `tasks.target_per_day`/`recurrence` + `task_completions.value`) --
the standalone Habit entity (`habits`/`habit_entries`) is gone as of this
same slice (Peter: no real entities in use; its tables are left physically
in place, never force-dropped, same convention as every other table
removal in db.py). Every habit surface renders from `habit_items` below
instead of reading task rows directly, so a habit never has to look like a
task (status, due date, Kanban column) anywhere it's shown -- the Habits
page (`/habits`, H2) and the Dashboard's Habit Check-in widget. (The
Tasks table's own Habits group was retired in H2.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import db, habit_heatmap, habit_schedule

# A done/archived habit task stops being tracked -- same pair
# routers/tasks.py's DONE_STATUSES names.
_INACTIVE_STATUSES = ("done", "archived")


def excluded_dates_for_row(conn, row: dict, entries_by_date: dict, today: date) -> set[str]:
    """Resolve a recurring task's holiday_calendar/exclude_saturday/
    exclude_sunday policy into the concrete dates streaks should skip.
    Cheap no-op (no DB read) when the row has no policy set at all."""
    if not (row.get("holiday_calendar") or row.get("exclude_saturday") or row.get("exclude_sunday")):
        return set()
    logged = [date.fromisoformat(d) for d in entries_by_date if d]
    start = min(logged) if logged else today
    start = max(start, today - timedelta(days=730))
    holiday_calendars = db.list_holidays_by_calendar(conn)
    return habit_heatmap.excluded_dates_in_range(row, holiday_calendars, start, today)


_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# 2026-09-26 (Peter): per-habit icon + colour. Icons a habit can pick
# (all in _icons_sprite.html; "no icon" draws the default check glyph, so
# check-circle itself isn't listed); colours are the label palette
# (routers/labels.py COLORS, duplicated here to avoid a router import).
HABIT_ICONS = (
    "activity", "heart", "droplet", "coffee", "book-open", "notebook", "pencil",
    "graduation-cap", "code", "music", "headphones", "camera", "moon", "sun", "sunrise",
    "wind", "feather", "smile", "users", "phone", "mail", "dollar-sign", "shopping-cart",
    "home", "map-pin", "navigation", "clock", "target", "zap", "trophy", "medal",
    "award", "shield", "x-circle",
)
HABIT_COLORS = (
    "red", "orange", "yellow", "lime", "green", "mint", "teal", "cyan",
    "blue", "indigo", "purple", "magenta", "pink", "brown", "gray", "slate",
)


def habit_look(task: dict | None) -> dict:
    """{"icon", "color"} for a habit -- its own picks, or None (templates
    fall back to the kind's default glyph and the accent colour)."""
    icon = (task or {}).get("habit_icon")
    color = (task or {}).get("habit_color")
    return {"icon": icon if icon in HABIT_ICONS else None, "color": color if color in HABIT_COLORS else None}


_WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _created_date(task: dict) -> date | None:
    try:
        return date.fromisoformat((task.get("created_at") or "")[:10])
    except ValueError:
        return None


def pause_info(pauses: list[dict], uid: str, today: date) -> dict:
    """Habits H6: which days (up to today) this habit is paused, whether
    it's paused today and until when, and the pauses that apply to it
    (its own plus all-habit ones) that haven't ended yet."""
    dates: set[str] = set()
    until = None
    upcoming = []
    for p in pauses:
        if p.get("task_uid") not in (None, uid):
            continue
        try:
            start, end = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
        except (TypeError, ValueError):
            continue
        d = start
        while d <= min(end, today):
            dates.add(d.isoformat())
            d += timedelta(days=1)
        if start <= today <= end:
            until = max(until, end) if until else end
        if end >= today:
            upcoming.append({**p, "is_global": p.get("task_uid") is None})
    return {"dates": dates, "paused_today": until is not None, "paused_until": until.isoformat() if until else None,
            "upcoming": upcoming}


def quantity_target(task: dict) -> float | None:
    """2026-09-25 (UI audit H-01/H-02/C-5): the daily target of an *amount*
    habit ("8 glasses a day": target_per_day > 1, not an avoid habit), or
    None for a plain check-off / avoid habit. The one place that decides
    whether "done" means value >= target or just value > 0."""
    target = task.get("target_per_day") or 1
    if target > 1 and task.get("habit_kind") != "avoid":
        return target
    return None


def day_state(value: float | None, target: float | None) -> str:
    """"done" / "partial" / "" for one logged day. An amount habit's day is
    only done at its target; 1..target-1 is "partial" -- shown lighter in
    the strip, month calendar and heatmap alike, never counted as kept
    (habit_schedule.habit_stats' `target_per_day`)."""
    value = value or 0
    if value <= 0:
        return ""
    if target and value < target:
        return "partial"
    return "done"


def stats_for_task(
    task: dict, entries_by_date: dict, excluded: set[str], today: date | None = None, paused: set[str] | None = None
) -> dict:
    """habit_schedule.habit_stats for one recurring task row (habits H1)."""
    return habit_schedule.habit_stats(
        entries_by_date,
        task.get("recurrence"),
        per_period=task.get("habits_per_period"),
        today=today,
        excluded_dates=excluded,
        created=_created_date(task),
        kind=task.get("habit_kind"),
        paused_dates=paused,
        target_per_day=quantity_target(task),
    )


def cadence_label(task: dict) -> str:
    """"Daily", "Every 2 days", "Mon, Wed, Fri", "Weekly", "3x a week",
    "Monthly" -- the schedule in words, never the raw RRULE. An avoid
    habit (H5) has no schedule: "Avoid"."""
    if task.get("habit_kind") == "avoid":
        return "Avoid"
    sched = habit_schedule.parse_schedule(task.get("recurrence"), task.get("habits_per_period"))
    if sched.kind == "weekdays":
        if len(sched.weekdays) == 7:
            return "Daily"
        return ", ".join(_DAY_NAMES[d] for d in sorted(sched.weekdays))
    if sched.kind == "every_n_days":
        return "Daily" if sched.interval == 1 else f"Every {sched.interval} days"
    unit_word = {"week": "week", "month": "month", "year": "year"}[sched.unit]
    if sched.interval > 1:
        base = f"every {sched.interval} {unit_word}s"
    else:
        base = f"a {unit_word}"
    if sched.per_period > 1:
        return f"{sched.per_period}x {base}"
    return habit_heatmap.recurrence_label(task.get("recurrence")) if sched.interval == 1 else f"Once {base}"


_DAY_FULL = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def days_label(codes: list[str], week_start: str = "monday") -> str:
    """The habit form's Days dropdown summary (static/habit_day.js mirrors
    it): "Every day" / "Weekdays" / "Weekends" / "Mon, Wed, Fri" in week
    order / "Pick days"."""
    picked = set(codes)
    if not picked:
        return "Pick days"
    if len(picked) == 7:
        return "Every day"
    if picked == {"MO", "TU", "WE", "TH", "FR"}:
        return "Weekdays"
    if picked == {"SA", "SU"}:
        return "Weekends"
    order = _week_order(week_start)
    return ", ".join(_DAY_NAMES[i] for i in order if _WEEKDAY_CODES[i] in picked)


def _week_order(week_start: str) -> list[int]:
    return [6, 0, 1, 2, 3, 4, 5] if week_start == "sunday" else list(range(7))


def repeat_choice(task: dict | None, week_start: str = "monday") -> dict:
    """The habit form's "How often" choice for an existing habit
    (2026-09-26, Peter: no raw "FREQ=WEEKLY;BYDAY=..." in the edit modal).
    mode is "daily" / "days" (fixed weekdays) / "week" / "month" (N times
    per period) or "keep" for anything those four can't express (every 2
    days, every 2 weeks, yearly, an end date) -- the form then offers the
    current schedule in words and leaves the stored rule untouched."""
    rrule = (task or {}).get("recurrence") or "FREQ=DAILY"
    per = (task or {}).get("habits_per_period")
    out = {
        "mode": "keep", "days": [], "times": int(per or 1),
        "label": cadence_label({**(task or {}), "habit_kind": None}),
        # 2026-09-26: the Days dropdown, in the configured week order.
        "day_options": [
            {"code": _WEEKDAY_CODES[i], "name": _DAY_FULL[i], "short": _DAY_NAMES[i]} for i in _week_order(week_start)
        ],
        "days_label": "Pick days",
    }
    if any(p.upper().startswith(("UNTIL=", "COUNT=")) for p in rrule.split(";")):
        return out
    sched = habit_schedule.parse_schedule(rrule, per)
    if sched.kind == "weekdays":
        out.update(mode="days", days=[_WEEKDAY_CODES[d] for d in sorted(sched.weekdays)])
        out["days_label"] = days_label(out["days"], week_start)
    elif sched.kind == "every_n_days" and sched.interval == 1:
        out["mode"] = "daily"
    elif sched.kind == "period" and sched.interval == 1 and sched.unit in ("week", "month"):
        out["mode"] = sched.unit
    return out


def week_strip(
    uid: str,
    entries_by_date: dict,
    today: date,
    excluded: set[str] | None = None,
    target: float | None = None,
    schedule: habit_schedule.Schedule | None = None,
    week_start: str = "monday",
) -> list[dict]:
    """The calendar week containing `today`, starting on the configured
    first day of the week (2026-09-26, Peter: the strip didn't respect
    it -- it used to be the rolling last seven days). Days after today
    are `is_future`: shown, never clickable."""
    excluded = excluded or set()
    days = []
    first = today - timedelta(days=(today.weekday() + (1 if week_start == "sunday" else 0)) % 7)
    for offset in range(7):
        d = first + timedelta(days=offset)
        iso = d.isoformat()
        value = entries_by_date.get(iso, 0) or 0
        state = day_state(value, target)
        days.append(
            {
                "iso": iso,
                # 2026-09-25 (UI audit H-16): two letters ("Tu"/"Th",
                # "Sa"/"Su") -- a 7-day strip of single initials always
                # repeated T and S.
                "initial": _DAY_NAMES[d.weekday()][:2],
                "day_name": _DAY_NAMES[d.weekday()],
                "value": value,
                "done": state == "done",
                # UI audit H-02: an amount habit's day below target.
                "partial": state == "partial",
                "is_today": d == today,
                "is_future": d > today,
                "excluded": iso in excluded,
                # UI audit H-16 / flesh-out 9: a day this habit isn't
                # scheduled on (Tue for a Mon/Wed/Fri habit) -- styled as
                # an off day, not as a miss.
                "off_day": bool(schedule) and not habit_schedule.is_due_on(schedule, d),
                "toggle_url": f"/tasks/{uid}/completion/{iso}/toggle",
            }
        )
    return days


def _shift_month(first: date, delta: int) -> date:
    idx = first.year * 12 + first.month - 1 + delta
    return date(idx // 12, idx % 12 + 1, 1)


def recent_notes(completions: list[dict], limit: int = 10) -> list[dict]:
    """Habits H3: newest-first logged days that carry a note."""
    rows = [c for c in completions if (c.get("note") or "").strip()]
    rows.sort(key=lambda c: c["due_date"], reverse=True)
    return [{"iso": c["due_date"], "note": c["note"].strip(), "value": c.get("value") or 0} for c in rows[:limit]]


def habit_item(conn, task: dict, today: date, pauses: list[dict] | None = None, week_start: str = "monday") -> dict:
    today_iso = today.isoformat()
    entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, task["uid"])}
    target = task.get("target_per_day") or 1
    qty_target = quantity_target(task)
    excluded = excluded_dates_for_row(conn, task, entries_by_date, today)
    pinfo = pause_info(db.list_habit_pauses(conn) if pauses is None else pauses, task["uid"], today)
    stats = stats_for_task(task, entries_by_date, excluded, today, pinfo["dates"])
    today_value = entries_by_date.get(today_iso, 0) or 0
    today_state = day_state(today_value, qty_target)
    return {
        "uid": task["uid"],
        "title": task["title"],
        "tags": task.get("tags") or [],
        # Per-habit reminder time (2026-09-25): "HH:MM" or None.
        "reminder_time": task.get("reminder_time") or None,
        "is_quantity": qty_target is not None,
        "target": target,
        "today": today_iso,
        "today_value": today_value,
        "next_value": today_value + 1,
        # 2026-09-25 (UI audit H-01): an amount habit is done today only at
        # its target; below it `partial_today` (display only).
        "done_today": today_state == "done",
        "partial_today": today_state == "partial",
        # Amount still to go today ("7 left"), 0 once the target is met.
        "remaining_today": max(0, (qty_target or 0) - today_value),
        # Schedule-aware (habits H1): counted in `streak_unit`s -- due
        # days for a daily/weekday habit, weeks/months for a period one.
        "current_streak": stats["current"],
        "longest_streak": stats["longest"],
        "streak_unit": stats["unit"],
        "completion_rate": stats["rate"],
        "strength": stats.get("strength"),
        "due_today": stats["due_today"],
        "period_done": stats["period_done"],
        "period_target": stats["period_target"],
        "is_period": stats["kind"] == "period",
        # Habits H5: an avoid habit logs relapses; its streak is clean days.
        "is_avoid": stats["kind"] == "avoid",
        "relapsed_today": stats.get("relapsed_today", False),
        "unit": (task.get("habit_unit") or "").strip(),
        # Habits H6: vacation / pause.
        # 2026-09-25 (UI audit H-12): a pause never applies to an avoid
        # habit (_avoid_stats ignores it -- clean days are clean), so it
        # isn't shown as paused either.
        "paused_today": pinfo["paused_today"] and task.get("habit_kind") != "avoid",
        "paused_until": pinfo["paused_until"] if task.get("habit_kind") != "avoid" else None,
        # The habit's cadence in words, never the raw RRULE.
        "recurrence_label": cadence_label(task),
        # Habits H2: the last seven days, oldest first, for the Habits
        # page's (and later the widget's) tap-a-day strip.
        "week": week_strip(
            task["uid"],
            entries_by_date,
            today,
            excluded | pinfo["dates"],
            target=qty_target,
            week_start=week_start,
            schedule=None
            if task.get("habit_kind") == "avoid"
            else habit_schedule.parse_schedule(task.get("recurrence"), task.get("habits_per_period"), _created_date(task)),
        ),
        **habit_look(task),
        "detail_url": f"/tasks/{task['uid']}",
        "edit_url": f"/tasks/{task['uid']}/edit",
        "toggle_url": f"/tasks/{task['uid']}/completion/{today_iso}/toggle",
        "plus_url": f"/tasks/{task['uid']}/completions",
        "delete_url": f"/tasks/{task['uid']}/delete",
    }


WEEK_START_KEY = "calendar_week_start"  # deps.WEEK_START_KEY (no import cycle)


def habit_items(conn, today: date | None = None) -> list[dict]:
    """Every active habit, alphabetical (list_habit_tasks' own order)."""
    today = today or date.today()
    pauses = db.list_habit_pauses(conn)
    week_start = db.get_app_meta(conn, WEEK_START_KEY) or "monday"
    return [
        habit_item(conn, t, today, pauses, week_start=week_start)
        for t in db.list_habit_tasks(conn)
        if t["status"] not in _INACTIVE_STATUSES
    ]


def habits_for_day(conn, d: date, today: date | None = None) -> list[dict]:
    """Habits H7: the habits scheduled on day `d` (calendar day view) --
    build habits only (an avoid habit has nothing to do on a day), minus
    paused and non-working days. Each carries whether `d` was logged and
    a toggle URL unless `d` is in the future.

    2026-09-25 (UI audit C-5): an amount habit carries `is_quantity`,
    `target`, `value`, `next_value`, `date` and `plus_url` so the Day view
    renders n/target with a +1 (like the Agenda widget) instead of a
    toggle that marked 8/day "done" at 1; `done` only at target,
    `partial` below it."""
    today = today or date.today()
    iso = d.isoformat()
    pauses = db.list_habit_pauses(conn)
    out = []
    for t in db.list_habit_tasks(conn):
        if t["status"] in _INACTIVE_STATUSES or t.get("habit_kind") == "avoid":
            continue
        sched = habit_schedule.parse_schedule(t.get("recurrence"), t.get("habits_per_period"), _created_date(t))
        if not habit_schedule.is_due_on(sched, d):
            continue
        if iso in pause_info(pauses, t["uid"], max(d, today))["dates"]:
            continue
        entries = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, t["uid"])}
        if iso in excluded_dates_for_row(conn, t, {iso: 1}, max(d, today)):
            continue
        value = entries.get(iso, 0) or 0
        qty_target = quantity_target(t)
        state = day_state(value, qty_target)
        out.append(
            {
                "uid": t["uid"],
                "title": t["title"],
                "done": state == "done",
                "partial": state == "partial",
                "value": value,
                "is_quantity": qty_target is not None,
                "target": qty_target or 1,
                "next_value": value + 1,
                "date": iso,
                "plus_url": f"/tasks/{t['uid']}/completions",
                "is_future": d > today,
                "toggle_url": f"/tasks/{t['uid']}/completion/{iso}/toggle",
                "detail_url": f"/tasks/{t['uid']}",
            }
        )
    return out


def period_grid(
    entries_by_date: dict, schedule: habit_schedule.Schedule, today: date, week_start: str = "monday",
    target: float | None = None,
) -> dict:
    """2026-09-26 (Peter): a "3x a week" / "once a month" habit's history
    as periods, not days -- the last 52 weeks (weeks starting on the
    configured first day) or the last 12 months. Each cell: logged days
    in that period against the per-period target; `done` at the target,
    `partial` below it. A day counts once it's done (at the daily target
    for an amount habit)."""
    per = max(1, schedule.per_period)
    done_days = {iso for iso, v in entries_by_date.items() if day_state(v or 0, target) == "done"}
    cells = []
    if schedule.unit == "week":
        this_week = today - timedelta(days=(today.weekday() + (1 if week_start == "sunday" else 0)) % 7)
        for i in range(51, -1, -1):
            start = this_week - timedelta(weeks=i)
            n = sum(1 for k in range(7) if (start + timedelta(days=k)).isoformat() in done_days)
            cells.append({
                "label": start.strftime("%b") if start.day <= 7 else "",
                "title": f"Week of {start.day} {start.strftime('%b')}: {n}/{per}",
                "count": n, "target": per, "done": n >= per, "partial": 0 < n < per, "is_current": i == 0,
            })
        return {"unit": "week", "cells": cells}
    first = today.replace(day=1)
    for i in range(11, -1, -1):
        m = _shift_month(first, -i)
        key = m.strftime("%Y-%m")
        n = sum(1 for iso in done_days if iso.startswith(key))
        cells.append({
            "label": m.strftime("%b"), "title": f"{m.strftime('%B %Y')}: {n}/{per}",
            "count": n, "target": per, "done": n >= per, "partial": 0 < n < per, "is_current": i == 0,
        })
    return {"unit": "month", "cells": cells}


def history(conn, task: dict, today: date | None = None, week_start: str = "monday") -> dict:
    """What a habit's history view shows (the Habits page's expandable
    row, the view modal): the year heatmap for a daily / fixed-days /
    avoid habit, or the week / month grid for a period habit, plus
    insights (2026-09-26: moved here from the view modal)."""
    today = today or date.today()
    rows = db.list_task_completions(conn, task["uid"])
    entries = {r["due_date"]: r.get("value") or 0 for r in rows}
    out = {"heatmap": None, "periods": None, "insights": insights(rows, today)}
    sched = habit_schedule.parse_schedule(task.get("recurrence"), task.get("habits_per_period"), _created_date(task))
    if task.get("habit_kind") != "avoid" and sched.kind == "period":
        out["periods"] = period_grid(entries, sched, today, week_start, target=quantity_target(task))
    else:
        out["heatmap"] = habit_heatmap.heatmap_weeks(
            entries, task.get("target_per_day") or 1, habit_heatmap.DETAIL_WEEKS, today, week_start=week_start
        )
    return out


INSIGHTS_MIN_DAYS = 14


def insights(completions: list[dict], today: date | None = None, months: int = 12) -> dict:
    """Habits H8: logged days per month for the last `months` months
    (oldest first, with a 0-1 bar height), and the hour of day check-ins
    usually happen. The hour histogram only counts check-ins made on the
    day they were for (a backfilled day's timestamp says nothing about
    when the habit was done) and reads `completed_at` in the server's
    local time zone -- there's no per-user zone setting. Hidden (None)
    until at least 5 such check-ins exist."""
    today = today or date.today()
    first = _shift_month(today.replace(day=1), -(months - 1))
    counts: dict[str, int] = {}
    hours = [0] * 24
    same_day = 0
    for c in completions:
        if not (c.get("value") or 0) > 0:
            continue
        key = (c.get("due_date") or "")[:7]
        counts[key] = counts.get(key, 0) + 1
        try:
            stamp = datetime.fromisoformat(c.get("completed_at") or "")
        except ValueError:
            continue
        local = stamp.astimezone() if stamp.tzinfo else stamp
        if local.date().isoformat() == c.get("due_date"):
            hours[local.hour] += 1
            same_day += 1
    month_rows = []
    peak = 0
    for i in range(months):
        m = _shift_month(first, i)
        n = counts.get(m.strftime("%Y-%m"), 0)
        peak = max(peak, n)
        month_rows.append({"label": m.strftime("%b"), "key": m.strftime("%Y-%m"), "count": n})
    for row in month_rows:
        row["height"] = (row["count"] / peak) if peak else 0
    hour_rows = None
    top_hour = None
    if same_day >= 5:
        hmax = max(hours)
        hour_rows = [{"hour": h, "count": n, "height": n / hmax if hmax else 0} for h, n in enumerate(hours)]
        top_hour = max(range(24), key=lambda h: hours[h])
    # 2026-09-26: the view modal shows insights only past two weeks of
    # logged days -- a handful of check-ins makes a meaningless chart.
    logged = sum(row["count"] for row in month_rows)
    return {
        "months": month_rows,
        "hours": hour_rows,
        "top_hour": top_hour,
        "same_day": same_day,
        "enough": logged >= INSIGHTS_MIN_DAYS,
    }
