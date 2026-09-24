"""Schedule-aware habit streaks (2026-09-24, plans/ui-cleanup-2026-09.md
item 14, slice H1).

`habit_heatmap.streaks()` walks calendar days, so any habit that isn't
due every day "broke" its streak on every day it wasn't due: a weekly
habit kept four weeks running read `(current 0, best 1)`. This module
counts **due windows** instead of days.

A habit's schedule comes from its RRULE (`tasks.recurrence`) plus the
optional `tasks.habits_per_period` ("X times per week/month"):

- **period** -- FREQ=WEEKLY/MONTHLY/YEARLY with no BYDAY: each calendar
  week (Mon-Sun) / month / year is one window, kept once it has
  `habits_per_period` (default 1) logged days. INTERVAL=N groups N
  periods into one window, counted from a fixed epoch so it's stable.
- **weekdays** -- any FREQ with BYDAY (e.g. Mon/Wed/Fri): each due
  weekday opens a window that runs until the next due weekday, kept by
  one log anywhere in it (doing Monday's habit on Tuesday still counts).
- **every_n_days** -- FREQ=DAILY (INTERVAL=N, default 1): a window every
  N days, anchored on the habit's creation date. N=1 is exactly the old
  calendar-day behavior.

A window whose due day is a non-working day (holiday/weekend policy,
`excluded_dates`) is neutral -- neither kept nor broken -- and a log on an
excluded day doesn't count toward a weekdays/daily window (same rule as
the old `streaks()`). Period windows count every logged day. The window
containing today never breaks a streak while it's still open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

_WEEKDAY_CODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_WEEK_EPOCH = date(2000, 1, 3)  # a Monday
# How far back any walk goes -- same two-year cap habit_view's exclusion
# lookup already uses.
_MAX_HISTORY_DAYS = 730


@dataclass(frozen=True)
class Schedule:
    kind: str  # "period" | "weekdays" | "every_n_days"
    unit: str  # streak unit: "day" | "week" | "month" | "year"
    interval: int = 1
    per_period: int = 1
    weekdays: frozenset[int] = frozenset()
    anchor: date | None = None


def _rrule_parts(rrule: str | None) -> dict[str, str]:
    return {k.upper(): v for k, v in (p.split("=", 1) for p in (rrule or "").split(";") if "=" in p)}


def parse_schedule(rrule: str | None, per_period: int | None = None, anchor: date | None = None) -> Schedule:
    parts = _rrule_parts(rrule)
    freq = (parts.get("FREQ") or "DAILY").upper()
    try:
        interval = max(1, int(parts.get("INTERVAL") or 1))
    except ValueError:
        interval = 1
    days = frozenset(
        _WEEKDAY_CODES[code[-2:].upper()]
        for code in (parts.get("BYDAY") or "").split(",")
        if code[-2:].upper() in _WEEKDAY_CODES
    )
    if days:
        return Schedule("weekdays", "day", weekdays=days)
    if freq in ("WEEKLY", "MONTHLY", "YEARLY"):
        unit = {"WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}[freq]
        return Schedule("period", unit, interval=interval, per_period=max(1, int(per_period or 1)))
    return Schedule("every_n_days", "day", interval=interval, anchor=anchor)


def _period_ordinal(d: date, unit: str) -> int:
    if unit == "week":
        return (d - _WEEK_EPOCH).days // 7
    if unit == "month":
        return d.year * 12 + d.month - 1
    return d.year


def _period_start(ordinal: int, unit: str) -> date:
    if unit == "week":
        return _WEEK_EPOCH + timedelta(weeks=ordinal)
    if unit == "month":
        return date(ordinal // 12, ordinal % 12 + 1, 1)
    return date(ordinal, 1, 1)


def _windows(schedule: Schedule, start: date, today: date) -> list[tuple[date, date]]:
    """[(window_start, window_end_exclusive)] covering start..today, in
    order; the last one contains today."""
    out: list[tuple[date, date]] = []
    if schedule.kind == "period":
        first = _period_ordinal(start, schedule.unit) // schedule.interval
        last = _period_ordinal(today, schedule.unit) // schedule.interval
        for i in range(first, last + 1):
            out.append(
                (
                    _period_start(i * schedule.interval, schedule.unit),
                    _period_start((i + 1) * schedule.interval, schedule.unit),
                )
            )
        return out
    if schedule.kind == "weekdays":
        dues = [start + timedelta(days=i) for i in range((today - start).days + 1)]
        dues = [d for d in dues if d.weekday() in schedule.weekdays]
        # A log before the first due day in range belongs to the previous
        # due day's window -- walk back to it so it isn't dropped. Only
        # when `start` itself isn't a due day, or that earlier window
        # (with nothing in it) would count as a miss.
        if start.weekday() not in schedule.weekdays:
            back = start - timedelta(days=1)
            while back.weekday() not in schedule.weekdays:
                back -= timedelta(days=1)
            dues.insert(0, back)
        for i, d in enumerate(dues):
            end = dues[i + 1] if i + 1 < len(dues) else _next_weekday(d, schedule.weekdays)
            out.append((d, end))
        return out
    n = schedule.interval
    anchor = schedule.anchor or start
    offset = (start - anchor).days % n
    d = start - timedelta(days=offset)
    while d <= today:
        out.append((d, d + timedelta(days=n)))
        d += timedelta(days=n)
    return out


def _next_weekday(d: date, weekdays: frozenset[int]) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() not in weekdays:
        nxt += timedelta(days=1)
    return nxt


def habit_stats(
    entries_by_date: dict[str, float],
    rrule: str | None,
    per_period: int | None = None,
    today: date | None = None,
    excluded_dates: set[str] | None = None,
    created: date | None = None,
    kind: str | None = None,
    paused_dates: set[str] | None = None,
) -> dict:
    """Streaks and progress for one habit.

    Returns current/longest streak (in `unit`s), completion `rate`
    (kept / counted windows, None before any window counts), whether the
    habit is `due_today` (its open window isn't kept yet), and the open
    window's `period_done`/`period_target` (e.g. 2 of 3 this week).
    """
    today = today or date.today()
    if kind == "avoid":
        return _avoid_stats(entries_by_date, today, created)
    # Habits H6: paused (vacation) days are neutral like a non-working day
    # for a daily/weekday habit; a period window (week/month) that
    # includes any paused day is neutral unless it was kept anyway.
    paused = paused_dates or set()
    excluded = (excluded_dates or set()) | paused
    schedule = parse_schedule(rrule, per_period, created)
    done = {d for d, v in entries_by_date.items() if v and v > 0 and d <= today.isoformat()}
    dates = [date.fromisoformat(d) for d in done]
    if created and created <= today:
        dates.append(created)
    start = min(dates) if dates else today
    start = max(start, today - timedelta(days=_MAX_HISTORY_DAYS))

    windows = _windows(schedule, start, today)
    results: list[bool | None] = []  # True kept, False missed, None neutral
    period_done = 0
    for i, (w_start, w_end) in enumerate(windows):
        is_open = i == len(windows) - 1
        in_window = [
            (w_start + timedelta(days=k)).isoformat() for k in range((min(w_end, today + timedelta(days=1)) - w_start).days)
        ]
        if schedule.kind == "period":
            count = sum(1 for d in in_window if d in done)
            kept = count >= schedule.per_period
            if is_open:
                period_done = count
            if not kept and any(d in paused for d in in_window):
                results.append(None)
                continue
        else:
            if w_start.isoformat() in excluded:
                results.append(None)
                continue
            count = sum(1 for d in in_window if d in done and d not in excluded)
            kept = count >= 1
            if is_open:
                period_done = count
        if is_open and not kept:
            results.append(None)  # still open -- can't be missed yet
        else:
            results.append(kept)

    longest = run = 0
    for r in results:
        if r is None:
            continue
        run = run + 1 if r else 0
        longest = max(longest, run)
    current = 0
    for r in reversed(results):
        if r is None:
            continue
        if not r:
            break
        current += 1
    counted = [r for r in results if r is not None]
    rate = (sum(counted) / len(counted)) if counted else None

    # "Still to do": the open window isn't kept yet (for a weekdays habit
    # that includes Wednesday's window on Thursday) and isn't a neutral
    # non-working day.
    open_start = windows[-1][0] if windows else today
    kept_now = bool(results) and results[-1] is True
    due_today = (
        not kept_now
        and today.isoformat() not in paused
        and (schedule.kind == "period" or open_start.isoformat() not in excluded)
    )
    return {
        "paused_today": today.isoformat() in paused,
        "current": current,
        "longest": longest,
        "unit": schedule.unit,
        "rate": rate,
        "due_today": due_today,
        "period_done": period_done,
        "period_target": schedule.per_period if schedule.kind == "period" else 1,
        "kind": schedule.kind,
    }


def _avoid_stats(entries_by_date: dict[str, float], today: date, created: date | None) -> dict:
    """Habits H5: an *avoid* habit (e.g. "no smoking") logs relapses, not
    successes -- every day without a logged relapse, from creation (or the
    first relapse, if earlier) through today, is a clean day. Current
    streak = clean days ending today (today counts while it's still
    clean), longest = the longest clean run, rate = clean / all days.
    Never "to do": there's nothing to check off, only something to avoid.
    The recurrence/exclusion settings don't apply."""
    relapses = {d for d, v in entries_by_date.items() if v and v > 0 and d <= today.isoformat()}
    starts = [date.fromisoformat(d) for d in relapses]
    if created and created <= today:
        starts.append(created)
    start = max(min(starts) if starts else today, today - timedelta(days=_MAX_HISTORY_DAYS))
    clean = [(start + timedelta(days=i)).isoformat() not in relapses for i in range((today - start).days + 1)]
    longest = run = 0
    for c in clean:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current = 0
    for c in reversed(clean):
        if not c:
            break
        current += 1
    return {
        "current": current,
        "longest": longest,
        "unit": "day",
        "rate": sum(clean) / len(clean) if clean else None,
        "due_today": False,
        "period_done": 0,
        "period_target": 1,
        "kind": "avoid",
        "relapsed_today": today.isoformat() in relapses,
    }


def is_due_on(schedule: Schedule, d: date) -> bool:
    """Habits H7: does this schedule call for the habit on day `d`? A
    weekdays habit on its weekdays, an every-N-days habit on its N-day
    beat (from its anchor), a period habit on any day (it's done whenever
    in the week/month)."""
    if schedule.kind == "weekdays":
        return d.weekday() in schedule.weekdays
    if schedule.kind == "every_n_days":
        anchor = schedule.anchor or d
        return (d - anchor).days % schedule.interval == 0
    return True
