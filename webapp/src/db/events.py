"""Events, holidays and recurrence exceptions.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from typing import Any

from .core import ENTITY_SYNC_FIELDS, MultipleProjectLabelsError, _row_columns, _row_to_dict
from .labels import _attach_tags, _attach_tags_bulk, list_labels_for_object, list_object_label_names, list_project_labels, set_object_labels


# --------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------- #

_EVENT_JSON_FIELDS = ("reminders_json", "exdates_json")


def upsert_event(
    conn: sqlite3.Connection, row: dict[str, Any], *, record_server_write: bool = True
) -> None:
    from .sync import record_server_sync_write
    data = dict(row)
    if record_server_write:
        previous = _row_columns(conn, "events", str(data.get("uid")), _EVENT_SYNC_COLUMNS)
    data["reminders_json"] = json.dumps(data.get("reminders") or [])
    data["exdates_json"] = json.dumps(data.get("exdates") or [])
    # NOT NULL DEFAULT 0 columns -- must coerce None -> 0 explicitly here;
    # an INSERT that names the column with an explicit NULL value doesn't
    # fall back to the column's own DEFAULT the way omitting it would.
    data["exclude_saturday"] = 1 if data.get("exclude_saturday") else 0
    data["exclude_sunday"] = 1 if data.get("exclude_sunday") else 0
    tags = data.pop("tags", None)
    if tags is not None:
        _reject_new_multiple_project_labels_on_event(conn, str(data.get("uid")), tags)
    data.pop("reminders", None)
    data.pop("exdates", None)
    cols = [
        "uid", "title", "description",
        "start_at", "end_at", "all_day", "location", "meeting_url", "status",
        "recurrence", "exdates_json", "reminders_json",
        # 1.6 ("Generalized recurrence and the non-working-day policy") --
        # see the `events` CREATE TABLE comment. NULL/0 (not present in
        # `row`) is the correct default for every event that isn't a
        # recurring one specifying a policy, same "missing key -> column
        # default" convention every other upsert_* in this file already
        # relies on via data.get(c).
        "holiday_calendar", "exclude_saturday", "exclude_sunday",
        "created_at", "updated_at",
    ]
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "event", data["uid"], tags)
    if record_server_write:
        record_server_sync_write(
            conn,
            "event",
            data["uid"],
            previous,
            _row_columns(conn, "events", data["uid"], _EVENT_SYNC_COLUMNS),
        )
    conn.commit()


def delete_event(
    conn: sqlite3.Connection, uid: str, *, record_server_write: bool = True
) -> None:
    from .sync import record_server_delete
    if record_server_write:
        record_server_delete(conn, "event", uid)
    conn.execute("DELETE FROM events WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'event' AND object_id = ?", (uid,))
    # Relations are graph links, not ownership -- the task on the other end
    # stays, only this event's rows go (an event always owns the `event_uid`
    # side of an event_task_relations row).
    conn.execute("DELETE FROM event_task_relations WHERE event_uid = ?", (uid,))
    # 1.6 ("Manual recurrence exceptions") -- a per-occurrence override is
    # owned by its master event; deleting the master (the whole recurring
    # series) makes every override for it meaningless, same ownership
    # relationship as event_task_relations above.
    conn.execute("DELETE FROM event_occurrence_overrides WHERE master_uid = ?", (uid,))
    conn.commit()


def get_event(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM events WHERE uid = ?", (uid,)).fetchone()
    return _attach_tags(conn, "event", _row_to_dict(row, _EVENT_JSON_FIELDS)) if row else None


def list_events(
    conn: sqlite3.Connection,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Real bug fix (found 2026-08-14 while building 1.6's manual
    recurrence exceptions, via a router test that moved an occurrence into
    a later week and it silently never rendered): a *recurring* row's own
    literal start_at/end_at only anchor its first occurrence -- the date
    range filter below used to exclude the row entirely once `start`/`end`
    fell far enough past that literal end_at, even though its RRULE would
    still generate real occurrences inside the window. Nothing caught this
    before because no existing test seeded a recurring event and then
    queried a week more than ~one occurrence-length past its own creation
    date. Fix: a recurring row (recurrence IS NOT NULL) is always a
    candidate regardless of its own literal bounds -- `recurrence_expand.
    expand_events` (which every caller of this function already runs
    recurring rows through) is what actually decides whether it produces
    any occurrence in the window, via the real RRULE/UNTIL/COUNT."""
    query = "SELECT * FROM events"
    params: list[str] = []
    bounds_clauses = []
    if start:
        bounds_clauses.append("(end_at IS NULL OR end_at >= ?)")
        params.append(start)
    if end:
        bounds_clauses.append("start_at <= ?")
        params.append(end)
    if bounds_clauses:
        query += " WHERE (recurrence IS NOT NULL OR (" + " AND ".join(bounds_clauses) + "))"
    query += " ORDER BY start_at ASC"
    rows = conn.execute(query, params).fetchall()
    return _attach_tags_bulk(conn, "event", [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows])


