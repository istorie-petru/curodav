"""Flat dict row <-> icalendar VEVENT/VTODO, for the web app's own simpler
schema (db.py). This intentionally duplicates the *shape* of the mapping in
desktop/src/core/caldav/ical.py (same priority/status conventions, so a
task edited here and one edited on desktop mean the same thing) but not the
code -- this app has no Object/TaskDetails model, just flat dicts matching
the `events`/`tasks` table columns, and no X-COMMANDCENTER-* properties at
all, since this app never has graph metadata to preserve in the first
place. If the two ever drift, desktop's mapping is authoritative (it's the
one with the fuller object model behind it).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from icalendar import Alarm, Event, Todo

# --------------------------------------------------------------------- #
# Importance/Urgency <-> iCal PRIORITY (1.1, plans/open-priority.md
# § Virtual & derived states -- "Importance and urgency (replacing WebDAV
# priority)").
#
# Recorded decision: PRIORITY is the single WebDAV channel for the two
# semantic axes. Export combines Importance and Urgency into one PRIORITY
# via a deterministic, urgency-dominant precedence table; import maps
# PRIORITY back to explicit *urgency* only. That asymmetry is deliberate:
# this app is the write-source for its own tasks, and foreign CalDAV
# clients render PRIORITY (and may re-author it) without understanding the
# app's importance axis -- so the urgency axis (the time-sensitive one a
# calendar client's red-flag PRIORITY is actually about) round-trips
# faithfully, importance is preserved in this app's own DB, and no
# incompatible second model or made-up X- property is introduced. See the
# phase spec slice 4.
#
# Export table (importance, urgency) -> PRIORITY, urgency dominant:
#   urgency 3 -> 1    urgency 2 -> 3    urgency 1 -> 5
#   urgency 0, importance 3 -> 2
#   urgency 0, importance 2 -> 4
#   urgency 0, importance 1 -> 6
#   both 0 -> 0 (undefined)
_URGENCY_TO_ICAL = {3: 1, 2: 3, 1: 5}
_IMPORTANCE_ONLY_TO_ICAL = {3: 2, 2: 4, 1: 6}


def _priority_to_ical(importance: int | None, urgency: int | None) -> int:
    """Importance/Urgency (1..3 each, 0/None = unset) -> one iCal PRIORITY
    per the precedence table above. Urgency (the time-sensitive axis) wins
    the lower/redder numbers; importance fills the between-values when
    urgency is unset. Both unset -> 0 (undefined), matching iCalendar's own
    meaning of PRIORITY 0 and the old code's behavior for a None priority."""
    importance = int(importance or 0)
    urgency = int(urgency or 0)
    if urgency:
        return _URGENCY_TO_ICAL[urgency]
    if importance:
        return _IMPORTANCE_ONLY_TO_ICAL[importance]
    return 0


def _priority_from_ical(v: int | None) -> int | None:
    """iCal PRIORITY -> explicit urgency (1..3), per the recorded decision.
    0/absent -> None (unset). Urgency-dominant export means a client that
    re-writes PRIORITY changes the urgency axis; importance is untouched by
    import either way."""
    if not v:
        return None
    if v <= 2:
        return 3
    if v <= 5:
        return 2
    return 1


_STATUS_TO_VTODO = {
    "active": "NEEDS-ACTION",
    "waiting": "NEEDS-ACTION",
    "in_progress": "IN-PROCESS",
    "done": "COMPLETED",
    "archived": "CANCELLED",
}
_VTODO_TO_STATUS = {
    "NEEDS-ACTION": "active",
    "IN-PROCESS": "in_progress",
    "COMPLETED": "done",
    "CANCELLED": "archived",
}
_STATUS_TO_VEVENT = {
    "active": "CONFIRMED",
    "waiting": "TENTATIVE",
    "in_progress": "CONFIRMED",
    "done": "CONFIRMED",
    "archived": "CANCELLED",
}
_VEVENT_TO_STATUS = {
    "TENTATIVE": "waiting",
    "CONFIRMED": "active",
    "CANCELLED": "archived",
}


def _parse_dt(value: str) -> date | datetime:
    if len(value) == 10:
        return date.fromisoformat(value)
    return datetime.fromisoformat(value)


def _dt_to_field(value: date | datetime) -> str:
    return value.isoformat()


