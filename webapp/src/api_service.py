"""The read side shared by the REST API (/api/v1) and the MCP server: plain functions over a connection returning JSON-ready dicts.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Words follow the app: a shelf is a label (`object_labels`), a tag is a `label_tags` row, a space is a label group.
A note's `revision` is its `updated_at`; a later write must name the revision it read.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from . import clock, db, search_index, tags
from .db.citation_library import decode_cursor, encode_cursor, list_editions, page_citations
from .notebook_markdown import blocks_to_markdown

MAX_LIMIT = 100
SEARCH_KINDS = ("note", "entry", "citation", "task", "event", "contact")


class NotFound(LookupError):
    """The uid names nothing of that kind."""


def _limit(limit: int | None, default: int = 30) -> int:
    return max(1, min(int(limit or default), MAX_LIMIT))


def _tag_names(d: dict[str, Any]) -> list[str]:
    return [t["name"] for t in d.get("tag_items") or []]


def _url(kind: str, uid: str) -> str:
    return {
        "note": f"/notebook/{uid}", "entry": f"/notebook/glossary/{uid}", "citation": f"/library/{uid}",
        "task": f"/tasks/{uid}", "event": f"/events/{uid}", "contact": f"/contacts/{uid}",
    }[kind]


# ---- Search ----

def search(conn: sqlite3.Connection, query: str, kinds: list[str] | None = None, limit: int | None = 20) -> list[dict[str, Any]]:
    """Every kind asked for, best match first across kinds."""
    limit = _limit(limit, 20)
    wanted = [k for k in (kinds or SEARCH_KINDS) if k in SEARCH_KINDS]
    hits: list[dict[str, Any]] = []
    for kind in wanted:
        if kind == "note":
            rows = search_index.search_notes(conn, query, limit)
        elif kind == "citation":
            rows = [{"kind": "citation", "uid": c["uid"], "title": c["title"], "status": c.get("type"), "date": c.get("year"),
                     "snippet": db.format_citation_display(c), "score": 0.0, "updated_at": c.get("updated_at")}
                    for c in page_citations(conn, q=query, limit=limit)["items"]]
        else:
            rows = search_index.search_kind(conn, kind, query, limit)
        hits += rows
    hits.sort(key=lambda h: h.get("score") or 0.0)
    return [{"kind": h["kind"], "uid": h["uid"], "title": h.get("title") or "", "snippet": h.get("snippet") or "",
             "status": h.get("status") or h.get("note_type") or None, "date": h.get("date"), "updated_at": h.get("updated_at"),
             "url": _url(h["kind"], h["uid"])} for h in hits[:limit]]


# ---- Notes ----

def _note_summary(d: dict[str, Any]) -> dict[str, Any]:
    return {"uid": d["uid"], "title": d.get("title") or "", "note_type": d.get("note_type") or "",
            "shelves": d.get("tags") or [], "tags": _tag_names(d), "pinned": bool(d.get("pinned")),
            "journal_week": d.get("journal_week") or "", "created_at": d.get("created_at"), "updated_at": d.get("updated_at"),
            "revision": d.get("updated_at") or "", "url": _url("note", d["uid"])}


def list_notes(conn: sqlite3.Connection, *, shelf: str = "", tag: str = "", note_type: str = "", updated_since: str = "",
               cursor: str = "", limit: int | None = None) -> dict[str, Any]:
    """Notes newest edit first, one keyset page at a time. Templates are left out."""
    limit = _limit(limit)
    where, args = ["d.is_template = 0"], []
    if shelf:
        where.append("EXISTS (SELECT 1 FROM object_labels l WHERE l.object_type = 'notebook' AND l.object_id = d.uid AND l.label_name = ? COLLATE NOCASE)")
        args.append(shelf)
    if tag:
        where.append("EXISTS (SELECT 1 FROM object_tags t WHERE t.object_type = 'note' AND t.object_id = d.uid AND t.tag_name = ?)")
        args.append(tag)
    if note_type:
        where.append("d.note_type = ?")
        args.append(note_type)
    if updated_since:
        where.append("coalesce(d.updated_at, '') >= ?")
        args.append(updated_since)
    after = decode_cursor(cursor) if cursor else None
    if after and len(after) == 2:
        where.append("(coalesce(d.updated_at, ''), d.uid) < (?, ?)")
        args += after
    rows = conn.execute(
        f"SELECT d.* FROM notebook_documents d WHERE {' AND '.join(where)} ORDER BY coalesce(d.updated_at, '') DESC, d.uid DESC LIMIT ?",
        [*args, limit + 1],
    ).fetchall()
    docs = [dict(r) for r in rows]
    more = len(docs) > limit
    docs = db._attach_tags_bulk(conn, "notebook", docs[:limit])
    last = docs[-1] if docs else None
    return {"items": [_note_summary(d) for d in docs],
            "next": encode_cursor([last.get("updated_at") or "", last["uid"]]) if more and last else ""}


def get_note(conn: sqlite3.Connection, uid: str, *, include_blocks: bool = False) -> dict[str, Any]:
    """One note: its fields, its text as Markdown, what it links to and from, its citations and entries.
    `include_blocks` adds the Editor.js blocks with their ids, so a later edit can name one block."""
    doc = db.get_notebook_document(conn, uid)
    if doc is None or doc.get("is_template"):
        raise NotFound(uid)
    content = db.get_notebook_document_content(conn, uid) or {"blocks": []}
    blocks = content.get("blocks") or []
    out = _note_summary(doc)
    out["properties"] = {p["key"]: p["value"] for p in doc.get("properties") or [] if p.get("key")}
    out["markdown"] = blocks_to_markdown(blocks)
    out["links_to"] = [{"uid": r["uid"], "title": r["title"]} for r in conn.execute(
        "SELECT d.uid, d.title FROM notebook_links l JOIN notebook_documents d ON d.uid = l.target_uid WHERE l.source_uid = ? "
        "ORDER BY d.title COLLATE NOCASE", (uid,))]
    out["linked_from"] = [{"uid": d["uid"], "title": d["title"]} for d in db.list_notebook_backlinks(conn, uid)]
    out["citations"] = [{"uid": c["uid"], "display": db.format_citation_display(c)} for c in db.list_notebook_citations(conn, uid)]
    out["entries"] = [{"uid": e["uid"], "kind": e["kind"], "name": e["names"][0] if e["names"] else ""}
                      for e in db.list_document_entry_names(conn, uid)]
    if include_blocks:
        out["blocks"] = blocks
    return out


# ---- Citations ----

def _citation_out(c: dict[str, Any]) -> dict[str, Any]:
    keep = ("uid", "type", "title", "subtitle", "authors", "editors", "year", "container_title", "publisher", "place", "edition",
            "volume", "issue", "pages", "doi", "isbn", "issn", "url", "accessed", "institution", "degree", "keywords", "note",
            "created_at", "updated_at")
    out = {k: c.get(k) for k in keep if k in c}
    out["display"] = db.format_citation_display(c)
    out["url_in_app"] = _url("citation", c["uid"])
    return out


def list_citations(conn: sqlite3.Connection, *, q: str = "", types: list[str] | None = None, cursor: str = "",
                   limit: int | None = None) -> dict[str, Any]:
    page = page_citations(conn, q=q, types=types or None, after=cursor, limit=_limit(limit))
    return {"items": [_citation_out(c) for c in page["items"]], "next": page["next"], "total": page["total"]}


def get_citation(conn: sqlite3.Connection, uid: str) -> dict[str, Any]:
    c = db.get_citation(conn, uid)
    if c is None:
        raise NotFound(uid)
    out = _citation_out(c)
    out["editions"] = [{k: e.get(k) for k in ("uid", "year", "publisher", "place", "edition", "isbn", "doi", "url", "file_label")}
                       for e in list_editions(conn, uid)]
    out["notes"] = [{"uid": r["uid"], "title": r["title"]} for r in conn.execute(
        "SELECT d.uid, d.title FROM notebook_citations nc JOIN notebook_documents d ON d.uid = nc.notebook_uid "
        "WHERE nc.citation_uid = ? AND d.is_template = 0 ORDER BY d.title COLLATE NOCASE", (uid,))]
    return out


# ---- Entries (glossary) ----

def list_entry_kinds(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [{"name": k["name"], "icon": k["icon"], "color": k["color"], "fields": k["fields"]} for k in db.list_entry_kinds(conn)]


def list_entries(conn: sqlite3.Connection, *, q: str = "", kind: str = "") -> list[dict[str, Any]]:
    return [{"uid": t["uid"], "name": t["term"], "kind": t["kind"], "aliases": t["aliases"], "url": _url("entry", t["uid"])}
            for t in db.list_glossary_terms(conn, q=q, kind=kind)]


def get_entry(conn: sqlite3.Connection, uid: str) -> dict[str, Any]:
    t = db.get_glossary_term(conn, uid)
    if t is None:
        raise NotFound(uid)
    return {"uid": t["uid"], "name": t["term"], "kind": t["kind"], "aliases": t["aliases"], "definition": t["definition"],
            "sections": [{"title": s["title"], "text": s["body"]} for s in db.list_glossary_sections(conn, uid)],
            "wiki_note_uid": t.get("wiki_uid") or None, "updated_at": t.get("updated_at"), "url": _url("entry", uid)}


# ---- Tasks and events ----

def _task_out(t: dict[str, Any]) -> dict[str, Any]:
    return {"uid": t["uid"], "title": t.get("title") or "", "description": t.get("description") or "", "status": t.get("status"),
            "start_at": t.get("start_at"), "due_at": t.get("due_at"), "completed_at": t.get("completed_at"),
            "progress": t.get("progress"), "shelves": t.get("tags") or [], "tags": _tag_names(t),
            "updated_at": t.get("updated_at"), "url": _url("task", t["uid"])}


def _page(items: list[dict[str, Any]], key, cursor: str, limit: int) -> dict[str, Any]:
    """A keyset page over an already ordered Python list; `key` gives each item's sort tuple as a JSON-ready list."""
    after = decode_cursor(cursor) if cursor else None
    if after:
        items = [i for i in items if key(i) > after]
    more = len(items) > limit
    items = items[:limit]
    return {"items": items, "next": encode_cursor(key(items[-1])) if more and items else ""}


