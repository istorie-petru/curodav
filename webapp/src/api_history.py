"""Undoable history of the changes made through the REST API and MCP.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Each write call becomes one row of `api_changes` holding a snapshot of what it touched, before and after: one note, one
library entry, one semester, or everything of one discipline in one semester (course sheet, timetable with its classes,
evaluation with its exams, topics, readings, homework, attendance and grades). Undo puts the "before" snapshot back. When
the same things changed again since (by hand, say), undo refuses unless forced, and the undo is itself a change that
can be undone. Events and tasks go back through `db.upsert_*` and `db.delete_*`, so calendar sync sees them; the
module's own tables go back row by row. Entries are kept KEEP_DAYS days.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from . import clock, db
from .api_write import EditError

KEEP_DAYS = 7

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS api_changes (
    uid TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    token_uid TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    scope_kind TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    undone_at TEXT,
    undoes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_api_changes_at ON api_changes(at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


# ---- Snapshots ----

def _rows(conn: sqlite3.Connection, sql: str, args: list[Any] | tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _in(values: list[str] | set[str]) -> str:
    return ",".join("?" for _ in values) or "NULL"


def _note(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    doc = conn.execute("SELECT * FROM notebook_documents WHERE uid = ?", (uid,)).fetchone()
    if doc is None:
        return None
    return {"doc": dict(doc), "properties": _rows(conn, "SELECT * FROM notebook_properties WHERE notebook_uid = ? ORDER BY uid", (uid,)),
            "labels": _rows(conn, "SELECT * FROM object_labels WHERE object_type = 'notebook' AND object_id = ? ORDER BY label_name", (uid,)),
            "tags": _rows(conn, "SELECT * FROM object_tags WHERE object_type IN ('note', 'notebook') AND object_id = ? ORDER BY tag_name", (uid,))}


def _library(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM citations WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        return None
    return {"row": dict(row), "ratings": _rows(conn, "SELECT * FROM citation_ratings WHERE citation_uid = ? ORDER BY criterion_uid", (uid,))}


def _semester(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM university_semesters WHERE uid = ?", (uid,)).fetchone()
    return {"row": dict(row)} if row else None


_SCOPED = ("university_sheet", "university_slots", "university_topics", "university_milestones", "university_readings",
           "university_grades")


def _discipline(conn: sqlite3.Connection, key: list[str]) -> dict[str, Any]:
    """Every row of one discipline in one semester, and the events and tasks they own."""
    sem, name = key
    by = "WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"
    tables = {t: _rows(conn, f"SELECT * FROM {t} {by} ORDER BY rowid", (sem, name)) for t in _SCOPED}
    series = [r["series_uid"] for r in tables["university_slots"]]
    topics = [r["uid"] for r in tables["university_topics"]]
    tables["event_series"] = _rows(conn, f"SELECT * FROM event_series WHERE uid IN ({_in(series)}) ORDER BY uid", series)
    tables["university_topic_classes"] = _rows(conn, f"SELECT * FROM university_topic_classes WHERE topic_uid IN ({_in(topics)}) "
                                                     "ORDER BY topic_uid, event_uid", topics)
    event_uids = {r["uid"] for r in conn.execute(f"SELECT uid FROM events WHERE series_uid IN ({_in(series)})", series)}
    event_uids |= {r["event_uid"] for r in tables["university_milestones"] if r["event_uid"]}
    task_uids = {r["task_uid"] for r in tables["university_milestones"] if r["task_uid"]}
    task_uids |= {r["task_uid"] for r in tables["university_readings"]}
    task_uids |= {r[0] for r in conn.execute("SELECT object_id FROM object_tags WHERE object_type = 'task' AND tag_name = ? COLLATE NOCASE", (name,))}
    events, tasks = sorted(event_uids), sorted(task_uids)
    tables["university_attendance"] = _rows(conn, f"SELECT * FROM university_attendance WHERE event_uid IN ({_in(events)}) ORDER BY event_uid", events)
    links = events + tasks
    for t in ("object_tags", "object_contacts"):
        tables[t] = _rows(conn, f"SELECT * FROM {t} WHERE object_type IN ('event', 'task') AND object_id IN ({_in(links)}) "
                                f"ORDER BY object_type, object_id, {'tag_name' if t == 'object_tags' else 'contact_uid'}", links)
    tables["teacher_tags"] = _rows(conn, "SELECT * FROM object_tags WHERE object_type = 'contact' AND tag_name = ? COLLATE NOCASE ORDER BY object_id", (name,))
    return {"tables": tables, "events": [e for e in (db.get_event(conn, u) for u in events) if e],
            "tasks": [t for t in (db.get_task(conn, u) for u in tasks) if t]}


SNAPSHOTS: dict[str, Callable[[sqlite3.Connection, Any], Any]] = {
    "note": _note, "library": _library, "semester": _semester, "discipline": _discipline,
}


def take(conn: sqlite3.Connection, kind: str, key: Any) -> Any:
    return SNAPSHOTS[kind](conn, key)


# ---- Putting a snapshot back ----

def _put_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    for r in rows:
        cols = list(r)
        conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [r[c] for c in cols])


def _restore_note(conn: sqlite3.Connection, uid: str, snap: dict[str, Any] | None) -> None:
    if snap is None:
        db.delete_notebook_document(conn, uid)
        return
    content = json.loads(snap["doc"]["content_json"] or '{"blocks": []}')
    conn.execute("DELETE FROM notebook_properties WHERE notebook_uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'notebook' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM object_tags WHERE object_type IN ('note', 'notebook') AND object_id = ?", (uid,))
    _put_rows(conn, "notebook_documents", [snap["doc"]])
    _put_rows(conn, "notebook_properties", snap["properties"])
    _put_rows(conn, "object_labels", snap["labels"])
    _put_rows(conn, "object_tags", snap["tags"])
    conn.commit()
    updated = snap["doc"]["updated_at"]
    db.set_notebook_document_content(conn, uid, content)
    conn.execute("UPDATE notebook_documents SET updated_at = ? WHERE uid = ?", (updated, uid))
    conn.commit()


def _restore_library(conn: sqlite3.Connection, uid: str, snap: dict[str, Any] | None) -> None:
    from . import media_books

    if snap is None:
        media_books.delete_work(conn, uid)
        db.delete_citation(conn, uid)
        return
    conn.execute("DELETE FROM citation_ratings WHERE citation_uid = ?", (uid,))
    _put_rows(conn, "citations", [snap["row"]])
    _put_rows(conn, "citation_ratings", snap["ratings"])
    conn.commit()
    media_books.push(conn, uid)


def _restore_semester(conn: sqlite3.Connection, uid: str, snap: dict[str, Any] | None) -> None:
    if snap is None:
        if conn.execute("SELECT 1 FROM university_slots WHERE semester_uid = ? UNION SELECT 1 FROM university_sheet WHERE semester_uid = ?",
                        (uid, uid)).fetchone():
            raise EditError("invalid", "The semester has disciplines with details now; undo those changes first")
        conn.execute("DELETE FROM university_semesters WHERE uid = ?", (uid,))
    else:
        _put_rows(conn, "university_semesters", [snap["row"]])
    conn.commit()


def _restore_discipline(conn: sqlite3.Connection, key: list[str], snap: dict[str, Any] | None) -> None:
    from . import university_plan as up

    sem_uid, name = key
    if snap is None:
        semester = up.get_semester(conn, sem_uid)
        if semester is None:
            return
        try:
            up.remove_discipline(conn, semester, name)
        except up.PlanError as exc:
            raise EditError("invalid", f"{exc} Undo the later changes to {name} first.") from None
        return
    now = _discipline(conn, key)
    keep_events = {e["uid"] for e in snap["events"]}
    keep_tasks = {t["uid"] for t in snap["tasks"]}
    with up._owner():
        for e in now["events"]:
            if e["uid"] not in keep_events:
                db.delete_event(conn, e["uid"])
        for t in now["tasks"]:
            if t["uid"] not in keep_tasks:
                db.delete_task(conn, t["uid"])
        by = "WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE"
        for t in _SCOPED:
            conn.execute(f"DELETE FROM {t} {by}", (sem_uid, name))
        series = [r["series_uid"] for r in now["tables"]["university_slots"]]
        topics = [r["uid"] for r in now["tables"]["university_topics"]]
        conn.execute(f"DELETE FROM event_series WHERE uid IN ({_in(series)})", series)
        conn.execute(f"DELETE FROM university_topic_classes WHERE topic_uid IN ({_in(topics)})", topics)
        links = [e["uid"] for e in now["events"]] + [t["uid"] for t in now["tasks"]]
        conn.execute(f"DELETE FROM university_attendance WHERE event_uid IN ({_in(links)})", links)
        for t in ("object_tags", "object_contacts"):
            conn.execute(f"DELETE FROM {t} WHERE object_type IN ('event', 'task') AND object_id IN ({_in(links)})", links)
        conn.execute("DELETE FROM object_tags WHERE object_type = 'contact' AND tag_name = ? COLLATE NOCASE", (name,))
        conn.commit()
        for e in snap["events"]:
            db.upsert_event(conn, dict(e))
        for t in snap["tasks"]:
            db.upsert_task(conn, dict(t))
        for table, rows in snap["tables"].items():
            _put_rows(conn, "object_tags" if table == "teacher_tags" else table, rows)
        conn.commit()


RESTORES: dict[str, Callable[[sqlite3.Connection, Any, Any], None]] = {
    "note": _restore_note, "library": _restore_library, "semester": _restore_semester, "discipline": _restore_discipline,
}


# ---- Recording and undoing ----

def _prune(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM api_changes WHERE at < ?", ((clock.now() - timedelta(days=KEEP_DAYS)).isoformat(),))


def record(conn: sqlite3.Connection, *, tool: str, summary: str, kind: str, key: Any, before: Any, after: Any, source: str,
           token_uid: str = "", undoes: str = "") -> str:
    uid = str(uuid.uuid4())
    _prune(conn)
    conn.execute("INSERT INTO api_changes (uid, at, token_uid, source, tool, summary, scope_kind, scope_key, before_json, after_json, undoes) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (uid, clock.now().isoformat(), token_uid, source, tool, summary[:200], kind, json.dumps(key), json.dumps(before, default=str),
                  json.dumps(after, default=str), undoes))
    conn.commit()
    return uid


def tracked(conn: sqlite3.Connection, *, tool: str, summary: str, kind: str, key: Any, run: Callable[[], Any], source: str,
            token_uid: str = "", key_after: Callable[[Any], Any] | None = None) -> Any:
    """Runs one write with its before and after snapshots recorded. `key` None means the thing does not exist yet;
    `key_after` then names it from the result."""
    before = take(conn, kind, key) if key is not None else None
    result = run()
    final_key = key_after(result) if key_after else key
    record(conn, tool=tool, summary=summary, kind=kind, key=final_key, before=before, after=take(conn, kind, final_key),
           source=source, token_uid=token_uid)
    return result


def list_changes(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    """The changes of the last KEEP_DAYS days, newest first, with the name of the token that made them."""
    since = (clock.now() - timedelta(days=KEEP_DAYS)).isoformat()
    return _rows(conn, "SELECT c.uid, c.at, c.source, c.tool, c.summary, c.undone_at, c.undoes, coalesce(t.name, '') AS token_name "
                       "FROM api_changes c LEFT JOIN api_tokens t ON t.uid = c.token_uid WHERE c.at >= ? ORDER BY c.at DESC, c.rowid DESC LIMIT ?",
                 (since, limit))


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def undo(conn: sqlite3.Connection, change_uid: str, *, force: bool = False, source: str = "web", token_uid: str = "") -> str:
    """Puts back what the change replaced; returns the uid of the new change that records the undo."""
    row = conn.execute("SELECT * FROM api_changes WHERE uid = ?", (change_uid,)).fetchone()
    if row is None:
        raise EditError("not_found", "That change is no longer kept")
    if row["undone_at"]:
        raise EditError("invalid", "That change is already undone")
    kind, key = row["scope_kind"], json.loads(row["scope_key"])
    before, after = json.loads(row["before_json"] or "null"), json.loads(row["after_json"] or "null")
    now = take(conn, kind, key)
    if not force and not _same(json.loads(json.dumps(now, default=str)), after):
        raise EditError("conflict", "It was changed again since")
    RESTORES[kind](conn, key, before)
    conn.execute("UPDATE api_changes SET undone_at = ? WHERE uid = ?", (clock.now().isoformat(), change_uid))
    conn.commit()
    return record(conn, tool="undo", summary=f"Undo: {row['summary']}", kind=kind, key=key, before=now,
                  after=take(conn, kind, key), source=source, token_uid=token_uid, undoes=change_uid)


# ---- Which thing a tool changes ----

def _rename_state(conn: sqlite3.Connection, key: list[str]) -> dict[str, Any]:
    from . import university_plan as up

    sem_uid, _old, new = key
    semester = up.get_semester(conn, sem_uid)
    names = {d["name"] for d in up.disciplines(conn, semester)} if semester else set()
    return {"name": new if new in names else None}


def _restore_rename(conn: sqlite3.Connection, key: list[str], snap: Any) -> None:
    from . import university_plan as up
    from .api_university import _colors

    sem_uid, old, new = key
    semester = up.get_semester(conn, sem_uid)
    look = next((d for d in up.disciplines(conn, semester) if d["name"] == new), None) if semester else None
    if look is None:
        raise EditError("not_found", f"No discipline named {new} to rename back")
    up.save_discipline(conn, semester, old=new, name=old, color=look.get("color") or "gray", icon=look.get("icon") or "",
                       teacher_names=None, colors=_colors())


SNAPSHOTS["rename"] = _rename_state


def _undo_rename(conn: sqlite3.Connection, key: list[str], before: Any) -> None:
    if before == "renamed-from":
        _restore_rename(conn, key, before)
    else:
        sem_uid, old, new = key
        _restore_rename(conn, [sem_uid, new, old], before)


RESTORES["rename"] = _undo_rename

_LABELS = {
    "edit_note": "Edited note", "rename_note": "Renamed note", "set_note_tag": "Changed the tag of", "set_note_properties": "Changed the properties of",
    "restore_note_version": "Restored an earlier version of", "create_note": "Created note", "library_save_entry": "Saved library entry",
    "library_set_tracking": "Changed tracking of", "university_save_semester": "Saved semester", "university_save_discipline": "Saved discipline",
    "university_set_course_sheet": "Filled the course sheet of", "university_set_teachers": "Set the teachers of",
    "university_save_class_slot": "Changed the timetable of", "university_save_evaluation": "Changed the evaluation of",
    "university_set_topics": "Set the topics of", "university_save_reading": "Saved a reading of", "university_save_homework": "Saved homework of",
}


def scope_for(conn: sqlite3.Connection, tool: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """What `tool` with `args` will change: kind, key (None when it does not exist yet), summary and how to name it after.
    None when the tool changes nothing or its target cannot be found (the tool then reports the problem itself)."""
    from . import api_service, note_versions

    label = _LABELS.get(tool)
    if label is None:
        return None
    if tool in ("edit_note", "rename_note", "set_note_tag", "set_note_properties", "restore_note_version"):
        uid = args.get("uid")
        if tool == "restore_note_version":
            version = note_versions.get_version(conn, args.get("version_uid") or "")
            uid = version["note_uid"] if version else None
        doc = db.get_notebook_document(conn, uid) if uid else None
        return {"kind": "note", "key": uid, "summary": f"{label} {doc['title'] if doc else ''}".strip()} if doc else None
    if tool == "create_note":
        return {"kind": "note", "key": None, "summary": f"{label} {args.get('title') or ''}".strip(), "key_after": lambda r: r["uid"]}
    if tool in ("library_save_entry", "library_set_tracking"):
        uid = args.get("uid")
        if uid:
            c = db.get_citation_raw(conn, uid)
            return {"kind": "library", "key": uid, "summary": f"{label} {c['title']}"} if c else None
        title = (args.get("entry") or {}).get("title") or ""
        return {"kind": "library", "key": None, "summary": f"{label} {title}".strip(), "key_after": lambda r: r["uid"]}
    try:
        semester = api_service._semester(conn, args.get("semester_uid") or (args.get("uid") if tool == "university_save_semester" else ""))
    except api_service.NotFound:
        return None
    if tool == "university_save_semester":
        if args.get("uid") and semester:
            return {"kind": "semester", "key": semester["uid"], "summary": f"{label} {semester['name']}"}
        return {"kind": "semester", "key": None, "summary": f"{label} {args.get('name') or ''}".strip(), "key_after": lambda r: r["semester_uid"]}
    if semester is None:
        return None
    from . import university_plan as up

    names = {d["name"].lower(): d["name"] for d in up.disciplines(conn, semester)}
    if tool == "university_save_discipline":
        old = names.get((args.get("old_name") or "").strip().lower())
        new = (args.get("name") or "").strip()
        if old and old.lower() != new.lower():
            return {"kind": "rename", "key": [semester["uid"], old, new], "summary": f"Renamed discipline {old} to {new}",
                    "before": "renamed-from"}
        current = names.get((old or new).lower())
        if current:
            return {"kind": "discipline", "key": [semester["uid"], current], "summary": f"{label} {current}"}
        return {"kind": "discipline", "key": None, "summary": f"Added discipline {new}",
                "key_after": lambda r: [semester["uid"], r["discipline"]]}
    current = names.get((args.get("discipline") or "").strip().lower())
    return {"kind": "discipline", "key": [semester["uid"], current], "summary": f"{label} {current}"} if current else None


def run_tracked(conn: sqlite3.Connection, tool: str, args: dict[str, Any], run: Callable[[], Any], *, source: str,
                token_uid: str = "") -> Any:
    """Runs a write tool and records it when it changes something that can be undone."""
    scope = scope_for(conn, tool, args)
    if scope is None:
        return run()
    if scope["kind"] == "rename":
        result = run()
        record(conn, tool=tool, summary=scope["summary"], kind="rename", key=scope["key"], before="renamed-from",
               after=take(conn, "rename", scope["key"]), source=source, token_uid=token_uid)
        return result
    return tracked(conn, tool=tool, summary=scope["summary"], kind=scope["kind"], key=scope["key"], run=run, source=source,
                   token_uid=token_uid, key_after=scope.get("key_after"))