def _normalize_rrule(recurrence: str, dtstart_is_datetime: bool) -> tuple[str, list[date]]:
    """The app's recurrence strings (both hand-typed in event/task forms
    and schedule.py-generated) use a dashed ISO-date convention for UNTIL,
    matching desktop's core/recurrence.py -- e.g. "UNTIL=2026-12-20". RFC
    5545's RRULE grammar does NOT accept that: `icalendar`'s parser raises
    ValueError on anything but the compact form ("UNTIL=20261220" or
    "...T235959"). RFC 5545 also doesn't allow EXDATE inside an RRULE
    value at all -- it's a distinct top-level property. Both were latent
    bugs (never hit because no test recurrence string included UNTIL or
    EXDATE) until the Schedule feature started actually generating both.

    RFC 5545 additionally requires UNTIL's value type to *match DTSTART's*
    (§3.3.10) -- a DATE-TIME DTSTART with a bare-DATE UNTIL is silently
    interpreted as "until midnight" by expansion libraries, which drops
    the final occurrence whenever its time-of-day is after 00:00 (caught
    by recurrence_expand.py's own test: a Tuesday-10am class with
    UNTIL=2026-09-22 was missing its Sep-22 occurrence entirely). So this
    always coerces UNTIL to match `dtstart_is_datetime`, regardless of
    whether the input string had a time component.

    Returns (rrule_string_safe_for_icalendar, embedded_exdates) -- the
    caller is responsible for adding those exdates as a proper EXDATE
    property rather than leaving them in the RRULE string.
    """
    parts = recurrence.split(";")
    safe_parts: list[str] = []
    exdates: list[date] = []
    for part in parts:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().upper()
        value = value.strip()
        if key == "EXDATE":
            for token in value.split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    exdates.append(date.fromisoformat(token[:10]))
                except ValueError:
                    continue
        elif key == "UNTIL":
            try:
                d = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
            except ValueError:
                safe_parts.append(part)  # not our dashed format -- pass through as-is
                continue
            if dtstart_is_datetime:
                safe_parts.append(f"UNTIL={d.strftime('%Y%m%d')}T235959")
            else:
                safe_parts.append(f"UNTIL={d.strftime('%Y%m%d')}")
        else:
            safe_parts.append(part)
    return ";".join(safe_parts), exdates


# --------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------- #


def task_row_to_ical(row: dict[str, Any]) -> bytes:
    todo = Todo()
    todo.add("UID", row["uid"])
    todo.add("SUMMARY", row.get("title") or "")
    if row.get("description"):
        todo.add("DESCRIPTION", row["description"])
    if row.get("start_at"):
        todo.add("DTSTART", _parse_dt(row["start_at"]))
    if row.get("due_at"):
        todo.add("DUE", _parse_dt(row["due_at"]))
    todo.add("PRIORITY", _priority_to_ical(row.get("importance"), row.get("urgency")))
    todo.add("STATUS", _STATUS_TO_VTODO.get(row.get("status", "active"), "NEEDS-ACTION"))
    if row.get("progress") is not None:
        todo.add("PERCENT-COMPLETE", round(row["progress"] * 100))
    if row.get("tags"):
        todo.add("CATEGORIES", list(row["tags"]))
    # 1.2 (task-model decision): the parent-task/subtask hierarchy is
    # removed -- tasks are flat, so there is no RELATED-TO;RELTYPE=PARENT
    # on export anymore. (The old `tasks.parent_uid` column stays
    # physically on disk, unused; a pre-1.2 VTODO that still carries a
    # RELATED-TO is simply ignored on import below.)
    if row.get("recurrence"):
        anchor = row.get("start_at") or row.get("due_at") or ""
        is_datetime = len(anchor) > 10
        rrule_str, embedded_exdates = _normalize_rrule(row["recurrence"], is_datetime)
        try:
            todo.add("RRULE", rrule_str)
        except (ValueError, TypeError):
            pass
        if embedded_exdates:
            todo.add("EXDATE", embedded_exdates)
    todo.add("DTSTAMP", datetime.now(timezone.utc))
    return todo.to_ical()


def ical_to_task_row(todo: Todo) -> dict[str, Any]:
    row: dict[str, Any] = {"uid": str(todo.get("UID"))}
    row["title"] = str(todo.get("SUMMARY", ""))
    row["description"] = str(todo.get("DESCRIPTION", "")) if "DESCRIPTION" in todo else ""
    if "DTSTART" in todo:
        row["start_at"] = _dt_to_field(todo.get("DTSTART").dt)
    if "DUE" in todo:
        row["due_at"] = _dt_to_field(todo.get("DUE").dt)
    row["urgency"] = _priority_from_ical(
        int(todo.get("PRIORITY")) if "PRIORITY" in todo else None
    )
    row["status"] = _VTODO_TO_STATUS.get(str(todo.get("STATUS", "")), "active")
    if "PERCENT-COMPLETE" in todo:
        row["progress"] = int(todo.get("PERCENT-COMPLETE")) / 100
    if "CATEGORIES" in todo:
        cats = todo.get("CATEGORIES")
        cats_list = cats.cats if hasattr(cats, "cats") else cats
        row["tags"] = [str(c) for c in cats_list]
    # 1.2: RELATED-TO;RELTYPE=PARENT (subtask links) is deliberately not
    # parsed back -- tasks are flat now. See the export-side comment above.
    if "RRULE" in todo:
        row["recurrence"] = todo.get("RRULE").to_ical().decode()
    return row


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #


