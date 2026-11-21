"""Highlights and notes kept on the text of a book in the reader, by section.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

MAX_QUOTE = 2000
COLORS = ("yellow", "orange", "green", "blue", "pink")


def add(conn: sqlite3.Connection, citation_uid: str, section: int, quote: str, note: str = "", cfi: str = "", color: str = "yellow") -> str | None:
    quote = " ".join((quote or "").split())[:MAX_QUOTE]
    if not quote:
        return None
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO book_annotations (uid, citation_uid, section, quote, note, cfi, color, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (uid, citation_uid, section, quote, (note or "").strip()[:2000], (cfi or "")[:2000], color if color in COLORS else "yellow",
                  datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return uid


def listing(conn: sqlite3.Connection, citation_uid: str, section: int | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM book_annotations WHERE citation_uid = ?", [citation_uid]
    if section is not None:
        sql, args = sql + " AND section = ?", [*args, section]
    return [dict(r) for r in conn.execute(sql + " ORDER BY section, created_at", args)]


def remove(conn: sqlite3.Connection, citation_uid: str, uid: str) -> None:
    conn.execute("DELETE FROM book_annotations WHERE uid = ? AND citation_uid = ?", (uid, citation_uid))
    conn.commit()


def count(conn: sqlite3.Connection, citation_uid: str) -> int:
    return conn.execute("SELECT count(*) FROM book_annotations WHERE citation_uid = ?", (citation_uid,)).fetchone()[0]


def update(conn: sqlite3.Connection, citation_uid: str, uid: str, note: str | None = None, color: str | None = None) -> None:
    """Changes the note or the colour of a highlight; what is not given stays."""
    if note is not None:
        conn.execute("UPDATE book_annotations SET note = ? WHERE uid = ? AND citation_uid = ?", (note.strip()[:2000], uid, citation_uid))
    if color in COLORS:
        conn.execute("UPDATE book_annotations SET color = ? WHERE uid = ? AND citation_uid = ?", (color, uid, citation_uid))
    conn.commit()


def books_with_highlights(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The books that have highlights, with how many, for the picker's book filter."""
    rows = conn.execute("SELECT c.uid AS uid, c.title AS title, count(*) AS n FROM book_annotations a JOIN citations c ON c.uid = a.citation_uid "
                        "GROUP BY c.uid ORDER BY c.title COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def search(conn: sqlite3.Connection, q: str = "", books: list[str] | None = None, colors: list[str] | None = None, only_notes: bool = False,
           limit: int = 100) -> dict[str, Any]:
    """Highlights across the library, newest first: {"items": [...], "total": n}. `q` matches the quote, the note and the book's title."""
    where, args = ["1 = 1"], []
    for word in (q or "").split():
        where.append("(a.quote LIKE ? OR a.note LIKE ? OR c.title LIKE ?)")
        args += [f"%{word}%"] * 3
    if books:
        where.append(f"a.citation_uid IN ({', '.join('?' for _ in books)})")
        args += list(books)
    if colors:
        where.append(f"a.color IN ({', '.join('?' for _ in colors)})")
        args += list(colors)
    if only_notes:
        where.append("a.note != ''")
    base = f"FROM book_annotations a JOIN citations c ON c.uid = a.citation_uid WHERE {' AND '.join(where)}"
    total = conn.execute(f"SELECT count(*) {base}", args).fetchone()[0]
    rows = conn.execute(f"SELECT a.uid, a.citation_uid, a.quote, a.note, a.color, a.section, a.created_at, c.title {base} ORDER BY a.created_at DESC LIMIT ?",
                        [*args, max(1, min(limit, 200))]).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}
