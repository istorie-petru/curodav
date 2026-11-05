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


def revert_class_contents(conn: sqlite3.Connection) -> None:
    """Planned contents are no longer placed on classes: every placement is removed and, where an older version had written the topic into the
    class description, that text is taken out again. Attendance is untouched. The topic rows stay (unused) so nothing typed is lost."""
    from . import db

    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_topic_classes'").fetchone():
        return
    for r in conn.execute("SELECT DISTINCT event_uid FROM university_topic_classes").fetchall():
        event = db.get_event(conn, r["event_uid"])
        if not event:
            continue
        lines = [f"{t['number']}. {t['title']}" for t in conn.execute(
            "SELECT t.number, t.title FROM university_topic_classes c JOIN university_topics t ON t.uid = c.topic_uid WHERE c.event_uid = ? AND t.kind != 'competence' ORDER BY t.number",
            (r["event_uid"],))]
        comp = [f"{t['number']}. {t['title']}" for t in conn.execute(
            "SELECT t.number, t.title FROM university_topic_classes c JOIN university_topics t ON t.uid = c.topic_uid WHERE c.event_uid = ? AND t.kind = 'competence' ORDER BY t.number",
            (r["event_uid"],))]
        composed = "\n".join(lines + (["Competences: " + "; ".join(comp)] if comp else []))
        text = (event.get("description") or "").strip()
        if composed and text.startswith(composed):
            db.upsert_event(conn, {**event, "description": text[len(composed):].strip()})
    conn.execute("DELETE FROM university_topic_classes")
    conn.commit()


def attendance_origin(conn: sqlite3.Connection) -> None:
    """An attendance row remembers which occurrence it is about, not only the event it was made on: the class kind and the occurrence's own start and end
    (`original_*`), and where a made-up class was moved to (`moved_*`). When a timetable edit rebuilds a slot's events, `university_attendance.reattach`
    uses them to put each mark, and each move, back on the new event of the same day. Rows written before this get their origin from their event; a
    legacy made-up row (an extra class made by the old move) has no origin and stays as it was. Safe to run twice."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(university_attendance)")}
    if "kind" not in cols:
        conn.execute("ALTER TABLE university_attendance ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
    if "original_start" not in cols:
        conn.execute("ALTER TABLE university_attendance ADD COLUMN original_start TEXT NOT NULL DEFAULT ''")
    if "original_end" not in cols:
        conn.execute("ALTER TABLE university_attendance ADD COLUMN original_end TEXT NOT NULL DEFAULT ''")
    if "moved_start" not in cols:
        conn.execute("ALTER TABLE university_attendance ADD COLUMN moved_start TEXT NOT NULL DEFAULT ''")
    if "moved_end" not in cols:
        conn.execute("ALTER TABLE university_attendance ADD COLUMN moved_end TEXT NOT NULL DEFAULT ''")
    for r in conn.execute("SELECT a.event_uid, a.status, e.start_at, e.end_at, s.kind, s.weeks FROM university_attendance a JOIN events e ON e.uid = a.event_uid "
                          "JOIN university_slots s ON s.series_uid = e.series_uid WHERE a.original_start = ''").fetchall():
        legacy_extra = r["status"] == "made_up" and r["weeks"] == "once"
        conn.execute("UPDATE university_attendance SET kind = ?, original_start = ?, original_end = ? WHERE event_uid = ?",
                     (r["kind"], "" if legacy_extra else r["start_at"], "" if legacy_extra else (r["end_at"] or ""), r["event_uid"]))
    conn.commit()
