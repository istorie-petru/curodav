"""Bookmarks in a book: a place with a label, kept apart from highlights.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def add(conn: sqlite3.Connection, citation_uid: str, section: int, cfi: str, label: str, fraction: float) -> str:
    uid = str(uuid.uuid4())
    conn.execute("INSERT INTO book_bookmarks (uid, citation_uid, section, cfi, label, fraction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (uid, citation_uid, section, (cfi or "")[:2000], " ".join((label or "").split())[:200], max(0.0, min(1.0, float(fraction))),
                  datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return uid


def listing(conn: sqlite3.Connection, citation_uid: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM book_bookmarks WHERE citation_uid = ? ORDER BY fraction, created_at", (citation_uid,))]


def remove(conn: sqlite3.Connection, citation_uid: str, uid: str) -> None:
    conn.execute("DELETE FROM book_bookmarks WHERE uid = ? AND citation_uid = ?", (uid, citation_uid))
    conn.commit()
