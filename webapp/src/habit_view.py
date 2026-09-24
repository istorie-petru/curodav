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

from datetime import date, timedelta

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


def week_strip(uid: str, entries_by_date: dict, today: date, excluded: set[str] | None = None) -> list[dict]:
    excluded = excluded or set()
    days = []
    for back in range(6, -1, -1):
        d = today - timedelta(days=back)
        iso = d.isoformat()
        value = entries_by_date.get(iso, 0) or 0
        days.append(
            {
                "iso": iso,
                "initial": _DAY_NAMES[d.weekday()][0],
                "day_name": _DAY_NAMES[d.weekday()],
                "value": value,
                "done": value > 0,
                "is_today": back == 0,
                "excluded": iso in excluded,
                "toggle_url": f"/tasks/{uid}/completion/{iso}/toggle",
            }
        )
    return days


def _shift_month(first: date, delta: int) -> date:
    idx = first.year * 12 + first.month - 1 + delta
    return date(idx // 12, idx % 12 + 1, 1)


def month_calendar(uid: str, completions: list[dict], month: str | None, today: date | None = None) -> dict:
    """Habits H3: one month (Mon-first weeks) for the habit detail modal --
    each day carries its logged value and note, and a toggle URL unless
    it's in the future. `month` is "YYYY-MM" (default: this month; never
    past this month). Prev/next point at the detail URL with ?month=."""
    today = today or date.today()
    this_month = today.replace(day=1)
    try:
        first = date.fromisoformat(f"{month}-01") if month else this_month
    except ValueError:
        first = this_month
    first = min(first, this_month)
    by_date = {c["due_date"]: c for c in completions}
    start = first - timedelta(days=first.weekday())
    nxt = _shift_month(first, 1)
    weeks = []
    d = start
    while d < nxt or d.weekday() != 0:
        if d.weekday() == 0:
            weeks.append([])
        iso = d.isoformat()
        row = by_date.get(iso) or {}
        value = row.get("value") or 0
        weeks[-1].append(
            {
                "iso": iso,
                "day": d.day,
                "in_month": d.month == first.month,
                "value": value,
                "done": value > 0,
                "note": (row.get("note") or "").strip(),
                "is_today": d == today,
                "is_future": d > today,
                "toggle_url": f"/tasks/{uid}/completion/{iso}/toggle",
            }
        )
        d += timedelta(days=1)
    prev_first = _shift_month(first, -1)
    return {
        "label": first.strftime("%B %Y"),
        "weeks": weeks,
        "day_names": _DAY_NAMES,
        "prev_url": f"/tasks/{uid}?month={prev_first.strftime('%Y-%m')}",
        "next_url": f"/tasks/{uid}?month={nxt.strftime('%Y-%m')}" if nxt <= this_month else None,
        "done_count": sum(1 for w in weeks for x in w if x["in_month"] and x["done"]),
    }


def recent_notes(completions: list[dict], limit: int = 10) -> list[dict]:
    """Habits H3: newest-first logged days that carry a note."""
    rows = [c for c in completions if (c.get("note") or "").strip()]
    rows.sort(key=lambda c: c["due_date"], reverse=True)
    return [{"iso": c["due_date"], "note": c["note"].strip(), "value": c.get("value") or 0} for c in rows[:limit]]


def habit_item(conn, task: dict, today: date, pauses: list[dict] | None = None) -> dict:
    today_iso = today.isoformat()
    entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, task["uid"])}
    target = task.get("target_per_day") or 1
    excluded = excluded_dates_for_row(conn, task, entries_by_date, today)
    pinfo = pause_info(db.list_habit_pauses(conn) if pauses is None else pauses, task["uid"], today)
    stats = stats_for_task(task, entries_by_date, excluded, today, pinfo["dates"])
    today_value = entries_by_date.get(today_iso, 0)
    return {
        "uid": task["uid"],
        "title": task["title"],
        "tags": task.get("tags") or [],
        "is_quantity": target > 1 and task.get("habit_kind") != "avoid",
        "target": target,
        "today": today_iso,
        "today_value": today_value,
        "next_value": today_value + 1,
        "done_today": today_value > 0,
        # Schedule-aware (habits H1): counted in `streak_unit`s -- due
        # days for a daily/weekday habit, weeks/months for a period one.
        "current_streak": stats["current"],
        "longest_streak": stats["longest"],
        "streak_unit": stats["unit"],
        "completion_rate": stats["rate"],
        "due_today": stats["due_today"],
        "period_done": stats["period_done"],
        "period_target": stats["period_target"],
        "is_period": stats["kind"] == "period",
        # Habits H5: an avoid habit logs relapses; its streak is clean days.
        "is_avoid": stats["kind"] == "avoid",
        "relapsed_today": stats.get("relapsed_today", False),
        "unit": (task.get("habit_unit") or "").strip(),
        # Habits H6: vacation / pause.
        "paused_today": pinfo["paused_today"],
        "paused_until": pinfo["paused_until"],
        # The habit's cadence in words, never the raw RRULE.
        "recurrence_label": cadence_label(task),
        # Habits H2: the last seven days, oldest first, for the Habits
        # page's (and later the widget's) tap-a-day strip.
        "week": week_strip(task["uid"], entries_by_date, today, excluded | pinfo["dates"]),
        "detail_url": f"/tasks/{task['uid']}",
        "edit_url": f"/tasks/{task['uid']}/edit",
        "toggle_url": f"/tasks/{task['uid']}/completion/{today_iso}/toggle",
        "plus_url": f"/tasks/{task['uid']}/completions",
        "delete_url": f"/tasks/{task['uid']}/delete",
    }


def habit_items(conn, today: date | None = None) -> list[dict]:
    """Every active habit, alphabetical (list_habit_tasks' own order)."""
    today = today or date.today()
    pauses = db.list_habit_pauses(conn)
    return [
        habit_item(conn, t, today, pauses)
        for t in db.list_habit_tasks(conn)
        if t["status"] not in _INACTIVE_STATUSES
    ]
