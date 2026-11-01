"""Media in the library: tracking fields, custom kinds, rating criteria and covers on the citations table.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import sqlite3

_TRACKING = (
    ("progress", "INTEGER NOT NULL DEFAULT 0"),
    ("progress_total", "INTEGER NOT NULL DEFAULT 0"),
    ("season", "INTEGER NOT NULL DEFAULT 0"),
    ("started_on", "TEXT NOT NULL DEFAULT ''"),
    ("finished_on", "TEXT NOT NULL DEFAULT ''"),
    ("repeats", "INTEGER NOT NULL DEFAULT 0"),
    ("score", "REAL"),
    ("summary", "TEXT NOT NULL DEFAULT ''"),
    ("cover_fetched", "TEXT NOT NULL DEFAULT ''"),
    ("cover_custom", "TEXT NOT NULL DEFAULT ''"),
    ("external_json", "TEXT NOT NULL DEFAULT '{}'"),
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def media_tracking(conn: sqlite3.Connection) -> None:
    """Statuses become kind-neutral (planned, current, finished), the 0 to 5 rating becomes a 0 to 100 score, and the tables
    for custom kinds and rating criteria appear. Safe to run twice."""
    have = _columns(conn, "citations")
    for column, ddl in _TRACKING:
        if column not in have:
            conn.execute(f"ALTER TABLE citations ADD COLUMN {column} {ddl}")
    conn.execute("UPDATE citations SET status = CASE status WHEN 'to_read' THEN 'planned' WHEN 'reading' THEN 'current' WHEN 'read' THEN 'finished' ELSE status END")
    if "rating" in have:
        conn.execute("UPDATE citations SET score = rating * 20.0 WHERE rating BETWEEN 1 AND 5 AND score IS NULL")
        conn.execute("ALTER TABLE citations DROP COLUMN rating")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citations_status ON citations(status, type)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_kinds (
            uid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT NOT NULL DEFAULT 'folder',
            verb TEXT NOT NULL DEFAULT 'read',
            unit TEXT NOT NULL DEFAULT 'none',
            position REAL NOT NULL DEFAULT 0,
            created_at TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rating_criteria (
            uid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1,
            kinds_json TEXT NOT NULL DEFAULT '[]',
            position REAL NOT NULL DEFAULT 0,
            created_at TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS citation_ratings (
            citation_uid TEXT NOT NULL,
            criterion_uid TEXT NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY (citation_uid, criterion_uid)
        )""")


def editions_in_calibre(conn: sqlite3.Connection) -> None:
    """An edition of a book or manga can be a book in the Calibre library: its uuid there and the formats it holds."""
    have = _columns(conn, "citation_editions")
    for column in ("calibre_uuid", "calibre_formats"):
        if column not in have:
            conn.execute(f"ALTER TABLE citation_editions ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation_editions_calibre ON citation_editions(calibre_uuid) WHERE calibre_uuid != ''")


def cite_an_edition(conn: sqlite3.Connection) -> None:
    """A note's bibliography can cite one edition of a work; blank cites the work."""
    if "edition_uid" not in _columns(conn, "notebook_citations"):
        conn.execute("ALTER TABLE notebook_citations ADD COLUMN edition_uid TEXT NOT NULL DEFAULT ''")


def progress_log(conn: sqlite3.Connection) -> None:
    """One row per work and day: how far it moved that day and where it ended."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media_progress_log (
            citation_uid TEXT NOT NULL,
            day TEXT NOT NULL,
            delta INTEGER NOT NULL DEFAULT 0,
            progress INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (citation_uid, day)
        )""")


def citation_series(conn: sqlite3.Connection) -> None:
    """A work can belong to a series; its volume number is the existing volume field."""
    if "series" not in _columns(conn, "citations"):
        conn.execute("ALTER TABLE citations ADD COLUMN series TEXT NOT NULL DEFAULT ''")