def list_tasks(conn: sqlite3.Connection, *, status: str = "", tag: str = "", due_before: str = "", due_after: str = "",
               cursor: str = "", limit: int | None = None) -> dict[str, Any]:
    """Tasks by due date (undated last), habits left out."""
    rows = [t for t in db.list_tasks(conn, status=status or None) if not t.get("deleted_at")]
    if tag:
        rows = [t for t in rows if tag.lower() in (n.lower() for n in _tag_names(t))]
    if due_before:
        rows = [t for t in rows if t.get("due_at") and t["due_at"] < due_before]
    if due_after:
        rows = [t for t in rows if t.get("due_at") and t["due_at"] >= due_after]
    items = [_task_out(t) for t in rows]
    items.sort(key=lambda t: (t["due_at"] is None, t["due_at"] or "", t["uid"]))
    return _page(items, lambda t: [t["due_at"] is None, t["due_at"] or "", t["uid"]], cursor, _limit(limit))


def get_task(conn: sqlite3.Connection, uid: str) -> dict[str, Any]:
    t = db.get_task(conn, uid)
    if t is None or t.get("deleted_at"):
        raise NotFound(uid)
    return _task_out(t)


def _event_out(e: dict[str, Any]) -> dict[str, Any]:
    return {"uid": e["uid"], "title": e.get("title") or "", "description": e.get("description") or "", "status": e.get("status"),
            "start_at": e.get("start_at"), "end_at": e.get("end_at"), "all_day": bool(e.get("all_day")),
            "location": e.get("location") or "", "series_uid": e.get("series_uid"), "shelves": e.get("tags") or [],
            "tags": _tag_names(e), "updated_at": e.get("updated_at"), "url": _url("event", e["uid"])}


