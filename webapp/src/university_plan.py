"""The University module's domain layer: a semester described in university terms, held as ordinary shelves, tags, events, tasks and contacts.

The semester is a shelf (adopted by name when it exists), a discipline is a tag under it, a timetable slot is one repeating event
series (the room is its location, the teacher a contact), an exam is a task plus an event on the task and event link, a reading is a
task, and a teacher is a contact carrying the discipline tag. Only what has no home elsewhere is stored here: the syllabus and its link
to a class, and which series, task or event belongs to the module. Every change that touches many rows has a `plan_*` function that
returns what would happen and a matching `save_*`/`apply_*` function that does it in one transaction.
Feature notes: curodav-notes/documentation/features/university-module.md.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from . import clock, db, event_series, study_lists, tags

MODULE_KEY = "university"
PAGE_TYPE = "study"
SLOT_KINDS = {"lecture": "Lecture", "seminar": "Seminar", "lab": "Lab", "other": "Class"}
PARITY = ("all", "odd", "even")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class PlanError(ValueError):
    """The input cannot be turned into a plan; the message is plain words for a toast."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date(value: str | None, field: str, required: bool = False) -> date | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise PlanError(f"{field} is required")
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise PlanError(f"{field} is not a date") from None


def _clock(value: str | None, field: str) -> time:
    try:
        return time.fromisoformat((value or "").strip())
    except ValueError:
        raise PlanError(f"{field} is not a time") from None


def _tag_item(conn: sqlite3.Connection, kind: str, uid: str, tag: str, on: bool = True) -> None:
    """Adds or removes a discipline tag on an item, the way the edit forms do: the tag link and the label (shelf) link."""
    current = tags.tags_for_object(conn, kind, uid)
    wanted = [t for t in current if t.lower() != tag.lower()] + ([tag] if on else [])
    tags.record(conn, kind, uid, wanted)
    if kind in ("task", "event", "contact"):
        db.set_object_labels(conn, kind, uid, tags.labels_of(conn, wanted, keep_unknown=True))


def _labels(conn: sqlite3.Connection, tag: str) -> list[str]:
    return tags.labels_of(conn, [tag], keep_unknown=True)


@contextmanager
def _owner():
    """The module is the one allowed writer of its shelf and tags."""
    with tags.managed_writes(MODULE_KEY):
        yield


# ---------------------------------------------------------------- semester

