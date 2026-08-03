"""SQLite database manager for the query cache.

Opens/creates the local SQLite DB, applies schema, provides connection access,
and can rebuild the cache from the file tree.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..models import Object, ObjectType
from .schema import SCHEMA_SQL


class Database:
    """Synchronous SQLite wrapper for the query cache."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or Path.home() / ".command_center" / "cache.sqlite"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def open(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not opened")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params: list[tuple]) -> None:
        self.conn.executemany(sql, params)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Cache rebuild

    def rebuild_from_path(self, file_tree_path: Path) -> int:
        """Walk *file_tree_path/objects/* and populate the cache.

        Returns the number of objects inserted/updated.
        """
        objects_dir = file_tree_path / "objects"
        if not objects_dir.exists():
            return 0

        count = 0
        for child in sorted(objects_dir.iterdir()):
            if not child.is_dir():
                continue
            obj_file = child / "object.json"
            if not obj_file.exists():
                continue
            try:
                data = json.loads(obj_file.read_text(encoding="utf-8"))
                self._upsert_from_dict(child.name, data)
                count += 1
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        self.commit()
        return count

    # ------------------------------------------------------------------ #
    # Incremental updates

    def upsert_object(self, obj: Object) -> None:
        """Insert or replace a single object in the cache."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO objects
                (id, workspace_id, type, title, description, icon, cover_path,
                 status, priority, progress, start_at, due_at, pinned,
                 parent_id, sort_key, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obj.id,
                obj.workspace_id,
                obj.type.value,
                obj.title,
                obj.description,
                obj.icon,
                obj.cover_path,
                obj.status,
                obj.priority,
                obj.progress,
                obj.start_at,
                obj.due_at,
                1 if obj.pinned else 0,
                obj.parent_id,
                obj.sort_key,
                obj.created_at,
                obj.updated_at,
                obj.deleted_at,
            ),
        )
        self.commit()

        # Sync object_tags
        if obj.tags:
            for tag_name in obj.tags:
                tag = self.add_tag(tag_name)
                self.conn.execute(
                    "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
                    (obj.id, tag["id"]),
                )
            self.commit()

    def delete_object(self, object_id: str) -> None:
        """Mark an object as deleted in the cache."""
        self.conn.execute(
            "UPDATE objects SET deleted_at = ? WHERE id = ?",
            (__import__("datetime").datetime.now().isoformat(), object_id),
        )
        self.commit()

    def remove_object(self, object_id: str) -> None:
        """Permanently remove an object from the cache."""
        self.conn.execute("DELETE FROM objects WHERE id = ?", (object_id,))
        self.conn.execute("DELETE FROM object_tags WHERE object_id = ?", (object_id,))
        self.conn.execute(
            "DELETE FROM links WHERE from_id = ? OR to_id = ?",
            (object_id, object_id),
        )
        self.conn.execute("DELETE FROM object_tags WHERE object_id = ?", (object_id,))
        self.commit()

    # ------------------------------------------------------------------ #
    # Tag queries

    def list_tags(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, color, created_at FROM tags WHERE deleted_at IS NULL "
            "ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_tag(self, name: str, color: str | None = None) -> dict:
        import uuid
        from datetime import datetime, timezone
        tag_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO tags (id, name, color, created_at) VALUES (?, ?, ?, ?)",
            (tag_id, name, color, now),
        )
        self.commit()
        row = self.conn.execute(
            "SELECT id, name, color, created_at FROM tags WHERE name = ? AND deleted_at IS NULL",
            (name,),
        ).fetchone()
        return dict(row) if row else {"id": tag_id, "name": name, "color": color, "created_at": now}

    def delete_tag(self, tag_id: str) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "UPDATE tags SET deleted_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), tag_id),
        )
        self.conn.execute("DELETE FROM object_tags WHERE tag_id = ?", (tag_id,))
        self.commit()

    def rename_tag(self, tag_id: str, new_name: str) -> None:
        self.conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id))
        self.commit()

    def update_tag_color(self, tag_id: str, color: str) -> None:
        self.conn.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))
        self.commit()

    def get_object_tag_names(self, object_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN object_tags ot ON ot.tag_id = t.id
            WHERE ot.object_id = ? AND t.deleted_at IS NULL
            """,
            (object_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def set_object_tags(self, object_id: str, tag_names: list[str]) -> None:
        self.conn.execute("DELETE FROM object_tags WHERE object_id = ?", (object_id,))
        for name in tag_names:
            tag = self.add_tag(name)
            self.conn.execute(
                "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
                (object_id, tag["id"]),
            )
        self.commit()

    def objects_by_tag(self, tag_name: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT ot.object_id FROM object_tags ot
            JOIN tags t ON t.id = ot.tag_id
            WHERE t.name = ? AND t.deleted_at IS NULL
            """,
            (tag_name,),
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------ #
    # Link queries

    def create_link(self, from_id: str, to_id: str, link_type: str = "related") -> dict:
        import uuid
        from datetime import datetime, timezone
        link_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO links (id, from_id, to_id, link_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (link_id, from_id, to_id, link_type, now),
        )
        self.commit()
        row = self.conn.execute(
            "SELECT id, from_id, to_id, link_type, created_at FROM links WHERE id = ?",
            (link_id,),
        ).fetchone()
        return dict(row) if row else {"id": link_id}

    def delete_link(self, link_id: str) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "UPDATE links SET deleted_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), link_id),
        )
        self.commit()

    def get_outgoing_links(self, object_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, from_id, to_id, link_type, created_at FROM links "
            "WHERE from_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (object_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_incoming_links(self, object_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, from_id, to_id, link_type, created_at FROM links "
            "WHERE to_id = ? AND deleted_at IS NULL ORDER BY created_at",
            (object_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_objects_by_title(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, type, title, status FROM objects "
            "WHERE deleted_at IS NULL AND title LIKE ? ORDER BY title LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Internal helpers

    def _upsert_from_dict(self, object_id: str, data: dict) -> None:
        """Insert/update cache from a raw object.json dict (with HLC fields)."""
        def _unwrap(key: str, default: Any = None) -> Any:
            field = data.get(key)
            if isinstance(field, dict) and "v" in field:
                return field["v"]
            return field if field is not None else default

        self.conn.execute(
            """
            INSERT OR REPLACE INTO objects
                (id, workspace_id, type, title, description, icon, cover_path,
                 status, priority, progress, start_at, due_at, pinned,
                 parent_id, sort_key, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_id,
                _unwrap("workspace_id", "default"),
                _unwrap("type", "task"),
                _unwrap("title", ""),
                _unwrap("description", ""),
                _unwrap("icon"),
                _unwrap("cover_path"),
                _unwrap("status", "active"),
                _unwrap("priority"),
                _unwrap("progress"),
                _unwrap("start_at"),
                _unwrap("due_at"),
                1 if _unwrap("pinned", False) else 0,
                _unwrap("parent_id"),
                _unwrap("sort_key"),
                _unwrap("created_at", ""),
                _unwrap("updated_at", ""),
                _unwrap("deleted_at"),
            ),
        )

        raw_tags = _unwrap("tags", [])
        if isinstance(raw_tags, list) and raw_tags:
            self.conn.execute("DELETE FROM object_tags WHERE object_id = ?", (object_id,))
            for tag_name in raw_tags:
                tag = self.add_tag(str(tag_name))
                self.conn.execute(
                    "INSERT OR IGNORE INTO object_tags (object_id, tag_id) VALUES (?, ?)",
                    (object_id, tag["id"]),
                )

    def _upsert_fts(self, object_id: str, title: str, description: str, body: str) -> None:
        """Update the FTS5 index for an object."""
        self.conn.execute(
            "INSERT OR REPLACE INTO objects_fts(rowid, title, description, body) "
            "VALUES (?, ?, ?, ?)",
            (object_id, title, description, body),
        )
