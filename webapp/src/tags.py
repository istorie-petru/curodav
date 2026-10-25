"""App-wide tags (stored in `label_tags`, the older `tags` table of earlier versions is left alone): the boxes users apply to items (features/tags-groups-labels.md).

A tag always belongs to one label and has no page of its own: it is an alias of its label with its own identity. Every label has a default tag with the label's own name. `object_tags` links tags to tasks, events, notes, contacts and
transactions. `plan_migration` reports what the one-off move from finance tags, projects and plain labels would
do; `apply_migration` performs it. Neither runs at startup.
"""

from __future__ import annotations

import contextlib
import contextvars
import sqlite3
from datetime import datetime, timezone
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS label_tags (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    label_name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'gray',
    icon TEXT NOT NULL DEFAULT '',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS object_tags (
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    tag_name TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (object_type, object_id, tag_name)
);
CREATE INDEX IF NOT EXISTS idx_object_tags_tag ON object_tags(tag_name, object_type);
"""
OBJECT_TYPES = ("task", "event", "note", "contact", "transaction", "scheduled")
LABEL_OBJECT_TYPES = ("task", "event", "contact", "notebook")  # object_labels spells notes "notebook"
FINANCE_LABEL, FINANCE_GROUP = "Finance", "Personal"


class ManagedLabelError(ValueError):
    """A shelf managed by a module was changed by someone other than that module."""

    def __init__(self, label_name: str, module_key: str):
        from . import modules

        module = modules.get(module_key)
        super().__init__(f'"{label_name}" is managed by the {module.title} module. Change it in its settings ({module.settings_url}).')
        self.label_name, self.module_key = label_name, module_key


_managed_writer: contextvars.ContextVar[str | None] = contextvars.ContextVar("managed_writer", default=None)


@contextlib.contextmanager
def managed_writes(module_key: str):
    """Lets the named module change the shelves it manages; every other caller is refused."""
    token = _managed_writer.set(module_key)
    try:
        yield
    finally:
        _managed_writer.reset(token)


def managed_by(conn: sqlite3.Connection, label_name: str) -> str | None:
    try:
        row = conn.execute("SELECT managed_by FROM label_config WHERE name = ? COLLATE NOCASE", (label_name,)).fetchone() if label_name else None
    except sqlite3.OperationalError:  # a database from before the column existed
        return None
    return (row[0] or None) if row else None


def assert_writable(conn: sqlite3.Connection, *label_names: str) -> None:
    """Raises ManagedLabelError when a named shelf is managed by a module other than the current writer."""
    for name in label_names:
        owner = managed_by(conn, name)
        if owner and _managed_writer.get() != owner:
            raise ManagedLabelError(name, owner)


def set_managed_by(conn: sqlite3.Connection, label_name: str, module_key: str | None) -> None:
    """Marks a shelf as managed by a module (or clears the mark); only the module itself may do either."""
    assert_writable(conn, label_name)
    conn.execute("UPDATE label_config SET managed_by = ? WHERE name = ?", (module_key, label_name))
    conn.commit()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def restore(conn: sqlite3.Connection, label_name: str) -> None:
    assert_writable(conn, label_name)
    conn.execute("UPDATE label_config SET archived_at = NULL WHERE name = ?", (label_name,))
    conn.commit()


def list_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    usage = {r["tag_name"]: r["n"] for r in conn.execute("SELECT tag_name, COUNT(*) AS n FROM object_tags GROUP BY tag_name")}
    rows = conn.execute("SELECT * FROM label_tags ORDER BY label_name COLLATE NOCASE, name COLLATE NOCASE")
    return [{**dict(r), "usage": usage.get(r["name"], 0)} for r in rows]


def tags_for_object(conn: sqlite3.Connection, object_type: str, object_id: str) -> list[str]:
    rows = conn.execute("SELECT tag_name FROM object_tags WHERE object_type = ? AND object_id = ? ORDER BY tag_name COLLATE NOCASE",
                        (object_type, object_id))
    return [r["tag_name"] for r in rows]


def set_object_tags(conn: sqlite3.Connection, object_type: str, object_id: str, names: list[str]) -> list[str]:
    """Replaces an item's tags. Every name must already be a tag."""
    if object_type not in OBJECT_TYPES:
        raise ValueError(f"tags are not available on {object_type}")
    known = {r["name"].lower(): r["name"] for r in conn.execute("SELECT name FROM label_tags")}
    wanted = list(dict.fromkeys(n.strip().lower() for n in names if n and n.strip()))
    missing = [n for n in wanted if n not in known]
    if missing:
        raise ValueError(f"unknown tags: {', '.join(missing)}")
    conn.execute("DELETE FROM object_tags WHERE object_type = ? AND object_id = ?", (object_type, object_id))
    for key in wanted:
        conn.execute("INSERT OR IGNORE INTO object_tags (object_type, object_id, tag_name) VALUES (?, ?, ?)",
                     (object_type, object_id, known[key]))
    conn.commit()
    return tags_for_object(conn, object_type, object_id)


def tags_of_label(conn: sqlite3.Connection, label_name: str) -> list[dict[str, Any]]:
    if not _has(conn, "label_tags"):
        return []
    return [dict(r) for r in conn.execute("SELECT * FROM label_tags WHERE label_name = ? ORDER BY name COLLATE NOCASE", (label_name,))]


def get_tag(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM label_tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return dict(row) if row else None


def name_taken(conn: sqlite3.Connection, name: str, allow_label: str | None = None) -> bool:
    """Tags and labels share one namespace. `allow_label` is the label a same-named default tag may sit under."""
    if conn.execute("SELECT 1 FROM label_tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
        return True
    other = conn.execute("SELECT name FROM label_config WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return bool(other) and (other["name"] or "").lower() != (allow_label or "").lower()


def add_default_tag(conn: sqlite3.Connection, label_name: str, color: str = "gray", icon: str = "") -> None:
    """The same-named tag a new label gets once; after this nothing is synced between the two."""
    ensure_schema(conn)
    conn.execute("INSERT OR IGNORE INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                 (label_name, label_name, color or "gray", icon or "", datetime.now(timezone.utc).isoformat()))
    conn.commit()


def parse_rows(form) -> list[dict[str, Any]]:
    """The tag rows of a label form: `tag_idx` lists the row numbers; each row has tag_old_N, tag_name_N, tag_color_N,
    tag_icon_N and tag_del_N."""
    rows = []
    for i in form.getlist("tag_idx"):
        rows.append({"old": (form.get(f"tag_old_{i}") or "").strip(), "name": (form.get(f"tag_name_{i}") or "").strip(),
                     "color": (form.get(f"tag_color_{i}") or "gray").strip(), "icon": (form.get(f"tag_icon_{i}") or "").strip(),
                     "delete": form.get(f"tag_del_{i}") == "1"})
    return rows


def validate_rows(conn: sqlite3.Connection, label_name: str, rows: list[dict[str, Any]]) -> str | None:
    """An error message, or None. Checked before anything is saved."""
    own = tags_of_label(conn, label_name)
    leaving = {r["old"].lower() for r in rows if r["old"]}
    kept = [r for r in rows if not r["delete"] and r["name"]]
    seen: set[str] = set()
    for r in kept:
        key = r["name"].lower()
        if key in seen:
            return f"Two tags are named {r['name']}"
        seen.add(key)
        if key in leaving:
            continue
        if name_taken(conn, r["name"], allow_label=label_name if not own else None):
            return f"A tag or label named {r['name']} already exists"
    for r in rows:
        if r["old"] and not r["name"] and not r["delete"]:
            return "A tag needs a name"
    remaining = len([t for t in own if t["name"].lower() not in {r["old"].lower() for r in rows if r["delete"]}]) + len([r for r in kept if not r["old"]])
    if own and remaining < 1:
        return "A shelf keeps at least one tag"
    return None


def apply_rows(conn: sqlite3.Connection, label_name: str, rows: list[dict[str, Any]], colors) -> None:
    assert_writable(conn, label_name)
    """Deletes, renames/restyles and creates the tags of a label as one change."""
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        if r["old"] and r["delete"]:
            conn.execute("DELETE FROM object_tags WHERE tag_name = ? COLLATE NOCASE", (r["old"],))
            conn.execute("DELETE FROM label_tags WHERE name = ? COLLATE NOCASE AND label_name = ?", (r["old"], label_name))
    for r in rows:
        if r["delete"] or not r["name"]:
            continue
        color = r["color"] if r["color"] in colors else "gray"
        if r["old"]:
            conn.execute("UPDATE label_tags SET name = ?, color = ?, icon = ? WHERE name = ? COLLATE NOCASE AND label_name = ?",
                         (r["name"], color, r["icon"], r["old"], label_name))
            if r["old"] != r["name"]:
                conn.execute("UPDATE OR IGNORE object_tags SET tag_name = ? WHERE tag_name = ? COLLATE NOCASE", (r["name"], r["old"]))
        else:
            conn.execute("INSERT INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                         (r["name"], label_name, color, r["icon"], now))
    conn.commit()


def move_error(conn: sqlite3.Connection, name: str, dest: str) -> str | None:
    """Why a tag cannot go to another shelf, or None. A shelf keeps at least one tag, so its last tag stays."""
    tag = get_tag(conn, name)
    if not tag:
        return f"There is no tag named {name}"
    for shelf in (tag["label_name"], dest):
        if managed_by(conn, shelf):
            return str(ManagedLabelError(shelf, managed_by(conn, shelf)))
    if not dest or not conn.execute("SELECT 1 FROM label_config WHERE name = ?", (dest,)).fetchone():
        return "Choose a shelf to move the tag to"
    if dest == tag["label_name"]:
        return f"{tag['name']} is already on the shelf {dest}"
    if len(tags_of_label(conn, tag["label_name"])) < 2:
        return f"{tag['name']} is the only tag of {tag['label_name']}, and a shelf keeps at least one tag"
    return None


def move_tag(conn: sqlite3.Connection, name: str, dest: str) -> None:
    """Files a tag under another shelf. Its items keep it, and their shelf links follow: they gain the new shelf and leave
    the old one unless another of their tags still sits there."""
    tag = get_tag(conn, name)
    assert_writable(conn, tag["label_name"], dest)
    conn.execute("UPDATE label_tags SET label_name = ? WHERE name = ? COLLATE NOCASE", (dest, tag["name"]))
    from . import db

    kinds = {"note": "notebook"}
    for r in conn.execute("SELECT object_type, object_id FROM object_tags WHERE tag_name = ? COLLATE NOCASE", (tag["name"],)).fetchall():
        if kinds.get(r["object_type"], r["object_type"]) in LABEL_OBJECT_TYPES:
            kind = kinds.get(r["object_type"], r["object_type"])
            db.set_object_labels(conn, kind, r["object_id"], labels_of(conn, tags_for_object(conn, r["object_type"], r["object_id"])))
    conn.commit()


def label_renamed(conn: sqlite3.Connection, old: str, new: str) -> None:
    if _has(conn, "label_tags"):
        conn.execute("UPDATE label_tags SET label_name = ? WHERE label_name = ?", (new, old))


def label_removed(conn: sqlite3.Connection, name: str, into: str | None = None) -> None:
    """A deleted label takes its tags with it; a merged one hands them to the label it merged into."""
    if not _has(conn, "label_tags"):
        return
    if into:
        conn.execute("UPDATE label_tags SET label_name = ? WHERE label_name = ?", (into, name))
        return
    conn.execute("DELETE FROM object_tags WHERE tag_name IN (SELECT name FROM label_tags WHERE label_name = ?)", (name,))
    conn.execute("DELETE FROM label_tags WHERE label_name = ?", (name,))


TAG_TYPE = {"notebook": "note"}  # object_labels spells notes "notebook"


def picker(conn: sqlite3.Connection, object_type: str, object_id: str, old_labels: list[str]) -> dict[str, Any]:
    """The Tag dropdown's options and the item's current picks. Until the migration gives every label its tag, a label
    with none is offered as its future default tag, and an item with no tag links yet shows its old labels as those tags.
    Tags of archived labels are offered only when the item already carries them."""
    kind = TAG_TYPE.get(object_type, object_type)
    chosen = tags_for_object(conn, kind, object_id) if object_id and _has(conn, "object_tags") else []
    selected = chosen or [n for n in old_labels if n]
    rows = list_tags(conn) if _has(conn, "label_tags") else []
    labels = _label_rows(conn)
    with_tags = {r["label_name"] for r in rows}
    names = {r["name"] for r in rows if not labels.get(r["label_name"], {}).get("archived_at")}
    names |= {n for n, cfg in labels.items() if n not in with_tags and not cfg.get("archived_at")}
    names |= set(selected)
    probe = [{"uid": n, "tags": [n]} for n in names]
    looks = {}
    for t in rows:
        looks[t["name"]] = t
    cfg = {r["name"]: r for r in labels.values()}
    items = []
    for n in sorted(names, key=str.lower):
        base = looks.get(n) or cfg.get(n) or {}
        items.append({"uid": n, "name": n, "color": base.get("color") or "gray", "icon": base.get("icon") or ""})
    return {"items": items, "selected": selected}


def labels_of(conn: sqlite3.Connection, names: list[str], keep_unknown: bool = False) -> list[str]:
    """The old label links for picked tags: a tag stands for its label; a label without a tag yet stands for itself. A name
    that is neither is dropped (tags are never made on the fly), unless `keep_unknown` is set for the older bulk calls."""
    labels = _label_rows(conn)
    out: list[str] = []
    for name in names:
        tag = get_tag(conn, name) if _has(conn, "label_tags") else None
        label = tag["label_name"] if tag else (name if (name in labels or (keep_unknown and name)) else None)
        if label and label not in out:
            out.append(label)
    return out


def record(conn: sqlite3.Connection, object_type: str, object_id: str, names: list[str]) -> None:
    """Stores the picked tags as tag links (labels without a tag yet are carried by their old label link)."""
    kind = TAG_TYPE.get(object_type, object_type)
    if kind not in OBJECT_TYPES or not _has(conn, "label_tags"):
        return
    real = [n for n in names if get_tag(conn, n)]
    set_object_tags(conn, kind, object_id, real)


def filter_items(conn: sqlite3.Connection, object_type: str, items: list[dict[str, str]], *, lowercase_values: bool = False) -> list[dict[str, str]]:
    """A label filter's options with the label entries swapped for tags: every tag carried by an item of this type, plus
    the labels in use that carry no tag links yet (their future default tags). Group entries stay as they are."""
    kind = TAG_TYPE.get(object_type, object_type)
    linked = [r[0] for r in conn.execute("SELECT DISTINCT tag_name FROM object_tags WHERE object_type = ?", (kind,))] \
        if _has(conn, "object_tags") else []
    names = sorted({i["name"] for i in items if i.get("section") == "label"} | set(linked), key=str.lower)
    kept = [i for i in items if i.get("section") != "label"]
    return kept + [{"value": n.lower() if lowercase_values else n, "name": n, "section": "label"} for n in names]


def matcher(conn: sqlite3.Connection, object_type: str, values) -> Any:
    """A predicate over item dicts (`uid`, `tags`) for a filter selection of tag names and `group:<name>` entries. An item
    matches a tag when it carries that tag link; an item with no tag links yet counts as carrying the default tag of each
    of its labels, so nothing disappears from a filter before the migration."""
    from . import db
    from .db.labels import GROUP_KEY_PREFIX

    kind = TAG_TYPE.get(object_type, object_type)
    picked = [(v or "").strip() for v in values if (v or "").strip()]
    group_labels = db.expand_label_filter(conn, [v for v in picked if v.lower().startswith(GROUP_KEY_PREFIX)])
    wanted = {v.lower() for v in picked if not v.lower().startswith(GROUP_KEY_PREFIX)}
    linked: dict[str, set[str]] = {}
    has_links: set[str] = set()
    if _has(conn, "object_tags"):
        for r in conn.execute("SELECT object_id, tag_name FROM object_tags WHERE object_type = ?", (kind,)):
            has_links.add(r["object_id"])
            if r["tag_name"].lower() in wanted:
                linked.setdefault(r["object_id"], set()).add(r["tag_name"].lower())
    defaults = {n.lower() for n in wanted if _is_default(conn, n)}

    def match(item: dict[str, Any]) -> bool:
        labels = {(t or "").lower() for t in item.get("tags") or []}
        if labels & group_labels:
            return True
        if item["uid"] in linked:
            return True
        return item["uid"] not in has_links and bool(labels & defaults)

    return match


def _is_default(conn: sqlite3.Connection, name: str) -> bool:
    """A name that stands for a whole label: a tag named like its label, or a label name with no tag yet."""
    tag = get_tag(conn, name) if _has(conn, "label_tags") else None
    if tag:
        return tag["label_name"].lower() == tag["name"].lower()
    return True  # not a tag, so it can only be a label that has no tag yet


def attach_items(conn: sqlite3.Connection, object_type: str, dicts: list[dict[str, Any]]) -> None:
    """Gives each item dict `tag_items`: its tags with their own colour and icon, for every pill and colour in the app.
    An item with tag links shows those; one without shows the default tag of each of its labels (or the label's own look
    while the label has no tag yet). `tags` keeps the label names for grouping and filters."""
    if not dicts:
        return
    kind = TAG_TYPE.get(object_type, object_type)
    links: dict[str, list[str]] = {}
    if _has(conn, "object_tags"):
        ids = [d["uid"] for d in dicts]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ", ".join("?" for _ in chunk)
            for r in conn.execute(f"SELECT object_id, tag_name FROM object_tags WHERE object_type = ? AND object_id IN ({marks})", (kind, *chunk)):
                links.setdefault(r["object_id"], []).append(r["tag_name"])
    defs = {r["name"].lower(): dict(r) for r in conn.execute("SELECT * FROM label_tags")} if _has(conn, "label_tags") else {}
    cfg = {r["name"].lower(): dict(r) for r in conn.execute("SELECT name, color, icon FROM label_config")}

    def look(name: str, label: str | None = None) -> dict[str, Any]:
        tag = defs.get(name.lower())
        if tag:
            return {"name": tag["name"], "color": tag["color"] or "gray", "icon": tag["icon"] or "", "label": tag["label_name"]}
        base = cfg.get(name.lower(), {})
        return {"name": name, "color": base.get("color") or "blue", "icon": base.get("icon") or "", "label": label or name}

    for d in dicts:
        names = links.get(d["uid"])
        items = [look(n) for n in names] if names else [look(n) for n in d.get("tags") or []]
        d["tag_items"] = sorted(items, key=lambda t: t["name"].lower())


def bulk_change(conn: sqlite3.Connection, object_type: str, object_id: str, labels: list[str],
                add: list[str] = (), remove: list[str] = (), single: bool = False) -> list[str]:
    """Adds and removes tags on one item for a bulk edit, records the tag links and returns the item's new label list (the
    labels the tags belong to). An item with no tag links yet starts from the default tags of its labels."""
    kind = TAG_TYPE.get(object_type, object_type)
    current = (tags_for_object(conn, kind, object_id) if _has(conn, "object_tags") else []) or list(labels)
    gone = {r.lower() for r in remove}
    wanted = [t for t in current if t.lower() not in gone]
    for name in add:
        if name and name.lower() not in {w.lower() for w in wanted}:
            wanted = [name] if single else wanted + [name]
    record(conn, object_type, object_id, wanted)
    return labels_of(conn, wanted, keep_unknown=True)


def ensure_finance_shelf(conn: sqlite3.Connection) -> None:
    """The Finance shelf, in the space Personal, is where the tags of transactions started; created once."""
    ensure_schema(conn)
    group = FINANCE_GROUP
    if _has(conn, "label_groups"):
        from .db.labels import ensure_group

        group = ensure_group(conn, FINANCE_GROUP)
    conn.execute("INSERT OR IGNORE INTO label_config (name, color) VALUES (?, 'green')", (FINANCE_LABEL,))
    conn.execute("UPDATE label_config SET label_group = ? WHERE name = ? AND COALESCE(label_group, '') = ''", (group, FINANCE_LABEL))
    if not conn.execute("SELECT 1 FROM label_tags WHERE label_name = ?", (FINANCE_LABEL,)).fetchone():
        add_default_tag(conn, FINANCE_LABEL, "green")
    conn.commit()


def add_finance_tag(conn: sqlite3.Connection, name: str, color: str = "gray", icon: str = "") -> None:
    """A tag from an older backup, filed under the Finance shelf unless the name already means something."""
    ensure_finance_shelf(conn)
    if not name_taken(conn, name):
        conn.execute("INSERT INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                     (name, FINANCE_LABEL, color or "gray", icon or "", datetime.now(timezone.utc).isoformat()))


def tag_styles(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Colour and icon by tag name, for drawing tag pills in tables."""
    if not _has(conn, "label_tags"):
        return {}
    return {r["name"]: {"color": r["color"] or "gray", "icon": r["icon"] or ""} for r in conn.execute("SELECT name, color, icon FROM label_tags")}


def move_finance_tags(conn: sqlite3.Connection) -> int:
    """Files the old finance tags under the Finance shelf and turns their links on transactions and scheduled transactions
    into tag links, then drops the old finance tag tables. A finance tag whose name is already a tag or shelf elsewhere gets
    the suffix " (finance)". Returns the number of tags moved."""
    old = [t for t in ("finance_tags", "finance_transaction_tags", "finance_scheduled_tags") if _has(conn, t)]
    if not old:
        return 0
    ensure_finance_shelf(conn)
    now = datetime.now(timezone.utc).isoformat()
    names: dict[str, str] = {}
    rows = [dict(r) for r in conn.execute("SELECT name, color, icon FROM finance_tags")] if "finance_tags" in old else []
    used = {r["tag_name"] for r in conn.execute("SELECT DISTINCT tag AS tag_name FROM finance_transaction_tags")} if "finance_transaction_tags" in old else set()
    used |= {r["tag_name"] for r in conn.execute("SELECT DISTINCT tag AS tag_name FROM finance_scheduled_tags")} if "finance_scheduled_tags" in old else set()
    known = {r["name"] for r in rows}
    rows += [{"name": n, "color": "gray", "icon": ""} for n in sorted(used - known)]
    for r in rows:
        existing = get_tag(conn, r["name"])
        target = r["name"]
        if existing and existing["label_name"] == FINANCE_LABEL:
            names[r["name"]] = existing["name"]
            continue
        if name_taken(conn, target, allow_label=None):
            target = f"{r['name']} (finance)"
        names[r["name"]] = target
        conn.execute("INSERT OR IGNORE INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                     (target, FINANCE_LABEL, r["color"] or "gray", r["icon"] or "", now))
    if "finance_transaction_tags" in old:
        for r in conn.execute("SELECT txn_uid, tag FROM finance_transaction_tags").fetchall():
            conn.execute("INSERT OR IGNORE INTO object_tags VALUES ('transaction', ?, ?)", (r["txn_uid"], names.get(r["tag"], r["tag"])))
    if "finance_scheduled_tags" in old:
        for r in conn.execute("SELECT scheduled_uid, tag FROM finance_scheduled_tags").fetchall():
            conn.execute("INSERT OR IGNORE INTO object_tags VALUES ('scheduled', ?, ?)", (r["scheduled_uid"], names.get(r["tag"], r["tag"])))
    for t in old:
        conn.execute(f"DROP TABLE {t}")
    conn.commit()
    return len(rows)


PROJECTS_SHELF = "Projects"


def fold_projects(conn: sqlite3.Connection) -> list[str]:
    """Every remaining project becomes a tag (with its own look) on the shelf Projects, which takes the farthest of their
    deadlines, in the space most of them sat in. Their items keep the tag; the project shelves, their auto-shelf lists and
    the project flag go. Returns the names folded."""
    from . import db

    ensure_schema(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM label_config WHERE is_project = 1 ORDER BY name COLLATE NOCASE")]
    if not rows:
        return []
    spaces = [r["label_group"] for r in rows if r.get("label_group")]
    conn.execute("INSERT OR IGNORE INTO label_config (name, color, icon) VALUES (?, 'gray', 'folder')", (PROJECTS_SHELF,))
    if spaces:
        conn.execute("UPDATE label_config SET label_group = ? WHERE name = ? COLLATE NOCASE AND COALESCE(label_group, '') = ''",
                     (max(set(spaces), key=spaces.count), PROJECTS_SHELF))
    shelf = conn.execute("SELECT name FROM label_config WHERE name = ? COLLATE NOCASE", (PROJECTS_SHELF,)).fetchone()["name"]
    add_default_tag(conn, shelf, "gray", "folder")
    deadlines = [r.get("deadline_date") or r.get("end_date") for r in rows]
    farthest = max((d for d in deadlines if d), default=None)
    if farthest:
        conn.execute("UPDATE label_config SET has_deadline = 1, deadline_date = ? WHERE name = ? AND (deadline_date IS NULL OR deadline_date < ?)",
                     (farthest, shelf, farthest))
    folded = []
    for r in rows:
        name = r["name"]
        if name.lower() == shelf.lower():
            conn.execute("UPDATE label_config SET is_project = 0 WHERE name = ?", (name,))
            continue
        add_default_tag(conn, name, r.get("color") or "gray", r.get("icon") or "")
        linked = {(x["object_type"], x["object_id"]) for x in conn.execute("SELECT DISTINCT object_type, object_id FROM object_tags")}
        for x in conn.execute(f"SELECT object_type, object_id FROM object_labels WHERE label_name = ? AND object_type IN ({', '.join('?' for _ in LABEL_OBJECT_TYPES)})",
                              (name, *LABEL_OBJECT_TYPES)).fetchall():
            kind = TAG_TYPE.get(x["object_type"], x["object_type"])
            if (kind, x["object_id"]) not in linked:
                conn.execute("INSERT OR IGNORE INTO object_tags VALUES (?, ?, ?)", (kind, x["object_id"], name))
        db.merge_labels(conn, name, shelf)
        folded.append(name)
    conn.execute("UPDATE label_config SET auto_labels = NULL WHERE auto_labels IS NOT NULL")
    conn.commit()
    return folded


def _label_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {r["name"]: dict(r) for r in conn.execute("SELECT * FROM label_config")}


def plan_migration(conn: sqlite3.Connection, fold: dict[str, str] | None = None) -> dict[str, Any]:
    """What `apply_migration` would create, as counts and lists. Changes nothing. `fold` maps a project name to the
    label it becomes a tag under (for example a semester label holding its classes)."""
    labels = _label_rows(conn)
    used = {r["label_name"] for r in conn.execute("SELECT DISTINCT label_name FROM object_labels")}
    fold = {k: v for k, v in (fold or {}).items() if labels.get(k, {}).get("is_project")}
    finance = [r["name"] for r in conn.execute("SELECT name FROM finance_tags")] if _has(conn, "finance_tags") else []
    links = conn.execute("SELECT COUNT(*) FROM finance_transaction_tags").fetchone()[0] if _has(conn, "finance_tags") else 0
    label_links = conn.execute(f"SELECT COUNT(*) FROM object_labels WHERE object_type IN ({', '.join('?' for _ in LABEL_OBJECT_TYPES)})",
                               LABEL_OBJECT_TYPES).fetchone()[0]
    return {"labels": sorted((set(labels) | used) - set(fold) | set(fold.values()), key=str.lower), "folded": fold,
            "projects": [n for n, c in labels.items() if c.get("is_project")], "finance_tags": finance,
            "finance_links": links, "label_links": label_links}


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def apply_migration(conn: sqlite3.Connection, fold: dict[str, str] | None = None) -> dict[str, Any]:
    """Gives every label its default tag, files finance tags under a Finance label and turns label links into tag
    links. A folded project becomes a tag under its target label, which takes the latest folded deadline. Old rows
    stay in place, dormant."""
    ensure_schema(conn)
    plan = plan_migration(conn, fold)
    labels = _label_rows(conn)
    now = datetime.now(timezone.utc).isoformat()

    def ensure_label(name: str, group: str, color: str = "gray") -> None:
        conn.execute("INSERT OR IGNORE INTO label_config (name, color) VALUES (?, ?)", (name, color))
        conn.execute("UPDATE label_config SET label_group = ? WHERE name = ? AND COALESCE(label_group, '') = ''", (group, name))

    for project, target in plan["folded"].items():
        cfg = labels[project]
        ensure_label(target, cfg.get("label_group") or "", cfg.get("color") or "gray")
        deadline = cfg.get("deadline_date") or cfg.get("end_date")
        if deadline:
            conn.execute("UPDATE label_config SET has_deadline = 1, deadline_date = ? WHERE name = ? "
                         "AND (deadline_date IS NULL OR deadline_date < ?)", (deadline, target, deadline))
        conn.execute("INSERT OR IGNORE INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                     (project, target, cfg.get("color") or "gray", cfg.get("icon") or "", now))
    labels = _label_rows(conn)
    for name in set(plan["labels"]):
        cfg = labels.get(name, {})
        conn.execute("INSERT OR IGNORE INTO label_tags (name, label_name, color, icon, created_at) VALUES (?, ?, ?, ?, ?)",
                     (name, name, cfg.get("color") or "gray", cfg.get("icon") or "", now))
    move_finance_tags(conn)
    # An item that already has tag links (picked in the Tag dropdown) keeps exactly those; only items without any get
    # a link to the default tag of each of their labels.
    tagged = {(r["object_type"], r["object_id"]) for r in conn.execute("SELECT DISTINCT object_type, object_id FROM object_tags")}
    for r in conn.execute(f"SELECT object_type, object_id, label_name FROM object_labels WHERE object_type IN ({', '.join('?' for _ in LABEL_OBJECT_TYPES)})",
                          LABEL_OBJECT_TYPES).fetchall():
        kind = "note" if r["object_type"] == "notebook" else r["object_type"]
        if (kind, r["object_id"]) not in tagged:
            conn.execute("INSERT OR IGNORE INTO object_tags VALUES (?, ?, ?)", (kind, r["object_id"], r["label_name"]))
    conn.commit()
    return plan
