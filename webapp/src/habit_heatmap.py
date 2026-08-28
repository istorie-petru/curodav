"""Shared GitHub-style heatmap/streak math for anything tracked as a daily
{date: value} log -- the standalone Habits feature (habit_entries) and
(2026-08-08, "add habits page as a view on tasks") habit-labeled tasks
(task_completions) both need the exact same grid-building and streak-
counting logic, just fed from different tables. Factored out of
routers/habits.py into its own module (not left there and imported by
routers/tasks.py) specifically to avoid a circular import:
routers/labels.py imports from routers/tasks.py (IMPORTANCE_COLORS etc.),
and routers/tasks.py needs this logic too now -- if it lived in
routers/habits.py (which itself imports from routers/labels.py for
LABEL_ICONS), that would close a labels -> tasks -> habits -> labels
cycle. This module imports nothing from any router, so both can depend on
it safely."""

from __future__ import annotations

from datetime import date, timedelta


def heatmap_weeks(
    entries_by_date: dict[str, float], target: float, weeks: int, today: date | None = None
) -> list[list[dict]]:
    """Builds a Monday-aligned grid of `weeks` columns x 7 day-rows ending
    on `today` (real date.today() by default; a fixed value is accepted
    purely so tests are deterministic instead of depending on the clock).
    Each cell carries enough to both paint and act as a toggle target:
    `date` (ISO string, used as both the form action and a stable dict
    key), `level` (0-4 color-intensity bucket, or -1 for a future day that
    should render blank/non-interactive since there's nothing to log yet),
    and `month_label` (only set on the first Monday of a month, so the
    header row can print month names without repeating them every
    column)."""
    today = today or date.today()
    start = today - timedelta(days=weeks * 7 - 1)
    start -= timedelta(days=start.weekday())  # snap back to the preceding Monday

    days = []
    d = start
    while d <= today:
        days.append(d)
        d += timedelta(days=1)
    while len(days) % 7 != 0:
        days.append(days[-1] + timedelta(days=1))

    result: list[list[dict]] = []
    for week_start in range(0, len(days), 7):
        col = []
        for day in days[week_start : week_start + 7]:
            iso = day.isoformat()
            is_future = day > today
            value = entries_by_date.get(iso, 0)
            if is_future:
                level = -1
            elif value <= 0:
                level = 0
            elif target and target > 0:
                ratio = value / target
                level = 4 if ratio >= 1 else 3 if ratio >= 0.66 else 2 if ratio >= 0.33 else 1
            else:
                level = 4  # no meaningful target (e.g. 0) -- any logged value is "full"
            col.append(
                {
                    "date": iso,
                    "value": value,
                    "level": level,
                    "is_future": is_future,
                    "weekday": day.weekday(),
                    "month_label": day.strftime("%b") if day.day <= 7 and day.weekday() == 0 else None,
                }
            )
        result.append(col)
    return result


def heatmap_range(
    entries_by_date: dict[str, float], target: float, start: date, end: date, today: date | None = None
) -> list[list[dict]]:
    """Same cell shape as heatmap_weeks (date/value/level/is_future/
    weekday/month_label), but a fixed calendar range (`start` through
    `end`, Monday-aligned) instead of "N weeks ending today" -- 2026-08-08
    direct feedback ("pick a fixed date for all ... and show from there")
    for Tasks > Habits: every habit-task's heatmap starts on the same
    fixed date (the current half-year's first day) regardless of when
    that task was created, so cards line up and compare directly instead
    of each scrolling its own rolling window. `end` can be in the future
    (the current half-year's last day, e.g. Dec 31) -- any day after the
    real `today` still renders (level -1, non-interactive) so the grid's
    *shape* (how many weeks wide) stays identical all year, only the
    filled-in portion grows as the year progresses."""
    today = today or date.today()
    aligned_start = start - timedelta(days=start.weekday())  # snap back to the preceding Monday

    days = []
    d = aligned_start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    while len(days) % 7 != 0:
        days.append(days[-1] + timedelta(days=1))

    result: list[list[dict]] = []
    for week_start in range(0, len(days), 7):
        col = []
        for day in days[week_start : week_start + 7]:
            iso = day.isoformat()
            is_future = day > today
            value = entries_by_date.get(iso, 0)
            if is_future:
                level = -1
            elif value <= 0:
                level = 0
            elif target and target > 0:
                ratio = value / target
                level = 4 if ratio >= 1 else 3 if ratio >= 0.66 else 2 if ratio >= 0.33 else 1
            else:
                level = 4
            col.append(
                {
                    "date": iso,
                    "value": value,
                    "level": level,
                    "is_future": is_future,
                    "weekday": day.weekday(),
                    "month_label": day.strftime("%b") if day.day <= 7 and day.weekday() == 0 else None,
                }
            )
        result.append(col)
    return result


