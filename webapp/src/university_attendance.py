"""University attendance: whether each class was attended, missed, excused, marked present, cancelled or made up, and how many absences a discipline still allows.

A past class with no row in `university_attendance` was attended, so nothing has to be marked after an ordinary week. A cancelled class
keeps its event with the status `archived` (CANCELLED on the phone), so it leaves the calendar's count without being deleted. Excused, marked present (missed in fact, but the teacher wrote
the student present), cancelled and made-up classes are not absences. The limit is "at most N absences" per class kind, on the Teaching section of the course
sheet; no number means no limit. Feature notes: curodav-notes/documentation/features/university-module.md.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from . import clock, db
from . import university_plan as up

STATUSES = {"attended": "Attended", "missed": "Missed", "excused": "Excused", "marked_present": "Marked present", "cancelled": "Cancelled", "made_up": "Made up"}
TONES = {"attended": "green", "missed": "red", "excused": "orange", "marked_present": "teal", "cancelled": "gray", "made_up": "blue"}
KINDS = ("lecture", "seminar", "lab")
LIMIT_KEYS = {kind: f"absences_{kind}" for kind in KINDS}


def _class(conn: sqlite3.Connection, event_uid: str) -> tuple[dict[str, Any], sqlite3.Row]:
    event = db.get_event(conn, event_uid)
    slot = conn.execute("SELECT * FROM university_slots WHERE series_uid = ?", (event.get("series_uid") if event else None,)).fetchone()
    if not event or not slot:
        raise up.PlanError("That event is not a class of the semester")
    return event, slot


def statuses_of(conn: sqlite3.Connection, event_uids: list[str]) -> dict[str, dict[str, str]]:
    if not event_uids:
        return {}
    rows = conn.execute("SELECT event_uid, status, note FROM university_attendance WHERE event_uid IN (SELECT value FROM json_each(?))",
                        (json.dumps(event_uids),)).fetchall()
    return {r["event_uid"]: {"status": r["status"], "note": r["note"]} for r in rows}


def _mark(conn: sqlite3.Connection, event_uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM university_attendance WHERE event_uid = ?", (event_uid,)).fetchone()


def set_status(conn: sqlite3.Connection, event_uid: str, status: str, note: str = "") -> None:
    """Marks one class. Attended with no note removes the row. A class is never deleted or cancelled from the calendar: a missed, excused or marked-present one stays
    where it was (the calendar draws it faded) and a made-up one is moved with `make_up`. Any other mark on a class that was moved puts it back at its
    own time. Cancelled archives the event (CANCELLED on the phone) and the calendar still draws it faded."""
    if status not in STATUSES:
        raise up.PlanError("Pick attended, missed, excused, marked present, cancelled or made up")
    event, slot = _class(conn, event_uid)
    note = (note or "").strip()
    old = _mark(conn, event_uid)
    if old and old["moved_start"] and status != "made_up":
        event = _put_back(conn, event, old)
    if status == "made_up" and not (old and old["moved_start"]):
        raise up.PlanError("Pick the new date of a made-up class")
    if status == "attended" and not note:
        conn.execute("DELETE FROM university_attendance WHERE event_uid = ?", (event_uid,))
    else:
        origin = (old["original_start"], old["original_end"]) if old and old["original_start"] else (event["start_at"], event.get("end_at") or "")
        moved = (old["moved_start"], old["moved_end"]) if old and status == "made_up" else ("", "")
        conn.execute("INSERT INTO university_attendance (event_uid, semester_uid, discipline_tag, status, note, updated_at, kind, original_start, original_end, moved_start, moved_end) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_uid) DO UPDATE SET status = excluded.status, note = excluded.note, updated_at = excluded.updated_at, "
                     "kind = excluded.kind, original_start = excluded.original_start, original_end = excluded.original_end, moved_start = excluded.moved_start, moved_end = excluded.moved_end",
                     (event_uid, slot["semester_uid"], slot["discipline_tag"], status, note, up._now(), slot["kind"], *origin, *moved))
    wanted = "archived" if status == "cancelled" else "active"
    if (event.get("status") or "active") != wanted:
        db.upsert_event(conn, {**event, "status": wanted, "updated_at": up._now()})
    conn.commit()


def _put_back(conn: sqlite3.Connection, event: dict[str, Any], mark: sqlite3.Row) -> dict[str, Any]:
    event = {**event, "start_at": mark["original_start"], "end_at": mark["original_end"] or mark["original_start"], "updated_at": up._now()}
    db.upsert_event(conn, event)
    conn.execute("UPDATE university_attendance SET moved_start = '', moved_end = '' WHERE event_uid = ?", (event["uid"],))
    return event


def make_up(conn: sqlite3.Connection, event_uid: str, start_at: str, end_at: str, note: str = "") -> None:
    """A missed class made up another day: the same occurrence is moved to the new time and marked made up. Its own time is kept, so marking it
    anything else (or `set_status` attended) puts it back. Moving it again keeps the first time."""
    event, slot = _class(conn, event_uid)
    end_at = end_at or start_at
    if end_at <= start_at:
        raise up.PlanError("The class ends before it starts")
    old = _mark(conn, event_uid)
    origin = (old["original_start"], old["original_end"]) if old and old["original_start"] else (event["start_at"], event.get("end_at") or "")
    db.upsert_event(conn, {**event, "start_at": start_at, "end_at": end_at, "status": "active", "updated_at": up._now()})
    conn.execute("INSERT INTO university_attendance (event_uid, semester_uid, discipline_tag, status, note, updated_at, kind, original_start, original_end, moved_start, moved_end) "
                 "VALUES (?, ?, ?, 'made_up', ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(event_uid) DO UPDATE SET status = 'made_up', note = excluded.note, updated_at = excluded.updated_at, "
                 "kind = excluded.kind, original_start = excluded.original_start, original_end = excluded.original_end, moved_start = excluded.moved_start, moved_end = excluded.moved_end",
                 (event_uid, slot["semester_uid"], slot["discipline_tag"], (note or (old["note"] if old else "")).strip(), up._now(), slot["kind"], *origin, start_at, end_at))
    conn.commit()


def reattach(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> int:
    """After a timetable edit rebuilt a discipline's class events, puts every mark whose event is gone on the new event of the same kind that starts on
    the day the mark was made for, and moves that event again if the mark was a made-up class. Returns how many marks were repaired. Safe to repeat."""
    fixed = 0
    rows = conn.execute("SELECT * FROM university_attendance WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND original_start != ''", (semester_uid, discipline)).fetchall()
    for r in rows:
        if db.get_event(conn, r["event_uid"]):
            continue
        day = r["original_start"][:10]
        target = next((e for e in up.class_events(conn, semester_uid, discipline, r["kind"] or None) if e["start_at"][:10] == day and not _mark(conn, e["uid"])), None)
        if not target:
            continue
        conn.execute("UPDATE university_attendance SET event_uid = ? WHERE event_uid = ?", (target["uid"], r["event_uid"]))
        if r["moved_start"]:
            db.upsert_event(conn, {**target, "start_at": r["moved_start"], "end_at": r["moved_end"] or r["moved_start"], "updated_at": up._now()})
        elif r["status"] == "cancelled":
            db.upsert_event(conn, {**target, "status": "archived", "updated_at": up._now()})
        fixed += 1
    conn.commit()
    return fixed


def for_event(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any] | None:
    """The attendance of an event that is a class of the semester, for the calendar's event window; None for any other event."""
    row = conn.execute("SELECT discipline_tag, kind FROM university_slots WHERE series_uid = ?", (event.get("series_uid"),)).fetchone() if event.get("series_uid") else None
    if not row:
        return None
    mark = statuses_of(conn, [event["uid"]]).get(event["uid"]) or {"status": "", "note": ""}
    stored = _mark(conn, event["uid"])
    mark = {**mark, "moved_start": stored["moved_start"] if stored else ""}
    status = mark["status"] or ("attended" if (event.get("start_at") or "") < clock.local_now().strftime("%Y-%m-%dT%H:%M") else "")
    return {"discipline": row["discipline_tag"], "kind": up.SLOT_KINDS.get(row["kind"], "Class"), "status": status, "label": STATUSES.get(status, "Not held yet"),
            "note": mark["note"], "choices": [(k, v) for k, v in STATUSES.items() if k != status], "moved": bool(mark.get("moved_start"))}


