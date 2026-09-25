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


def week_strip(
    uid: str,
    entries_by_date: dict,
    today: date,
    excluded: set[str] | None = None,
    target: float | None = None,
    schedule: habit_schedule.Schedule | None = None,
) -> list[dict]:
    excluded = excluded or set()
    days = []
    for back in range(6, -1, -1):
        d = today - timedelta(days=back)
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
                "is_today": back == 0,
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


def month_calendar(
    uid: str, completions: list[dict], month: str | None, today: date | None = None, target: float | None = None
) -> dict:
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
        state = day_state(value, target)
        weeks[-1].append(
            {
                "iso": iso,
                "day": d.day,
                "in_month": d.month == first.month,
                "value": value,
                # UI audit H-02: full days only; partial is its own state.
                "done": state == "done",
                "partial": state == "partial",
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
            schedule=None
            if task.get("habit_kind") == "avoid"
            else habit_schedule.parse_schedule(task.get("recurrence"), task.get("habits_per_period"), _created_date(task)),
        ),
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
    return {"months": month_rows, "hours": hour_rows, "top_hour": top_hour, "same_day": same_day}
