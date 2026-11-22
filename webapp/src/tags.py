"""Spaces and tags (features/spaces-and-tags.md).

There are two levels. A space is a row of `label_groups`. A tag is a row of `label_config` whose `label_group` names its
space; every tag belongs to exactly one space. Items link to tags in `object_labels` (notes are spelled `notebook`
there). Every item may also have a space of its own, kept in `object_spaces`, which is what the item's pill shows when it
has no tag. The space is set by the tags an item carries (all of them from one space, or the change is refused with
`SpaceConflict`), by naming it directly, and it stays when the tags are removed or deleted.

Everything that writes an item's tags goes through `db.set_object_labels`, which calls `check_space` first and `sync_space`
after, so the rules live here and nowhere else. The three-level code from before is kept in `tags_legacy.py` for the old
numbered migrations only.
"""

from __future__ import annotations

import sqlite3
from typing import Any

SPACE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS object_spaces (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    space TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (object_type, object_id)
);
CREATE INDEX IF NOT EXISTS idx_object_spaces_space ON object_spaces(space, object_type);
"""
KIND = {"note": "notebook"}  # object_labels spells notes "notebook"
OBJECT_TYPES = ("task", "event", "notebook", "contact", "transaction", "scheduled")
OTHER_SPACE = "Other"


class SpaceConflict(ValueError):
    """An item was given tags from more than one space."""

    def __init__(self, spaces: list[str]):
        self.spaces = spaces
        super().__init__(f"An item sits in one space only, and these tags are from {' and '.join(spaces)}")


def _kind(object_type: str) -> str:
    return KIND.get(object_type, object_type)


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SPACE_TABLE_SQL)
    if "code" not in {r[1] for r in conn.execute("PRAGMA table_info(label_config)")}:
        conn.execute("ALTER TABLE label_config ADD COLUMN code TEXT NOT NULL DEFAULT ''")


# ---------------------------------------------------------------- tags

def get_tag(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM label_config WHERE name = ? COLLATE NOCASE", ((name or "").strip(),)).fetchone()
    return _tag(dict(row)) if row else None


def _tag(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "space": (row.get("label_group") or "").strip(), "color": row.get("color") or "blue", "icon": row.get("icon") or ""}


def list_tags(conn: sqlite3.Connection, space: str | None = None) -> list[dict[str, Any]]:
    """Every tag with how many items carry it, by space then name; one space's tags when `space` is given."""
    usage = {r["label_name"]: r["n"] for r in conn.execute("SELECT label_name, COUNT(*) AS n FROM object_labels GROUP BY label_name")}
    rows = conn.execute("SELECT * FROM label_config ORDER BY label_group COLLATE NOCASE, name COLLATE NOCASE")
    out = [{**_tag(dict(r)), "usage": usage.get(r["name"], 0)} for r in rows]
    return [t for t in out if space is None or t["space"].lower() == space.lower()]


def tags_of_code(conn: sqlite3.Connection, code: str) -> list[dict[str, Any]]:
    """The tags carrying a University semester's identification code."""
    return [_tag(dict(r)) for r in conn.execute("SELECT * FROM label_config WHERE code = ? COLLATE NOCASE AND code != '' ORDER BY name COLLATE NOCASE", (code,))]


def tags_of_space(conn: sqlite3.Connection, space: str) -> list[dict[str, Any]]:
    return list_tags(conn, space)


def add_tag(conn: sqlite3.Connection, name: str, space: str = "Personal", color: str = "gray", icon: str = "") -> None:
    """Makes a tag in a space (and the space, when it is new) unless a tag of that name exists."""
    name = (name or "").strip()
    if not name or get_tag(conn, name):
        return
    conn.execute("INSERT OR IGNORE INTO label_groups (name, color, created_at) VALUES (?, 'gray', datetime('now'))", (space,))
    conn.execute("INSERT INTO label_config (name, color, icon, label_group, created_at) VALUES (?, ?, ?, ?, datetime('now'))", (name, color or "gray", icon or "", space))
    conn.commit()