def _number(value: Any) -> float | None:
    try:
        return float(str(value or "").replace(",", ".")) if str(value or "").strip() else None
    except ValueError:
        return None


def settings(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, dict[str, Any]]:
    """Per class kind, what the course sheet says about absences: a percent of the classes that may be missed, and a number that overrides it."""
    values = up.get_sheet(conn, semester_uid, discipline)["values"]
    out = {}
    for kind in KINDS:
        number, pct = _number(values.get(LIMIT_KEYS[kind])), _number(values.get(f"absences_pct_{kind}"))
        out[kind] = {"number": None if number is None else int(number), "percent": pct}
    return out


def limits(conn: sqlite3.Connection, semester_uid: str, discipline: str, totals: dict[str, int] | None = None) -> dict[str, int | None]:
    """The absences each class kind allows: the number set by hand, else the percent of the kind's classes rounded down, else no limit."""
    out: dict[str, int | None] = {}
    for kind, s in settings(conn, semester_uid, discipline).items():
        if s["number"] is not None:
            out[kind] = s["number"]
        elif s["percent"] is not None and totals is not None:
            out[kind] = int(s["percent"] / 100 * totals.get(kind, 0))
        else:
            out[kind] = None
    return out


def _row(c: dict[str, Any], mark: dict[str, str] | None) -> dict[str, Any]:
    status = mark["status"] if mark else ("attended" if c["past"] else "")
    return {**c, "status": status, "status_label": STATUSES.get(status, "Coming"), "tone": TONES.get(status, "gray"),
            "note": mark["note"] if mark else "", "counts": status == "missed"}