# --------------------------------------------------------------------- #
# Manual recurrence exceptions (1.6, "Manual recurrence exceptions") --
# see event_occurrence_overrides' own CREATE TABLE comment for the model.
# --------------------------------------------------------------------- #


def _occurrence_override_uid(master_uid: str, occurrence_date: str) -> str:
    """Deterministic key for the one override a given (master, original
    occurrence) pair can have -- lets upsert_event_occurrence_override use
    the same ON CONFLICT(uid) idiom every other upsert_* in this file uses,
    instead of a separate find-then-update step."""
    return f"{master_uid}::{occurrence_date}"


def upsert_event_occurrence_override(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Cancels or moves/modifies one occurrence of a recurring event
    without touching its recurrence rule. `row`: {master_uid,
    occurrence_date, cancelled, start_at, end_at, title, location,
    created_at, updated_at} -- cancelled=True and a moved start_at are
    mutually exclusive in practice (routers/calendar.py only ever sets
    one), but nothing here enforces that; recurrence_expand.py only reads
    start_at when cancelled is falsy. Returns the override's own uid."""
    uid = _occurrence_override_uid(row["master_uid"], row["occurrence_date"])
    conn.execute(
        "INSERT INTO event_occurrence_overrides "
        "(uid, master_uid, occurrence_date, cancelled, start_at, end_at, title, location, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET cancelled=excluded.cancelled, start_at=excluded.start_at, "
        "end_at=excluded.end_at, title=excluded.title, location=excluded.location, updated_at=excluded.updated_at",
        (
            uid, row["master_uid"], row["occurrence_date"],
            1 if row.get("cancelled") else 0,
            row.get("start_at"), row.get("end_at"), row.get("title"), row.get("location"),
            row.get("created_at"), row.get("updated_at"),
        ),
    )
    conn.commit()
    return uid


def delete_event_occurrence_override(conn: sqlite3.Connection, master_uid: str, occurrence_date: str) -> None:
    """Restores one occurrence back to whatever the recurrence rule alone
    would generate -- "undo" for a cancel or a move."""
    conn.execute(
        "DELETE FROM event_occurrence_overrides WHERE uid = ?",
        (_occurrence_override_uid(master_uid, occurrence_date),),
    )
    conn.commit()


def list_event_occurrence_overrides(conn: sqlite3.Connection, master_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM event_occurrence_overrides WHERE master_uid = ? ORDER BY occurrence_date",
        (master_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_event_occurrence_overrides_by_master(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """{master_uid: [override row, ...]} -- the shape
    `recurrence_expand.expand_events`'s `overrides_by_master` parameter
    expects. Built once per request, same "routers compute, pure logic
    just reads what it's given" layering `list_holidays_by_calendar`
    already follows."""
    by_master: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute("SELECT * FROM event_occurrence_overrides ORDER BY occurrence_date").fetchall()
    for row in rows:
        by_master.setdefault(row["master_uid"], []).append(dict(row))
    return by_master


def all_event_uids(conn: sqlite3.Connection) -> set[str]:
    return {r["uid"] for r in conn.execute("SELECT uid FROM events").fetchall()}


def _reject_new_multiple_project_labels_on_event(conn: sqlite3.Connection, uid: str, tags: list[str]) -> None:
    """One project per event (project-picker slice, 2026-09-25, Peter: "one
    project per data model"). Same rule as tasks, with one difference: an
    event that already carries the same set of project labels is let
    through. Events are re-saved whole by non-form paths (the week grid's
    drag-to-reschedule, work-session time edits) and could already hold
    two projects from before this rule existed. Rejecting those would break
    an unrelated edit rather than protect anything, so only a *new*
    combination is refused."""
    project_names = {cfg["name"] for cfg in list_project_labels(conn)}
    selected = {t for t in tags if t in project_names}
    if len(selected) <= 1:
        return
    current = set(list_labels_for_object(conn, "event", uid)) & project_names
    if selected == current:
        return
    raise MultipleProjectLabelsError(sorted(selected, key=str.lower), "event")


def list_events_sharing_labels(conn: sqlite3.Connection, label_names: list[str]) -> list[dict[str, Any]]:
    """Every event carrying at least one of `label_names` -- the "link an
    existing event" pool for a task's Relations card."""
    labels = [n for n in (label_names or []) if n]
    if not labels:
        return []
    placeholders = ", ".join("?" for _ in labels)
    rows = conn.execute(
        f"SELECT events.* FROM events "
        f"WHERE events.uid IN (SELECT DISTINCT object_id FROM object_labels "
        f"  WHERE object_type = 'event' AND label_name IN ({placeholders})) "
        f"ORDER BY events.start_at ASC",
        labels,
    ).fetchall()
    return _attach_tags_bulk(conn, "event", [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows])


def _search_events(
    conn: sqlite3.Connection,
    q: str | None,
    labels: list[str] | None,
    event_start: str | None,
    event_end: str | None,
    excluded: set[str],
    exclude_past: bool = False,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM events"
    params: list[str] = []
    clauses: list[str] = []

    if q:
        like = f"%{q}%"
        clauses.append(
            "(title LIKE ? OR description LIKE ? OR uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'event' AND label_name LIKE ?))"
        )
        params.extend([like, like, like])
    if event_start:
        clauses.append("end_at IS NULL OR end_at >= ?")
        params.append(event_start)
    if event_end:
        # Same end-of-day normalization every calendar view applies when
        # passing a bare date range to list_events (e.g. routers/calendar.py
        # appends "T23:59:59"), so "on this day" includes that day's events.
        clauses.append("start_at <= ?")
        params.append(event_end + "T23:59:59" if "T" not in event_end else event_end)
    if labels:
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(
            f"uid IN (SELECT DISTINCT object_id FROM object_labels WHERE object_type = 'event' AND label_name IN ({placeholders}))"
        )
        params.extend(labels)
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        clauses.append(f"uid NOT IN ({placeholders})")
        params.extend(excluded)
    if exclude_past:
        # Whole-day cutoff (date(start_at) not start_at itself) -- an event
        # still in progress or later today stays; only a start date before
        # today is "past" here, matching the client's own dateBucket split
        # (diffDays < 0) so this server-side drop and the palette's Overdue/
        # Past/This week grouping agree on what "past" means.
        clauses.append("date(start_at) >= date(?)")
        params.append(date.today().isoformat())

    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY start_at ASC"
    rows = conn.execute(query, params).fetchall()
    dicts = _attach_tags_bulk(conn, "event", [_row_to_dict(r, _EVENT_JSON_FIELDS) for r in rows])
    out: list[dict[str, Any]] = []
    for d in dicts:
        start = d.get("start_at") or ""
        subtitle = f"{start[:10]} {start[11:16]}" if start else "No start time"
        out.append(
            {
                "type": "event",
                "uid": d["uid"],
                "title": d["title"],
                "subtitle": subtitle,
                "tags": d["tags"],
                "entity": d,
            }
        )
    return out


def _birthday_event_uid(contact_uid: str) -> str:
    return f"birthday::{contact_uid}"


def list_event_label_names(conn: sqlite3.Connection) -> list[str]:
    """Distinct labels across all events -- Phase 9b toolbar rework's new
    Calendar label filter (Month/Week/Day/Agenda all share this)."""
    return list_object_label_names(conn, "event")


_HOLIDAY_YEARLESS_RE = re.compile(r"^--\d{2}-\d{2}$")


def is_year_agnostic_holiday_date(value: str | None) -> bool:
    """True for a "--MM-DD" holiday date_from/date_to -- same vCard-derived
    year-less convention Contacts' Birthday field already uses (see
    parse_contact_birthday/_BIRTHDAY_YEARLESS_RE above), reused here rather
    than adding a new column: `schedule_holidays.date_from`/`date_to` stay
    plain TEXT, just holding an alternate string shape for a holiday that
    "repeats every year" (audit-fixes-2.1.md, e.g. a fixed-date national/
    religious holiday) instead of one dated range that only ever applies
    once."""
    return bool(_HOLIDAY_YEARLESS_RE.match((value or "").strip()))


def parse_holiday_date(value: str, year_agnostic: bool) -> str:
    """Normalizes one holiday date_from/date_to form field into its stored
    shape. The shared date picker (_datetime_picker.html) has no
    year-agnostic mode of its own -- it always submits a real "YYYY-MM-DD"
    -- so `year_agnostic` (the modal's "Repeats every year" checkbox) is
    what decides whether the year gets kept or discarded here; an
    already-yearless "--MM-DD" value round-tripping back in (e.g. the edit
    form re-submitting a value unchanged) is accepted either way. Raises
    ValueError on anything that isn't a real calendar date (invalid
    month/day, non-leap Feb 29, ...), same "server validates, form is just
    a hint" convention as parse_contact_birthday."""
    v = (value or "").strip()
    if is_year_agnostic_holiday_date(v):
        if not year_agnostic:
            # Only reachable via a hand-crafted request -- the shared date
            # picker never submits a "--MM-DD" value itself (see
            # holiday_date_picker_value), so the UI can't produce this.
            raise ValueError(f"Holiday date must be a full YYYY-MM-DD date, got '{value}'")
        month, day = v[2:4], v[5:7]
    else:
        d = date.fromisoformat(v)  # raises ValueError for a genuinely bad value
        if not year_agnostic:
            return v
        month, day = f"{d.month:02d}", f"{d.day:02d}"
    # 2000 is a leap year -- same Feb 29 allowance parse_contact_birthday
    # uses, so "--02-29" always validates regardless of which years the
    # holiday actually recurs through.
    datetime.strptime(f"2000-{month}-{day}", "%Y-%m-%d")
    return f"--{month}-{day}"


def holiday_date_picker_value(value: str | None) -> str:
    """A real "YYYY-MM-DD" for feeding a stored holiday date into the
    shared calendar date picker, which -- like `parse_holiday_date` above --
    has no year-agnostic mode. A "--MM-DD" value gets a fixed placeholder
    year (2000, leap-safe) purely so the picker has something to render/
    highlight while editing; nothing about which year is shown is saved
    back -- the "Repeats every year" checkbox is what makes the year get
    discarded again on save."""
    v = (value or "").strip()
    if is_year_agnostic_holiday_date(v):
        return f"2000-{v[2:]}"
    return v


def format_holiday_date(value: str | None) -> str:
    """Human display for a year-agnostic holiday date -- "25 Dec" (no year
    to show). Full "YYYY-MM-DD" holiday dates keep using the Holidays
    table's own `relative_date` filter (Today/Tmw/"5 Sep" shorthand);
    this is only the fallback for the one shape that filter can't parse."""
    v = (value or "").strip()
    if is_year_agnostic_holiday_date(v):
        month, day = int(v[2:4]), int(v[5:7])
        return f"{day} {date(2000, month, 1).strftime('%b')}"
    return v


def upsert_holiday(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO schedule_holidays (uid, calendar_name, label, date_from, date_to) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET calendar_name=excluded.calendar_name, label=excluded.label, "
        "date_from=excluded.date_from, date_to=excluded.date_to",
        (row["uid"], row.get("calendar_name") or "Default", row.get("label", ""), row["date_from"], row["date_to"]),
    )
    conn.commit()


def get_holiday(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM schedule_holidays WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def delete_holiday(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM schedule_holidays WHERE uid = ?", (uid,))
    conn.commit()


def list_holidays(conn: sqlite3.Connection, calendar_name: str | None = None) -> list[dict[str, Any]]:
    if calendar_name:
        rows = conn.execute(
            "SELECT * FROM schedule_holidays WHERE calendar_name = ? ORDER BY date_from", (calendar_name,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM schedule_holidays ORDER BY calendar_name COLLATE NOCASE, date_from").fetchall()
    return [dict(r) for r in rows]


def list_holiday_calendar_names(conn: sqlite3.Connection) -> list[str]:
    """Every distinct named holiday calendar in use -- there's no separate
    `holiday_calendars` table (see schedule_holidays' own CREATE TABLE
    comment), a calendar is just a name some holiday rows share. Powers the
    recurrence editor's "Holiday calendar" dropdown and the manage UI's own
    list of existing calendars."""
    rows = conn.execute(
        "SELECT DISTINCT calendar_name FROM schedule_holidays ORDER BY calendar_name COLLATE NOCASE"
    ).fetchall()
    return [r["calendar_name"] for r in rows]


def list_holidays_by_calendar(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """{calendar_name: [holiday rows]} -- the shape
    `recurrence_expand.expand_events`'s `holiday_calendars` parameter
    expects. Built once per request (never per-event), same "routers
    compute, pure logic just reads what it's given" layering every other
    feature in this app follows."""
    by_calendar: dict[str, list[dict[str, Any]]] = {}
    for row in list_holidays(conn):
        by_calendar.setdefault(row["calendar_name"], []).append(row)
    return by_calendar
_EVENT_SYNC_COLUMNS = sorted(ENTITY_SYNC_FIELDS["event"])