def tag_styles(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Colour and icon by tag name, for drawing tag pills in tables."""
    return {r["name"]: {"color": r["color"] or "gray", "icon": r["icon"] or ""} for r in conn.execute("SELECT name, color, icon FROM label_config")}


def space_look(conn: sqlite3.Connection, space: str) -> dict[str, str]:
    row = conn.execute("SELECT name, color, icon FROM label_groups WHERE name = ? COLLATE NOCASE", (space,)).fetchone()
    return {"name": row["name"], "color": row["color"] or "gray", "icon": row["icon"] or "layers"} if row else {"name": space, "color": "gray", "icon": "layers"}


def name_taken(conn: sqlite3.Connection, name: str, space: str | None = None) -> bool:
    """A tag name is unique within its space, so two spaces may each have a tag of that name. Without `space`, any tag of the name counts."""
    if space is None:
        return conn.execute("SELECT 1 FROM label_config WHERE name = ? COLLATE NOCASE", (name,)).fetchone() is not None
    return conn.execute("SELECT 1 FROM label_config WHERE name = ? COLLATE NOCASE AND COALESCE(label_group, '') = ? COLLATE NOCASE", (name, space)).fetchone() is not None


# ---------------------------------------------------------------- items: tags

def tags_for_object(conn: sqlite3.Connection, object_type: str, object_id: str) -> list[str]:
    rows = conn.execute("SELECT label_name FROM object_labels WHERE object_type = ? AND object_id = ? ORDER BY label_name COLLATE NOCASE",
                        (_kind(object_type), object_id))
    return [r["label_name"] for r in rows]


def spaces_of(conn: sqlite3.Connection, names: list[str]) -> list[str]:
    """The distinct spaces the named tags belong to, in the spaces' own spelling; a tag with no space adds none."""
    seen: dict[str, str] = {}
    for name in names:
        tag = get_tag(conn, name)
        if tag and tag["space"]:
            seen.setdefault(tag["space"].lower(), tag["space"])
    return sorted(seen.values(), key=str.lower)


def check_space(conn: sqlite3.Connection, names: list[str]) -> str | None:
    """The one space these tags give an item, or None when none of them has a space; raises SpaceConflict for two or more."""
    spaces = spaces_of(conn, names)
    if len(spaces) > 1:
        raise SpaceConflict(spaces)
    return spaces[0] if spaces else None


def item_space(conn: sqlite3.Connection, object_type: str, object_id: str) -> str | None:
    row = conn.execute("SELECT space FROM object_spaces WHERE object_type = ? AND object_id = ?", (_kind(object_type), object_id)).fetchone()
    return row["space"] if row else None


def set_item_space(conn: sqlite3.Connection, object_type: str, object_id: str, space: str | None) -> None:
    """Gives an item a space directly (or clears it). The item's tags must all be from that space."""
    space = (space or "").strip() or None
    if space and any(s.lower() != space.lower() for s in spaces_of(conn, tags_for_object(conn, object_type, object_id))):
        raise SpaceConflict([space, *spaces_of(conn, tags_for_object(conn, object_type, object_id))])
    kind = _kind(object_type)
    if space:
        conn.execute("INSERT INTO object_spaces (object_type, object_id, space) VALUES (?, ?, ?) "
                     "ON CONFLICT(object_type, object_id) DO UPDATE SET space = excluded.space", (kind, object_id, space))
    else:
        conn.execute("DELETE FROM object_spaces WHERE object_type = ? AND object_id = ?", (kind, object_id))
    conn.commit()


def apply_space(conn: sqlite3.Connection, object_type: str, object_id: str, space: str) -> None:
    """A space that arrived with an item (a sync client's X-CURODAV-SPACE, an API write): kept when the space exists and the
    item's tags do not already put it elsewhere. Anything else is ignored, so a client can never make a space."""
    found = conn.execute("SELECT name FROM label_groups WHERE name = ? COLLATE NOCASE", ((space or "").strip(),)).fetchone()
    if found and not any(s.lower() != found["name"].lower() for s in spaces_of(conn, tags_for_object(conn, object_type, object_id))):
        set_item_space(conn, object_type, object_id, found["name"])


def sync_space(conn: sqlite3.Connection, object_type: str, object_id: str) -> None:
    """After an item's tags changed: when they give it a space, that is its space; when they give none (the tags were removed or
    deleted), the space it had stays. The caller commits."""
    space = check_space(conn, tags_for_object(conn, object_type, object_id))
    if space:
        conn.execute("INSERT INTO object_spaces (object_type, object_id, space) VALUES (?, ?, ?) "
                     "ON CONFLICT(object_type, object_id) DO UPDATE SET space = excluded.space", (_kind(object_type), object_id, space))


def items_in_space(conn: sqlite3.Connection, space: str, object_type: str) -> list[str]:
    return [r["object_id"] for r in conn.execute("SELECT object_id FROM object_spaces WHERE space = ? AND object_type = ?", (space, _kind(object_type)))]


def space_counts(conn: sqlite3.Connection, space: str) -> dict[str, int]:
    return {r["object_type"]: r["n"] for r in conn.execute(
        "SELECT object_type, COUNT(*) AS n FROM object_spaces WHERE space = ? COLLATE NOCASE GROUP BY object_type", (space,))}


def set_object_tags(conn: sqlite3.Connection, object_type: str, object_id: str, names: list[str]) -> list[str]:
    """Replaces an item's tags. Every name must already be a tag, and all must be from one space."""
    kind = _kind(object_type)
    if kind not in OBJECT_TYPES:
        raise ValueError(f"tags are not available on {object_type}")
    known = {t["name"].lower(): t["name"] for t in list_tags(conn)}
    wanted = list(dict.fromkeys(n.strip().lower() for n in names if n and n.strip()))
    missing = [n for n in wanted if n not in known]
    if missing:
        raise ValueError(f"unknown tags: {', '.join(missing)}")
    chosen = [known[k] for k in wanted]
    from . import db

    db.set_object_labels(conn, kind, object_id, chosen)
    return tags_for_object(conn, kind, object_id)


def record(conn: sqlite3.Connection, object_type: str, object_id: str, names: list[str]) -> None:
    """Stores the picked tags on an item; a name that is not a tag is left out (tags are never made on the fly)."""
    if _kind(object_type) not in OBJECT_TYPES:
        return
    set_object_tags(conn, object_type, object_id, [n for n in names if get_tag(conn, n)])


def labels_of(conn: sqlite3.Connection, names: list[str], keep_unknown: bool = False) -> list[str]:
    """The picked names in the tags' own spelling. A name that is not a tag is dropped, unless `keep_unknown` is set."""
    out: list[str] = []
    for name in names:
        tag = get_tag(conn, name)
        picked = tag["name"] if tag else (name.strip() if keep_unknown and name and name.strip() else None)
        if picked and picked not in out:
            out.append(picked)
    return out


def bulk_change(conn: sqlite3.Connection, object_type: str, object_id: str, labels: list[str],
                add: list[str] = (), remove: list[str] = (), single: bool = False) -> list[str]:
    """Adds and removes tags on one item for a bulk edit and returns its new tag list."""
    current = tags_for_object(conn, object_type, object_id) or list(labels)
    gone = {r.lower() for r in remove}
    wanted = [t for t in current if t.lower() not in gone]
    for name in add:
        if name and name.lower() not in {w.lower() for w in wanted}:
            wanted = [name] if single else wanted + [name]
    record(conn, object_type, object_id, wanted)
    return labels_of(conn, wanted, keep_unknown=True)


def attach_items(conn: sqlite3.Connection, object_type: str, dicts: list[dict[str, Any]]) -> None:
    """Gives each item dict `tag_items`: its tags with their colour and icon, for every pill and colour in the app. An item
    with no tag but a space gets one entry that stands for the space (`is_space`), so it never shows as untagged."""
    if not dicts:
        return
    kind = _kind(object_type)
    cfg = {r["name"].lower(): dict(r) for r in conn.execute("SELECT name, color, icon, label_group, code FROM label_config")}
    spaces: dict[str, str] = {}
    ids = [d["uid"] for d in dicts]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ", ".join("?" for _ in chunk)
        for r in conn.execute(f"SELECT object_id, space FROM object_spaces WHERE object_type = ? AND object_id IN ({marks})", (kind, *chunk)):
            spaces[r["object_id"]] = r["space"]
    looks: dict[str, dict[str, str]] = {}
    for d in dicts:
        names = d.get("tags") or []
        items = []
        for n in names:
            base = cfg.get(n.lower(), {})
            items.append({"name": n, "color": base.get("color") or "blue", "icon": base.get("icon") or "", "space": (base.get("label_group") or "").strip(),
                          "code": base.get("code") or ""})
        if not items and spaces.get(d["uid"]):
            space = spaces[d["uid"]]
            look = looks.setdefault(space.lower(), space_look(conn, space))
            items = [{"name": look["name"], "color": look["color"], "icon": look["icon"], "space": look["name"], "is_space": True}]
        d["tag_items"] = sorted(items, key=lambda t: t["name"].lower())
        d["space"] = spaces.get(d["uid"]) or ((items[0]["space"] or None) if items else None)


def picker(conn: sqlite3.Connection, object_type: str, object_id: str, old_labels: list[str]) -> dict[str, Any]:
    """The Tag dropdown's options and the item's current picks. Archived tags are offered only when the item already carries them."""
    chosen = tags_for_object(conn, object_type, object_id) if object_id else []
    selected = chosen or [n for n in old_labels if n]
    rows = list_tags(conn)
    names = {t["name"] for t in rows if not t.get("archived_at")} | set(selected)
    by = {t["name"]: t for t in rows}
    items = [{"uid": n, "name": n, "color": by.get(n, {}).get("color") or "gray", "icon": by.get(n, {}).get("icon") or "", "space": by.get(n, {}).get("space") or ""}
             for n in sorted(names, key=str.lower)]
    return {"items": items, "selected": selected}


def filter_items(conn: sqlite3.Connection, object_type: str, items: list[dict[str, str]], *, lowercase_values: bool = False) -> list[dict[str, str]]:
    """A tag filter's options: every tag carried by an item of this type. Space entries stay as they are."""
    kind = _kind(object_type)
    linked = [r[0] for r in conn.execute("SELECT DISTINCT label_name FROM object_labels WHERE object_type = ?", (kind,))]
    names = sorted({i["name"] for i in items if i.get("section") == "label"} | set(linked), key=str.lower)
    kept = [i for i in items if i.get("section") != "label"]
    return kept + [{"value": n.lower() if lowercase_values else n, "name": n, "section": "label"} for n in names]


def matcher(conn: sqlite3.Connection, object_type: str, values) -> Any:
    """A predicate over item dicts (`uid`, `tags`) for a filter selection of tag names and `group:<space>` entries. An item
    matches a tag when it carries it, and a space when it carries one of its tags or sits in it with none."""
    from . import db
    from .db.labels import GROUP_KEY_PREFIX

    kind = _kind(object_type)
    picked = [(v or "").strip() for v in values if (v or "").strip()]
    spaces = {v[len(GROUP_KEY_PREFIX):].strip().lower() for v in picked if v.lower().startswith(GROUP_KEY_PREFIX)}
    wanted = {v.lower() for v in picked if not v.lower().startswith(GROUP_KEY_PREFIX)}
    in_space: set[str] = set()
    for space in spaces:
        in_space |= set(items_in_space(conn, space, kind))
    tags_of = db.expand_label_filter(conn, [v for v in picked if v.lower().startswith(GROUP_KEY_PREFIX)])

    def match(item: dict[str, Any]) -> bool:
        carried = {(t or "").lower() for t in item.get("tags") or []}
        return bool(carried & wanted) or bool(carried & tags_of) or item["uid"] in in_space

    return match


# ---------------------------------------------------------------- tags being changed

def label_removed(conn: sqlite3.Connection, name: str, into: str | None = None) -> None:
    """A tag is deleted or merged into another. Items that carried it keep their space, because the space was stored when the tag
    was set; a merge hands the links to the tag it went into."""
    items = [(r["object_type"], r["object_id"]) for r in conn.execute("SELECT object_type, object_id FROM object_labels WHERE label_name = ? COLLATE NOCASE", (name,))]
    tag = get_tag(conn, name)
    for kind, uid in items:  # make sure the space is stored before the link goes
        if tag and tag["space"] and not item_space(conn, kind, uid):
            conn.execute("INSERT INTO object_spaces (object_type, object_id, space) VALUES (?, ?, ?)", (kind, uid, tag["space"]))
    if into:
        conn.execute("INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) SELECT object_type, object_id, ? FROM object_labels WHERE label_name = ? COLLATE NOCASE", (into, name))
    conn.execute("DELETE FROM object_labels WHERE label_name = ? COLLATE NOCASE", (name,))
    conn.commit()


def space_renamed(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Items and library entries filed under a space follow it when it is renamed or merged into another."""
    for statement in ("UPDATE object_spaces SET space = ? WHERE space = ? COLLATE NOCASE",
                      "UPDATE citations SET space = ? WHERE space = ? COLLATE NOCASE"):
        try:
            conn.execute(statement, (new, old))
        except sqlite3.OperationalError:
            pass


def semester_code(conn: sqlite3.Connection) -> str:
    """The identification code of the current University semester, lowercase; "" when there is none. Tags carrying it are the
    semester's disciplines."""
    from . import modules

    if not modules.is_enabled("academic"):
        return ""
    try:
        from . import university_plan

        semester = university_plan.current_semester(conn)
    except Exception:
        return ""
    return ((semester or {}).get("code") or (semester or {}).get("shelf_name") or "").lower()


def move_error(conn: sqlite3.Connection, name: str, space: str) -> str | None:
    """Why a tag cannot go to another space, or None. Items carrying it must not carry tags of the old space besides."""
    tag = get_tag(conn, name)
    if not tag:
        return f"There is no tag named {name}"
    if not conn.execute("SELECT 1 FROM label_groups WHERE name = ? COLLATE NOCASE", (space,)).fetchone():
        return f"There is no space called {space}"
    clash = conn.execute(
        "SELECT 1 FROM object_labels a JOIN object_labels b ON a.object_type = b.object_type AND a.object_id = b.object_id "
        "AND b.label_name != a.label_name COLLATE NOCASE JOIN label_config c ON c.name = b.label_name "
        "WHERE a.label_name = ? COLLATE NOCASE AND c.label_group != ? COLLATE NOCASE LIMIT 1", (name, space)).fetchone()
    return "Some items carry this tag together with tags of its current space, so it would put them in two spaces" if clash else None


def move_tag(conn: sqlite3.Connection, name: str, space: str) -> None:
    tag = get_tag(conn, name)
    conn.execute("UPDATE label_config SET label_group = ? WHERE name = ? COLLATE NOCASE", (space, name))
    conn.execute("UPDATE object_spaces SET space = ? WHERE (object_type, object_id) IN "
                 "(SELECT object_type, object_id FROM object_labels WHERE label_name = ? COLLATE NOCASE)", (space, tag["name"]))
    conn.commit()


def merge_error(conn: sqlite3.Connection, name: str, dest: str) -> str | None:
    a, b = get_tag(conn, name), get_tag(conn, dest)
    if not a or not b:
        return "Choose a tag to merge into"
    if a["name"].lower() == b["name"].lower():
        return "A tag cannot be merged into itself"
    if a["space"].lower() != b["space"].lower() and move_error(conn, name, b["space"]):
        return "These tags are in different spaces and some items carry both spaces' tags"
    return None