def event_row_to_ical(row: dict[str, Any]) -> bytes:
    event = Event()
    event.add("UID", row["uid"])
    event.add("SUMMARY", row.get("title") or "")
    if row.get("description"):
        event.add("DESCRIPTION", row["description"])
    start_is_datetime = True
    if row.get("start_at"):
        start = _parse_dt(row["start_at"])
        if row.get("all_day") and isinstance(start, datetime):
            start = start.date()
        start_is_datetime = isinstance(start, datetime)
        event.add("DTSTART", start)
        if row.get("end_at"):
            end = _parse_dt(row["end_at"])
            if row.get("all_day") and isinstance(end, datetime):
                end = end.date()
            event.add("DTEND", end)
    event.add("STATUS", _STATUS_TO_VEVENT.get(row.get("status", "active"), "CONFIRMED"))
    if row.get("location"):
        event.add("LOCATION", row["location"])
    if row.get("meeting_url"):
        event.add("URL", row["meeting_url"])
    if row.get("tags"):
        event.add("CATEGORIES", list(row["tags"]))
    exdate_values: list[date | datetime] = []
    if row.get("recurrence"):
        rrule_str, embedded_exdates = _normalize_rrule(row["recurrence"], start_is_datetime)
        try:
            event.add("RRULE", rrule_str)
        except (ValueError, TypeError):
            pass
        exdate_values.extend(embedded_exdates)
    for raw_exdate in row.get("exdates") or []:
        exdate_values.append(_parse_dt(raw_exdate) if isinstance(raw_exdate, str) else raw_exdate)
    if exdate_values:
        event.add("EXDATE", exdate_values)
    for minutes_before in row.get("reminders") or []:
        alarm = Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", row.get("title") or "Reminder")
        from datetime import timedelta

        alarm.add("TRIGGER", timedelta(minutes=-abs(minutes_before)))
        event.add_component(alarm)
    event.add("DTSTAMP", datetime.now(timezone.utc))
    return event.to_ical()


def ical_to_event_row(event: Event) -> dict[str, Any]:
    row: dict[str, Any] = {"uid": str(event.get("UID"))}
    row["title"] = str(event.get("SUMMARY", ""))
    row["description"] = str(event.get("DESCRIPTION", "")) if "DESCRIPTION" in event else ""
    if "DTSTART" in event:
        dtstart = event.get("DTSTART").dt
        row["start_at"] = _dt_to_field(dtstart)
        row["all_day"] = not isinstance(dtstart, datetime)
    if "DTEND" in event:
        row["end_at"] = _dt_to_field(event.get("DTEND").dt)
    row["status"] = _VEVENT_TO_STATUS.get(str(event.get("STATUS", "")), "active")
    if "LOCATION" in event:
        row["location"] = str(event.get("LOCATION"))
    if "URL" in event:
        row["meeting_url"] = str(event.get("URL"))
    if "CATEGORIES" in event:
        cats = event.get("CATEGORIES")
        cats_list = cats.cats if hasattr(cats, "cats") else cats
        row["tags"] = [str(c) for c in cats_list]
    if "RRULE" in event:
        row["recurrence"] = event.get("RRULE").to_ical().decode()
    if "EXDATE" in event:
        exdate_prop = event.get("EXDATE")
        exdate_items = exdate_prop if isinstance(exdate_prop, list) else [exdate_prop]
        exdates: list[str] = []
        for item in exdate_items:
            for dt in getattr(item, "dts", [item]):
                exdates.append(_dt_to_field(dt.dt if hasattr(dt, "dt") else dt))
        row["exdates"] = exdates
    reminders = []
    for alarm in event.walk("VALARM"):
        trigger = alarm.get("TRIGGER")
        if trigger is not None and hasattr(trigger.dt, "total_seconds"):
            reminders.append(round(-trigger.dt.total_seconds() / 60))
    if reminders:
        row["reminders"] = reminders
    return row
