"""Citation editions: a work (citation) has many editions, each with its own details and PDF; the search index covers both.

Feature document: curodav-notes/documentation/features/bibliography.md
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

FTS_COLUMNS = "title, authors, container_title, publisher, isbn, doi, note, keywords, editions"
_AUTHORS = ("(SELECT group_concat(coalesce(json_extract(value, '$.family'), '') || ' ' || coalesce(json_extract(value, '$.given'), ''), ' ') "
            "FROM json_each(c.authors_json))")
_EDITIONS = ("(SELECT group_concat(e.edition || ' ' || e.year || ' ' || e.publisher || ' ' || e.place || ' ' || e.isbn || ' ' || e.doi, ' ') "
             "FROM citation_editions e WHERE e.citation_uid = c.uid)")
FTS_VALUES = (f"c.title, coalesce({_AUTHORS}, ''), c.container_title, c.publisher, c.isbn, c.doi, c.note, c.keywords_json, coalesce({_EDITIONS}, '')")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def citation_editions(conn: sqlite3.Connection) -> None:
    """Books gain status, rating and keywords; each has editions with their own details, link or PDF; the search index covers both.

    Safe on a database that ran the first form of this step: the old file columns move into a first edition and the edition label goes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS citation_editions (
            uid TEXT PRIMARY KEY,
            citation_uid TEXT NOT NULL,
            edition TEXT NOT NULL DEFAULT '',
            year TEXT NOT NULL DEFAULT '',
            publisher TEXT NOT NULL DEFAULT '',
            place TEXT NOT NULL DEFAULT '',
            isbn TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            file_label TEXT NOT NULL DEFAULT '',
            created_at TEXT
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation_editions_citation ON citation_editions(citation_uid)")
    for trigger in ("citations_fts_insert", "citations_fts_delete", "citations_fts_update",
                    "citation_editions_fts_insert", "citation_editions_fts_update", "citation_editions_fts_delete"):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    editions = _columns(conn, "citation_editions")
    if "doi" not in editions:
        conn.execute("ALTER TABLE citation_editions ADD COLUMN doi TEXT NOT NULL DEFAULT ''")
    if "label" in editions:
        conn.execute("ALTER TABLE citation_editions DROP COLUMN label")
    have = _columns(conn, "citations")
    for column, ddl in (("status", "TEXT NOT NULL DEFAULT ''"), ("rating", "INTEGER NOT NULL DEFAULT 0"), ("keywords_json", "TEXT NOT NULL DEFAULT '[]'")):
        if column not in have:
            conn.execute(f"ALTER TABLE citations ADD COLUMN {column} {ddl}")
    if "file_name" in have:
        now = datetime.now(timezone.utc).isoformat()
        for row in conn.execute("SELECT uid, file_name, file_label FROM citations WHERE file_name != ''").fetchall():
            conn.execute("INSERT INTO citation_editions (uid, citation_uid, file_name, file_label, created_at) VALUES (?, ?, ?, ?, ?)",
                         (str(uuid.uuid4()), row[0], row[1], row[2], now))
        for column in ("file_name", "file_label"):
            conn.execute(f"ALTER TABLE citations DROP COLUMN {column}")
    moved = ("edition", "publisher", "place", "isbn", "doi", "url")
    now = datetime.now(timezone.utc).isoformat()
    lone = conn.execute("SELECT uid, year, edition, publisher, place, isbn, doi, url FROM citations c WHERE (edition != '' OR publisher != '' OR place != '' OR isbn != '' OR doi != '' OR url != '') "
                        "AND NOT EXISTS (SELECT 1 FROM citation_editions e WHERE e.citation_uid = c.uid)").fetchall()
    for row in lone:
        conn.execute("INSERT INTO citation_editions (uid, citation_uid, year, edition, publisher, place, isbn, doi, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), row["uid"], row["year"], row["edition"], row["publisher"], row["place"], row["isbn"], row["doi"], row["url"], now))
    conn.execute(f"UPDATE citations SET {', '.join(f'{m} = {chr(39)}{chr(39)}' for m in moved)} WHERE EXISTS (SELECT 1 FROM citation_editions e WHERE e.citation_uid = citations.uid)")
    conn.execute("DROP TABLE IF EXISTS citations_fts")
    conn.execute(f"CREATE VIRTUAL TABLE citations_fts USING fts5({FTS_COLUMNS}, tokenize='unicode61 remove_diacritics 2')")
    cols = FTS_COLUMNS
    refresh = f"DELETE FROM citations_fts WHERE rowid = (SELECT rowid FROM citations WHERE uid = {{uid}}); INSERT INTO citations_fts(rowid, {cols}) SELECT c.rowid, {FTS_VALUES} FROM citations c WHERE c.uid = {{uid}};"
    conn.execute(f"CREATE TRIGGER citations_fts_insert AFTER INSERT ON citations BEGIN {refresh.format(uid='new.uid')} END")
    conn.execute(f"CREATE TRIGGER citations_fts_update AFTER UPDATE ON citations BEGIN DELETE FROM citations_fts WHERE rowid = old.rowid; {refresh.format(uid='new.uid')} END")
    conn.execute("CREATE TRIGGER citations_fts_delete AFTER DELETE ON citations BEGIN DELETE FROM citations_fts WHERE rowid = old.rowid; END")
    for event, uid in (("INSERT", "new.citation_uid"), ("UPDATE", "new.citation_uid"), ("DELETE", "old.citation_uid")):
        conn.execute(f"CREATE TRIGGER citation_editions_fts_{event.lower()} AFTER {event} ON citation_editions BEGIN {refresh.format(uid=uid)} END")
    conn.execute(f"INSERT INTO citations_fts(rowid, {cols}) SELECT c.rowid, {FTS_VALUES} FROM citations c")
