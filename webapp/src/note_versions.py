"""Earlier versions of a note: the content as it was before a change, so a change from the editor, the API or MCP can be undone.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

A version holds the title and blocks from before a change and says who made the change (`source`: web, api or mcp,
with the token). The editor saves every few seconds, so a web save keeps a version only when the newest one came from
the API or MCP, or is older than WEB_EVERY. The last KEEP versions of each note are kept.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from . import clock

KEEP = 20
WEB_EVERY = timedelta(minutes=15)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS note_versions (
    uid TEXT PRIMARY KEY,
    note_uid TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content_json TEXT NOT NULL,
    revision TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    token_uid TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_versions_note ON note_versions(note_uid, created_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def save(conn: sqlite3.Connection, note_uid: str, *, source: str, token_uid: str = "", summary: str = "") -> str | None:
    """Keeps the note as it is now; returns the version uid, or None when the note does not exist. Does not commit."""
    row = conn.execute("SELECT title, content_json, updated_at FROM notebook_documents WHERE uid = ?", (note_uid,)).fetchone()
    if row is None:
        return None
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO note_versions (uid, note_uid, title, content_json, revision, source, token_uid, summary, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (uid, note_uid, row["title"] or "", row["content_json"] or '{"blocks": []}', row["updated_at"] or "", source, token_uid,
                  summary[:200], clock.now().isoformat()))
    conn.execute("DELETE FROM note_versions WHERE note_uid = ? AND uid NOT IN "
                 "(SELECT uid FROM note_versions WHERE note_uid = ? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                 (note_uid, note_uid, KEEP))
    return uid


def list_versions(conn: sqlite3.Connection, note_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT uid, title, revision, source, summary, created_at FROM note_versions WHERE note_uid = ? "
                        "ORDER BY created_at DESC, rowid DESC", (note_uid,)).fetchall()
    return [dict(r) for r in rows]


def get_version(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM note_versions WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def save_before_web_save(conn: sqlite3.Connection, note_uid: str) -> str | None:
    """Keeps a version before the editor's save when the rule in the module docstring asks for one. Does not commit."""
    current = conn.execute("SELECT content_json FROM notebook_documents WHERE uid = ?", (note_uid,)).fetchone()
    try:
        empty = current is None or not (json.loads(current["content_json"] or "{}").get("blocks"))
    except (json.JSONDecodeError, TypeError, AttributeError):
        empty = False
    if empty:
        return None
    row = conn.execute("SELECT source, created_at FROM note_versions WHERE note_uid = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                       (note_uid,)).fetchone()
    if row and row["source"] == "web" and clock.now() - datetime.fromisoformat(row["created_at"]) < WEB_EVERY:
        return None
    return save(conn, note_uid, source="web")
