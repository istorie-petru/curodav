"""What the API and MCP did, in plain words: a short "what" and a "where" for each call, grouped into visits.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

A visit is one token's calls with no pause longer than VISIT_GAP between them, shown as one entry (who and when) that
opens to the calls.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

VISIT_GAP = timedelta(minutes=10)

WHAT = {
    "search": "Search", "list_notes": "List notes", "get_note": "Read note", "list_citations": "List library",
    "get_citation": "Read library entry", "list_entries": "List entries", "get_entry": "Read entry", "list_entry_kinds": "List entry kinds",
    "list_tasks": "List tasks", "get_task": "Read task", "list_events": "List events", "get_event": "Read event",
    "media_now": "Reading and watching", "university_overview": "Semester", "list_exams": "Exams", "get_discipline": "Read discipline",
    "list_organisation": "Spaces and tags", "list_note_versions": "Note versions", "edit_note": "Edit note",
    "restore_note_version": "Restore note version", "create_note": "Create note", "rename_note": "Rename note", "set_note_tag": "Tag note",
    "set_note_properties": "Note properties", "library_entry_types": "Library types", "library_save_entry": "Save library entry",
    "library_set_tracking": "Track library entry", "university_save_semester": "Save semester", "university_save_discipline": "Save discipline",
    "university_set_course_sheet": "Course sheet", "university_set_teachers": "Teachers", "university_save_class_slot": "Timetable",
    "university_save_evaluation": "Evaluation", "university_set_topics": "Topics", "university_save_reading": "Reading",
    "university_save_homework": "Homework",
}


def _title(conn: sqlite3.Connection, table: str, column: str, uid: str) -> str:
    row = conn.execute(f"SELECT {column} FROM {table} WHERE uid = ?", (uid,)).fetchone() if uid else None
    return (row[0] or "") if row else ""


def describe_tool(conn: sqlite3.Connection, name: str, args: Any) -> tuple[str, str]:
    """(what, where) for one MCP tool call."""
    args = args if isinstance(args, dict) else {}
    what = WHAT.get(name, name or "Unknown tool")
    uid = str(args.get("uid") or "")
    if args.get("query"):
        where = f"“{args['query']}”"
    elif name in ("get_note", "edit_note", "rename_note", "set_note_tag", "set_note_properties", "list_note_versions"):
        where = _title(conn, "notebook_documents", "title", uid)
    elif name in ("get_citation", "library_set_tracking") or (name == "library_save_entry" and uid):
        where = _title(conn, "citations", "title", uid)
    elif name == "library_save_entry":
        where = str((args.get("entry") or {}).get("title") or "")
    elif name in ("get_task",):
        where = _title(conn, "tasks", "title", uid)
    elif name in ("get_event",):
        where = _title(conn, "events", "title", uid)
    elif name in ("get_entry",):
        where = _title(conn, "glossary_terms", "term", uid)
    elif name in ("create_note", "university_save_semester"):
        where = str(args.get("title") or args.get("name") or "")
    else:
        where = str(args.get("discipline") or args.get("name") or args.get("shelf") or args.get("tag") or args.get("q") or "")
    return what, where[:120]


_PATHS = {"search": "Search", "notes": "Notes", "citations": "Library", "entries": "Entries", "entry-kinds": "Entry kinds",
          "tasks": "Tasks", "events": "Events", "organisation": "Spaces and tags", "media": "Reading and watching",
          "university": "University", "note-versions": "Note version"}


def describe_request(conn: sqlite3.Connection, method: str, path: str, query: str = "") -> tuple[str, str]:
    """(what, where) for one REST call, from its method and path."""
    parts = [p for p in path.removeprefix("/api/v1/").split("/") if p]
    area = _PATHS.get(parts[0], parts[0]) if parts else "API"
    verb = {"GET": "Read" if len(parts) > 1 else "List", "PATCH": "Edit", "POST": "Change"}.get(method, method)
    where = ""
    if len(parts) > 1 and parts[0] == "notes":
        where = _title(conn, "notebook_documents", "title", parts[1])
    elif len(parts) > 1 and parts[0] == "citations":
        where = _title(conn, "citations", "title", parts[1])
    elif len(parts) > 1 and parts[0] in ("tasks", "events"):
        where = _title(conn, parts[0], "title", parts[1])
    elif len(parts) > 2 and parts[0] == "university":
        where = parts[-1]
    elif query:
        where = query
    what = "Search" if area == "Search" else f"{verb} {area.lower()}" if verb in ("List", "Read", "Edit", "Change") else area
    return what, where[:120]


def visits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Activity rows (newest first) grouped into visits, newest first; each visit lists its calls oldest first."""
    out: list[dict[str, Any]] = []
    open_visit: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: r["at"]):
        at = datetime.fromisoformat(row["at"])
        key = row.get("token_uid") or row.get("token_name") or ""
        visit = open_visit.get(key)
        if visit is None or at - visit["last"] > VISIT_GAP:
            visit = {"who": row.get("token_name") or "Removed token", "start": at, "last": at, "calls": []}
            open_visit[key] = visit
            out.append(visit)
        visit["last"] = at
        visit["calls"].append(row)
    for v in out:
        v["start_local"] = v["start"].astimezone().strftime("%Y-%m-%dT%H:%M")
        v["last_local"] = v["last"].astimezone().strftime("%Y-%m-%dT%H:%M")
        for c in v["calls"]:
            c["time"] = datetime.fromisoformat(c["at"]).astimezone().strftime("%H:%M")
    return sorted(out, key=lambda v: v["start"], reverse=True)


def _legacy(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    """Rows logged before calls had a "where" keep their raw action ("tool get_note", "GET /api/v1/notes")."""
    action = row.get("action") or ""
    if action.startswith("tool "):
        return row | {"action": WHAT.get(action[5:], action[5:])}
    method, _, path = action.partition(" ")
    if path.startswith("/api/v1"):
        what, where = describe_request(conn, method, path)
        return row | {"action": what, "target": row.get("target") or where}
    return row


def recent_visits(conn: sqlite3.Connection, limit: int = 400) -> list[dict[str, Any]]:
    from . import access_tokens

    return visits([_legacy(conn, r) for r in access_tokens.recent_activity(conn, limit)])