def current_semester(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM university_semesters ORDER BY created_at DESC, uid LIMIT 1").fetchone()
    return dict(row) if row else None


def get_semester(conn: sqlite3.Connection, uid: str | None) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM university_semesters WHERE uid = ?", (uid,)).fetchone() if uid else None
    return dict(row) if row else None


def plan_semester(conn: sqlite3.Connection, shelf_name: str) -> dict[str, Any]:
    """What saving would do to the shelf: adopt one that exists or create it, and which tags become disciplines."""
    existing = db.get_label_config(conn, shelf_name) if shelf_name.strip() else None
    return {"shelf": shelf_name.strip(), "adopts": bool(existing), "tags": [t["name"] for t in tags.tags_of_label(conn, shelf_name)] if existing else []}


def save_semester(conn: sqlite3.Connection, *, uid: str | None, name: str, shelf_name: str, start_date: str, end_date: str,
                  class_end_date: str, holiday_calendar: str = "") -> str:
    name, shelf_name = name.strip(), (shelf_name.strip() or name.strip())
    if not name:
        raise PlanError("The semester needs a name")
    start, end, class_end = _date(start_date, "Start date"), _date(end_date, "End date"), _date(class_end_date, "Class end date")
    if start and end and end < start:
        raise PlanError("The end date is before the start date")
    if start and class_end and class_end < start:
        raise PlanError("The class end date is before the start date")
    existing = get_semester(conn, uid)
    if existing:
        shelf_name = existing["shelf_name"]
    elif conn.execute("SELECT 1 FROM university_semesters WHERE shelf_name = ? COLLATE NOCASE", (shelf_name,)).fetchone():
        raise PlanError(f"{shelf_name} already holds a semester")
    with _owner():
        if db.get_label_config(conn, shelf_name) is None:
            db.upsert_label_config(conn, {"name": shelf_name, "color": "blue", "icon": "graduation-cap", "sidebar_pin": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": shelf_name, "page_type": PAGE_TYPE, "managed_by": MODULE_KEY})
    uid = existing["uid"] if existing else str(uuid.uuid4())
    conn.execute(
        "INSERT INTO university_semesters (uid, shelf_name, name, start_date, end_date, class_end_date, holiday_calendar, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET name=excluded.name, start_date=excluded.start_date, "
        "end_date=excluded.end_date, class_end_date=excluded.class_end_date, holiday_calendar=excluded.holiday_calendar",
        (uid, shelf_name, name, start.isoformat() if start else None, end.isoformat() if end else None,
         class_end.isoformat() if class_end else None, holiday_calendar.strip() or None, existing["created_at"] if existing else _now()),
    )
    conn.commit()
    if existing and (existing.get("class_end_date") or "") != (class_end.isoformat() if class_end else ""):
        if class_end:
            set_class_end(conn, uid, class_end)
    return uid


# ---------------------------------------------------------------- disciplines

def _teacher_uids(conn: sqlite3.Connection, tag: str) -> list[str]:
    rows = conn.execute("SELECT object_id FROM object_tags WHERE object_type = 'contact' AND tag_name = ? COLLATE NOCASE", (tag,)).fetchall()
    return [r["object_id"] for r in rows]


def teachers(conn: sqlite3.Connection, tag: str) -> list[dict[str, str]]:
    uids = _teacher_uids(conn, tag)
    return [{"uid": u, "name": (db.get_contact(conn, u) or {}).get("full_name") or ""} for u in uids]


def disciplines(conn: sqlite3.Connection, semester: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in tags.tags_of_label(conn, semester["shelf_name"]):
        out.append({**t, "teachers": teachers(conn, t["name"]), **count_items(conn, semester["uid"], t["name"])})
    return out


def count_items(conn: sqlite3.Connection, semester_uid: str, tag: str) -> dict[str, int]:
    def n(sql: str) -> int:
        return conn.execute(sql, (semester_uid, tag)).fetchone()[0]
    return {"slots": n("SELECT COUNT(*) FROM university_slots WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"),
            "exams": n("SELECT COUNT(*) FROM university_exams WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"),
            "readings": n("SELECT COUNT(*) FROM university_readings WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"),
            "topics": n("SELECT COUNT(*) FROM university_topics WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE")}


def _split_names(text: str) -> list[str]:
    seen: dict[str, str] = {}
    for part in (text or "").replace(",", "\n").splitlines():
        part = part.strip()
        if part:
            seen.setdefault(part.lower(), part)
    return list(seen.values())


def save_discipline(conn: sqlite3.Connection, semester: dict[str, Any], *, old: str, name: str, color: str, icon: str,
                    teacher_names: str, colors) -> str:
    """Creates a discipline (a tag on the semester's shelf) or restyles and renames one; teachers are contacts that carry its tag."""
    name = name.strip()
    if not name:
        raise PlanError("A discipline needs a name")
    row = {"old": old, "name": name, "color": color or "gray", "icon": icon, "delete": False}
    shelf = semester["shelf_name"]
    problem = tags.validate_rows(conn, shelf, [row])
    if problem and not (not old and not tags.tags_of_label(conn, shelf) and name.lower() == shelf.lower()):
        raise PlanError(problem)
    with _owner():
        tags.apply_rows(conn, shelf, [row], colors)
    if old and old.lower() != name.lower():
        for table in ("university_topics",):
            conn.execute(f"UPDATE {table} SET discipline_tag = ? WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (name, semester["uid"], old))
        for table in ("university_slots", "university_exams", "university_readings"):
            conn.execute(f"UPDATE {table} SET discipline_tag = ? WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (name, semester["uid"], old))
        conn.commit()
        _retitle_classes(conn, semester["uid"], name)
    wanted = db.resolve_contact_entries(conn, _split_names(teacher_names))
    for uid in _teacher_uids(conn, name):
        if uid not in wanted:
            _tag_item(conn, "contact", uid, name, False)
    for uid in wanted:
        _tag_item(conn, "contact", uid, name)
    return name


def removal_blockers(conn: sqlite3.Connection, semester: dict[str, Any], tag: str) -> str | None:
    counts = count_items(conn, semester["uid"], tag)
    parts = [f"{counts[k]} {label}" for k, label in (("slots", "timetable slots"), ("exams", "exams"), ("readings", "readings")) if counts[k]]
    if parts:
        return f"{tag} still has {', '.join(parts)}. Remove them first."
    return None


def remove_discipline(conn: sqlite3.Connection, semester: dict[str, Any], tag: str) -> None:
    problem = removal_blockers(conn, semester, tag)
    if problem:
        raise PlanError(problem)
    for uid in _teacher_uids(conn, tag):
        _tag_item(conn, "contact", uid, tag, False)
    conn.execute("DELETE FROM university_topics WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (semester["uid"], tag))
    conn.commit()
    with _owner():
        tags.apply_rows(conn, semester["shelf_name"], [{"old": tag, "name": "", "color": "", "icon": "", "delete": True}], set())


# ---------------------------------------------------------------- timetable

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def first_class_date(start: date, weekday: int, weeks: str) -> date:
    """The first day on or after `start` that falls on `weekday` in a week of the wanted parity; week 1 is the week of `start`."""
    d = start
    for _ in range(21):
        index = (_monday(d) - _monday(start)).days // 7
        if d.weekday() == weekday and (weeks == "all" or (index % 2 == 0) == (weeks == "odd")):
            return d
        d += timedelta(days=1)
    raise PlanError("No class day was found")


def slot_rule(weekday: int, weeks: str, until: date) -> str:
    return f"FREQ=WEEKLY;INTERVAL={1 if weeks == 'all' else 2};BYDAY={_BYDAY[weekday]};UNTIL={until.isoformat()}"


def _class_title(discipline: str, kind: str) -> str:
    return f"{discipline} {SLOT_KINDS.get(kind, 'Class')}".strip()


def _validate_slot(slot: dict[str, Any]) -> dict[str, Any]:
    try:
        weekday = int(slot.get("weekday"))
    except (TypeError, ValueError):
        raise PlanError("Pick a weekday") from None
    if not 0 <= weekday <= 6:
        raise PlanError("Pick a weekday")
    start, end = _clock(slot.get("start"), "Start time"), _clock(slot.get("end"), "End time")
    if end <= start:
        raise PlanError("The class ends before it starts")
    weeks = slot.get("weeks") or "all"
    if weeks not in PARITY:
        raise PlanError("Weeks must be every, odd or even")
    kind = slot.get("kind") or "lecture"
    return {"weekday": weekday, "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"), "weeks": weeks,
            "kind": kind if kind in SLOT_KINDS else "other", "room": (slot.get("room") or "").strip(),
            "teachers": [t for t in (slot.get("teachers") or []) if t]}


def _class_end(semester: dict[str, Any]) -> date:
    end = _date(semester.get("class_end_date") or semester.get("end_date"), "Class end date")
    if not end:
        raise PlanError("Set the class end date of the semester first")
    return end


def _planned_dates(conn: sqlite3.Connection, semester: dict[str, Any], slot: dict[str, Any]) -> list[date]:
    start = _date(semester.get("start_date"), "Semester start date", True)
    until = _class_end(semester)
    first = first_class_date(start, slot["weekday"], slot["weeks"])
    step = 7 if slot["weeks"] == "all" else 14
    calendars = db.list_holidays_by_calendar(conn)
    policy = {"holiday_calendar": semester.get("holiday_calendar"), "exclude_saturday": 0, "exclude_sunday": 0}
    from . import recurrence_expand
    dates, d = [], first
    while d <= until:
        if not recurrence_expand.is_excluded_by_policy(d, policy, calendars):
            dates.append(d)
        d += timedelta(days=step)
    return dates


def series_members(conn: sqlite3.Connection, series_uid: str) -> list[dict[str, Any]]:
    return event_series.members(conn, series_uid)


def list_slots(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None) -> list[dict[str, Any]]:
    """The timetable, read from the event series themselves."""
    sql = "SELECT * FROM university_slots WHERE semester_uid = ?"
    args: list[Any] = [semester_uid]
    if discipline:
        sql += " AND discipline_tag = ? COLLATE NOCASE"
        args.append(discipline)
    out = []
    for row in conn.execute(sql, args).fetchall():
        members = series_members(conn, row["series_uid"])
        series = event_series.get_series(conn, row["series_uid"])
        if not members or not series:
            continue
        first = members[0]
        parts = event_series.parts_of(series["rule"])
        out.append({"series_uid": row["series_uid"], "discipline": row["discipline_tag"], "kind": row["kind"], "weeks": row["weeks"],
                    "weekday": _BYDAY.index(parts.get("BYDAY", "MO").split(",")[0]), "start": first["start_at"][11:16], "end": (first.get("end_at") or "")[11:16],
                    "room": first.get("location") or "", "count": len(members), "first": first["start_at"][:10], "last": members[-1]["start_at"][:10],
                    "teachers": [c["uid"] for c in db.list_object_contacts(conn, "event", first["uid"])]})
    out.sort(key=lambda s: (s["weekday"], s["start"]))
    return out


def _slot_by_series(conn: sqlite3.Connection, semester_uid: str, series_uid: str) -> dict[str, Any] | None:
    return next((s for s in list_slots(conn, semester_uid) if s["series_uid"] == series_uid), None)


def plan_slot(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, slot: dict[str, Any], series_uid: str | None = None) -> dict[str, Any]:
    """What saving a slot creates, and the typed descriptions a rebuild would lose."""
    slot = _validate_slot(slot)
    dates = _planned_dates(conn, semester, slot)
    lost: list[str] = []
    rebuilds = True
    if series_uid:
        old = _slot_by_series(conn, semester["uid"], series_uid)
        if old and old["weekday"] == slot["weekday"] and old["weeks"] == slot["weeks"]:
            rebuilds = False
        else:
            keep = {d.isoformat() for d in dates}
            lost = [m["start_at"][:10] for m in series_members(conn, series_uid) if (m.get("description") or "").strip() and m["start_at"][:10] not in keep]
    return {"classes": len(dates), "first": dates[0].isoformat() if dates else "", "last": dates[-1].isoformat() if dates else "",
            "rebuilds": rebuilds, "lost": lost, "slot": slot}


def save_slot(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, slot: dict[str, Any], series_uid: str | None = None) -> str:
    """Creates a slot's series, or updates the existing one (in place when only times, room, kind or teachers changed)."""
    plan = plan_slot(conn, semester, discipline, slot, series_uid)
    slot = plan["slot"]
    if not plan["classes"]:
        raise PlanError("That timetable produces no classes between the semester dates")
    title = _class_title(discipline, slot["kind"])
    old_members = series_members(conn, series_uid) if series_uid else []
    if series_uid and not plan["rebuilds"]:
        for m in old_members:
            day = m["start_at"][:10]
            db.upsert_event(conn, {**m, "title": title, "location": slot["room"], "start_at": f"{day}T{slot['start']}", "end_at": f"{day}T{slot['end']}", "updated_at": _now()})
            db.set_object_contacts(conn, "event", m["uid"], slot["teachers"])
        conn.execute("UPDATE university_slots SET kind = ? WHERE series_uid = ?", (slot["kind"], series_uid))
        conn.commit()
        return series_uid
    kept = {m["start_at"][:10]: m.get("description") or "" for m in old_members}
    if series_uid:
        event_series.delete_scope(conn, old_members[0]["uid"], "all")
        conn.execute("DELETE FROM university_slots WHERE series_uid = ?", (series_uid,))
    dates = _planned_dates(conn, semester, slot)
    first = dates[0]
    until = _class_end(semester)
    now = _now()
    row = {"uid": str(uuid.uuid4()), "title": title, "description": "", "start_at": f"{first.isoformat()}T{slot['start']}",
           "end_at": f"{first.isoformat()}T{slot['end']}", "all_day": 0, "location": slot["room"], "status": "active", "tags": _labels(conn, discipline),
           "holiday_calendar": semester.get("holiday_calendar"), "created_at": now, "updated_at": now}
    db.upsert_event(conn, row)
    _tag_item(conn, "event", row["uid"], discipline)
    event_series.create_series(conn, row, slot_rule(slot["weekday"], slot["weeks"], until), contacts=slot["teachers"])
    new_series = (db.get_event(conn, row["uid"]) or {}).get("series_uid")
    if not new_series:
        raise PlanError("The classes could not be created")
    conn.execute("INSERT INTO university_slots (series_uid, semester_uid, discipline_tag, kind, weeks) VALUES (?, ?, ?, ?, ?)",
                 (new_series, semester["uid"], discipline, slot["kind"], slot["weeks"]))
    conn.commit()
    for m in series_members(conn, new_series):
        text = kept.get(m["start_at"][:10])
        if text:
            db.upsert_event(conn, {**m, "description": text})
    return new_series


def delete_slot(conn: sqlite3.Connection, semester_uid: str, series_uid: str) -> int:
    members = series_members(conn, series_uid)
    if not members:
        conn.execute("DELETE FROM university_slots WHERE series_uid = ?", (series_uid,))
        conn.commit()
        return 0
    removed = event_series.delete_scope(conn, members[0]["uid"], "all")
    conn.execute("DELETE FROM university_slots WHERE series_uid = ?", (series_uid,))
    conn.commit()
    return removed


def _retitle_classes(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> None:
    for row in conn.execute("SELECT series_uid, kind FROM university_slots WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (semester_uid, discipline)).fetchall():
        for m in series_members(conn, row["series_uid"]):
            db.upsert_event(conn, {**m, "title": _class_title(discipline, row["kind"])})


def plan_class_end(conn: sqlite3.Connection, semester_uid: str, new_end: date) -> dict[str, int]:
    """What moving the class end date does to every class series: classes removed (and how many carry typed text) and classes added."""
    removed = texts = added = 0
    for slot in list_slots(conn, semester_uid):
        for m in series_members(conn, slot["series_uid"]):
            if m["start_at"][:10] > new_end.isoformat():
                removed += 1
                texts += 1 if (m.get("description") or "").strip() else 0
        if date.fromisoformat(slot["last"]) < new_end:
            semester = get_semester(conn, semester_uid) or {}
            candidate = dict(semester, class_end_date=new_end.isoformat())
            have = {m["start_at"][:10] for m in series_members(conn, slot["series_uid"])}
            added += len([d for d in _planned_dates(conn, candidate, _validate_slot(slot)) if d.isoformat() not in have and d.isoformat() > slot["last"]])
    return {"removed": removed, "removed_with_text": texts, "added": added}


def set_class_end(conn: sqlite3.Connection, semester_uid: str, new_end: date) -> dict[str, int]:
    """Shortens or extends every class series of the semester to `new_end`; exams, tasks and one-off events are never touched."""
    summary = plan_class_end(conn, semester_uid, new_end)
    semester = get_semester(conn, semester_uid)
    for slot in list_slots(conn, semester_uid):
        series = event_series.get_series(conn, slot["series_uid"])
        members = series_members(conn, slot["series_uid"])
        for m in members:
            if m["start_at"][:10] > new_end.isoformat():
                db.delete_event(conn, m["uid"])
        parts = event_series.parts_of(series["rule"])
        parts["UNTIL"] = new_end.isoformat()
        series["rule"] = event_series.join_parts(parts)
        remaining = series_members(conn, slot["series_uid"])
        if remaining and date.fromisoformat(slot["last"]) < new_end:
            template = dict(remaining[-1], description="")
            limit = datetime.combine(new_end, time.max).replace(microsecond=0)
            event_series._generate(conn, series, template, None, event_series._minute(remaining[-1]["start_at"]), limit)
            series["extended_until"] = max(series.get("extended_until") or "", new_end.isoformat())
        event_series._save_series(conn, series)
    conn.execute("UPDATE university_semesters SET class_end_date = ? WHERE uid = ?", (new_end.isoformat(), semester_uid))
    conn.commit()
    del semester
    return summary


# ---------------------------------------------------------------- syllabus

def topic_text(number: int, title: str) -> str:
    return f"{number}. {title}"


def list_topics(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM university_topics WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE ORDER BY number, title",
                        (semester_uid, discipline)).fetchall()
    out = []
    for r in rows:
        events = [x["event_uid"] for x in conn.execute("SELECT event_uid FROM university_topic_classes WHERE topic_uid = ?", (r["uid"],))]
        out.append({**dict(r), "events": events})
    return out


def syllabus_text(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> str:
    return "\n".join(f"{t['number']}. {t['title']}{' ' + '*' * t['importance'] if t['importance'] else ''}" for t in list_topics(conn, semester_uid, discipline))


def save_syllabus(conn: sqlite3.Connection, semester_uid: str, discipline: str, text: str) -> int:
    """Replaces the syllabus with the pasted list; a topic that keeps its number and title keeps its uid and its classes."""
    themes = study_lists.parse_themes(text)
    old = {(t["number"], t["title"]): t["uid"] for t in list_topics(conn, semester_uid, discipline)}
    keep: set[str] = set()
    for t in themes:
        uid = old.get((t.number, t.title)) or str(uuid.uuid4())
        keep.add(uid)
        conn.execute("INSERT INTO university_topics (uid, semester_uid, discipline_tag, number, title, kind, importance) VALUES (?, ?, ?, ?, ?, 'lecture', ?) "
                     "ON CONFLICT(uid) DO UPDATE SET importance = excluded.importance", (uid, semester_uid, discipline, t.number, t.title, t.importance))
    for uid in set(old.values()) - keep:
        conn.execute("DELETE FROM university_topics WHERE uid = ?", (uid,))
        conn.execute("DELETE FROM university_topic_classes WHERE topic_uid = ?", (uid,))
    conn.commit()
    return len(themes)


def _own_text(conn: sqlite3.Connection, event_uid: str) -> set[str]:
    """The texts the module itself wrote into this class: those of the topics it was assigned."""
    rows = conn.execute("SELECT t.number, t.title FROM university_topic_classes c JOIN university_topics t ON t.uid = c.topic_uid WHERE c.event_uid = ?", (event_uid,)).fetchall()
    return {topic_text(r["number"], r["title"]) for r in rows}


def assign_topic(conn: sqlite3.Connection, topic_uid: str, event_uid: str, *, force: bool = False) -> str:
    """Writes a topic into a class description. Returns "written", or "conflict" when typed text is there and `force` is not set."""
    topic = conn.execute("SELECT * FROM university_topics WHERE uid = ?", (topic_uid,)).fetchone()
    event = db.get_event(conn, event_uid)
    if not topic or not event:
        raise PlanError("The topic or the class no longer exists")
    current = (event.get("description") or "").strip()
    if current and current not in _own_text(conn, event_uid) and not force:
        return "conflict"
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ?", (event_uid,))
    conn.execute("INSERT OR IGNORE INTO university_topic_classes (topic_uid, event_uid) VALUES (?, ?)", (topic_uid, event_uid))
    conn.commit()
    db.upsert_event(conn, {**event, "description": topic_text(topic["number"], topic["title"]), "updated_at": _now()})
    return "written"


def unassign_topic(conn: sqlite3.Connection, event_uid: str) -> None:
    event = db.get_event(conn, event_uid)
    if event and (event.get("description") or "").strip() in _own_text(conn, event_uid):
        db.upsert_event(conn, {**event, "description": "", "updated_at": _now()})
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ?", (event_uid,))
    conn.commit()


def class_events(conn: sqlite3.Connection, semester_uid: str, discipline: str, kind: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for slot in list_slots(conn, semester_uid, discipline):
        if kind and slot["kind"] != kind:
            continue
        rows += series_members(conn, slot["series_uid"])
    return sorted(rows, key=lambda e: (e["start_at"], e["uid"]))


def plan_assign_in_order(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, Any]:
    """Pairs the unassigned topics, in order, with the lecture classes that have no text; classes with typed text are named, not touched."""
    topics = [t for t in list_topics(conn, semester_uid, discipline) if not t["events"]]
    classes = class_events(conn, semester_uid, discipline, "lecture")
    free, blocked = [], []
    for c in classes:
        text = (c.get("description") or "").strip()
        if not text or text in _own_text(conn, c["uid"]):
            if not text:
                free.append(c)
        else:
            blocked.append(c["start_at"][:10])
    pairs = list(zip(topics, free))
    return {"pairs": [(t["uid"], c["uid"], t["number"], t["title"], c["start_at"][:10]) for t, c in pairs], "blocked": blocked,
            "left_over": max(0, len(topics) - len(free))}


def apply_assign_in_order(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> int:
    plan = plan_assign_in_order(conn, semester_uid, discipline)
    for topic_uid, event_uid, *_ in plan["pairs"]:
        assign_topic(conn, topic_uid, event_uid)
    return len(plan["pairs"])


# ---------------------------------------------------------------- exams and readings

def _exam_task_title(discipline: str, title: str) -> str:
    return title.strip() or f"{discipline} exam"


def save_exam(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, *, task_uid: str | None, title: str, day: str,
              start: str, end: str, weight: str, location: str = "") -> str:
    """An exam is a task due on the exam day plus an event at the exam time, joined by an exam link; editing moves both together."""
    d = _date(day, "Exam date", True)
    s, e = _clock(start or "09:00", "Start time"), _clock(end or "11:00", "End time")
    if e <= s:
        raise PlanError("The exam ends before it starts")
    try:
        w = float(weight) if str(weight).strip() else None
    except ValueError:
        raise PlanError("Weight is not a number") from None
    if w is not None and not 0 <= w <= 100:
        raise PlanError("Weight is a percentage from 0 to 100")
    existing = conn.execute("SELECT * FROM university_exams WHERE task_uid = ?", (task_uid,)).fetchone() if task_uid else None
    title = _exam_task_title(discipline, title)
    now = _now()
    task_uid = task_uid if existing else str(uuid.uuid4())
    event_uid = existing["event_uid"] if existing else str(uuid.uuid4())
    old_task = db.get_task(conn, task_uid) if existing else None
    old_event = db.get_event(conn, event_uid) if existing else None
    db.upsert_task(conn, {**(old_task or {}), "uid": task_uid, "title": title, "description": (old_task or {}).get("description") or "",
                          "due_at": d.isoformat(), "status": (old_task or {}).get("status") or "active", "tags": _labels(conn, discipline),
                          "created_at": (old_task or {}).get("created_at") or now, "updated_at": now})
    _tag_item(conn, "task", task_uid, discipline)
    db.upsert_event(conn, {**(old_event or {}), "uid": event_uid, "title": title, "description": (old_event or {}).get("description") or "",
                           "start_at": f"{d.isoformat()}T{s.strftime('%H:%M')}", "end_at": f"{d.isoformat()}T{e.strftime('%H:%M')}", "all_day": 0,
                           "location": location.strip(), "status": "active", "tags": _labels(conn, discipline),
                           "created_at": (old_event or {}).get("created_at") or now, "updated_at": now})
    _tag_item(conn, "event", event_uid, discipline)
    db.add_event_task_relation(conn, event_uid, task_uid, kind="exam")
    conn.execute("INSERT INTO university_exams (task_uid, event_uid, semester_uid, discipline_tag, weight) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(task_uid) DO UPDATE SET discipline_tag = excluded.discipline_tag, weight = excluded.weight",
                 (task_uid, event_uid, semester["uid"], discipline, w))
    conn.commit()
    return task_uid


def list_exams(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None, today: date | None = None) -> list[dict[str, Any]]:
    today = today or clock.today()
    sql = "SELECT * FROM university_exams WHERE semester_uid = ?"
    args: list[Any] = [semester_uid]
    if discipline:
        sql += " AND discipline_tag = ? COLLATE NOCASE"
        args.append(discipline)
    out = []
    for r in conn.execute(sql, args).fetchall():
        event, task = db.get_event(conn, r["event_uid"]), db.get_task(conn, r["task_uid"])
        if not event or not task:
            continue
        day = date.fromisoformat(event["start_at"][:10])
        out.append({"task_uid": r["task_uid"], "event_uid": r["event_uid"], "discipline": r["discipline_tag"], "title": task["title"], "date": day.isoformat(),
                    "start": event["start_at"][11:16], "end": (event.get("end_at") or "")[11:16], "location": event.get("location") or "",
                    "weight": r["weight"], "days_left": (day - today).days, "status": task["status"],
                    "notes": lecture_notes(conn, semester_uid, r["discipline_tag"])})
    out.sort(key=lambda x: (x["date"], x["start"]))
    return out


def delete_exam(conn: sqlite3.Connection, task_uid: str) -> None:
    row = conn.execute("SELECT * FROM university_exams WHERE task_uid = ?", (task_uid,)).fetchone()
    if not row:
        return
    db.delete_event(conn, row["event_uid"])
    db.delete_task(conn, task_uid)
    conn.execute("DELETE FROM university_exams WHERE task_uid = ?", (task_uid,))
    conn.commit()


def save_reading(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, *, task_uid: str | None, title: str, author: str,
                 due: str, status: str, citation_id: str = "") -> str:
    title = title.strip()
    if not title:
        raise PlanError("A reading needs a title")
    d = _date(due, "Due date")
    existing = conn.execute("SELECT 1 FROM university_readings WHERE task_uid = ?", (task_uid,)).fetchone() if task_uid else None
    task_uid = task_uid if existing else str(uuid.uuid4())
    old = db.get_task(conn, task_uid) if existing else None
    now = _now()
    db.upsert_task(conn, {**(old or {}), "uid": task_uid, "title": title, "description": author.strip(), "due_at": d.isoformat() if d else None,
                          "status": status if status in ("active", "in_progress", "waiting", "done", "archived") else ((old or {}).get("status") or "active"),
                          "tags": _labels(conn, discipline), "created_at": (old or {}).get("created_at") or now, "updated_at": now})
    _tag_item(conn, "task", task_uid, discipline)
    conn.execute("INSERT INTO university_readings (task_uid, semester_uid, discipline_tag, author, citation_id) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(task_uid) DO UPDATE SET discipline_tag = excluded.discipline_tag, author = excluded.author, citation_id = excluded.citation_id",
                 (task_uid, semester["uid"], discipline, author.strip(), citation_id or None))
    conn.commit()
    return task_uid


def list_readings(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM university_readings WHERE semester_uid = ?"
    args: list[Any] = [semester_uid]
    if discipline:
        sql += " AND discipline_tag = ? COLLATE NOCASE"
        args.append(discipline)
    out = []
    for r in conn.execute(sql, args).fetchall():
        task = db.get_task(conn, r["task_uid"])
        if task:
            out.append({"task_uid": r["task_uid"], "discipline": r["discipline_tag"], "title": task["title"], "author": r["author"] or "",
                        "due": (task.get("due_at") or "")[:10], "status": task["status"], "citation_id": r["citation_id"] or ""})
    out.sort(key=lambda x: (x["due"] or "9999", x["title"]))
    return out


def delete_reading(conn: sqlite3.Connection, task_uid: str) -> None:
    db.delete_task(conn, task_uid)
    conn.execute("DELETE FROM university_readings WHERE task_uid = ?", (task_uid,))
    conn.commit()


# ---------------------------------------------------------------- notebook

def lecture_notes(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, str]]:
    """The notes filed under the discipline's tag, which hold its lecture notes."""
    rows = conn.execute(
        "SELECT n.uid, n.title FROM notebook_documents n JOIN object_tags o ON o.object_id = n.uid AND o.object_type = 'note' "
        "WHERE o.tag_name = ? COLLATE NOCASE ORDER BY n.title", (discipline,)).fetchall() if _has_notes(conn) else []
    return [{"uid": r["uid"], "title": r["title"]} for r in rows]


def _has_notes(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'notebook_documents'").fetchone())


# ---------------------------------------------------------------- JSON export and import (format: study_format.py)

def export_discipline(conn: sqlite3.Connection, semester: dict[str, Any], name: str) -> dict[str, Any]:
    d = next((x for x in disciplines(conn, semester) if x["name"].lower() == name.lower()), None)
    if not d:
        raise PlanError("No such discipline")
    return {"name": d["name"], "color": d.get("color") or "", "icon": d.get("icon") or "", "teachers": [t["name"] for t in d["teachers"]],
            "timetable": [{"weekday": s["weekday"], "start": s["start"], "end": s["end"], "room": s["room"], "kind": s["kind"], "weeks": s["weeks"]}
                          for s in list_slots(conn, semester["uid"], d["name"])],
            "themes": [{"number": t["number"], "title": t["title"], "importance": t["importance"]} for t in list_topics(conn, semester["uid"], d["name"])],
            "exams": [{"title": e["title"], "date": e["date"], "time": e["start"], "weight": e["weight"]} for e in list_exams(conn, semester["uid"], d["name"])],
            "readings": [{"title": r["title"], "author": r["author"]} for r in list_readings(conn, semester["uid"], d["name"])]}


def export_semester(conn: sqlite3.Connection, semester: dict[str, Any]) -> dict[str, Any]:
    return {"name": semester["name"], "start_date": semester.get("start_date") or "", "end_date": semester.get("end_date") or "",
            "class_end_date": semester.get("class_end_date") or "",
            "disciplines": [export_discipline(conn, semester, d["name"]) for d in disciplines(conn, semester)]}


def _disciplines_of(kind: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    return [data] if kind == "discipline" else data["disciplines"]


def plan_import(conn: sqlite3.Connection, semester: dict[str, Any], kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """What importing a file would create in the current semester: one line per discipline, and what already exists."""
    lines, warnings = [], []
    have = {d["name"].lower() for d in disciplines(conn, semester)}
    for d in _disciplines_of(kind, data):
        lines.append(f"{d['name']}: {len(d['timetable'])} timetable slots, {len(d['themes'])} topics, {len(d['exams'])} exams, {len(d['readings'])} readings.")
        if d["name"].lower() in have:
            warnings.append(f"{d['name']} already exists; its timetable, exams and readings would be added to it.")
        if d["timetable"]:
            try:
                for slot in d["timetable"]:
                    _planned_dates(conn, semester, _validate_slot(slot))
            except PlanError as exc:
                warnings.append(f"{d['name']}: {exc}.")
    return {"lines": lines, "warnings": warnings, "blocked": any("class end date" in w or "Semester start" in w for w in warnings)}


def apply_import(conn: sqlite3.Connection, semester: dict[str, Any], kind: str, data: dict[str, Any], *, colors) -> int:
    """Creates the disciplines of an imported file in the current semester; returns how many disciplines were handled."""
    plan = plan_import(conn, semester, kind, data)
    if plan["blocked"]:
        raise PlanError("Set the semester start and class end dates first")
    for d in _disciplines_of(kind, data):
        known = next((x for x in disciplines(conn, semester) if x["name"].lower() == d["name"].lower()), None)
        if known:
            teacher_names = ", ".join(sorted({t["name"] for t in known["teachers"]} | set(d["teachers"])))
            save_discipline(conn, semester, old=known["name"], name=known["name"], color=known["color"], icon=known["icon"], teacher_names=teacher_names, colors=colors)
        else:
            save_discipline(conn, semester, old="", name=d["name"], color=d["color"] or "gray", icon=d["icon"], teacher_names=", ".join(d["teachers"]), colors=colors)
        name = known["name"] if known else d["name"]
        for slot in d["timetable"]:
            save_slot(conn, semester, name, slot)
        if d["themes"]:
            save_syllabus(conn, semester["uid"], name, "\n".join(f"{t['number']}. {t['title']}{' ' + '*' * t['importance'] if t['importance'] else ''}" for t in d["themes"]))
        for e in d["exams"]:
            if e["date"]:
                save_exam(conn, semester, name, task_uid=None, title=e["title"], day=e["date"], start=e["time"] or "09:00",
                          end=_plus_two_hours(e["time"] or "09:00"), weight="" if e["weight"] is None else str(e["weight"]))
        for r in d["readings"]:
            save_reading(conn, semester, name, task_uid=None, title=r["title"], author=r["author"], due="", status="active")
    return len(_disciplines_of(kind, data))


def _plus_two_hours(start: str) -> str:
    t = _clock(start, "Start time")
    return time(min(t.hour + 2, 23), t.minute).strftime("%H:%M")


# ---------------------------------------------------------------- lecture notes

LECTURE_TEMPLATE = "Lecture"
LECTURE_FIELDS = ("discipline", "date", "topic", "lecture number")


def ensure_lecture_template(conn: sqlite3.Connection) -> str:
    """The notebook template a class note starts from; made once, then left to the user to restyle."""
    row = conn.execute("SELECT uid FROM notebook_documents WHERE is_template = 1 AND title = ? COLLATE NOCASE", (LECTURE_TEMPLATE,)).fetchone()
    if row:
        return row["uid"]
    uid, now = str(uuid.uuid4()), _now()
    db.upsert_notebook_document(conn, {"uid": uid, "title": LECTURE_TEMPLATE, "content_json": '{"blocks": []}', "document_type": "full", "note_type": "",
                                       "is_template": 1, "created_at": now, "updated_at": now, "properties": [{"key": k, "value": ""} for k in LECTURE_FIELDS]})
    return uid


def class_note(conn: sqlite3.Connection, event_uid: str) -> str | None:
    row = conn.execute("SELECT notebook_uid FROM notebook_properties WHERE key = 'class' AND value = ? LIMIT 1", (event_uid,)).fetchone()
    return row["notebook_uid"] if row else None


def class_notes_by_event(conn: sqlite3.Connection, event_uids: list[str]) -> dict[str, str]:
    if not event_uids:
        return {}
    marks = ", ".join("?" for _ in event_uids)
    rows = conn.execute(f"SELECT value, notebook_uid FROM notebook_properties WHERE key = 'class' AND value IN ({marks})", event_uids).fetchall()
    return {r["value"]: r["notebook_uid"] for r in rows}


def open_class_note(conn: sqlite3.Connection, event_uid: str) -> str:
    """The note of one class: the existing one, or a new one from the Lecture template, filed under the discipline's tag."""
    existing = class_note(conn, event_uid)
    if existing:
        return existing
    event = db.get_event(conn, event_uid)
    slot = conn.execute("SELECT * FROM university_slots WHERE series_uid = ?", (event.get("series_uid") if event else None,)).fetchone()
    if not event or not slot:
        raise PlanError("That event is not a class of the semester")
    tag = slot["discipline_tag"]
    classes = class_events(conn, slot["semester_uid"], tag, "lecture")
    number = next((i + 1 for i, c in enumerate(classes) if c["uid"] == event_uid), len(classes) + 1)
    day = event["start_at"][:10]
    topic = (event.get("description") or "").strip()
    template = db.get_notebook_document(conn, ensure_lecture_template(conn))
    uid, now = str(uuid.uuid4()), _now()
    values = {"discipline": tag, "date": day, "topic": topic, "lecture number": str(number)}
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": f"{tag} lecture {number}, {day}", "content_json": template["content_json"], "document_type": "full",
        "note_type": template.get("note_type") or "", "created_at": now, "updated_at": now, "tags": _labels(conn, tag),
        "properties": [{"key": p["key"], "value": values.get(p["key"], p["value"])} for p in template["properties"]] + [{"key": "class", "value": event_uid}]})
    tags.record(conn, "notebook", uid, [tag])
    return uid


def is_locked(conn: sqlite3.Connection, kind: str, uid: str) -> bool:
    """A class or an exam (its event or its task) keeps its title and description: only the module edits them."""
    if not uid or not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_slots'").fetchone():
        return False
    if kind == "event":
        event = db.get_event(conn, uid)
        if event and event.get("series_uid") and conn.execute("SELECT 1 FROM university_slots WHERE series_uid = ?", (event["series_uid"],)).fetchone():
            return True
        return bool(conn.execute("SELECT 1 FROM university_exams WHERE event_uid = ?", (uid,)).fetchone())
    return bool(conn.execute("SELECT 1 FROM university_exams WHERE task_uid = ?", (uid,)).fetchone())
