"""Search engine — FTS5 queries over the SQLite cache (ARCHITECTURE.md §10).

Shared by the global search bar and the command palette.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    object_id: str
    type: str
    title: str
    description: str
    status: str
    rank: float = 0.0
    highlights: dict[str, str] = field(default_factory=dict)


class SearchEngine:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def search(
        self,
        query: str,
        limit: int = 50,
        type_filter: str | None = None,
        status_filter: str | None = None,
    ) -> list[SearchResult]:
        """FTS5 search across objects.title, objects.description, note_details.body.

        Results ranked by BM25. Supports exact-prefix boost and type/status
        filtering.
        """
        if not query.strip():
            return self._list_recent(type_filter, status_filter, limit)

        fts_query = self._build_fts_query(query)
        sql = """
        SELECT o.id, o.type, o.title, o.description, o.status,
               rank
        FROM objects_fts
        JOIN objects o ON o.id = objects_fts.rowid
        WHERE objects_fts MATCH ?
        """
        params: list[Any] = [fts_query]

        if type_filter:
            sql += " AND o.type = ?"
            params.append(type_filter)
        if status_filter:
            sql += " AND o.status = ?"
            params.append(status_filter)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        cursor = self._db.execute(sql, params)
        rows = cursor.fetchall()

        return [
            SearchResult(
                object_id=row[0],
                type=row[1],
                title=row[2],
                description=row[3],
                status=row[4],
                rank=row[5],
            )
            for row in rows
        ]

    def search_by_prefix(
        self, prefix: str, limit: int = 10
    ) -> list[SearchResult]:
        """Exact prefix match on title (for autocomplete)."""
        cursor = self._db.execute(
            """
            SELECT id, type, title, description, status, 0.0
            FROM objects
            WHERE deleted_at IS NULL
              AND title LIKE ? || '%'
            ORDER BY title
            LIMIT ?
            """,
            (prefix, limit),
        )
        rows = cursor.fetchall()
        return [
            SearchResult(
                object_id=row[0],
                type=row[1],
                title=row[2],
                description=row[3],
                status=row[4],
            )
            for row in rows
        ]

    @staticmethod
    def _build_fts_query(raw: str) -> str:
        """Convert user query to FTS5 query syntax."""
        terms = raw.strip().split()
        return " AND ".join(f'"{t}"*' for t in terms if t)

    def _list_recent(
        self,
        type_filter: str | None = None,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        sql = """
        SELECT id, type, title, description, status, 0.0
        FROM objects
        WHERE deleted_at IS NULL
        """
        params: list[Any] = []
        if type_filter:
            sql += " AND type = ?"
            params.append(type_filter)
        if status_filter:
            sql += " AND status = ?"
            params.append(status_filter)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        cursor = self._db.execute(sql, params)
        rows = cursor.fetchall()
        return [
            SearchResult(
                object_id=row[0],
                type=row[1],
                title=row[2],
                description=row[3],
                status=row[4],
            )
            for row in rows
        ]
