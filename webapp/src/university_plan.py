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

CURRENT_KEY = "university_current"
GROUP_NAME = "University"


def list_semesters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM university_semesters ORDER BY created_at DESC, uid")]


def current_semester(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The semester the module is showing: the one picked in the header menu, or the newest."""
    picked = get_semester(conn, db.get_app_meta(conn, CURRENT_KEY))
    if picked:
        return picked
    rows = list_semesters(conn)
    return rows[0] if rows else None


def select_semester(conn: sqlite3.Connection, uid: str) -> None:
    if not get_semester(conn, uid):
        raise PlanError("No such semester")
    db.set_app_meta(conn, CURRENT_KEY, uid)


def get_semester(conn: sqlite3.Connection, uid: str | None) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM university_semesters WHERE uid = ?", (uid,)).fetchone() if uid else None
    return dict(row) if row else None


def plan_semester(conn: sqlite3.Connection, shelf_name: str) -> dict[str, Any]:
    """What saving would do to the shelf: adopt one that exists or create it, and which tags become disciplines."""
    existing = db.get_label_config(conn, shelf_name) if shelf_name.strip() else None
    return {"shelf": shelf_name.strip(), "adopts": bool(existing), "tags": [t["name"] for t in tags.tags_of_label(conn, shelf_name)] if existing else []}


def adoptable_shelves(conn: sqlite3.Connection, current: str = "") -> list[str]:
    """Shelves a semester can take over: not archived, not managed by a module, not already a semester. `current` stays listed."""
    taken = {r["shelf_name"].lower() for r in conn.execute("SELECT shelf_name FROM university_semesters")}
    names = [l["name"] for l in db.list_labels(conn)
             if not l.get("archived_at") and not tags.managed_by(conn, l["name"]) and l["name"].lower() not in taken]
    return sorted(([current] if current else []) + names, key=str.lower)


def semester_group(conn: sqlite3.Connection, semester: dict[str, Any]) -> str:
    """The space the semester's shelf sits in; its page is the study page."""
    row = conn.execute("SELECT label_group FROM label_config WHERE name = ? COLLATE NOCASE", (semester["shelf_name"],)).fetchone()
    return ((row["label_group"] if row else "") or "").strip()


def attach_group(conn: sqlite3.Connection, semester: dict[str, Any], group_name: str = "") -> str:
    """Puts the semester's shelf in its space (made if needed) and gives the space the study page. Safe to repeat."""
    group = semester_group(conn, semester) or db.ensure_group(conn, (group_name or GROUP_NAME).strip())
    with _owner():
        db.upsert_label_config(conn, {"name": semester["shelf_name"], "label_group": group, "page_type": "sections"})
    style = db.get_group_style(conn, group)
    if not style["icon"]:
        db.set_group_style(conn, group, "graduation-cap", style["color"] if style["color"] != "gray" else "blue")
    db.set_group_page_type(conn, group, PAGE_TYPE)
    return group


def semester_for_group(conn: sqlite3.Connection, group: str) -> dict[str, Any] | None:
    picked = current_semester(conn)
    if picked and semester_group(conn, picked).lower() == (group or "").strip().lower():
        return picked
    row = conn.execute(
        "SELECT s.* FROM university_semesters s JOIN label_config l ON l.name = s.shelf_name COLLATE NOCASE "
        "WHERE l.label_group = ? COLLATE NOCASE ORDER BY s.created_at DESC LIMIT 1", (group,)).fetchone()
    return dict(row) if row else None


def save_semester(conn: sqlite3.Connection, *, uid: str | None, name: str, shelf_name: str, start_date: str, end_date: str,
                  class_end_date: str, holiday_calendar: str = "", group_name: str = "", credits_target: str = "") -> str:
    name, picked = name.strip(), shelf_name.strip()
    shelf_name = picked or name
    if not name:
        raise PlanError("The semester needs a name")
    start, end, class_end = _date(start_date, "Start date"), _date(end_date, "End date"), _date(class_end_date, "Class end date")
    if start and end and end < start:
        raise PlanError("The end date is before the start date")
    if start and class_end and class_end < start:
        raise PlanError("The class end date is before the start date")
    try:
        target = float(credits_target) if str(credits_target).strip() else None
    except ValueError:
        raise PlanError("Credits to reach is not a number") from None
    if target is not None and target < 0:
        raise PlanError("Credits to reach cannot be negative")
    existing = get_semester(conn, uid)
    switching = bool(existing and picked and picked.lower() != existing["shelf_name"].lower())
    if existing and not switching:
        shelf_name = existing["shelf_name"]
    elif switching and tags.managed_by(conn, picked):
        raise PlanError(f"{picked} is managed already")
    if (switching or not existing) and conn.execute("SELECT 1 FROM university_semesters WHERE shelf_name = ? COLLATE NOCASE", (shelf_name,)).fetchone():
        raise PlanError(f"{shelf_name} already holds a semester")
    with _owner():
        if switching:
            db.upsert_label_config(conn, {"name": existing["shelf_name"], "managed_by": None})
        if db.get_label_config(conn, shelf_name) is None:
            db.upsert_label_config(conn, {"name": shelf_name, "color": "blue", "icon": "graduation-cap", "created_at": _now()})
        db.upsert_label_config(conn, {"name": shelf_name, "managed_by": MODULE_KEY})
    uid = existing["uid"] if existing else str(uuid.uuid4())
    conn.execute(
        "INSERT INTO university_semesters (uid, shelf_name, name, start_date, end_date, class_end_date, holiday_calendar, credits_target, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET shelf_name=excluded.shelf_name, name=excluded.name, start_date=excluded.start_date, "
        "end_date=excluded.end_date, class_end_date=excluded.class_end_date, holiday_calendar=excluded.holiday_calendar, credits_target=excluded.credits_target",
        (uid, shelf_name, name, start.isoformat() if start else None, end.isoformat() if end else None,
         class_end.isoformat() if class_end else None, holiday_calendar.strip() or None, target, existing["created_at"] if existing else _now()),
    )
    conn.commit()
    attach_group(conn, get_semester(conn, uid), group_name)
    if not existing:
        select_semester(conn, uid)
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
            "milestones": n("SELECT COUNT(*) FROM university_milestones WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"),
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
                    teacher_names: str | None, colors) -> str:
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
        for table in ("university_slots", "university_milestones", "university_readings", "university_sheet"):
            conn.execute(f"UPDATE {table} SET discipline_tag = ? WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (name, semester["uid"], old))
        conn.commit()
        _retitle_classes(conn, semester["uid"], name)
    if teacher_names is not None:
        wanted = db.resolve_contact_entries(conn, _split_names(teacher_names))
        for uid in _teacher_uids(conn, name):
            if uid not in wanted:
                _tag_item(conn, "contact", uid, name, False)
        for uid in wanted:
            _tag_item(conn, "contact", uid, name)
    return name


def removal_blockers(conn: sqlite3.Connection, semester: dict[str, Any], tag: str) -> str | None:
    counts = count_items(conn, semester["uid"], tag)
    parts = [f"{counts[k]} {label}" for k, label in (("slots", "timetable slots"), ("milestones", "milestones"), ("readings", "readings")) if counts[k]]
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


def _follow_split(conn: sqlite3.Connection, old_series: str, new_series: str) -> None:
    """The later half of a class series that was split (a class deleted, or an edit from some day on) is a slot of the same kind."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_slots'").fetchone():
        return
    row = conn.execute("SELECT * FROM university_slots WHERE series_uid = ?", (old_series,)).fetchone()
    if row:
        conn.execute("INSERT OR IGNORE INTO university_slots (series_uid, semester_uid, discipline_tag, kind, weeks, continues) VALUES (?, ?, ?, ?, ?, ?)",
                     (new_series, row["semester_uid"], row["discipline_tag"], row["kind"], row["weeks"], old_series))
        conn.commit()


event_series.SPLIT_HOOKS.append(_follow_split)
event_series.SPLIT_ON_DELETE.append(lambda conn, series_uid: bool(
    conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_slots'").fetchone()
    and conn.execute("SELECT 1 FROM university_slots WHERE series_uid = ?", (series_uid,)).fetchone()))


def series_members(conn: sqlite3.Connection, series_uid: str) -> list[dict[str, Any]]:
    return event_series.members(conn, series_uid)


def list_slots(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None, history: bool = False) -> list[dict[str, Any]]:
    """The timetable, read from the event series themselves. The past half of a slot edited from some day on is left out unless `history`."""
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
        out.append({"series_uid": row["series_uid"], "continues": row["continues"] if "continues" in row.keys() else None, "discipline": row["discipline_tag"], "kind": row["kind"], "weeks": row["weeks"],
                    "weekday": _BYDAY.index(parts.get("BYDAY", "MO").split(",")[0]), "start": first["start_at"][11:16], "end": (first.get("end_at") or "")[11:16],
                    "room": first.get("location") or "", "count": len(members), "first": first["start_at"][:10], "last": members[-1]["start_at"][:10],
                    "teachers": [c["uid"] for c in db.list_object_contacts(conn, "event", first["uid"])]})
    if not history:
        out = [s for s in out if not _superseded(s, out)]
    out.sort(key=lambda s: (s["weekday"], s["start"]))
    return out


def _superseded(slot: dict[str, Any], slots: list[dict[str, Any]]) -> bool:
    """The past half of a slot that was edited from some day on: a later series of the same discipline starts right after it ends, or says it continues it."""
    if any(o["continues"] == slot["series_uid"] for o in slots):
        return True
    last = date.fromisoformat(slot["last"])
    return any(o is not slot and o["discipline"].lower() == slot["discipline"].lower()
               and timedelta(0) < date.fromisoformat(o["first"]) - last <= timedelta(days=21) for o in slots)


def _slot_by_series(conn: sqlite3.Connection, semester_uid: str, series_uid: str) -> dict[str, Any] | None:
    return next((s for s in list_slots(conn, semester_uid) if s["series_uid"] == series_uid), None)


def plan_slot(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, slot: dict[str, Any], series_uid: str | None = None,
              today: date | None = None) -> dict[str, Any]:
    """What saving a slot creates, the typed descriptions a rebuild would lose, and how many past classes stay as they are."""
    slot = _validate_slot(slot)
    today = (today or clock.today()).isoformat()
    dates = _planned_dates(conn, semester, slot)
    lost: list[str] = []
    rebuilds = True
    past = 0
    if series_uid:
        members = series_members(conn, series_uid)
        past = sum(1 for m in members if m["start_at"][:10] < today)
        old = _slot_by_series(conn, semester["uid"], series_uid)
        if old and old["weekday"] == slot["weekday"] and old["weeks"] == slot["weeks"]:
            rebuilds = False
        else:
            keep = {d.isoformat() for d in dates}
            lost = [m["start_at"][:10] for m in members if m["start_at"][:10] >= today and (m.get("description") or "").strip() and m["start_at"][:10] not in keep]
    return {"classes": len(dates), "first": dates[0].isoformat() if dates else "", "last": dates[-1].isoformat() if dates else "",
            "rebuilds": rebuilds, "lost": lost, "past": past, "slot": slot}


def _minutes_between(a: str, b: str) -> timedelta:
    return timedelta(minutes=(int(b[:2]) * 60 + int(b[3:5])) - (int(a[:2]) * 60 + int(a[3:5])))


def _edit_following(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, slot: dict[str, Any], series_uid: str,
                    members: list[dict[str, Any]], plan: dict[str, Any], today: str) -> str:
    """Applies a timetable edit to the classes from today on with the calendar's "this and following" scope; past classes stay put."""
    future = [m for m in members if m["start_at"][:10] >= today]
    if not future:
        raise PlanError("Every class of this slot is already past, so there is nothing left to change")
    cut = future[0]
    title = _class_title(discipline, slot["kind"])
    if not plan["rebuilds"]:
        event_series.apply_edit(conn, cut["uid"], "following", {"title": title, "location": slot["room"]},
                                _minutes_between(cut["start_at"][11:16], slot["start"]), _minutes_between((cut.get("end_at") or "")[11:16] or slot["end"], slot["end"]),
                                None, slot["teachers"])
    else:
        dates = [d for d in _planned_dates(conn, semester, slot) if d.isoformat() >= today]
        if not dates:
            raise PlanError("That timetable produces no classes from today on")
        kept = {m["start_at"][:10]: m.get("description") or "" for m in future}
        first = dates[0].isoformat()
        base = {**cut, "title": title, "location": slot["room"], "description": kept.get(first, ""),
                "start_at": f"{first}T{slot['start']}", "end_at": f"{first}T{slot['end']}", "updated_at": _now()}
        event_series.change_rule(conn, cut["uid"], "following", slot_rule(slot["weekday"], slot["weeks"], _class_end(semester)), base, slot["teachers"])
        for m in series_members(conn, (db.get_event(conn, cut["uid"]) or {}).get("series_uid") or ""):
            if kept.get(m["start_at"][:10]) and not (m.get("description") or "").strip():
                db.upsert_event(conn, {**m, "description": kept[m["start_at"][:10]]})
    new_series = (db.get_event(conn, cut["uid"]) or {}).get("series_uid") or series_uid
    if new_series != series_uid:
        conn.execute("INSERT OR REPLACE INTO university_slots (series_uid, semester_uid, discipline_tag, kind, weeks, continues) VALUES (?, ?, ?, ?, ?, ?)",
                     (new_series, semester["uid"], discipline, slot["kind"], slot["weeks"], series_uid if series_members(conn, series_uid) else None))
        if not series_members(conn, series_uid):
            conn.execute("DELETE FROM university_slots WHERE series_uid = ?", (series_uid,))
    else:
        conn.execute("UPDATE university_slots SET kind = ?, weeks = ? WHERE series_uid = ?", (slot["kind"], slot["weeks"], series_uid))
    conn.commit()
    return new_series


def save_slot(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, slot: dict[str, Any], series_uid: str | None = None,
              today: date | None = None) -> str:
    """Creates a slot's series, or edits the existing one from today on (the whole series when no class is past yet)."""
    today = today or clock.today()
    plan = plan_slot(conn, semester, discipline, slot, series_uid, today)
    slot = plan["slot"]
    if not plan["classes"]:
        raise PlanError("That timetable produces no classes between the semester dates")
    title = _class_title(discipline, slot["kind"])
    old_members = series_members(conn, series_uid) if series_uid else []
    if series_uid and (plan["past"] or plan["rebuilds"]):
        return _edit_following(conn, semester, discipline, slot, series_uid, old_members, plan, today.isoformat())
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


TOPIC_KINDS = {"lecture": "Lectures", "seminar": "Seminars", "lab": "Labs", "competence": "Competences"}


def list_topics(conn: sqlite3.Connection, semester_uid: str, discipline: str, kind: str | None = None) -> list[dict[str, Any]]:
    """The planned contents of a discipline (all class kinds, or one) or, with kind "competence", its competences."""
    where, args = ("AND kind = ?", [kind]) if kind else ("AND kind != 'competence'", [])
    rows = conn.execute(f"SELECT * FROM university_topics WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE {where} ORDER BY kind, number, title",
                        (semester_uid, discipline, *args)).fetchall()
    out = []
    for r in rows:
        events = [x["event_uid"] for x in conn.execute(
            "SELECT c.event_uid FROM university_topic_classes c JOIN events e ON e.uid = c.event_uid WHERE c.topic_uid = ?", (r["uid"],))]
        out.append({**dict(r), "events": events})
    return out


def syllabus_text(conn: sqlite3.Connection, semester_uid: str, discipline: str, kind: str = "lecture") -> str:
    return "\n".join(f"{t['number']}. {t['title']}{' ' + '*' * t['importance'] if t['importance'] else ''}" for t in list_topics(conn, semester_uid, discipline, kind))


def save_syllabus(conn: sqlite3.Connection, semester_uid: str, discipline: str, text: str, kind: str = "lecture") -> int:
    """Replaces the topics of one kind with a pasted list (used by imports); see `save_topic_rows` for the page's own rows."""
    return save_topic_rows(conn, semester_uid, discipline, [(t.number, t.title, t.importance) for t in study_lists.parse_themes(text)], kind)


def save_topic_rows(conn: sqlite3.Connection, semester_uid: str, discipline: str, rows: list[tuple[Any, str, Any]], kind: str = "lecture") -> int:
    """Replaces the topics of one kind with rows of (number, title, importance); a blank number continues the count, a blank title drops the row,
    and a topic that keeps its number and title keeps its uid and its classes."""
    themes, last = [], 0
    for number, title, importance in rows:
        title = (title or "").strip()
        if not title:
            continue
        try:
            n = int(str(number).strip())
        except ValueError:
            n = last + 1
        try:
            stars = max(0, min(int(str(importance).strip() or 0), 3))
        except ValueError:
            stars = 0
        last = n
        themes.append(study_lists.Theme(n, title, stars))
    existing = list_topics(conn, semester_uid, discipline, kind)
    old = {(t["number"], t["title"]): t["uid"] for t in existing}
    by_number = {t["number"]: t["uid"] for t in existing}
    keep: set[str] = set()
    for t in themes:
        uid = old.get((t.number, t.title))
        if not uid and by_number.get(t.number) not in keep:
            uid = by_number.get(t.number)  # the same number with a new title is the same topic, renamed
        uid = uid or str(uuid.uuid4())
        keep.add(uid)
        conn.execute("INSERT INTO university_topics (uid, semester_uid, discipline_tag, number, title, kind, importance) VALUES (?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(uid) DO UPDATE SET importance = excluded.importance, title = excluded.title, number = excluded.number",
                     (uid, semester_uid, discipline, t.number, t.title, kind, t.importance))
    for uid in set(t["uid"] for t in existing) - keep:
        conn.execute("DELETE FROM university_topics WHERE uid = ?", (uid,))
        conn.execute("DELETE FROM university_topic_classes WHERE topic_uid = ?", (uid,))
    conn.commit()
    return len(themes)


def class_links(conn: sqlite3.Connection, event_uid: str) -> dict[str, list[dict[str, Any]]]:
    """The planned contents and competences applied to one class."""
    rows = conn.execute("SELECT t.* FROM university_topic_classes c JOIN university_topics t ON t.uid = c.topic_uid WHERE c.event_uid = ? ORDER BY t.number", (event_uid,)).fetchall()
    return {"topics": [dict(r) for r in rows if r["kind"] != "competence"], "competences": [dict(r) for r in rows if r["kind"] == "competence"]}


def composed_text(conn: sqlite3.Connection, event_uid: str) -> str:
    """What the module writes into a class description: the topic, then the competences."""
    links = class_links(conn, event_uid)
    lines = [topic_text(t["number"], t["title"]) for t in links["topics"]]
    if links["competences"]:
        lines.append("Competences: " + "; ".join(f"{c['number']}. {c['title']}" for c in links["competences"]))
    return "\n".join(lines)


def _own_text(conn: sqlite3.Connection, event_uid: str) -> set[str]:
    """The text the module itself wrote into this class."""
    text = composed_text(conn, event_uid)
    return {text} if text else set()


def _write_description(conn: sqlite3.Connection, event_uid: str, text: str) -> None:
    event = db.get_event(conn, event_uid)
    db.upsert_event(conn, {**event, "description": text, "updated_at": _now()})


def assign_topic(conn: sqlite3.Connection, topic_uid: str, event_uid: str, *, force: bool = False) -> str:
    """Writes a topic into a class description. Returns "written", or "conflict" when typed text is there and `force` is not set."""
    topic = conn.execute("SELECT * FROM university_topics WHERE uid = ?", (topic_uid,)).fetchone()
    event = db.get_event(conn, event_uid)
    if not topic or not event:
        raise PlanError("The topic or the class no longer exists")
    current = (event.get("description") or "").strip()
    if current and current not in _own_text(conn, event_uid) and not force:
        return "conflict"
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ? AND topic_uid IN (SELECT uid FROM university_topics WHERE kind != 'competence')", (event_uid,))
    conn.execute("INSERT OR IGNORE INTO university_topic_classes (topic_uid, event_uid) VALUES (?, ?)", (topic_uid, event_uid))
    conn.commit()
    _write_description(conn, event_uid, composed_text(conn, event_uid))
    return "written"


def unassign_topic(conn: sqlite3.Connection, event_uid: str) -> None:
    event = db.get_event(conn, event_uid)
    was_ours = bool(event) and (event.get("description") or "").strip() in _own_text(conn, event_uid)
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ?", (event_uid,))
    conn.commit()
    if was_ours:
        _write_description(conn, event_uid, "")


def class_events(conn: sqlite3.Connection, semester_uid: str, discipline: str, kind: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for slot in list_slots(conn, semester_uid, discipline, history=True):
        if kind and slot["kind"] != kind:
            continue
        rows += series_members(conn, slot["series_uid"])
    return sorted(rows, key=lambda e: (e["start_at"], e["uid"]))


def plan_assign_in_order(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, Any]:
    """Pairs the unplaced topics of each class kind, in order, with the classes of that kind that have no text; classes with typed text are named, not touched."""
    pairs, blocked, left_over = [], [], 0
    for kind in ("lecture", "seminar", "lab"):
        topics = [t for t in list_topics(conn, semester_uid, discipline, kind) if not t["events"]]
        free = []
        for c in class_events(conn, semester_uid, discipline, kind):
            text = (c.get("description") or "").strip()
            if not text:
                free.append(c)
            elif text not in _own_text(conn, c["uid"]):
                blocked.append(c["start_at"][:10])
        pairs += [(t["uid"], c["uid"], t["number"], t["title"], c["start_at"][:10]) for t, c in zip(topics, free)]
        left_over += max(0, len(topics) - len(free))
    return {"pairs": pairs, "blocked": blocked, "left_over": left_over}


def apply_assign_in_order(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> int:
    plan = plan_assign_in_order(conn, semester_uid, discipline)
    for topic_uid, event_uid, *_ in plan["pairs"]:
        assign_topic(conn, topic_uid, event_uid)
    return len(plan["pairs"])


# ---------------------------------------------------------------- exams and readings

def _milestone_title(discipline: str, way: str, title: str) -> str:
    return title.strip() or f"{discipline}: {way}".strip(": ")


def _milestone_row(conn: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM university_milestones WHERE uid = ?", (uid,)).fetchone()


def _drop_milestone_items(conn: sqlite3.Connection, row: sqlite3.Row, *, event: bool = True, task: bool = True) -> None:
    if event and row["event_uid"]:
        db.delete_event(conn, row["event_uid"])
    if task and row["task_uid"]:
        db.delete_task(conn, row["task_uid"])


def _save_milestone(conn: sqlite3.Connection, semester_uid: str, discipline: str, way: dict[str, Any], ms: dict[str, Any], position: int) -> str:
    """A milestone is an event on its day (a day you are somewhere), a task due on its deadline (a day you hand something in), or both,
    joined by an exam link; a date creates or moves the item and clearing it removes the item."""
    day, due = _date(ms.get("day"), "Date", False), _date(ms.get("due"), "Deadline", False)
    start = _clock(ms.get("start") or "09:00", "Start time")
    end = _clock(ms.get("end") or _plus_two_hours(start.strftime("%H:%M")), "End time")
    end_day = _date(ms.get("end_day"), "End date", False) or day
    if day and (end_day, end) <= (day, start):
        raise PlanError("The event ends before it starts")
    title = _milestone_title(discipline, way["name"], ms.get("title") or "")
    uid = ms.get("uid") or ""
    old = _milestone_row(conn, uid) if uid else None
    uid = uid if old else str(uuid.uuid4())
    now = _now()
    event_uid, task_uid = (old["event_uid"] if old else None), (old["task_uid"] if old else None)
    if old and not day and event_uid:
        _drop_milestone_items(conn, old, task=False)
        event_uid = None
    if old and not due and task_uid:
        _drop_milestone_items(conn, old, event=False)
        task_uid = None
    if day:
        event_uid = event_uid or str(uuid.uuid4())
        prev = db.get_event(conn, event_uid)
        db.upsert_event(conn, {**(prev or {}), "uid": event_uid, "title": title, "description": (prev or {}).get("description") or "",
                               "start_at": f"{day.isoformat()}T{start.strftime('%H:%M')}", "end_at": f"{end_day.isoformat()}T{end.strftime('%H:%M')}", "all_day": 0,
                               "location": (ms.get("location") or "").strip(), "status": "active", "tags": _labels(conn, discipline),
                               "created_at": (prev or {}).get("created_at") or now, "updated_at": now})
        _tag_item(conn, "event", event_uid, discipline)
    if due:
        task_uid = task_uid or str(uuid.uuid4())
        prev = db.get_task(conn, task_uid)
        db.upsert_task(conn, {**(prev or {}), "uid": task_uid, "title": title, "description": (prev or {}).get("description") or "",
                              "due_at": due.isoformat(), "status": (prev or {}).get("status") or "active", "tags": _labels(conn, discipline),
                              "created_at": (prev or {}).get("created_at") or now, "updated_at": now})
        _tag_item(conn, "task", task_uid, discipline)
    if event_uid and task_uid:
        db.add_event_task_relation(conn, event_uid, task_uid, kind="exam")
    conn.execute("INSERT INTO university_milestones (uid, semester_uid, discipline_tag, way_id, title, day, start, end_day, end, location, due, notes, event_uid, task_uid, position) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET discipline_tag = excluded.discipline_tag, way_id = excluded.way_id, "
                 "title = excluded.title, day = excluded.day, start = excluded.start, end_day = excluded.end_day, end = excluded.end, location = excluded.location, due = excluded.due, "
                 "notes = excluded.notes, event_uid = excluded.event_uid, task_uid = excluded.task_uid, position = excluded.position",
                 (uid, semester_uid, discipline, way["id"], (ms.get("title") or "").strip(), day.isoformat() if day else "", start.strftime("%H:%M") if day else "",
                  end_day.isoformat() if day else "", end.strftime("%H:%M") if day else "", (ms.get("location") or "").strip() if day else "", due.isoformat() if due else "", (ms.get("notes") or "").strip(),
                  event_uid, task_uid, position))
    return uid


def list_milestones(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None, today: date | None = None, way_id: str | None = None) -> list[dict[str, Any]]:
    """Milestones as the pages show them, dated ones first. `date` is the event day or else the deadline; `weight` is the way's share of the grade."""
    today = today or clock.today()
    sql = "SELECT * FROM university_milestones WHERE semester_uid = ?"
    args: list[Any] = [semester_uid]
    if discipline:
        sql += " AND discipline_tag = ? COLLATE NOCASE"
        args.append(discipline)
    if way_id:
        sql += " AND way_id = ?"
        args.append(way_id)
    out, ways = [], {}
    for r in conn.execute(sql + " ORDER BY position", args).fetchall():
        key = r["discipline_tag"].lower()
        if key not in ways:
            ways[key] = {w["id"]: w for w in get_evaluation(conn, semester_uid, r["discipline_tag"], with_milestones=False)}
        way = ways[key].get(r["way_id"]) or {"name": "", "weight": None}
        when = r["day"] or r["due"]
        status = (db.get_task(conn, r["task_uid"]) or {}).get("status") if r["task_uid"] else ""
        out.append({"uid": r["uid"], "discipline": r["discipline_tag"], "way_id": r["way_id"], "way": way["name"], "weight": way["weight"],
                    "title": _milestone_title(r["discipline_tag"], way["name"], r["title"]), "raw_title": r["title"], "day": r["day"], "start": r["start"], "end_day": r["end_day"], "end": r["end"],
                    "location": r["location"], "due": r["due"], "notes": r["notes"], "event_uid": r["event_uid"] or "", "task_uid": r["task_uid"] or "",
                    "date": when, "days_left": (date.fromisoformat(when) - today).days if when else None, "status": status or ""})
    out.sort(key=lambda m: (not m["date"], m["date"], m["start"]))
    return out


def delete_milestone(conn: sqlite3.Connection, uid: str) -> None:
    row = _milestone_row(conn, uid)
    if not row:
        return
    _drop_milestone_items(conn, row)
    conn.execute("DELETE FROM university_milestones WHERE uid = ?", (uid,))
    conn.commit()


READING_CATEGORIES = {"obligatory": "Obligatory", "recommended": "Recommended", "auxiliary": "Auxiliary"}


def save_reading(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, *, task_uid: str | None, title: str = "", author: str = "",
                 due: str = "", status: str = "", citation_id: str = "", locator: str = "", category: str = "", notes: str = "") -> str:
    """A reading is a task that points at a book of the library, with the page or chapter, a category and notes. A reading with no
    library book keeps the title and author it was typed with (older readings and imported files)."""
    citation = db.get_citation(conn, citation_id) if citation_id else None
    if citation_id and not citation:
        raise PlanError("That book is not in the library")
    if citation:
        title = citation["title"]
        author = db.format_citation_authors(citation["authors"])
    title = title.strip()
    if not title:
        raise PlanError("A reading needs a book")
    locator = (locator or "").strip()
    category = category if category in READING_CATEGORIES else "recommended"
    d = _date(due, "Due date")
    existing = conn.execute("SELECT 1 FROM university_readings WHERE task_uid = ?", (task_uid,)).fetchone() if task_uid else None
    task_uid = task_uid if existing else str(uuid.uuid4())
    old = db.get_task(conn, task_uid) if existing else None
    now = _now()
    db.upsert_task(conn, {**(old or {}), "uid": task_uid, "title": f"{title}, {locator}" if locator else title, "description": (notes or "").strip(), "due_at": d.isoformat() if d else None,
                          "status": status if status in ("active", "in_progress", "waiting", "done", "archived") else ((old or {}).get("status") or "active"),
                          "tags": _labels(conn, discipline), "created_at": (old or {}).get("created_at") or now, "updated_at": now})
    _tag_item(conn, "task", task_uid, discipline)
    conn.execute("INSERT INTO university_readings (task_uid, semester_uid, discipline_tag, author, citation_id, locator, category, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(task_uid) DO UPDATE SET discipline_tag = excluded.discipline_tag, author = excluded.author, citation_id = excluded.citation_id, "
                 "locator = excluded.locator, category = excluded.category, notes = excluded.notes",
                 (task_uid, semester["uid"], discipline, author.strip(), citation_id or None, locator, category, (notes or "").strip()))
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
        if not task:
            continue
        citation = db.get_citation(conn, r["citation_id"]) if r["citation_id"] else None
        title = citation["title"] if citation else task["title"]
        out.append({"task_uid": r["task_uid"], "discipline": r["discipline_tag"], "title": title, "author": r["author"] or "", "locator": r["locator"] or "",
                    "category": r["category"] or "recommended", "category_label": READING_CATEGORIES.get(r["category"] or "recommended", "Recommended"),
                    "notes": r["notes"] or "", "due": (task.get("due_at") or "")[:10], "status": task["status"], "citation_id": r["citation_id"] or ""})
    out.sort(key=lambda x: (list(READING_CATEGORIES).index(x["category"]) if x["category"] in READING_CATEGORIES else 9, x["due"] or "9999", x["title"]))
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
            "exams": [{"title": e["title"], "date": e["day"] or e["due"], "time": e["start"], "weight": e["weight"]} for e in list_milestones(conn, semester["uid"], d["name"])],
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
                save_way(conn, semester["uid"], name, {"id": "", "name": e["title"], "weight": "" if e["weight"] is None else f"{e['weight']:g}", "subs": [],
                                                       "milestones": [{"title": e["title"], "day": e["date"], "start": e["time"] or "09:00"}]})
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
        return bool(conn.execute("SELECT 1 FROM university_milestones WHERE event_uid = ?", (uid,)).fetchone())
    return bool(conn.execute("SELECT 1 FROM university_milestones WHERE task_uid = ?", (uid,)).fetchone())


def _slot_chain(conn: sqlite3.Connection, series_uid: str) -> set[str]:
    """The series of one slot: the one given and every half it was split into or continues."""
    chain, todo = set(), [series_uid]
    while todo:
        current = todo.pop()
        if current in chain:
            continue
        chain.add(current)
        for r in conn.execute("SELECT series_uid, continues FROM university_slots WHERE series_uid = ? OR continues = ?", (current, current)).fetchall():
            todo += [r["series_uid"], r["continues"] or ""]
    chain.discard("")
    return chain


def rename_everywhere(conn: sqlite3.Connection, kind: str, uid: str, title: str) -> None:
    """A class or an exam edited elsewhere (the calendar, the task page) can take a new title: it is applied to every class of the
    slot, or to the exam's event and task together, so the module and the item never disagree."""
    title = (title or "").strip()
    if not title or not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_slots'").fetchone():
        return
    column = "event_uid" if kind == "event" else "task_uid"
    ms = conn.execute(f"SELECT * FROM university_milestones WHERE {column} = ?", (uid,)).fetchone()
    if ms:
        conn.execute("UPDATE university_milestones SET title = ? WHERE uid = ?", (title, ms["uid"]))
        for event_uid in (ms["event_uid"],):
            event = db.get_event(conn, event_uid) if event_uid else None
            if event and event["title"] != title:
                db.upsert_event(conn, {**event, "title": title, "updated_at": _now()})
        task = db.get_task(conn, ms["task_uid"]) if ms["task_uid"] else None
        if task and task["title"] != title:
            db.upsert_task(conn, {**task, "title": title, "updated_at": _now()})
        conn.commit()
        return
    event = db.get_event(conn, uid) if kind == "event" else None
    if event and event.get("series_uid"):
        for series in _slot_chain(conn, event["series_uid"]):
            for m in series_members(conn, series):
                if m["title"] != title:
                    db.upsert_event(conn, {**m, "title": title, "updated_at": _now()})
        conn.commit()


# ---------------------------------------------------------------- homework and class contents (the discipline page)

def list_homework(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, Any]]:
    """Tasks carrying the discipline tag that are neither an exam nor a reading."""
    rows = conn.execute(
        "SELECT t.uid FROM tasks t JOIN object_tags o ON o.object_id = t.uid AND o.object_type = 'task' WHERE o.tag_name = ? COLLATE NOCASE "
        "AND t.uid NOT IN (SELECT task_uid FROM university_milestones WHERE task_uid IS NOT NULL) AND t.uid NOT IN (SELECT task_uid FROM university_readings)", (discipline,)).fetchall()
    out = []
    for r in rows:
        task = db.get_task(conn, r["uid"])
        if task:
            out.append({"task_uid": task["uid"], "title": task["title"], "due": (task.get("due_at") or "")[:10], "status": task["status"],
                        "description": task.get("description") or ""})
    out.sort(key=lambda h: (h["status"] in ("done", "archived"), h["due"] or "9999", h["title"]))
    return out


def list_other_items(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, Any]]:
    """Tasks and events that carry the discipline tag and are tracked nowhere else: not a class, a repeating event, a habit,
    a milestone, a reading, nor anything linked to an event or task (an exam or homework date is shown under evaluation)."""
    linked = {r[0] for r in conn.execute("SELECT task_uid FROM event_task_relations UNION SELECT event_uid FROM event_task_relations")}
    habits = {r[0] for r in conn.execute("SELECT uid FROM tasks WHERE is_habit = 1")}
    out = [{"kind": "task", "uid": h["task_uid"], "title": h["title"], "when": h["due"], "status": h["status"]}
           for h in list_homework(conn, semester_uid, discipline) if h["task_uid"] not in linked and h["task_uid"] not in habits]
    rows = conn.execute(
        "SELECT e.uid FROM events e JOIN object_tags o ON o.object_id = e.uid AND o.object_type = 'event' WHERE o.tag_name = ? COLLATE NOCASE "
        "AND e.uid NOT IN (SELECT event_uid FROM university_milestones WHERE event_uid IS NOT NULL) "
        "AND COALESCE(e.series_uid, '') = ''", (discipline,)).fetchall()
    for r in rows:
        event = db.get_event(conn, r["uid"])
        if event and event["uid"] not in linked:
            out.append({"kind": "event", "uid": event["uid"], "title": event["title"], "when": event["start_at"][:10], "status": event.get("status") or ""})
    out.sort(key=lambda i: (i["status"] in ("done", "archived"), i["when"] or "9999", i["title"]))
    return out


def is_other_event(conn: sqlite3.Connection, semester_uid: str, discipline: str, uid: str) -> bool:
    return any(i["kind"] == "event" and i["uid"] == uid for i in list_other_items(conn, semester_uid, discipline))


def save_homework(conn: sqlite3.Connection, semester: dict[str, Any], discipline: str, *, task_uid: str | None, title: str, due: str, status: str) -> str:
    title = title.strip()
    if not title:
        raise PlanError("Homework needs a title")
    d = _date(due, "Due date")
    old = db.get_task(conn, task_uid) if task_uid else None
    if old and not is_homework(conn, task_uid):
        raise PlanError("That task is not homework")
    uid = task_uid if old else str(uuid.uuid4())
    now = _now()
    db.upsert_task(conn, {**(old or {}), "uid": uid, "title": title, "description": (old or {}).get("description") or "", "due_at": d.isoformat() if d else None,
                          "status": status if status in ("active", "in_progress", "waiting", "done", "archived") else ((old or {}).get("status") or "active"),
                          "tags": _labels(conn, discipline), "created_at": (old or {}).get("created_at") or now, "updated_at": now})
    _tag_item(conn, "task", uid, discipline)
    return uid


def is_homework(conn: sqlite3.Connection, task_uid: str) -> bool:
    return not conn.execute("SELECT 1 FROM university_milestones WHERE task_uid = ? UNION SELECT 1 FROM university_readings WHERE task_uid = ?", (task_uid, task_uid)).fetchone()


def list_classes(conn: sqlite3.Connection, semester_uid: str, discipline: str, today: date | None = None) -> list[dict[str, Any]]:
    """Every class of the discipline with the topic or text it carries and its note, for the Contents view."""
    today = (today or clock.today()).isoformat()
    kinds = {s["series_uid"]: s["kind"] for s in list_slots(conn, semester_uid, discipline, history=True)}
    events = class_events(conn, semester_uid, discipline)
    topic_of: dict[str, str] = {}
    competences_of: dict[str, list[str]] = {}
    for r in conn.execute("SELECT c.event_uid, c.topic_uid, t.kind FROM university_topic_classes c JOIN university_topics t ON t.uid = c.topic_uid WHERE t.semester_uid = ?", (semester_uid,)):
        if r["kind"] == "competence":
            competences_of.setdefault(r["event_uid"], []).append(r["topic_uid"])
        else:
            topic_of[r["event_uid"]] = r["topic_uid"]
    notes = class_notes_by_event(conn, [e["uid"] for e in events])
    counts: dict[str, int] = {}
    out = []
    for e in events:
        kind = kinds.get(e.get("series_uid"), "other")
        counts[kind] = counts.get(kind, 0) + 1
        out.append({"uid": e["uid"], "date": e["start_at"][:10], "start": e["start_at"][11:16], "end": (e.get("end_at") or "")[11:16], "kind": kind,
                    "kind_label": SLOT_KINDS.get(kind, "Class"), "number": counts[kind], "room": e.get("location") or "", "content": (e.get("description") or "").strip(),
                    "free_text": class_free_text(conn, e["uid"], e.get("description") or ""), "topic_uid": topic_of.get(e["uid"]), "competence_uids": competences_of.get(e["uid"], []), "note_uid": notes.get(e["uid"]), "past": e["start_at"][:10] < today})
    return out


def save_class_content(conn: sqlite3.Connection, event_uid: str, topic_uid: str, text: str, competence_uids: list[str] | tuple = ()) -> None:
    """What a class covered: a planned topic, some competences and free text, applied on that date. Only the module writes a class description."""
    event = db.get_event(conn, event_uid)
    if not event or not conn.execute("SELECT 1 FROM university_slots WHERE series_uid = ?", (event.get("series_uid"),)).fetchone():
        raise PlanError("That event is not a class of the semester")
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ?", (event_uid,))
    for uid in [topic_uid, *competence_uids]:
        if uid and conn.execute("SELECT 1 FROM university_topics WHERE uid = ?", (uid,)).fetchone():
            conn.execute("INSERT OR IGNORE INTO university_topic_classes (topic_uid, event_uid) VALUES (?, ?)", (uid, event_uid))
    conn.commit()
    composed = composed_text(conn, event_uid)
    text = (text or "").strip()
    _write_description(conn, event_uid, f"{composed}\n\n{text}" if composed and text else (composed or text))


def _class_event(conn: sqlite3.Connection, event_uid: str) -> dict[str, Any]:
    event = db.get_event(conn, event_uid)
    if not event or not conn.execute("SELECT 1 FROM university_slots WHERE series_uid = ?", (event.get("series_uid"),)).fetchone():
        raise PlanError("That event is not a class of the semester")
    return event


def save_class_schedule(conn: sqlite3.Connection, event_uid: str, day: str, start: str, end: str, room: str) -> None:
    """Moves one class to another day or hour, or gives it another room, without touching the rest of its slot."""
    event = _class_event(conn, event_uid)
    when = _date(day, "Date")
    if not when:
        raise PlanError("A class needs a date")
    first, last = _clock(start, "Start time"), _clock(end, "End time")
    if last <= first:
        raise PlanError("The class ends before it starts")
    db.upsert_event(conn, {**event, "start_at": f"{when.isoformat()}T{first.strftime('%H:%M')}", "end_at": f"{when.isoformat()}T{last.strftime('%H:%M')}",
                           "location": (room or "").strip(), "updated_at": _now()})
    conn.commit()


def delete_class(conn: sqlite3.Connection, event_uid: str) -> None:
    """Removes one class of a slot, with its place in the planned contents. The other classes of the slot stay."""
    _class_event(conn, event_uid)
    conn.execute("DELETE FROM university_topic_classes WHERE event_uid = ?", (event_uid,))
    event_series.delete_scope(conn, event_uid, "this")
    conn.commit()


def class_free_text(conn: sqlite3.Connection, event_uid: str, description: str) -> str:
    """The part of a class description that is not the module's composed text."""
    composed = composed_text(conn, event_uid)
    description = (description or "").strip()
    if composed and description.startswith(composed):
        return description[len(composed):].strip()
    return description


# ---------------------------------------------------------------- the course sheet (fișa disciplinei)

SHEET_SECTIONS = (
    ("identification", "Identification", (
        ("abbreviation", "Abbreviation", "text", ()), ("code", "Code", "text", ()), ("credits", "Credits", "number", ()),
        ("year", "Year of study", "select", ("1", "2", "3", "4", "5", "6")),
        ("type", "Type", "select", ("Compulsory", "Optional", "Facultative")), ("language", "Language of teaching", "text", ()))),
    ("teaching", "Teaching", (
        ("hours_lecture", "Lecture hours per week", "number", ()), ("hours_seminar", "Seminar hours per week", "number", ()),
        ("hours_lab", "Lab hours per week", "number", ()))),
    ("content", "Content", (
        ("objectives", "Objectives", "long", ()), ("prerequisites", "Prerequisites", "long", ()), ("summary", "Summary", "long", ()))),
)
SHEET_FIELDS = tuple((key, label) for _, _, fields in SHEET_SECTIONS for key, label, _, _ in fields)
SHEET_SECTION_KEYS = tuple(k for k, _, _ in SHEET_SECTIONS)


def _sheet_rows(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE ORDER BY position", (semester_uid, discipline)).fetchall()
    return {r["key"]: dict(r) for r in rows}


def _contact_list(conn: sqlite3.Connection, raw: str) -> list[dict[str, str]]:
    import json
    try:
        uids = json.loads(raw or "[]")
    except ValueError:
        uids = []
    out = []
    for u in uids:
        c = db.get_contact(conn, u)
        if c:
            out.append({"uid": u, "name": c.get("full_name") or ""})
    return out


def encode_custom(section: str, first: str, second: str = "") -> str:
    """The stored value of a field the user added to a section: one value (the hours of a teaching activity, or the text of a field)."""
    return first.strip()


def _custom_entry(section: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"label": row["label"], "value": row["value"]}


def get_sheet(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, Any]:
    """The course sheet in sections. Each section lists its fixed fields (always, empty or not) and the fields the user added to it.
    `values` is the flat key to value map, and the teachers come by kind of class."""
    rows = _sheet_rows(conn, semester_uid, discipline)
    sections = []
    for key, label, fields in SHEET_SECTIONS:
        sections.append({"key": key, "label": label,
                         "fields": [{"key": k, "label": fl, "type": t, "options": list(o), "value": (rows.get(k) or {}).get("value", "")} for k, fl, t, o in fields],
                         "custom": [_custom_entry(key, r) for r in rows.values() if r["key"].startswith(f"custom:{key}:")]})
    return {"sections": sections, "values": {k: (rows.get(k) or {}).get("value", "") for k, _ in SHEET_FIELDS},
            "lecture_teachers": _contact_list(conn, (rows.get("teachers_lecture") or {}).get("value", "")),
            "seminar_teachers": _contact_list(conn, (rows.get("teachers_seminar") or {}).get("value", ""))}


def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if str(value).strip() else None
    except ValueError:
        return None


def get_evaluation(conn: sqlite3.Connection, semester_uid: str, discipline: str, with_milestones: bool = True) -> list[dict[str, Any]]:
    """The ways a discipline is evaluated: each has a name and a weight in percent of the whole, may have components whose weights are percent
    of their way (`subs`), and may have dated milestones. `effective` is the share of the whole grade; a component's is its weight times its way's."""
    import json
    out = []
    for key, row in _sheet_rows(conn, semester_uid, discipline).items():
        if not key.startswith("eval:"):
            continue
        try:
            data = json.loads(row["value"] or "{}")
        except ValueError:
            data = {}
        weight = _num(data.get("weight"))
        elimination = bool(data.get("elimination"))
        comp = {"id": data.get("id") or key[5:], "name": row["label"], "form": data.get("form", ""), "weight": None if elimination else weight,
                "stored_weight": weight, "elimination": elimination, "notes": data.get("notes", ""), "effective": None if elimination else weight,
                "subs": [], "milestones": []}
        for sub in data.get("subs", []):
            w = _num(sub.get("weight"))
            comp["subs"].append({"id": sub.get("id") or "", "name": sub.get("name", ""), "weight": w, "parent": comp["id"],
                                 "effective": round(weight * w / 100, 4) if comp["weight"] is not None and w is not None else None})
        out.append(comp)
    if with_milestones and out:
        by_way: dict[str, list[dict[str, Any]]] = {}
        for m in list_milestones(conn, semester_uid, discipline):
            by_way.setdefault(m["way_id"], []).append(m)
        for comp in out:
            comp["milestones"] = by_way.get(comp["id"], [])
    return out


def evaluation_warnings(components: list[dict[str, Any]]) -> list[str]:
    """What does not add up: the weights of the whole should reach 100, and the components of one way should reach 100 of it."""
    notes = []
    weights = [c["weight"] for c in components if c["weight"] is not None]
    if weights and abs(sum(weights) - 100) > 0.01:
        notes.append(f"The evaluation weights add up to {sum(weights):g}%, not 100%")
    for c in components:
        subs = [s["weight"] for s in c["subs"] if s["weight"] is not None]
        if subs and abs(sum(subs) - 100) > 0.01:
            notes.append(f"The components of {c['name'] or 'a way of evaluating'} add up to {sum(subs):g}%, not 100%")
    return notes


EVALUATION_TONES = {"Exam": "red", "Colloquium": "red", "Oral": "red", "Practical": "red", "Continuous assessment": "orange", "Project": "blue", "Homework": "blue"}
EVALUATION_FORMS = ("Exam", "Colloquium", "Continuous assessment", "Project", "Homework", "Oral", "Practical", "Other")


def save_evaluation(conn: sqlite3.Connection, semester_uid: str, discipline: str, components: list[dict[str, Any]]) -> list[str]:
    """Replaces the ways of evaluating with the given ones ({id, name, weight, subs: [{id, name, weight}], milestones: [{uid, title, day, start, end,
    location, due, notes}]}). Ids that were sent are kept; a way with no name is dropped. A way or milestone that is no longer sent is removed with its
    events and tasks. Returns the warnings, which the user may keep: weights
    that do not add up, and what was removed."""
    import json
    sent = {c.get("id") for c in components if c.get("id")}
    removed = 0
    for old in get_evaluation(conn, semester_uid, discipline, with_milestones=False):
        if old["id"] not in sent:
            for m in list_milestones(conn, semester_uid, discipline, way_id=old["id"]):
                delete_milestone(conn, m["uid"])
                removed += 1
    conn.execute("DELETE FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND key LIKE 'eval:%'", (semester_uid, discipline))
    n = 0
    plans = []
    for comp in components:
        name = (comp.get("name") or "").strip()
        if not name:
            continue
        if str(comp.get("weight") or "").strip() and _num(comp.get("weight")) is None:
            conn.rollback()
            raise PlanError(f"Weight of {name} must be a number")
        subs = []
        for sub in comp.get("subs", []):
            if (sub.get("name") or "").strip():
                if str(sub.get("weight") or "").strip() and _num(sub.get("weight")) is None:
                    conn.rollback()
                    raise PlanError(f"Weight of {sub['name']} must be a number")
                subs.append({"id": sub.get("id") or uuid.uuid4().hex[:8], "name": sub["name"].strip(), "weight": str(sub.get("weight") or "").strip()})
        n += 1
        cid = comp.get("id") or uuid.uuid4().hex[:8]
        _put_sheet(conn, semester_uid, discipline, f"eval:{cid}", name, json.dumps({"id": cid, "form": (comp.get("form") or "").strip(), "weight": str(comp.get("weight") or "").strip(), "subs": subs,
                                                                                                     "elimination": bool(comp.get("elimination")), "notes": (comp.get("notes") or "").strip()}), 200 + n)
        plans.append(({"id": cid, "name": name}, comp.get("milestones")))
    for way, milestones in plans:
        if milestones is None:
            continue
        keep = {m.get("uid") for m in milestones if m.get("uid")}
        for old in list_milestones(conn, semester_uid, discipline, way_id=way["id"]):
            if old["uid"] not in keep:
                delete_milestone(conn, old["uid"])
                removed += 1
        for i, ms in enumerate(milestones):
            if any(str(ms.get(k) or "").strip() for k in ("title", "day", "due", "notes")):
                _save_milestone(conn, semester_uid, discipline, way, ms, i)
    conn.commit()
    notes = evaluation_warnings(get_evaluation(conn, semester_uid, discipline, with_milestones=False))
    if removed:
        notes.append(f"{removed} milestone{'s' if removed != 1 else ''} removed with {'its' if removed == 1 else 'their'} events and tasks")
    return notes


def _ways_as_input(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, Any]]:
    fmt = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
    return [{"id": w["id"], "name": w["name"], "form": w["form"], "weight": fmt(w["stored_weight"]), "elimination": w["elimination"], "notes": w["notes"], "subs": [{**x, "weight": fmt(x["weight"])} for x in w["subs"]]}
            for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False)]


def save_way(conn: sqlite3.Connection, semester_uid: str, discipline: str, way: dict[str, Any]) -> list[str]:
    """Adds a way of evaluating, or replaces the one with the same id in its place; the other ways and their milestones are left as they are."""
    ways = _ways_as_input(conn, semester_uid, discipline)
    if way.get("id") and any(w["id"] == way["id"] for w in ways):
        ways = [way if w["id"] == way["id"] else w for w in ways]
    else:
        ways.append(way)
    return save_evaluation(conn, semester_uid, discipline, ways)


def delete_way(conn: sqlite3.Connection, semester_uid: str, discipline: str, way_id: str) -> list[str]:
    return save_evaluation(conn, semester_uid, discipline, [w for w in _ways_as_input(conn, semester_uid, discipline) if w["id"] != way_id])


def evaluation_rows(conn: sqlite3.Connection, semester_uid: str, discipline: str, today: date | None = None) -> dict[str, Any]:
    """The Examination page: every way of evaluating with its components and dated milestones."""
    ways = get_evaluation(conn, semester_uid, discipline)
    today = today or clock.today()
    for w in ways:
        for m in w["milestones"]:
            m["days_left"] = (date.fromisoformat(m["date"]) - today).days if m["date"] else None
    for w in ways:
        w["tone"] = EVALUATION_TONES.get(w["form"], "orange")
    return {"ways": ways, "warnings": evaluation_warnings(ways)}


def sheet_filled(sheet: dict[str, Any]) -> bool:
    return any(v for v in sheet["values"].values()) or any(sec["custom"] for sec in sheet["sections"]) or bool(sheet["lecture_teachers"] or sheet["seminar_teachers"])


def _put_sheet(conn: sqlite3.Connection, semester_uid: str, discipline: str, key: str, label: str, value: str, position: float) -> None:
    conn.execute("INSERT INTO university_sheet (semester_uid, discipline_tag, key, label, value, position) VALUES (?, ?, ?, ?, ?, ?) "
                 "ON CONFLICT(semester_uid, discipline_tag, key) DO UPDATE SET label = excluded.label, value = excluded.value, position = excluded.position",
                 (semester_uid, discipline, key, label, value.strip(), position))


def save_sheet(conn: sqlite3.Connection, semester_uid: str, discipline: str, values: dict[str, str],
               custom: list[tuple[str, str, str]] | list[tuple[str, str]] | None = None, only_section: str | None = None) -> None:
    """Saves the fixed fields that were sent. `custom` is the complete list of the user's own fields as (section, label, stored value), or
    (label, value) for the identification section; it replaces the earlier ones (those of `only_section` when given), and a row with no
    label is dropped. None leaves them as they are."""
    for i, (key, label) in enumerate(SHEET_FIELDS):
        if key in values:
            if key in ("credits",) or key.startswith("hours_"):
                try:
                    float(str(values[key]).replace(",", ".") or 0)
                except ValueError:
                    conn.rollback()
                    raise PlanError(f"{label} must be a number") from None
            _put_sheet(conn, semester_uid, discipline, key, label, values[key] or "", i)
    if custom is not None:
        scope = f"custom:{only_section}:%" if only_section else "custom:%"
        conn.execute("DELETE FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND key LIKE ?", (semester_uid, discipline, scope))
        counts: dict[str, int] = {}
        for row in custom:
            section, label, value = (row if len(row) == 3 else ("identification", *row))
            section = section if section in SHEET_SECTION_KEYS else "identification"
            if only_section and section != only_section:
                continue
            if (label or "").strip():
                counts[section] = counts.get(section, 0) + 1
                _put_sheet(conn, semester_uid, discipline, f"custom:{section}:{counts[section]}", label.strip(), value or "", 100 + SHEET_SECTION_KEYS.index(section) * 10 + counts[section])
    conn.commit()


def set_teachers(conn: sqlite3.Connection, semester_uid: str, discipline: str, lecture: list[str], seminar: list[str]) -> None:
    """The people who teach the lectures and the people who teach seminars and labs; all of them carry the discipline's tag."""
    import json
    lec = db.resolve_contact_entries(conn, [x for x in lecture if x])
    sem = db.resolve_contact_entries(conn, [x for x in seminar if x])
    _put_sheet(conn, semester_uid, discipline, "teachers_lecture", "Lecture teachers", json.dumps(lec), 50)
    _put_sheet(conn, semester_uid, discipline, "teachers_seminar", "Seminar teachers", json.dumps(sem), 51)
    conn.commit()
    everyone = list(dict.fromkeys(lec + sem))
    for uid in _teacher_uids(conn, discipline):
        if uid not in everyone:
            _tag_item(conn, "contact", uid, discipline, False)
    for uid in everyone:
        _tag_item(conn, "contact", uid, discipline)


def credits_planned(conn: sqlite3.Connection, semester_uid: str) -> float:
    """The credits of the semester's disciplines, added up from their course sheets."""
    total = 0.0
    for row in conn.execute("SELECT value FROM university_sheet WHERE semester_uid = ? AND key = 'credits'", (semester_uid,)):
        try:
            total += float(str(row["value"]).replace(",", "."))
        except ValueError:
            pass
    return total


def abbreviations(conn: sqlite3.Connection, semester_uid: str) -> dict[str, str]:
    """The short name of each discipline that has one."""
    return {r["discipline_tag"]: r["value"] for r in conn.execute(
        "SELECT discipline_tag, value FROM university_sheet WHERE semester_uid = ? AND key = 'abbreviation' AND value != ''", (semester_uid,))}


def export_file(conn: sqlite3.Connection, semester: dict[str, Any], what: str) -> tuple[str, str]:
    """The versioned JSON file of the whole semester (what is "semester") or of one discipline ("discipline:<name>"), as (file name, text)."""
    from . import study_format
    try:
        if what.startswith("discipline:"):
            name = what.split(":", 1)[1]
            return f"{name.replace(' ', '-').lower()}.curodav-university.json", study_format.dump("discipline", export_discipline(conn, semester, name))
        return f"{semester['name'].replace(' ', '-').lower()}.curodav-university.json", study_format.dump("semester", export_semester(conn, semester))
    except study_format.FormatError as exc:
        raise PlanError(str(exc)) from exc


def import_file(conn: sqlite3.Connection, text: str, colors) -> str:
    """Adds the disciplines of a versioned University file to the current semester; returns the note to show."""
    from . import study_format
    semester = current_semester(conn)
    if not semester:
        raise PlanError("Set up a semester in the University settings before importing a University file")
    try:
        kind, data = study_format.load(text)
    except study_format.FormatError as exc:
        raise PlanError(str(exc)) from exc
    plan = plan_import(conn, semester, kind, data)
    count = apply_import(conn, semester, kind, data, colors=colors)
    existing = len([w for w in plan["warnings"] if "already exists" in w])
    return f"Imported {count} discipline{'s' if count != 1 else ''} into {semester['name']}" + (f"; {existing} already existed and were added to" if existing else "") + "."
