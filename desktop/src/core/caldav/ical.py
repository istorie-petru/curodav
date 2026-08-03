"""Task/event <-> RFC 5545 iCalendar (VTODO/VEVENT) translation.

Standard fields (SUMMARY, DESCRIPTION, DTSTART, DUE/DTEND, PRIORITY, STATUS,
PERCENT-COMPLETE, CATEGORIES, RELATED-TO, RRULE, LOCATION, URL, VALARM)
round-trip through any CalDAV client -- this is the wire format a
self-hosted Radicale/Baikal server, and any native OS calendar/reminders
app, would actually sync.

Everything CommandCenter-specific that has no standard RFC 5545 slot
(checklist, sort_key, pinned, icon, workspace_id, time tracking...) rides
along as `X-COMMANDCENTER-*` properties. RFC 5545 requires compliant
clients to preserve-or-ignore unrecognized properties, never reject them --
so a plain iOS Reminders sync stays correct for *its* view while our own
client still round-trips everything losslessly.

This module only builds/reads `icalendar.Todo`/`Event` objects in memory --
it doesn't know about HTTP, Radicale, or the file tree. `to_vtodo`/
`to_vevent` are the outbound half of a future sync bridge; `vtodo_to_fields`/
`vevent_to_fields` are the inbound half, returning a plain dict of
standard-field updates for `merge.merge_standard_fields_into` to apply --
they never construct a full `Object` themselves, so an incoming edit can
never clobber graph metadata (links, tags outside CATEGORIES, parent/child
outside RELATED-TO) that the source resource didn't touch.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from icalendar import Alarm, Event, Todo

from ..models import EventDetails, Object, ObjectStatus, Priority, TaskDetails

X_PREFIX = "X-COMMANDCENTER-"

# --- priority: our 1(urgent)..4(low) vs iCal's 1(highest)..9(lowest), 0=undefined ---
_PRIORITY_TO_ICAL = {
    Priority.urgent: 1,
    Priority.high: 3,
    Priority.medium: 5,
    Priority.low: 7,
}


def _priority_to_ical(p: int | None) -> int:
    if p is None:
        return 0
    return _PRIORITY_TO_ICAL.get(p, 5)


def _priority_from_ical(v: int | None) -> int | None:
    if not v:
        return None
    if v <= 2:
        return Priority.urgent
    if v <= 4:
        return Priority.high
    if v <= 6:
        return Priority.medium
    return Priority.low


# --- status: VTODO has NEEDS-ACTION/IN-PROCESS/COMPLETED/CANCELLED, no
# "waiting" concept -- collapse it to NEEDS-ACTION for external clients and
# rely on X-COMMANDCENTER-STATUS (below) for our own lossless round-trip. ---
_STATUS_TO_VTODO = {
    ObjectStatus.active: "NEEDS-ACTION",
    ObjectStatus.waiting: "NEEDS-ACTION",
    ObjectStatus.in_progress: "IN-PROCESS",
    ObjectStatus.done: "COMPLETED",
    ObjectStatus.archived: "CANCELLED",
}
_VTODO_TO_STATUS = {
    "NEEDS-ACTION": ObjectStatus.active,
    "IN-PROCESS": ObjectStatus.in_progress,
    "COMPLETED": ObjectStatus.done,
    "CANCELLED": ObjectStatus.archived,
}

# --- status: VEVENT has TENTATIVE/CONFIRMED/CANCELLED, coarser still ---
_STATUS_TO_VEVENT = {
    ObjectStatus.active: "CONFIRMED",
    ObjectStatus.waiting: "TENTATIVE",
    ObjectStatus.in_progress: "CONFIRMED",
    ObjectStatus.done: "CONFIRMED",
    ObjectStatus.archived: "CANCELLED",
}
_VEVENT_TO_STATUS = {
    "TENTATIVE": ObjectStatus.waiting,
    "CONFIRMED": ObjectStatus.active,
    "CANCELLED": ObjectStatus.archived,
}


def _parse_dt(value: str) -> date | datetime:
    """`due_at`/`start_at` are plain ISO strings in the object model -- a
    bare `YYYY-MM-DD` (10 chars) is a date-only field (task due dates,
    all-day markers); anything longer is a naive local datetime, matching
    how the rest of the app already parses these (see
    `core/utils/date_utils.py`, `core/recurrence.py` -- no TZID is ever
    attached, so datetimes here are deliberately floating, not UTC)."""
    if len(value) == 10:
        return date.fromisoformat(value)
    return datetime.fromisoformat(value)


def _dt_to_field(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _set_x(component: Todo | Event, name: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    if isinstance(value, (list, dict)):
        value = json.dumps(value)
    component.add(f"{X_PREFIX}{name}", str(value))


def _get_x(component: Todo | Event, name: str) -> str | None:
    v = component.get(f"{X_PREFIX}{name}")
    return str(v) if v is not None else None


def _get_x_json(component: Todo | Event, name: str) -> Any | None:
    raw = _get_x(component, name)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


# --------------------------------------------------------------------- #
# Task <-> VTODO
# --------------------------------------------------------------------- #


def to_vtodo(obj: Object, details: TaskDetails) -> Todo:
    todo = Todo()
    todo.add("UID", obj.id)
    todo.add("SUMMARY", obj.title)
    if obj.description:
        todo.add("DESCRIPTION", obj.description)
    if obj.start_at:
        todo.add("DTSTART", _parse_dt(obj.start_at))
    if obj.due_at:
        todo.add("DUE", _parse_dt(obj.due_at))
    todo.add("PRIORITY", _priority_to_ical(obj.priority))
    todo.add("STATUS", _STATUS_TO_VTODO.get(obj.status, "NEEDS-ACTION"))
    if obj.progress is not None:
        todo.add("PERCENT-COMPLETE", round(obj.progress * 100))
    if obj.tags:
        todo.add("CATEGORIES", list(obj.tags))
    if obj.parent_id:
        todo.add("RELATED-TO", obj.parent_id, parameters={"RELTYPE": "PARENT"})
    if details.recurrence:
        try:
            todo.add("RRULE", details.recurrence)
        except (ValueError, TypeError):
            _set_x(todo, "RECURRENCE-RAW", details.recurrence)
    if obj.created_at:
        try:
            todo.add("CREATED", datetime.fromisoformat(obj.created_at))
        except ValueError:
            pass
    if obj.updated_at:
        try:
            todo.add("LAST-MODIFIED", datetime.fromisoformat(obj.updated_at))
        except ValueError:
            pass
    todo.add("DTSTAMP", datetime.now(timezone.utc))

    # CommandCenter-only fields with no RFC 5545 slot.
    _set_x(todo, "STATUS", obj.status)
    _set_x(todo, "ICON", obj.icon)
    _set_x(todo, "COVER-PATH", obj.cover_path)
    _set_x(todo, "SORT-KEY", obj.sort_key)
    _set_x(todo, "PINNED", obj.pinned)
    _set_x(todo, "WORKSPACE-ID", obj.workspace_id)
    _set_x(todo, "CHECKLIST", details.checklist)
    _set_x(todo, "ESTIMATE-MIN", details.estimate_min)
    _set_x(todo, "TIME-SPENT-MIN", details.time_spent_min)
    _set_x(todo, "WAITING-ON", details.waiting_on)
    return todo


def vtodo_to_fields(todo: Todo) -> dict[str, Any]:
    """Everything recoverable from a VTODO, as a flat updates dict for
    `merge.merge_standard_fields_into`. Only keys actually present in the
    resource are included -- a foreign client that only touched SUMMARY
    produces a dict with just `title` (plus whatever DTSTAMP-adjacent
    bookkeeping fields are always present), never a full field set that
    would silently null out everything else on merge."""
    fields: dict[str, Any] = {}
    details: dict[str, Any] = {}

    if "SUMMARY" in todo:
        fields["title"] = str(todo.get("SUMMARY"))
    if "DESCRIPTION" in todo:
        fields["description"] = str(todo.get("DESCRIPTION"))
    if "DTSTART" in todo:
        fields["start_at"] = _dt_to_field(todo.get("DTSTART").dt)
    if "DUE" in todo:
        fields["due_at"] = _dt_to_field(todo.get("DUE").dt)
    if "PRIORITY" in todo:
        fields["priority"] = _priority_from_ical(int(todo.get("PRIORITY")))
    if "PERCENT-COMPLETE" in todo:
        fields["progress"] = int(todo.get("PERCENT-COMPLETE")) / 100
    if "CATEGORIES" in todo:
        cats = todo.get("CATEGORIES")
        cats_list = cats.cats if hasattr(cats, "cats") else cats
        fields["tags"] = [str(c) for c in cats_list]
    for rel in todo.get("RELATED-TO", []) if isinstance(todo.get("RELATED-TO"), list) else (
        [todo.get("RELATED-TO")] if "RELATED-TO" in todo else []
    ):
        params = getattr(rel, "params", {}) or {}
        if params.get("RELTYPE", "PARENT") == "PARENT":
            fields["parent_id"] = str(rel)
    if "RRULE" in todo:
        details["recurrence"] = todo.get("RRULE").to_ical().decode()

    x_status = _get_x(todo, "STATUS")
    fields["status"] = x_status if x_status else _VTODO_TO_STATUS.get(
        str(todo.get("STATUS", "")), None
    )
    if fields["status"] is None:
        fields.pop("status")

    x_icon = _get_x(todo, "ICON")
    if x_icon is not None:
        fields["icon"] = x_icon
    x_cover = _get_x(todo, "COVER-PATH")
    if x_cover is not None:
        fields["cover_path"] = x_cover
    x_sort = _get_x(todo, "SORT-KEY")
    if x_sort is not None:
        fields["sort_key"] = x_sort
    x_pinned = _get_x(todo, "PINNED")
    if x_pinned is not None:
        fields["pinned"] = x_pinned == "True"
    x_workspace = _get_x(todo, "WORKSPACE-ID")
    if x_workspace is not None:
        fields["workspace_id"] = x_workspace

    checklist = _get_x_json(todo, "CHECKLIST")
    if checklist is not None:
        details["checklist"] = checklist
    estimate = _get_x(todo, "ESTIMATE-MIN")
    if estimate is not None:
        details["estimate_min"] = int(estimate)
    time_spent = _get_x(todo, "TIME-SPENT-MIN")
    if time_spent is not None:
        details["time_spent_min"] = int(time_spent)
    waiting_on = _get_x(todo, "WAITING-ON")
    if waiting_on is not None:
        details["waiting_on"] = waiting_on

    if details:
        fields["details"] = details
    return fields


# --------------------------------------------------------------------- #
# Event <-> VEVENT
# --------------------------------------------------------------------- #


def to_vevent(obj: Object, details: EventDetails) -> Event:
    event = Event()
    event.add("UID", obj.id)
    event.add("SUMMARY", obj.title)
    if obj.description:
        event.add("DESCRIPTION", obj.description)

    if obj.start_at:
        start = _parse_dt(obj.start_at)
        if details.all_day and isinstance(start, datetime):
            start = start.date()
        event.add("DTSTART", start)
        if details.end_at:
            end = _parse_dt(details.end_at)
            if details.all_day and isinstance(end, datetime):
                end = end.date()
            event.add("DTEND", end)

    event.add("STATUS", _STATUS_TO_VEVENT.get(obj.status, "CONFIRMED"))
    if details.location:
        event.add("LOCATION", details.location)
    if details.meeting_url:
        event.add("URL", details.meeting_url)
    if obj.tags:
        event.add("CATEGORIES", list(obj.tags))
    if details.recurrence:
        try:
            event.add("RRULE", details.recurrence)
        except (ValueError, TypeError):
            _set_x(event, "RECURRENCE-RAW", details.recurrence)
    for minutes_before in details.reminders:
        alarm = Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", obj.title or "Reminder")
        alarm.add("TRIGGER", _minutes_to_trigger(minutes_before))
        event.add_component(alarm)
    if obj.created_at:
        try:
            event.add("CREATED", datetime.fromisoformat(obj.created_at))
        except ValueError:
            pass
    if obj.updated_at:
        try:
            event.add("LAST-MODIFIED", datetime.fromisoformat(obj.updated_at))
        except ValueError:
            pass
    event.add("DTSTAMP", datetime.now(timezone.utc))

    _set_x(event, "STATUS", obj.status)
    _set_x(event, "ICON", obj.icon)
    _set_x(event, "COVER-PATH", obj.cover_path)
    _set_x(event, "SORT-KEY", obj.sort_key)
    _set_x(event, "PINNED", obj.pinned)
    _set_x(event, "WORKSPACE-ID", obj.workspace_id)
    _set_x(event, "CALENDAR-ID", details.calendar_id)
    _set_x(event, "ALL-DAY", details.all_day)
    return event


def vevent_to_fields(event: Event) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    details: dict[str, Any] = {}

    if "SUMMARY" in event:
        fields["title"] = str(event.get("SUMMARY"))
    if "DESCRIPTION" in event:
        fields["description"] = str(event.get("DESCRIPTION"))
    if "DTSTART" in event:
        dtstart = event.get("DTSTART").dt
        fields["start_at"] = _dt_to_field(dtstart)
        details["all_day"] = not isinstance(dtstart, datetime)
    if "DTEND" in event:
        details["end_at"] = _dt_to_field(event.get("DTEND").dt)
    if "LOCATION" in event:
        details["location"] = str(event.get("LOCATION"))
    if "URL" in event:
        details["meeting_url"] = str(event.get("URL"))
    if "CATEGORIES" in event:
        cats = event.get("CATEGORIES")
        cats_list = cats.cats if hasattr(cats, "cats") else cats
        fields["tags"] = [str(c) for c in cats_list]
    if "RRULE" in event:
        details["recurrence"] = event.get("RRULE").to_ical().decode()

    reminders = []
    for alarm in event.walk("VALARM"):
        trigger = alarm.get("TRIGGER")
        if trigger is not None:
            reminders.append(_trigger_to_minutes(trigger.dt))
    if reminders:
        details["reminders"] = reminders

    x_status = _get_x(event, "STATUS")
    fields["status"] = x_status if x_status else _VEVENT_TO_STATUS.get(
        str(event.get("STATUS", "")), None
    )
    if fields["status"] is None:
        fields.pop("status")

    x_icon = _get_x(event, "ICON")
    if x_icon is not None:
        fields["icon"] = x_icon
    x_cover = _get_x(event, "COVER-PATH")
    if x_cover is not None:
        fields["cover_path"] = x_cover
    x_sort = _get_x(event, "SORT-KEY")
    if x_sort is not None:
        fields["sort_key"] = x_sort
    x_pinned = _get_x(event, "PINNED")
    if x_pinned is not None:
        fields["pinned"] = x_pinned == "True"
    x_workspace = _get_x(event, "WORKSPACE-ID")
    if x_workspace is not None:
        fields["workspace_id"] = x_workspace
    x_calendar_id = _get_x(event, "CALENDAR-ID")
    if x_calendar_id is not None:
        details["calendar_id"] = x_calendar_id
    x_all_day = _get_x(event, "ALL-DAY")
    if x_all_day is not None:
        details["all_day"] = x_all_day == "True"

    if details:
        fields["details"] = details
    return fields


def _minutes_to_trigger(minutes_before: int):
    from datetime import timedelta

    return timedelta(minutes=-abs(minutes_before))


def _trigger_to_minutes(trigger_value) -> int:
    from datetime import timedelta

    if isinstance(trigger_value, timedelta):
        return round(-trigger_value.total_seconds() / 60)
    # Absolute-time triggers (rare, VALUE=DATE-TIME) aren't expressible as
    # "minutes before" without the event's own start time in hand -- callers
    # only see this module's return value, so fall back to 0 rather than
    # raising; the caller still has the raw VALARM if it needs more.
    return 0