def discipline_attendance(conn: sqlite3.Connection, semester_uid: str, discipline: str, today: date | None = None) -> dict[str, Any]:
    """Every class of one discipline with its status, and per class kind: held, missed, the limit and how many absences are left."""
    today = today or clock.today()
    classes = up.list_classes(conn, semester_uid, discipline, today)
    marks = statuses_of(conn, [c["uid"] for c in classes])
    rows = [_row(c, marks.get(c["uid"])) for c in classes]
    caps = limits(conn, semester_uid, discipline, {k: len([r for r in rows if r["kind"] == k and r["status"] != "cancelled"]) for k in KINDS})
    kinds = []
    for kind in KINDS:
        of_kind = [r for r in rows if r["kind"] == kind]
        if not of_kind:
            continue
        held = [r for r in of_kind if r["past"] and r["status"] != "cancelled"]
        missed = len([r for r in held if r["counts"]])
        cap = caps.get(kind)
        left = None if cap is None else cap - missed
        kinds.append({"kind": kind, "label": up.SLOT_KINDS[kind], "total": len([r for r in of_kind if r["status"] != "cancelled"]), "held": len(held),
                      "missed": missed, "limit": cap, "left": left, "over": left is not None and left < 0, "at_risk": left is not None and 0 <= left <= 1})
    return {"classes": rows, "kinds": kinds, "missed": [r for r in rows if r["status"] == "missed"],
            "over": any(k["over"] for k in kinds), "at_risk": any(k["at_risk"] for k in kinds)}


def semester_attendance(conn: sqlite3.Connection, semester: dict[str, Any], today: date | None = None) -> list[dict[str, Any]]:
    """One entry per discipline that has classes, for the Attendance page of the semester."""
    out = []
    for d in up.disciplines(conn, semester):
        data = discipline_attendance(conn, semester["uid"], d["name"], today)
        if data["kinds"]:
            out.append({"discipline": d, **data})
    return out


def move_class(conn: sqlite3.Connection, event_uid: str, start_at: str, end_at: str) -> str:
    """A class dragged or edited to another time is made up: the same occurrence moves and is marked made up. Returns its uid."""
    make_up(conn, event_uid, start_at, end_at)
    return event_uid
