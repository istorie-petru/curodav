"""University attendance: whether each class was attended, missed, excused, cancelled or made up, and how many absences a discipline still allows.

A past class with no row in `university_attendance` was attended, so nothing has to be marked after an ordinary week. A cancelled class
keeps its event with the status `archived` (CANCELLED on the phone), so it leaves the calendar's count without being deleted. Excused,
cancelled and made-up classes are not absences. The limit is "at most N absences" per class kind, on the Teaching section of the course
sheet; no number means no limit. Feature notes: curodav-notes/documentation/features/university-module.md.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from . import clock, db
from . import university_plan as up

STATUSES = {"attended": "Attended", "missed": "Missed", "excused": "Excused", "cancelled": "Cancelled", "made_up": "Made up"}
TONES = {"attended": "green", "missed": "red", "excused": "orange", "cancelled": "gray", "made_up": "blue"}
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


def set_status(conn: sqlite3.Connection, event_uid: str, status: str, note: str = "") -> None:
    """Marks one class. Attended with no note removes the row; cancelling archives the event and any other status brings it back."""
    if status not in STATUSES:
        raise up.PlanError("Pick attended, missed, excused, cancelled or made up")
    event, slot = _class(conn, event_uid)
    note = (note or "").strip()
    if status == "attended" and not note:
        conn.execute("DELETE FROM university_attendance WHERE event_uid = ?", (event_uid,))
    else:
        conn.execute("INSERT INTO university_attendance (event_uid, semester_uid, discipline_tag, status, note, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(event_uid) DO UPDATE SET status = excluded.status, note = excluded.note, updated_at = excluded.updated_at",
                     (event_uid, slot["semester_uid"], slot["discipline_tag"], status, note, up._now()))
    wanted = "archived" if status == "cancelled" else "active"
    if (event.get("status") or "active") != wanted:
        db.upsert_event(conn, {**event, "status": wanted, "updated_at": up._now()})
    conn.commit()


def for_event(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any] | None:
    """The attendance of an event that is a class of the semester, for the calendar's event window; None for any other event."""
    row = conn.execute("SELECT discipline_tag, kind FROM university_slots WHERE series_uid = ?", (event.get("series_uid"),)).fetchone() if event.get("series_uid") else None
    if not row:
        return None
    mark = statuses_of(conn, [event["uid"]]).get(event["uid"]) or {"status": "", "note": ""}
    status = mark["status"] or ("attended" if (event.get("start_at") or "") < clock.local_now().strftime("%Y-%m-%dT%H:%M") else "")
    return {"discipline": row["discipline_tag"], "kind": up.SLOT_KINDS.get(row["kind"], "Class"), "status": status, "label": STATUSES.get(status, "Not held yet"),
            "note": mark["note"], "choices": [(k, v) for k, v in STATUSES.items() if k != status]}


def limits(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, int | None]:
    values = up.get_sheet(conn, semester_uid, discipline)["values"]
    out: dict[str, int | None] = {}
    for kind, key in LIMIT_KEYS.items():
        try:
            out[kind] = int(float(str(values.get(key) or "").replace(",", "."))) if str(values.get(key) or "").strip() else None
        except ValueError:
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
    caps = limits(conn, semester_uid, discipline)
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
    """A class moved to another day or hour is cancelled where it was and given back as a made-up class at the new time. Returns the new class's uid."""
    event, slot = _class(conn, event_uid)
    semester = up.get_semester(conn, slot["semester_uid"])
    set_status(conn, event_uid, "cancelled", "Moved")
    new = up.add_class(conn, semester, slot["discipline_tag"], slot["kind"], start_at[:10], start_at[11:16], (end_at or start_at)[11:16], event.get("location") or "")
    set_status(conn, new, "made_up", "")
    return new
