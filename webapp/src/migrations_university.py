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