def list_events(conn: sqlite3.Connection, *, start: str = "", end: str = "", tag: str = "", cursor: str = "",
                limit: int | None = None) -> dict[str, Any]:
    """Events overlapping [start, end], earliest first."""
    rows = [e for e in db.list_events(conn, start=start or None, end=end or None) if not e.get("deleted_at")]
    if tag:
        rows = [e for e in rows if tag.lower() in (n.lower() for n in _tag_names(e))]
    items = [_event_out(e) for e in rows]
    items.sort(key=lambda e: (e["start_at"] or "", e["uid"]))
    return _page(items, lambda e: [e["start_at"] or "", e["uid"]], cursor, _limit(limit))


def get_event(conn: sqlite3.Connection, uid: str) -> dict[str, Any]:
    e = db.get_event(conn, uid)
    if e is None or e.get("deleted_at"):
        raise NotFound(uid)
    return _event_out(e)


# ---- Spaces, shelves and tags ----

def list_organisation(conn: sqlite3.Connection) -> dict[str, Any]:
    """Spaces with their shelves, and every tag with the shelf it belongs to."""
    spaces = [{"name": g["name"], "shelves": [lbl["name"] for lbl in g.get("labels") or []]} for g in db.list_groups(conn)]
    return {"spaces": spaces, "tags": [{"name": t["name"], "shelf": t["label_name"]} for t in tags.list_tags(conn)]}


# ---- University ----

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _semester(conn: sqlite3.Connection, uid: str = "") -> dict[str, Any] | None:
    from . import university_plan as up

    semester = up.get_semester(conn, uid) if uid else up.current_semester(conn)
    if uid and semester is None:
        raise NotFound(uid)
    return semester


