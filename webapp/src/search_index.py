"""Full-text search over notes, entries, tasks, events and contacts (FTS5), used by the REST API and the MCP server.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Tasks, events, contacts and entries are kept in step by triggers, like `citations_fts`. A note's text needs Python
(Editor.js JSON with inline HTML), so a trigger only queues the note in `notes_fts_pending` and `refresh_notes`
indexes the queue before every note search.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from typing import Any

from .db.citation_library import fts_query

TOKENIZE = "tokenize='unicode61 remove_diacritics 2'"

# kind -> (source table, FTS table, title expression, body expression) over a row alias.
SOURCES = {
    "task": ("tasks", "tasks_fts", "{r}.title", "{r}.description"),
    "event": ("events", "events_fts", "{r}.title", "coalesce({r}.description, '') || ' ' || coalesce({r}.location, '')"),
    "contact": ("contacts", "contacts_fts", "{r}.full_name",
                "coalesce({r}.org, '') || ' ' || coalesce({r}.title, '') || ' ' || coalesce({r}.pseudonym, '') || ' ' "
                "|| coalesce({r}.role, '') || ' ' || coalesce({r}.notes, '')"),
    "entry": ("glossary_terms", "entries_fts", "{r}.term",
              "{r}.definition || ' ' || coalesce((SELECT group_concat(value, ' ') FROM json_each({r}.aliases_json)), '')"),
}

_TAG = re.compile(r"<[^>]+>")


def install(conn: sqlite3.Connection) -> None:
    """Creates every index table and trigger and fills them from the current rows. Safe to run twice."""
    for kind, (table, fts, title, body) in SOURCES.items():
        conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5(title, body, {TOKENIZE})")
        new_values = f"new.rowid, {title.format(r='new')}, {body.format(r='new')}"
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {fts}_insert AFTER INSERT ON {table} BEGIN "
                     f"INSERT INTO {fts}(rowid, title, body) VALUES ({new_values}); END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {fts}_delete AFTER DELETE ON {table} BEGIN "
                     f"DELETE FROM {fts} WHERE rowid = old.rowid; END")
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {fts}_update AFTER UPDATE ON {table} BEGIN "
                     f"DELETE FROM {fts} WHERE rowid = old.rowid; INSERT INTO {fts}(rowid, title, body) VALUES ({new_values}); END")
        conn.execute(f"DELETE FROM {fts}")
        conn.execute(f"INSERT INTO {fts}(rowid, title, body) SELECT rowid, {title.format(r=table)}, {body.format(r=table)} FROM {table}")
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(uid UNINDEXED, title, body, {TOKENIZE})")
    conn.execute("CREATE TABLE IF NOT EXISTS notes_fts_pending (uid TEXT PRIMARY KEY)")
    # A trigger's own OR IGNORE gives way to the firing statement's conflict policy (an upsert), so the queue insert
    # checks for the uid itself.
    queue = "INSERT INTO notes_fts_pending(uid) SELECT new.uid WHERE NOT EXISTS (SELECT 1 FROM notes_fts_pending WHERE uid = new.uid)"
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON notebook_documents BEGIN {queue}; END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE OF title, content_json ON notebook_documents BEGIN {queue}; END")
    conn.execute("CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON notebook_documents BEGIN "
                 "DELETE FROM notes_fts WHERE uid = old.uid; DELETE FROM notes_fts_pending WHERE uid = old.uid; END")
    conn.execute("DELETE FROM notes_fts")
    conn.execute("INSERT OR IGNORE INTO notes_fts_pending(uid) SELECT uid FROM notebook_documents")


def _strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        if not value.startswith("data:"):
            out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)


def note_plain_text(content_json: str) -> str:
    """The prose of a note: every string in its blocks' data, with inline markup removed."""
    try:
        blocks = json.loads(content_json or "{}").get("blocks") or []
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ""
    out: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            _strings(block.get("data"), out)
    return re.sub(r"\s+", " ", " ".join(html.unescape(_TAG.sub(" ", s)) for s in out)).strip()


def refresh_notes(conn: sqlite3.Connection) -> int:
    """Indexes the queued notes and returns how many were done."""
    uids = [r[0] for r in conn.execute("SELECT uid FROM notes_fts_pending").fetchall()]
    for uid in uids:
        conn.execute("DELETE FROM notes_fts WHERE uid = ?", (uid,))
        row = conn.execute("SELECT title, content_json FROM notebook_documents WHERE uid = ?", (uid,)).fetchone()
        if row is not None:
            conn.execute("INSERT INTO notes_fts(uid, title, body) VALUES (?, ?, ?)", (uid, row[0] or "", note_plain_text(row[1])))
        conn.execute("DELETE FROM notes_fts_pending WHERE uid = ?", (uid,))
    if uids:
        conn.commit()
    return len(uids)


def _snippet(fts: str) -> str:
    return f"snippet({fts}, -1, '[', ']', '…', 12)"


def search_notes(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Notes (templates left out) best match first, each with a short snippet around the matched words."""
    match = fts_query(query)
    if not match:
        return []
    refresh_notes(conn)
    rows = conn.execute(
        f"SELECT d.uid, d.title, d.note_type, d.updated_at, {_snippet('notes_fts')} AS snippet, bm25(notes_fts, 0, 4, 1) AS score "
        "FROM notes_fts JOIN notebook_documents d ON d.uid = notes_fts.uid "
        "WHERE notes_fts MATCH ? AND d.is_template = 0 ORDER BY score LIMIT ?",
        (match, limit),
    ).fetchall()
    return [dict(r) | {"kind": "note"} for r in rows]


_EXTRA = {
    "task": "s.status, s.due_at AS date",
    "event": "s.status, s.start_at AS date",
    "contact": "NULL AS status, NULL AS date",
    "entry": "s.kind AS status, NULL AS date",
}
_LIVE = {"task": "s.deleted_at IS NULL", "event": "s.deleted_at IS NULL", "contact": "s.deleted_at IS NULL", "entry": "1 = 1"}


def search_kind(conn: sqlite3.Connection, kind: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Tasks, events, contacts or entries matching `query`, best match first."""
    match = fts_query(query)
    if not match:
        return []
    table, fts, title, _body = SOURCES[kind]
    rows = conn.execute(
        f"SELECT s.uid, {title.format(r='s')} AS title, {_EXTRA[kind]}, s.updated_at, {_snippet(fts)} AS snippet, "
        f"bm25({fts}, 4, 1) AS score FROM {fts} JOIN {table} s ON s.rowid = {fts}.rowid "
        f"WHERE {fts} MATCH ? AND {_LIVE[kind]} ORDER BY score LIMIT ?",
        (match, limit),
    ).fetchall()
    return [dict(r) | {"kind": kind} for r in rows]
