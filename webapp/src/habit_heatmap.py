"""Shared GitHub-style heatmap/streak math for anything tracked as a daily
{date: value} log -- the standalone Habits feature (habit_entries) and
(2026-08-08, "add habits page as a view on tasks") habit-labeled tasks
(task_completions) both need the exact same grid-building and streak-
counting logic, just fed from different tables. Factored out of
routers/habits.py into its own module (not left there and imported by
routers/tasks.py) specifically to avoid a circular import:
routers/labels.py imports label/color maps from routers/tasks.py, and
routers/tasks.py needs this logic too now -- if it lived in
routers/habits.py (which itself imports from routers/labels.py for
LABEL_ICONS), that would close a labels -> tasks -> habits -> labels
cycle. This module imports nothing from any router, so both can depend on
it safely."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import recurrence_expand

# How many weeks a "full history" heatmap shows. Shared by both heatmap
# call sites that want this view (routers/habits.py's standalone habit
# detail modal, and routers/tasks.py's habit-tracked-task detail modal)
# rather than each picking its own week count -- 2026-08-29 direct feedback
# ("the heatmap graph should not have empty space... prefer to show more
# months, empty cells, but not empty space"): the task modal used to
# default to a 12-week window, far narrower than the modal body it sits in.
# Both call sites now render with `heatmap-wide` (style.css), which
# stretches each week column to fill the container's width -- so this
# constant no longer needs to match any one container's pixel width to
# avoid empty space or overflow, it only controls how many months are
# visible at once vs. how big each cell renders (fewer weeks -> the same
# container width divided among fewer columns -> bigger cells). Was 53
# ("a bit over a year," GitHub's own convention) while heatmap-wide's cells
# were still fixed-size-ish and small; dropped to 32 (~7.5 months)
# 2026-08-29, same-day follow-up ("make the cells a bit bigger") trading
# some of that history for meaningfully larger, easier-to-read cells.
DETAIL_WEEKS = 32


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


def excluded_dates_in_range(
    row: dict[str, Any],
    holiday_calendars: dict[str, list[dict[str, Any]]] | None,
    start: date,
    end: date,
) -> set[str]:
    """2026-08-29 (STATE.md backlog item 3, direct request): the 1.6
    non-working-day policy (`holiday_calendar`/`exclude_saturday`/
    `exclude_sunday` -- see db.py's `events` CREATE TABLE comment) extended
    to recurring tasks and habits. Those two entities don't go through
    recurrence_expand.expand_events (a habit has no RRULE at all; a
    recurring task's completion history is a flat {date: value} log, not
    RRULE-expanded occurrences) -- so rather than "is this occurrence
    excluded," the question here is just "which calendar days in
    [start, end] does this row's own policy mark as non-working," reusing
    the exact same day-level check (`recurrence_expand.
    is_excluded_by_policy`) `expand_events` applies per-occurrence. `row`
    just needs to carry `holiday_calendar`/`exclude_saturday`/
    `exclude_sunday` -- a task row, a habit row, and an event row all
    shape-match for this purpose."""
    if not row.get("holiday_calendar") and not row.get("exclude_saturday") and not row.get("exclude_sunday"):
        return set()
    result: set[str] = set()
    d = start
    while d <= end:
        if recurrence_expand.is_excluded_by_policy(d, row, holiday_calendars):
            result.add(d.isoformat())
        d += timedelta(days=1)
    return result


def streaks(
    entries_by_date: dict[str, float],
    today: date | None = None,
    excluded_dates: set[str] | None = None,
) -> tuple[int, int]:
    """(current_streak, longest_streak) in days, counting any day with a
    logged value > 0 as "done" -- target_per_day only affects heatmap
    color, not whether a day counts at all (a habit tracker that required
    hitting the exact target to keep a streak alive would punish e.g.
    "read 8/10 pages" as a broken streak, which isn't the intent). Current
    streak tolerates today itself not being logged yet (you haven't lost
    your streak just because it's 9am and you haven't meditated yet) but
    breaks the moment a full calendar day is skipped.

    `excluded_dates` (2026-08-29, STATE.md backlog item 3 -- see
    `excluded_dates_in_range` above): an optional set of ISO date strings
    the caller has already determined are non-working days for this
    specific task/habit. Such a day is treated as neither done nor
    skipped -- it's invisible to the streak walk, so a holiday or an
    excluded weekend day sitting between two logged days doesn't break the
    run, and a currently-excluded "today"/yesterday doesn't zero out the
    current streak either. An excluded day is never itself counted as a
    "done" day even if it happens to carry a logged value (backfilling a
    holiday you didn't actually need to keep up the habit is allowed, it
    just doesn't inflate the streak)."""
    excluded_dates = excluded_dates or set()
    today = today or date.today()
    done_dates = sorted(d for d, v in entries_by_date.items() if v and v > 0 and d not in excluded_dates)
    if not done_dates:
        return 0, 0
    done_set = set(done_dates)

    def _all_excluded_between(a: date, b: date) -> bool:
        """Every day strictly between `a` and `b` (exclusive both ends) is
        in `excluded_dates` -- the condition under which a gap doesn't
        break a streak."""
        span = (b - a).days
        return all((a + timedelta(days=i)).isoformat() in excluded_dates for i in range(1, span))

    longest = current_run = 0
    prev: date | None = None
    for d_str in done_dates:
        d = date.fromisoformat(d_str)
        if prev is not None and ((d - prev).days == 1 or _all_excluded_between(prev, d)):
            current_run += 1
        else:
            current_run = 1
        longest = max(longest, current_run)
        prev = d

    cursor = today
    # The "haven't logged today yet" tolerance only applies to the real
    # `today` itself, and only when today isn't already an excluded day --
    # an excluded today is handled by the loop below the same as any other
    # excluded day (skipped, never treated as "broken"), not by this
    # one-off step-back.
    if cursor.isoformat() not in done_set and cursor.isoformat() not in excluded_dates:
        cursor -= timedelta(days=1)
    current = 0
    while True:
        iso = cursor.isoformat()
        if iso in done_set:
            current += 1
            cursor -= timedelta(days=1)
        elif iso in excluded_dates:
            cursor -= timedelta(days=1)
        else:
            break
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