def _discipline_url(conn: sqlite3.Connection, semester: dict[str, Any], name: str) -> str:
    from . import university_plan as up

    return f"/groups/{quote(up.semester_group(conn, semester))}/disciplines/{quote(name)}"


def _semester_out(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ("uid", "name", "start_date", "end_date", "class_end_date", "exam_start", "exam_end")}


def _attendance_out(kinds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: a[k] for k in ("kind", "label", "total", "held", "missed", "limit", "left", "over", "at_risk")} for a in kinds]


def _exam_out(m: dict[str, Any]) -> dict[str, Any]:
    return {k: m.get(k) or None for k in ("uid", "discipline", "title", "way", "weight", "date", "start", "end_day", "end", "location",
                                          "due", "notes", "status", "event_uid", "task_uid")} | {"days_left": m.get("days_left")}


def university_overview(conn: sqlite3.Connection, *, semester_uid: str = "") -> dict[str, Any]:
    """The semester with every discipline: its teachers, absences per class kind against the limit, and the grade so far."""
    from . import university_attendance as ua, university_evaluation as ue, university_plan as up

    semester = _semester(conn, semester_uid)
    if semester is None:
        return {"semester": None, "semesters": [], "disciplines": []}
    today = clock.today()
    out = []
    for d in up.disciplines(conn, semester):
        standing = ue.standing(conn, semester["uid"], d["name"], today)
        attendance = ua.discipline_attendance(conn, semester["uid"], d["name"], today)
        out.append({"name": d["name"], "teachers": [t["name"] for t in d["teachers"] if t["name"]],
                    "attendance": _attendance_out(attendance["kinds"]), "grade": standing["final"], "grade_so_far": standing["so_far"],
                    "passed": standing["passed"], "url": _discipline_url(conn, semester, d["name"])})
    return {"semester": _semester_out(semester), "semesters": [_semester_out(s) for s in up.list_semesters(conn)], "disciplines": out}


def list_exams(conn: sqlite3.Connection, *, semester_uid: str = "", discipline: str = "", upcoming: bool = False) -> dict[str, Any]:
    """Exams, tests and other graded milestones of the semester, dated ones first."""
    from . import university_evaluation as ue

    semester = _semester(conn, semester_uid)
    if semester is None:
        return {"items": []}
    items = [_exam_out(m) for m in ue.list_milestones(conn, semester["uid"], discipline or None, clock.today())]
    if upcoming:
        items = [m for m in items if m["days_left"] is not None and m["days_left"] >= 0]
    return {"items": items}


def get_discipline(conn: sqlite3.Connection, name: str, *, semester_uid: str = "") -> dict[str, Any]:
    """One discipline: timetable, ways of evaluating with grades and conditions, exams, readings and every class's attendance."""
    from . import university_attendance as ua, university_evaluation as ue, university_plan as up

    semester = _semester(conn, semester_uid)
    found = next((d for d in up.disciplines(conn, semester) if d["name"].lower() == name.lower()), None) if semester else None
    if found is None:
        raise NotFound(name)
    sid, today = semester["uid"], clock.today()
    standing = ue.standing(conn, sid, found["name"], today)
    attendance = ua.discipline_attendance(conn, sid, found["name"], today)
    return {
        "name": found["name"], "semester": _semester_out(semester), "teachers": [t["name"] for t in found["teachers"] if t["name"]],
        "timetable": [{"kind": s["kind"], "weekday": _WEEKDAYS[s["weekday"]], "start": s["start"], "end": s["end"], "room": s["room"],
                       "weeks": s["weeks"], "first": s["first"], "last": s["last"]} for s in up.list_slots(conn, sid, found["name"])],
        "evaluation": [{"name": w["name"], "weight": w["weight"], "min_grade": w["min_grade"], "grade": w["grade"], "passed": w["passed"],
                        "eligible": w["eligible"], "conditions": [{"label": r["label"], "met": r["is_met"]} for r in w["condition_rows"]]}
                       for w in standing["ways"]],
        "grade": standing["final"], "grade_so_far": standing["so_far"], "passing_grade": standing["passing"], "passed": standing["passed"],
        "exams": [_exam_out(m) for m in ue.list_milestones(conn, sid, found["name"], today)],
        "readings": [{k: r[k] for k in ("title", "author", "locator", "category_label", "due", "status", "citation_id")}
                     for r in up.list_readings(conn, sid, found["name"])],
        "attendance": _attendance_out(attendance["kinds"]),
        "classes": [{"date": c["date"], "start": c["start"], "kind": c["kind_label"], "number": c["number"], "status": c["status_label"],
                     "content": c["content"]} for c in attendance["classes"]],
        "url": _discipline_url(conn, semester, found["name"]),
    }
