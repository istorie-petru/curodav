"""Candidates for the editor's mention pickers: `@` contacts, `$` tasks and events, `:` icons.

Feature notes: curodav-notes/documentation/features/notebook-editor.md.
"""

from __future__ import annotations

from typing import Any

from . import db, icon_font

LIMIT = 8


def _contains(text: str | None, query: str) -> bool:
    return not query or query.lower() in (text or "").lower()


def contacts(conn, query: str, limit: int = LIMIT) -> list[dict[str, Any]]:
    rows = db.list_contacts(conn, query or None)[:limit]
    return [{"kind": "contact", "uid": c["uid"], "title": c["full_name"], "subtitle": c.get("org") or ""} for c in rows]


def items(conn, query: str, limit: int = LIMIT) -> list[dict[str, Any]]:
    """Open tasks first, then events, then finished tasks, all matching the query by title."""
    tasks = [t for t in db.list_tasks(conn, q=query or None) if t.get("status") != "archived"]
    open_tasks = [t for t in tasks if t.get("status") != "done"]
    done_tasks = [t for t in tasks if t.get("status") == "done"]
    events = [e for e in db.list_events(conn) if _contains(e.get("title"), query)]
    events.sort(key=lambda e: e.get("start_at") or "", reverse=True)

    def task_row(t):
        return {"kind": "task", "uid": t["uid"], "title": t["title"], "subtitle": (t.get("due_at") or "")[:10]}

    def event_row(e):
        return {"kind": "event", "uid": e["uid"], "title": e["title"], "subtitle": (e.get("start_at") or "")[:10]}

    rows = [task_row(t) for t in open_tasks] + [event_row(e) for e in events] + [task_row(t) for t in done_tasks]
    return rows[:limit]


def icons(names, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Icon names containing the query, those starting with it first."""
    query = (query or "").lower()
    matches = [n for n in names if query in n and icon_font.glyph(n)]
    matches.sort(key=lambda n: (not n.startswith(query), n))
    return [{"kind": "icon", "name": n, "title": n, "char": icon_font.glyph(n)} for n in matches[:limit]]
