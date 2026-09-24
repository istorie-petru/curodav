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

from . import db, habit_heatmap

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


def habit_item(conn, task: dict, today: date) -> dict:
    today_iso = today.isoformat()
    entries_by_date = {c["due_date"]: c["value"] for c in db.list_task_completions(conn, task["uid"])}
    target = task.get("target_per_day") or 1
    excluded = excluded_dates_for_row(conn, task, entries_by_date, today)
    current_streak, _ = habit_heatmap.streaks(entries_by_date, excluded_dates=excluded)
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
        "current_streak": current_streak,
        # The habit's cadence ("Daily"/"Weekly"/...), never the raw
        # "FREQ=DAILY" the task's `recurrence` column stores.
        "recurrence_label": habit_heatmap.recurrence_label(task.get("recurrence")),
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
