"""The one frontend habit shape (2026-09-24, plans/ui-cleanup-2026-09.md
item 14, slice 1).

A habit is a habit-labeled task in the backend (task_habit_settings'
label + `tasks.target_per_day`/`recurrence` + `task_completions.value`) --
the standalone Habit entity (`habits`/`habit_entries`) is gone as of this
same slice (Peter: no real entities in use; its tables are left physically
in place, never force-dropped, same convention as every other table
removal in db.py). Every habit surface renders from `habit_items` below
instead of reading task rows directly, so a habit never has to look like a
task (status, due date, Kanban column) anywhere it's shown -- the Tasks
table's Habits group and the Dashboard's Habit Check-in widget today, the
dedicated Habits page next.
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


def stats_for_task(task: dict, entries_by_date: dict, excluded: set[str], today: date | None = None) -> dict:
    """habit_schedule.habit_stats for one recurring task row (habits H1)."""
    return habit_schedule.habit_stats(
        entries_by_date,
        task.get("recurrence"),
        per_period=task.get("habits_per_period"),
        today=today,
        excluded_dates=excluded,
        created=_created_date(task),
    )


def cadence_label(task: dict) -> str:
    """"Daily", "Every 2 days", "Mon, Wed, Fri", "Weekly", "3x a week",
    "Monthly" -- the schedule in words, never the raw RRULE."""
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


def habit_item(conn, task: dict, today: date) -> dict:
    today_iso = today.isoformat()
    entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, task["uid"])}
    target = task.get("target_per_day") or 1
    excluded = excluded_dates_for_row(conn, task, entries_by_date, today)
    stats = stats_for_task(task, entries_by_date, excluded, today)
    today_value = entries_by_date.get(today_iso, 0)
    return {
        "uid": task["uid"],
        "title": task["title"],
        "tags": task.get("tags") or [],
        "is_quantity": target > 1,
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
        # The habit's cadence in words, never the raw RRULE.
        "recurrence_label": cadence_label(task),
        "detail_url": f"/tasks/{task['uid']}",
        "toggle_url": f"/tasks/{task['uid']}/completion/{today_iso}/toggle",
        "plus_url": f"/tasks/{task['uid']}/completions",
        "delete_url": f"/tasks/{task['uid']}/delete",
    }


def habit_items(conn, today: date | None = None) -> list[dict]:
    """Every active habit, alphabetical (list_habit_tasks' own order)."""
    today = today or date.today()
    return [
        habit_item(conn, t, today)
        for t in db.list_habit_tasks(conn)
        if t["status"] not in _INACTIVE_STATUSES
    ]
