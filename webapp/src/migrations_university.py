"""Schema changes of the University module from migration 65 on, listed in `migrations.MIGRATIONS`. Each one can run twice."""

from __future__ import annotations

import sqlite3


def attendance(conn: sqlite3.Connection) -> None:
    """One row per class that is not simply attended: missed, excused, cancelled or made up. A past class with no row was attended."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS university_attendance (
            event_uid TEXT PRIMARY KEY,
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_university_attendance_discipline ON university_attendance(semester_uid, discipline_tag)")


def grades(conn: sqlite3.Connection) -> None:
    """The grade obtained on a way of evaluating or on one of its components, keyed by the id the course sheet gives it."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS university_grades (
            semester_uid TEXT NOT NULL,
            discipline_tag TEXT NOT NULL,
            item_id TEXT NOT NULL,
            grade REAL NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (semester_uid, discipline_tag, item_id)
        )
        """)


def sheet_teachers_to_slots(conn: sqlite3.Connection) -> None:
    """The teachers of the course sheet now come from the timetable. Where a slot named nobody, the sheet's lecture teachers (for a lecture slot) or
    seminar and lab teachers (for the others) become the teachers of its classes, so nothing entered before is lost."""
    import json

    from . import db
    from . import event_series

    for slot in conn.execute("SELECT series_uid, discipline_tag, semester_uid, kind FROM university_slots WHERE weeks != 'once'").fetchall():
        members = event_series.members(conn, slot["series_uid"])
        if not members or db.list_object_contacts(conn, "event", members[0]["uid"]):
            continue
        key = "teachers_lecture" if slot["kind"] == "lecture" else "teachers_seminar"
        row = conn.execute("SELECT value FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND key = ?",
                           (slot["semester_uid"], slot["discipline_tag"], key)).fetchone()
        try:
            uids = json.loads(row["value"]) if row else []
        except ValueError:
            uids = []
        for m in members:
            db.set_object_contacts(conn, "event", m["uid"], uids)
    conn.commit()
