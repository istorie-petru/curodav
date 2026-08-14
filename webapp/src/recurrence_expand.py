"""Expands recurring events/tasks (RRULE + EXDATE) into concrete
occurrences for a given date window.

Uses `recurring_ical_events` -- already a transitive dependency of
`caldav` (it's what powers `Calendar.date_search(expand=True)`), so this
is battle-tested RFC 5545 expansion rather than a hand-rolled subset like
desktop's `core/recurrence.py` (which deliberately only covers
daily/weekly + basic UNTIL/COUNT/EXDATE -- fine for that app's own
recurrence UI, but this module needs to correctly expand whatever a
DAV client wrote, including RRULE the user typed by hand).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import recurring_ical_events
from icalendar import Calendar, Event, Todo

from .ical_rows import (
    event_row_to_ical,
    ical_to_event_row,
    ical_to_task_row,
    task_row_to_ical,
)


def _occurrence_date(occ_row: dict[str, Any]) -> date | None:
    start_at = occ_row.get("start_at")
    if not start_at:
        return None
    try:
        return datetime.fromisoformat(start_at).date()
    except ValueError:
        return None


def _excluded_by_policy(
    d: date, row: dict[str, Any], holiday_calendars: dict[str, list[dict[str, Any]]] | None
) -> bool:
    """1.6 ("Generalized recurrence and the non-working-day policy"): a
    holiday calendar and a weekend exclusion are independent constraints
    (see db.py's `events` CREATE TABLE comment) -- an occurrence is
    excluded if *either* applies, never materialized into `exdates_json`,
    computed here at read time instead so a holiday calendar's contents or
    an event's own policy take effect immediately."""
    if row.get("exclude_saturday") and d.weekday() == 5:
        return True
    if row.get("exclude_sunday") and d.weekday() == 6:
        return True
    calendar_name = row.get("holiday_calendar")
    if calendar_name and holiday_calendars:
        for h in holiday_calendars.get(calendar_name, []):
            lo = date.fromisoformat(h["date_from"])
            hi = date.fromisoformat(h["date_to"])
            if lo <= d <= hi:
                return True
    return False


def expand_events(
    rows: list[dict[str, Any]],
    window_start: date,
    window_end: date,
    holiday_calendars: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Returns `rows` with every recurring row expanded into one row per
    occurrence inside [window_start, window_end] (same uid as the master --
    clicking any occurrence edits the master, matching desktop's "master is
    the source of truth, occurrences are computed, never stored"
    convention). Non-recurring rows pass through unchanged.

    `holiday_calendars` (optional, `{calendar_name: [holiday row, ...]}` --
    see `db.list_holidays_by_calendar`) applies each recurring row's own
    `holiday_calendar`/`exclude_saturday`/`exclude_sunday` policy on top of
    the RRULE/EXDATE expansion below -- an occurrence excluded by either is
    dropped from the result, same as one already excluded by a stored
    EXDATE. Passing nothing here just means "no holiday calendar lookups
    available" (weekend exclusion still works, since it needs no lookup)."""
    result: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("recurrence"):
            result.append(row)
            continue
        cal = Calendar()
        cal.add("PRODID", "-//command-center-web//")
        cal.add("VERSION", "2.0")
        cal.add_component(Event.from_ical(event_row_to_ical(row)))
        try:
            occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
        except Exception:
            result.append(row)  # malformed rule -- degrade to the anchor, don't crash the view
            continue
        for occ in occurrences:
            occ_row = ical_to_event_row(occ)
            merged = dict(row)
            merged.update(occ_row)
            merged["uid"] = row["uid"]  # always the master's id, never synthetic
            d = _occurrence_date(occ_row)
            if d is not None and _excluded_by_policy(d, row, holiday_calendars):
                continue
            result.append(merged)
    return result


def expand_tasks(
    rows: list[dict[str, Any]], window_start: date, window_end: date
) -> list[dict[str, Any]]:
    """Same idea as `expand_events`, for VTODO/`due_at`. Tasks don't have
    an `exdates` column yet (see db.py's schema note) -- any EXDATE a task's
    recurrence string happens to carry is honored for this expansion (it's
    still parsed correctly by `_normalize_rrule` inside `task_row_to_ical`)
    but won't survive a round trip through the cache, since there's
    nowhere to persist it. Not hit by anything built so far (the Schedule
    feature only mirrors into events, never tasks)."""
    result: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("recurrence"):
            result.append(row)
            continue
        cal = Calendar()
        cal.add("PRODID", "-//command-center-web//")
        cal.add("VERSION", "2.0")
        cal.add_component(Todo.from_ical(task_row_to_ical(row)))
        try:
            occurrences = recurring_ical_events.of(cal, components=["VTODO"]).between(
                window_start, window_end
            )
        except Exception:
            result.append(row)
            continue
        for occ in occurrences:
            occ_row = ical_to_task_row(occ)
            merged = dict(row)
            merged.update(occ_row)
            merged["uid"] = row["uid"]
            result.append(merged)
    return result