def current_half_year(today: date | None = None) -> tuple[date, date]:
    """(start, end) of whichever calendar half `today` falls in -- Jan 1
    through Jun 30, or Jul 1 through Dec 31. The fixed range
    heatmap_range's "pick a fixed date for all" callers (Tasks > Habits)
    anchor to."""
    today = today or date.today()
    if today.month <= 6:
        return date(today.year, 1, 1), date(today.year, 6, 30)
    return date(today.year, 7, 1), date(today.year, 12, 31)


def streaks(entries_by_date: dict[str, float], today: date | None = None) -> tuple[int, int]:
    """(current_streak, longest_streak) in days, counting any day with a
    logged value > 0 as "done" -- target_per_day only affects heatmap
    color, not whether a day counts at all (a habit tracker that required
    hitting the exact target to keep a streak alive would punish e.g.
    "read 8/10 pages" as a broken streak, which isn't the intent). Current
    streak tolerates today itself not being logged yet (you haven't lost
    your streak just because it's 9am and you haven't meditated yet) but
    breaks the moment a full calendar day is skipped."""
    today = today or date.today()
    done_dates = sorted(d for d, v in entries_by_date.items() if v and v > 0)
    if not done_dates:
        return 0, 0
    done_set = set(done_dates)

    longest = current_run = 0
    prev: date | None = None
    for d_str in done_dates:
        d = date.fromisoformat(d_str)
        current_run = current_run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, current_run)
        prev = d

    cursor = today
    if cursor.isoformat() not in done_set:
        cursor -= timedelta(days=1)
    current = 0
    while cursor.isoformat() in done_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def recurrence_frequency(rrule: str | None) -> str:
    """Coarse recurrence bucket ("daily"/"weekly"/"monthly"/"yearly"/
    "custom"/"") for an RRULE string -- looks only at FREQ=, so an
    INTERVAL/BYDAY/COUNT/UNTIL qualifier beyond the bare FREQ still
    resolves to its FREQ bucket (e.g. "FREQ=WEEKLY;INTERVAL=2" is still
    "weekly"). Used both for display (recurrence_label below) and for
    sizing a habit-tracked task's "how many work sessions does the
    displayed week still need" requirement (routers/calendar.py's
    Unscheduled work panel, 2026-08-29 "habit work sessions" slice)."""
    if not rrule:
        return ""
    parts = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    freq = (parts.get("FREQ") or "").upper()
    if freq in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return freq.lower()
    return "custom"


def recurrence_label(rrule: str | None) -> str:
    """Human phrasing for an RRULE string -- "Daily"/"Weekly"/"Monthly"/
    "Yearly"/"Custom" -- never the raw "FREQ=DAILY" a task's `recurrence`
    column stores (2026-08-29 direct feedback: the Habits group's Due
    column showed the raw RRULE verbatim). Every real caller only ever
    feeds this something that IS recurring (a habit is defined by
    recurring), so an empty/unrecognized value reads as "Custom" rather
    than blank."""
    return {
        "daily": "Daily",
        "weekly": "Weekly",
        "monthly": "Monthly",
        "yearly": "Yearly",
    }.get(recurrence_frequency(rrule), "Custom")


def streak_text(days: int, playful: bool = False) -> str:
    """Human-readable phrase for a `streaks()`-computed current streak --
    2026-08-28 direct feedback ("the due date for habits should display a
    text with the streak... that can be playful depending on the
    settings"). `days` is the same integer either way; only the wording
    changes (Settings > General's "Habit streak terminology", same
    presentation-layer-only pattern as 1.6's recurrence terminology --
    see deps.py's HABIT_STREAK_TERMINOLOGY_KEY). Standard mode is a plain,
    neutral count that reads the same at any length; playful mode
    escalates through weekly/monthly language as the streak grows,
    matching the concrete examples the feature request gave ("1 day
    streak", "This Week has been full", "Consistent for 1 Month")."""
    if days <= 0:
        return "Let's get started" if playful else "No streak yet"
    if not playful:
        return f"{days} day{'s' if days != 1 else ''} streak"
    if days == 1:
        return "1 day streak"
    if days < 7:
        return f"{days} days strong"
    if days < 14:
        return "This week has been full"
    if days < 30:
        weeks = days // 7
        return f"{weeks} weeks strong"
    months = days // 30
    return f"Consistent for {months} month{'s' if months != 1 else ''}"
