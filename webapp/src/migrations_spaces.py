"""Migration 95: shelves stop being a data model (features/spaces-and-tags.md).

Tags become rows of `label_config` (the old shelf table) whose `label_group` is their space. A shelf that held tags is removed
and its tags move up to its space; a shelf with no tags stays as a tag of its own name. Items link to tags in `object_labels`
and keep their own space in `object_spaces`. `plan` only reads and returns what `apply` will do, so it doubles as the dry-run
report (scripts/audit_spaces.py).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import tags

OBJECT_KIND = {"note": "notebook", "task": "task", "event": "event", "contact": "contact", "transaction": "transaction", "scheduled": "scheduled"}


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def plan(conn: sqlite3.Connection) -> dict[str, Any]:
    """What the migration will do: the final name and space of every tag, the shelves that go, and the conflicts."""
    shelves = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM label_config")}
    old_tags = [dict(r) for r in conn.execute("SELECT * FROM label_tags")] if _has(conn, "label_tags") else []
    has_tags = {t["label_name"].lower() for t in old_tags}
    taken = {n.lower() for n, s in shelves.items() if n.lower() not in has_tags}  # shelves that stay as tags
    tag_rows, renamed = [], {}
    for t in old_tags:
        shelf = shelves.get(t["label_name"]) or next((s for n, s in shelves.items() if n.lower() == t["label_name"].lower()), {})
        space = (shelf.get("label_group") or "").strip() or tags.OTHER_SPACE
        name = t["name"]
        if name.lower() in taken:
            name = f"{name} ({space})"
        taken.add(name.lower())
        renamed[t["name"].lower()] = name
        tag_rows.append({"name": name, "old": t["name"], "space": space, "color": t["color"], "icon": t["icon"], "shelf": t["label_name"]})
    kept = [{"name": n, "space": (s.get("label_group") or "").strip() or tags.OTHER_SPACE} for n, s in shelves.items() if n.lower() not in has_tags]
    removed = [n for n in shelves if n.lower() in has_tags]
    return {"tags": tag_rows, "kept_shelves": kept, "removed_shelves": removed, "renamed": renamed}


def apply(conn: sqlite3.Connection) -> None:
    tags.ensure_schema(conn)
    if not _has(conn, "label_tags"):
        return
    report = plan(conn)
    shelf_space = {r["name"].lower(): ((r["label_group"] or "").strip() or tags.OTHER_SPACE) for r in conn.execute("SELECT name, label_group FROM label_config")}
    semesters = {r[0].lower() for r in conn.execute("SELECT shelf_name FROM university_semesters")} if _has(conn, "university_semesters") else set()
    spaces_needed = {t["space"] for t in report["tags"]} | {k["space"] for k in report["kept_shelves"]} | {s for s in shelf_space.values() if s}
    for space in spaces_needed:
        conn.execute("INSERT OR IGNORE INTO label_groups (name, color, created_at) VALUES (?, 'gray', datetime('now'))", (space,))

    item_space: dict[tuple[str, str], str] = {}
    conflicts: list[str] = []

    def note(kind: str, uid: str, space: str) -> None:
        current = item_space.setdefault((kind, uid), space)
        if current.lower() != space.lower():
            conflicts.append(f"{kind} {uid}: {current} and {space}")

    # items linked to a shelf that is going away keep its space; items linked to a shelf that stays keep that link
    gone = {n.lower() for n in report["removed_shelves"]}
    for r in conn.execute("SELECT object_type, object_id, label_name FROM object_labels").fetchall():
        space = shelf_space.get(r["label_name"].lower())
        if space:
            note(r["object_type"], r["object_id"], space)
    for name in gone:
        conn.execute("DELETE FROM object_labels WHERE label_name = ? COLLATE NOCASE", (name,))
        conn.execute("DELETE FROM label_config WHERE name = ? COLLATE NOCASE", (name,))

    for t in report["tags"]:
        code = t["shelf"] if t["shelf"].lower() in semesters else ""
        conn.execute("INSERT INTO label_config (name, color, icon, label_group, code, created_at) VALUES (?, ?, ?, ?, ?, datetime('now')) "
                     "ON CONFLICT(name) DO UPDATE SET label_group = excluded.label_group, code = excluded.code",
                     (t["name"], t["color"] or "gray", t["icon"] or "", t["space"], code))
    for k in report["kept_shelves"]:
        conn.execute("UPDATE label_config SET label_group = ? WHERE name = ?", (k["space"], k["name"]))

    space_of_tag = {t["name"].lower(): t["space"] for t in report["tags"]} | {k["name"].lower(): k["space"] for k in report["kept_shelves"]}
    for r in conn.execute("SELECT object_type, object_id, tag_name FROM object_tags").fetchall():
        kind = OBJECT_KIND.get(r["object_type"])
        name = report["renamed"].get(r["tag_name"].lower(), r["tag_name"])
        space = space_of_tag.get(name.lower())
        if r["object_type"] == "media":  # the library has no tags; the entry keeps the tag's space
            if space and _has(conn, "citations"):
                conn.execute("UPDATE citations SET space = ? WHERE uid = ? AND COALESCE(space, '') = ''", (space, r["object_id"]))
            continue
        if not kind or not space:
            continue
        conn.execute("INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)", (kind, r["object_id"], name))
        note(kind, r["object_id"], space)
    for (kind, uid), space in item_space.items():
        conn.execute("INSERT OR IGNORE INTO object_spaces (object_type, object_id, space) VALUES (?, ?, ?)", (kind, uid, space))
    if conflicts and _has(conn, "app_meta"):
        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('spaces_migration_conflicts', ?)", ("\n".join(conflicts),))
    _retire(conn, "label_tags")
    _retire(conn, "object_tags")


_RETIRE = {
    "label_tags": ("INSERT OR IGNORE INTO legacy_label_tags SELECT * FROM label_tags", "DROP TABLE label_tags", "ALTER TABLE label_tags RENAME TO legacy_label_tags"),
    "object_tags": ("INSERT OR IGNORE INTO legacy_object_tags SELECT * FROM object_tags", "DROP TABLE object_tags", "ALTER TABLE object_tags RENAME TO legacy_object_tags"),
}


def _retire(conn: sqlite3.Connection, table: str) -> None:
    """Renames a finished table to legacy_<table>; when one is already there (the migrations ran again) its rows are merged in."""
    if not _has(conn, table):
        return
    merge, drop, rename = _RETIRE[table]
    if _has(conn, "legacy_" + table):
        conn.execute(merge)
        conn.execute(drop)
    else:
        conn.execute(rename)
