"""Notebook documents, frontmatter fields, citations, glossary and links.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import html
import json
import random
import re
import sqlite3
import string
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from .core import _HTML_TAG_RE, _WIKILINK_TARGET_RE, _collect_block_text, get_app_meta, set_app_meta
from .labels import _attach_tags, _attach_tags_bulk, list_project_labels, set_object_labels


def single_label_tags(conn: sqlite3.Connection, tags: list[str]) -> list[str]:
    """A note has at most one project and one label: the first project label and the first other label, in the given order."""
    project_names = {cfg["name"] for cfg in list_project_labels(conn)}
    project = next((t for t in tags if t in project_names), None)
    label = next((t for t in tags if t not in project_names), None)
    return [t for t in (project, label) if t]


def enforce_one_label_and_project(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Trims every note that has more than one project or label to the first of each, in the order they were attached.

    Returns one report row per changed note: its uid, title and the labels that were dropped."""
    report = []
    rows = conn.execute("SELECT uid, title FROM notebook_documents").fetchall()
    for row in rows:
        names = [r[0] for r in conn.execute(
            "SELECT label_name FROM object_labels WHERE object_type = 'notebook' AND object_id = ? ORDER BY rowid", (row["uid"],))]
        kept = single_label_tags(conn, names)
        if len(kept) < len(names):
            set_object_labels(conn, "notebook", row["uid"], kept)
            report.append({"uid": row["uid"], "title": row["title"], "kept": kept, "dropped": [n for n in names if n not in kept]})
    return report


def upsert_notebook_document(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    tags = data.pop("tags", None)
    properties = data.pop("properties", None)
    cols = ["uid", "title", "content_json", "document_type", "note_type", "is_template", "created_at", "updated_at"]
    if "journal_week" in data:
        cols.append("journal_week")
        data["journal_week"] = data["journal_week"] or ""
    if "pinned" in data:
        cols.append("pinned")
        data["pinned"] = 1 if data["pinned"] else 0
    data["is_template"] = 1 if data.get("is_template") else 0
    if data["is_template"]:
        tags = []
    elif tags is not None:
        tags = single_label_tags(conn, tags)
    values = [data.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid")
    conn.execute(
        f"INSERT INTO notebook_documents ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(uid) DO UPDATE SET {updates}",
        values,
    )
    if tags is not None:
        set_object_labels(conn, "notebook", data["uid"], tags)
    if properties is not None:
        set_notebook_properties(conn, data["uid"], properties)
    content_json = data.get("content_json")
    if content_json is not None:
        try:
            _rebuild_notebook_links(conn, data["uid"], json.loads(content_json))
        except (json.JSONDecodeError, TypeError):
            pass
    conn.commit()
    if data.get("note_type"):
        ensure_notebook_note_type_option(conn, data["note_type"])


def _attach_notebook_properties(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    d["properties"] = list_notebook_properties(conn, d["uid"])
    return d


def _attach_notebook_properties_bulk(conn: sqlite3.Connection, dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch form of `_attach_notebook_properties` -- one `IN (...)` query
    for the whole document list instead of one per row, same reasoning as
    `_attach_contact_phones_emails_bulk`. Mutates and returns `dicts` in
    place, same contract as `_attach_notebook_properties`."""
    if not dicts:
        return dicts
    ids = [d["uid"] for d in dicts]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM notebook_properties WHERE notebook_uid IN ({placeholders}) "
        "ORDER BY position ASC, created_at ASC",
        ids,
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["notebook_uid"], []).append(dict(r))
    for d in dicts:
        d["properties"] = grouped.get(d["uid"], [])
    return dicts


def get_notebook_document(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM notebook_documents WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        return None
    return _attach_notebook_properties(conn, _attach_tags(conn, "notebook", dict(row)))


def list_notebook_documents(
    conn: sqlite3.Connection, label: str | None = None, scope: str = "notes"
) -> list[dict[str, Any]]:
    """All documents by default -- the "All documents" safety-net view for anything with no label at
        all. `label` narrows to one label's membership, for the Groups/Labels
        widget (Phase 3) -- note that's a different, narrower query than a
        label/group *page* actually needs (those already aggregate membership
        themselves via object_labels; this is just the plain per-label list).

        `scope` is "notes" (the default: templates stay out of every list),
        "templates" or "all" (backups).
    """
    clauses: list[str] = []
    params: list[str] = []
    if scope == "notes":
        clauses.append("is_template = 0")
    elif scope == "templates":
        clauses.append("is_template = 1")
    if label:
        clauses.append(
            "uid IN (SELECT object_id FROM object_labels "
            "WHERE object_type = 'notebook' AND label_name = ?)"
        )
        params.append(label)
    query = "SELECT * FROM notebook_documents"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    docs = _attach_tags_bulk(conn, "notebook", [dict(r) for r in rows])
    return _attach_notebook_properties_bulk(conn, docs)


def _folder_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every note (no templates) with just what folders need, so content is never loaded for a count."""
    projects = list_project_labels(conn)
    open_projects = {c["name"] for c in projects if not c.get("archived_at")}
    all_projects = {c["name"] for c in projects}
    rows = [dict(r) for r in conn.execute(
        "SELECT uid, title, note_type, created_at, updated_at, journal_week, pinned FROM notebook_documents WHERE is_template = 0")]
    by_uid = {r["uid"]: r for r in rows}
    for uid, label in conn.execute("SELECT object_id, label_name FROM object_labels WHERE object_type = 'notebook' ORDER BY rowid"):
        row = by_uid.get(uid)
        if row is None:
            continue
        row.setdefault("tags", []).append(label)
    for row in rows:
        tags = row.setdefault("tags", [])
        if row["journal_week"]:
            row["folder"] = ("journal", row["journal_week"][:4])
            continue
        project = next((t for t in tags if t in open_projects), None)
        label = next((t for t in tags if t not in all_projects), None)
        row["folder"] = ("project", project) if project else (("label", label) if label else ("unfiled", ""))
    return rows


def get_journal_template(conn: sqlite3.Connection) -> str:
    """The uid of the template new journal entries start from, or an empty string."""
    uid = get_app_meta(conn, "notebook_journal_template") or ""
    doc = get_notebook_document(conn, uid) if uid else None
    return uid if doc and doc["is_template"] else ""


def set_journal_template(conn: sqlite3.Connection, uid: str) -> None:
    set_app_meta(conn, "notebook_journal_template", uid or "")


def week_key(day) -> str:
    """The ISO year and week of a date, as `2026-42`."""
    year, week, _ = day.isocalendar()
    return f"{year}-{week:02d}"


def weeks_in_year(year: int) -> int:
    from datetime import date

    return date(year, 12, 28).isocalendar()[1]


def list_journal_years(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The years that have journal notes, newest first, with their note counts."""
    counts: dict[str, int] = {}
    for row in _folder_rows(conn):
        if row["folder"][0] == "journal":
            counts[row["folder"][1]] = counts.get(row["folder"][1], 0) + 1
    return [{"name": y, "count": c} for y, c in sorted(counts.items(), reverse=True)]


def journal_entry_for(conn: sqlite3.Connection, week: str) -> str | None:
    row = conn.execute("SELECT uid FROM notebook_documents WHERE journal_week = ? AND is_template = 0", (week,)).fetchone()
    return row["uid"] if row else None


def create_journal_entry(conn: sqlite3.Connection, week: str, template_uid: str = "") -> str:
    """A week's journal note: the existing one, or a new one that starts from the journal template."""
    existing = journal_entry_for(conn, week)
    if existing:
        return existing
    template = get_notebook_document(conn, template_uid) if template_uid else None
    content = template["content_json"] if template and template["is_template"] else json.dumps({"blocks": []})
    now = datetime.now(timezone.utc).isoformat()
    uid = str(uuid.uuid4())
    upsert_notebook_document(conn, {
        "uid": uid, "title": week, "content_json": content, "document_type": "full",
        "note_type": template["note_type"] if template else "", "created_at": now, "updated_at": now,
        "journal_week": week, "tags": [],
        "properties": [{"key": p["key"], "value": p["value"]} for p in template["properties"]] if template else [],
    })
    return uid


def journal_year_weeks(conn: sqlite3.Connection, year: str, current_week: str) -> list[dict[str, Any]]:
    """Every week of a year with the note written that week, if any, for the week strip."""
    notes = {r["journal_week"]: r["uid"] for r in conn.execute(
        "SELECT uid, journal_week FROM notebook_documents WHERE journal_week LIKE ? AND is_template = 0", (year + "-%",))}
    return [
        {"week": f"{year}-{n:02d}", "nr": n, "uid": notes.get(f"{year}-{n:02d}"), "is_current": f"{year}-{n:02d}" == current_week}
        for n in range(1, weeks_in_year(int(year)) + 1)
    ]


def set_notebook_pinned(conn: sqlite3.Connection, uid: str, pinned: bool) -> None:
    conn.execute("UPDATE notebook_documents SET pinned = ? WHERE uid = ? AND is_template = 0", (1 if pinned else 0, uid))
    conn.commit()


def list_pinned_notebook_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The pinned notes, most recently edited first, with the same fields a folder row shows."""
    rows = sorted((r for r in _folder_rows(conn) if r["pinned"]), key=lambda r: r["updated_at"] or "", reverse=True)
    looks = notebook_note_type_looks(conn)
    for row in rows:
        content = conn.execute("SELECT content_json FROM notebook_documents WHERE uid = ?", (row["uid"],)).fetchone()
        row["subtitle"] = _first_line(content[0]) if content else ""
        look = looks.get(row["note_type"] or "", dict(NOTEBOOK_TYPE_LOOK_FALLBACK))
        row["type_icon"], row["type_color"] = look["icon"], look["color"]
    return rows


def latest_notebook_document(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """The most recently edited note, for the home's Continue card."""
    row = conn.execute("SELECT uid, title FROM notebook_documents WHERE is_template = 0 ORDER BY updated_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def list_notebook_folders(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """The home's folders: open projects first, then labels, with Unfiled last among the labels.

    A note sits in exactly one folder: its open project, else its label, else Unfiled."""
    from .labels import effective_label_config

    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _folder_rows(conn):
        if row["folder"][0] == "journal":
            continue
        entry = counts.setdefault(row["folder"], {"kind": row["folder"][0], "name": row["folder"][1], "count": 0, "last": ""})
        entry["count"] += 1
        entry["last"] = max(entry["last"], row["updated_at"] or "")
    out: dict[str, list[dict[str, Any]]] = {"projects": [], "labels": []}
    for (kind, name), entry in counts.items():
        if kind != "unfiled":
            cfg = effective_label_config(conn, name)
            entry["color"] = cfg.get("color") or "gray"
            entry["icon"] = cfg.get("icon") or ""
        else:
            entry["color"], entry["icon"] = "gray", "inbox"
        out["projects" if kind == "project" else "labels"].append(entry)
    out["projects"].sort(key=lambda e: e["last"], reverse=True)
    out["labels"].sort(key=lambda e: (e["kind"] == "unfiled", e["name"].lower()))
    return out


def list_notebook_folder_documents(
    conn: sqlite3.Connection, kind: str, name: str, note_type: str = "", sort: str = "created", query: str = "",
    limit: int = 30, offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """One page of a folder's notes and the total, filtered by type and a title search."""
    rows = [r for r in _folder_rows(conn) if r["folder"] == (kind, name if kind != "unfiled" else "")]
    if note_type:
        rows = [r for r in rows if r["note_type"] == note_type]
    if query:
        needle = query.lower()
        rows = [r for r in rows if needle in (r["title"] or "").lower()]
    if sort == "title":
        rows.sort(key=lambda r: (r["title"] or "").lower())
    elif kind == "journal":
        rows.sort(key=lambda r: r["journal_week"], reverse=True)
    elif sort == "updated":
        rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    else:
        rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    total = len(rows)
    page = rows[offset: offset + limit]
    for row in page:
        content = conn.execute("SELECT content_json FROM notebook_documents WHERE uid = ?", (row["uid"],)).fetchone()
        row["subtitle"] = _first_line(content[0]) if content else ""
    return page, total


def _first_line(content_json: str, limit: int = 110) -> str:
    """The first line of a note's body text, for the list's subtitle: the first paragraph, quote or list item."""
    try:
        blocks = json.loads(content_json or "{}").get("blocks") or []
    except (json.JSONDecodeError, TypeError, AttributeError):
        return ""
    for block in blocks:
        data = block.get("data") or {}
        raw = ""
        if block.get("type") in ("paragraph", "quote"):
            raw = data.get("text") or ""
        elif block.get("type") == "list" and data.get("items"):
            first = data["items"][0]
            raw = first.get("content", "") if isinstance(first, dict) else str(first)
        text = html.unescape(_HTML_TAG_RE.sub("", raw)).strip()
        if text:
            return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return ""


def list_notebook_note_types_in_use(conn: sqlite3.Connection) -> list[str]:
    """The Type picker's suggestion list --
        same "in use" shape as `list_tag_names_in_use` for Labels, not a
        hardcoded starter list: whatever `note_type` values currently exist on
        at least one document, nothing more. A type naturally drops off this
        list the moment nothing uses it any more (the last document carrying
        it gets re-typed or deleted) -- there's no separate registry table to
        clean up, unlike labels' `label_config` (note_type has no config of
        its own, just this one free-text column), so "in use" and "known" are
        the same query. `ms_allow_new` on the properties modal's Type field is
        what lets a brand-new type be typed in the first place; this is just
        what gets suggested afterward.
    """
    rows = conn.execute(
        "SELECT DISTINCT note_type FROM notebook_documents WHERE TRIM(note_type) != '' ORDER BY note_type COLLATE NOCASE"
    ).fetchall()
    return [r["note_type"] for r in rows]


def delete_notebook_document(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM notebook_documents WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM object_labels WHERE object_type = 'notebook' AND object_id = ?", (uid,))
    conn.execute("DELETE FROM notebook_properties WHERE notebook_uid = ?", (uid,))
    conn.execute("DELETE FROM glossary_term_references WHERE ref_type = 'notebook' AND ref_uid = ?", (uid,))
    conn.execute("DELETE FROM notebook_glossary_excluded_terms WHERE notebook_uid = ?", (uid,))
    conn.commit()


def list_notebook_properties(conn: sqlite3.Connection, notebook_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM notebook_properties WHERE notebook_uid = ? ORDER BY position ASC, created_at ASC",
        (notebook_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_notebook_properties(conn: sqlite3.Connection, notebook_uid: str, items: list[dict[str, Any]]) -> None:
    """Rows with a blank key are dropped silently -- an empty row in the
    form is "no property here", not a property with no name -- same
    "blank value means absent" rule set_contact_phones uses for blank
    numbers."""
    conn.execute("DELETE FROM notebook_properties WHERE notebook_uid = ?", (notebook_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        key = (item.get("key") or "").strip()
        if not key:
            continue
        conn.execute(
            "INSERT INTO notebook_properties (uid, notebook_uid, key, value, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), notebook_uid, key, (item.get("value") or "").strip(), position, now),
        )
        position += 1
    conn.commit()


def list_notebook_property_keys_in_use(conn: sqlite3.Connection) -> list[str]:
    """The property-key picker's suggestion list -- same "in use"
        shape as `list_notebook_note_types_in_use`/`list_tag_names_in_use`,
        across every document's properties, not scoped to one document: a key
        like "DOI" typed on one document should be pickable on another without
        retyping it. Distinct across the whole table (not just this
        document's own rows, which `list_notebook_properties` already
        covers), case-sensitive (keys are display labels like "DOI"/
        "Institution", not a normalized vocabulary the way note_type's
        canonical list is proposed to become).
    """
    rows = conn.execute(
        "SELECT DISTINCT key FROM notebook_properties WHERE TRIM(key) != '' ORDER BY key COLLATE NOCASE"
    ).fetchall()
    return [r["key"] for r in rows]


BUILTIN_NOTEBOOK_FIELD_UIDS: dict[str, str] = {
    "title": "builtin-title",
    "author": "builtin-author",
    "note_type": "builtin-note_type",
}

NOTEBOOK_TYPE_LOOK_FALLBACK = {"color": "gray", "icon": "file-text"}

# Field types the schema table offers (Settings > Notebook's Type picker).
# Only these two carry an option list -- NOTEBOOK_FIELD_OPTION_TYPES below.
NOTEBOOK_FIELD_TYPES = [
    ("text", "Text"),
    ("number", "Number"),
    ("date", "Date"),
    ("select", "Select"),
    ("multi-select", "Multi-select"),
    ("boolean", "Boolean"),
    ("url", "URL"),
]

NOTEBOOK_FIELD_OPTION_TYPES = frozenset({"select", "multi-select"})


def _attach_notebook_field_options(conn: sqlite3.Connection, field: dict[str, Any]) -> dict[str, Any]:
    field["options"] = (
        list_notebook_field_options(conn, field["uid"]) if field["type"] in NOTEBOOK_FIELD_OPTION_TYPES else []
    )
    return field


def list_notebook_field_config(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM notebook_field_config ORDER BY position ASC, created_at ASC"
    ).fetchall()
    return [_attach_notebook_field_options(conn, dict(r)) for r in rows]


def get_notebook_field_config(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM notebook_field_config WHERE uid = ?", (uid,)).fetchone()
    return _attach_notebook_field_options(conn, dict(row)) if row else None


def _next_notebook_field_position(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT MAX(position) AS m FROM notebook_field_config").fetchone()
    return (row["m"] or 0) + 1


def upsert_notebook_field_config(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Create (no `uid`) or update (existing `uid`) one field definition --
        same single-call-site contract as upsert_label_config/upsert_holiday. A
        new field is appended after the last position; an existing field keeps
        its position unless the caller explicitly reorders it.

        `options`: same pop-then-
        write-the-child-rows shape as upsert_notebook_document's `tags`/
        `properties` -- absent means "leave the option list alone", present
        (even `[]`) replaces it via set_notebook_field_options.
    """
    data = dict(row)
    options = data.pop("options", None)
    uid = data.get("uid") or str(uuid.uuid4())
    existing = get_notebook_field_config(conn, uid) if data.get("uid") else None
    position = data.get("position")
    if position is None:
        position = existing["position"] if existing else _next_notebook_field_position(conn)
    created_at = data.get("created_at") or (existing["created_at"] if existing else datetime.now(timezone.utc).isoformat())
    builtin = data.get("builtin")
    if builtin is None:
        builtin = existing["builtin"] if existing else 0
    conn.execute(
        "INSERT INTO notebook_field_config (uid, key, label, type, default_value, position, builtin, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET key=excluded.key, label=excluded.label, type=excluded.type, "
        "default_value=excluded.default_value, position=excluded.position, builtin=excluded.builtin",
        (
            uid, data.get("key") or "", data.get("label") or data.get("key") or "",
            data.get("type") or "text", data.get("default_value"),
            position, 1 if builtin else 0, created_at,
        ),
    )
    conn.commit()
    if options is not None:
        set_notebook_field_options(conn, uid, options)
    return uid


def new_notebook_field_key(conn: sqlite3.Connection, label: str) -> str:
    """Stored name for a new field: the label's slug plus a short random id (`birth_date_k3x9`), unique among fields."""
    slug = re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode().lower())
    slug = slug.strip("_")[:24].strip("_") or "field"
    taken = {r["key"].lower() for r in conn.execute("SELECT key FROM notebook_field_config")}
    while True:
        key = f"{slug}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
        if key not in taken:
            return key


def delete_notebook_field_config(conn: sqlite3.Connection, uid: str) -> None:
    field = conn.execute("SELECT key FROM notebook_field_config WHERE uid = ?", (uid,)).fetchone()
    if field is not None:
        conn.execute(
            "DELETE FROM notebook_properties WHERE LOWER(key) = LOWER(?) "
            "AND notebook_uid IN (SELECT uid FROM notebook_documents WHERE is_template = 1)",
            (field["key"],),
        )
    conn.execute("DELETE FROM notebook_field_config WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM notebook_field_options WHERE field_uid = ?", (uid,))
    conn.commit()


def list_notebook_field_options(conn: sqlite3.Connection, field_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM notebook_field_options WHERE field_uid = ? ORDER BY position ASC, created_at ASC",
        (field_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_notebook_field_options(conn: sqlite3.Connection, field_uid: str, items: list[dict[str, Any]]) -> None:
    """Rows with a blank value are dropped silently -- same "blank means
    absent" rule set_notebook_properties uses for a blank key."""
    conn.execute("DELETE FROM notebook_field_options WHERE field_uid = ?", (field_uid,))
    now = datetime.now(timezone.utc).isoformat()
    position = 0
    for item in items:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        conn.execute(
            "INSERT INTO notebook_field_options (uid, field_uid, value, color, icon, position, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), field_uid, value, item.get("color") or None, item.get("icon") or None, position, now),
        )
        position += 1
    conn.commit()


_NOTEBOOK_BUILTIN_FIELDS_SEEDED_KEY = "notebook_builtin_fields_seeded_v1"


def seed_builtin_notebook_fields(conn: sqlite3.Connection) -> None:
    """title/author/note_type always appear in Settings > Notebook -- see notebook_field_config's own CREATE
        TABLE comment. Runs once (app_meta marker, same convention as
        backfill_label_modules/_fix_contacts_widget_default): re-running on
        every connect would otherwise replace note_type's option list (color/
        icon) with these defaults on every restart, silently discarding
        anything the user already repainted from Settings.
    """
    if get_app_meta(conn, _NOTEBOOK_BUILTIN_FIELDS_SEEDED_KEY):
        return
    upsert_notebook_field_config(conn, {
        "uid": BUILTIN_NOTEBOOK_FIELD_UIDS["title"], "key": "title", "label": "Title",
        "type": "text", "builtin": 1, "position": -3,
    })
    upsert_notebook_field_config(conn, {
        "uid": BUILTIN_NOTEBOOK_FIELD_UIDS["author"], "key": "author", "label": "Author",
        "type": "text", "builtin": 1, "position": -2,
    })
    upsert_notebook_field_config(conn, {
        "uid": BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"], "key": "note_type", "label": "Type",
        "type": "select", "builtin": 1, "position": -1, "options": [],
    })
    set_app_meta(conn, _NOTEBOOK_BUILTIN_FIELDS_SEEDED_KEY, "1")


def ensure_notebook_note_type_option(conn: sqlite3.Connection, note_type: str) -> None:
    """A note_type typed for the first time (document_properties_modal's
        free-text "new type" path -- still possible, the "known inconsistency"
        its own comment flags) gets a real option row with a neutral fallback
        look, so it immediately shows up in Settings > Notebook ready to be
        repainted instead of silently having no editable color/icon anywhere.
        Called from upsert_notebook_document; a no-op once the value already
        has an option.
    """
    note_type = (note_type or "").strip()
    if not note_type:
        return
    field = get_notebook_field_config(conn, BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"])
    if field is None or any(o["value"] == note_type for o in field["options"]):
        return
    now = datetime.now(timezone.utc).isoformat()
    position = max((o["position"] for o in field["options"]), default=-1) + 1
    conn.execute(
        "INSERT INTO notebook_field_options (uid, field_uid, value, color, icon, position, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()), field["uid"], note_type,
            NOTEBOOK_TYPE_LOOK_FALLBACK["color"], NOTEBOOK_TYPE_LOOK_FALLBACK["icon"],
            position, now,
        ),
    )
    conn.commit()


def notebook_note_type_looks(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Every note_type's current color/icon, keyed by value -- the one
    place routers/notebook.py reads to paint the Browse rail/rows (and,
    eventually, any other note_type badge) instead of a hardcoded Python
    dict, so a color/icon edited from Settings > Notebook takes effect
    everywhere note_type renders."""
    field = get_notebook_field_config(conn, BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"])
    if field is None:
        return {}
    return {
        o["value"]: {"color": o["color"] or NOTEBOOK_TYPE_LOOK_FALLBACK["color"], "icon": o["icon"] or NOTEBOOK_TYPE_LOOK_FALLBACK["icon"]}
        for o in field["options"]
    }


def notebook_note_type_look(conn: sqlite3.Connection, note_type: str) -> dict[str, str]:
    """Single-value convenience wrapper around notebook_note_type_looks --
    the fallback look for a blank/unknown note_type (a document with no
    Type picked yet, or a race with ensure_notebook_note_type_option)."""
    return notebook_note_type_looks(conn).get(note_type, dict(NOTEBOOK_TYPE_LOOK_FALLBACK))


def get_notebook_document_content(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    """Raw Editor.js OutputData for the one JSON-in/JSON-out endpoint pair
    (GET/PUT /notebook/{uid}/content) -- see the `notebook_documents`
    schema comment for why this bypasses the normal HTML-fragment
    convention. Returns None only when the document itself doesn't exist;
    a document that somehow has unparseable `content_json` gets an empty
    document back rather than a 500, since Editor.js can always render and
    resave an empty block list."""
    row = conn.execute("SELECT content_json FROM notebook_documents WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["content_json"])
    except (json.JSONDecodeError, TypeError):
        return {"blocks": []}


def set_notebook_document_content(conn: sqlite3.Connection, uid: str, content: dict[str, Any]) -> bool:
    cur = conn.execute(
        "UPDATE notebook_documents SET content_json = ?, updated_at = ? WHERE uid = ?",
        (json.dumps(content), datetime.now(timezone.utc).isoformat(), uid),
    )
    if cur.rowcount > 0:
        _rebuild_notebook_links(conn, uid, content)
        _rebuild_notebook_glossary_terms(conn, uid, content)
        _rebuild_notebook_bibliography_from_footnotes(conn, uid, content)
    conn.commit()
    return cur.rowcount > 0


def _extract_wikilink_target_uids(content: dict[str, Any]) -> list[str]:
    """Every target uid currently linked from `content`'s own markers,
    document order, de-duped on first appearance -- see
    `_WIKILINK_TARGET_RE`'s own comment for why this is a flat regex pass
    rather than a block-structure walk."""
    text = json.dumps(content)
    seen: list[str] = []
    for m in _WIKILINK_TARGET_RE.finditer(text):
        uid = m.group(1)
        if uid and uid not in seen:
            seen.append(uid)
    return seen


def set_notebook_links(conn: sqlite3.Connection, source_uid: str, target_uids: list[str]) -> None:
    """Whole-list replace, same "delete everything, re-insert" convention
    as set_notebook_citations/set_notebook_glossary_terms -- the only
    caller is `_rebuild_notebook_links` below, never a route directly."""
    conn.execute("DELETE FROM notebook_links WHERE source_uid = ?", (source_uid,))
    now = datetime.now(timezone.utc).isoformat()
    for target_uid in target_uids:
        if target_uid == source_uid:
            continue  # a document can't link to itself
        conn.execute(
            "INSERT OR IGNORE INTO notebook_links (source_uid, target_uid, created_at) VALUES (?, ?, ?)",
            (source_uid, target_uid, now),
        )
    conn.commit()


def _rebuild_notebook_links(conn: sqlite3.Connection, uid: str, content: dict[str, Any]) -> None:
    set_notebook_links(conn, uid, _extract_wikilink_target_uids(content))


def list_notebook_backlinks(conn: sqlite3.Connection, uid: str) -> list[dict[str, Any]]:
    """Other documents whose content currently links TO this one -- the
    Relationships sidebar tab's "Linked from" section
    (roadmap-mvp-to-full-product-checklist's "Backlink/outbound-link
    queries powering the relationships sidebar section"). Server-rendered
    on page load only (no live client-side update the way Outline/
    Footnotes get) -- unlike this document's own outbound links, another
    document's content isn't loaded into this page's DOM for a client-side
    walk to ever find."""
    rows = conn.execute(
        "SELECT d.* FROM notebook_documents d JOIN notebook_links l ON l.source_uid = d.uid "
        "WHERE l.target_uid = ? AND d.is_template = 0 ORDER BY d.updated_at DESC",
        (uid,),
    ).fetchall()
    docs = [dict(r) for r in rows]
    type_looks = notebook_note_type_looks(conn)
    for d in docs:
        look = type_looks.get(d.get("note_type") or "", dict(NOTEBOOK_TYPE_LOOK_FALLBACK))
        d["type_icon"] = look["icon"]
        d["type_color"] = look["color"]
    return docs


def search_notebook_documents(
    conn: sqlite3.Connection, q: str = "", exclude_uid: str | None = None, limit: int = 20, rank_for: str | None = None
) -> list[dict[str, Any]]:
    """The wikilink inline tool's own search/pick autocomplete (static/
    notebook/notebook_wikilinks.js, GET /notebook/search) -- resolves a
    link to a real target uid at creation time (roadmap: "not fuzzy
    title-text matching at render time"), so this is only ever called from
    that one picker, never used to re-resolve an existing link later. Plain
    substring match on title, most-recently-updated first when `q` is
    blank (so opening the picker with nothing typed yet still shows
    something useful instead of an empty list). Each result carries its
    note_type's color/icon (notebook_note_type_looks) so the picker's
    dropdown and the inline marker it creates can both render the same
    look with no second lookup."""
    q = (q or "").strip().lower()
    rows = conn.execute(
        "SELECT uid, title, note_type FROM notebook_documents WHERE is_template = 0 ORDER BY updated_at DESC"
    ).fetchall()
    docs = [dict(r) for r in rows]
    if exclude_uid:
        docs = [d for d in docs if d["uid"] != exclude_uid]
    if q:
        docs = [d for d in docs if q in (d["title"] or "").lower()]
    if rank_for:
        # Recommended order: same project (a shared project label) first, then a shared label, then A-Z.
        labels = {
            r["label_name"]
            for r in conn.execute("SELECT label_name FROM object_labels WHERE object_type = 'notebook' AND object_id = ?", (rank_for,))
        }
        projects = {
            r["name"] for r in conn.execute("SELECT name FROM label_config WHERE is_project = 1")
        } & labels
        doc_labels: dict[str, set[str]] = {}
        for r in conn.execute("SELECT object_id, label_name FROM object_labels WHERE object_type = 'notebook'"):
            doc_labels.setdefault(r["object_id"], set()).add(r["label_name"])

        def tier(d: dict[str, Any]) -> int:
            mine = doc_labels.get(d["uid"], set())
            if mine & projects:
                return 0
            return 1 if mine & labels else 2

        docs.sort(key=lambda d: (tier(d), (d["title"] or "").lower()))
    type_looks = notebook_note_type_looks(conn)
    for d in docs:
        look = type_looks.get(d.get("note_type") or "", dict(NOTEBOOK_TYPE_LOOK_FALLBACK))
        d["color"] = look["color"]
        d["icon"] = look["icon"]
    return docs[:limit]


def search_link_targets(
    conn: sqlite3.Connection, q: str = "", exclude_uid: str | None = None, kinds: str = "all", limit: int = 40
) -> list[dict[str, Any]]:
    """What the link picker offers: entries first, then notes in the same project, the same label, and all others.

    Each result has a `group` heading, a `kind` (entry or doc), a subtitle and its icon and color. Within a
    group the order is A to Z. `kinds="doc"` leaves entries out."""
    q = (q or "").strip().lower()
    items: list[dict[str, Any]] = []
    if kinds != "doc":
        looks = entry_kind_looks(conn)
        for e in list_glossary_terms(conn):
            if q and not any(q in n.lower() for n in [e["term"], *e["aliases"]]):
                continue
            look = looks.get(e["kind"], {"icon": "tag", "color": "teal"})
            items.append({"kind": "entry", "uid": e["uid"], "title": e["term"], "subtitle": e["kind"],
                          "icon": look["icon"], "color": look["color"], "group": "Entries"})
    rows = [r for r in _folder_rows(conn) if r["uid"] != exclude_uid and (not q or q in (r["title"] or "").lower())]
    mine = next((r for r in _folder_rows(conn) if r["uid"] == exclude_uid), None)
    project_names = {c["name"] for c in list_project_labels(conn)}
    my_projects = {t for t in (mine["tags"] if mine else []) if t in project_names}
    my_labels = {t for t in (mine["tags"] if mine else []) if t not in project_names}
    looks = notebook_note_type_looks(conn)
    docs = []
    for r in rows:
        tags = set(r["tags"])
        group = "Same project" if tags & my_projects else "Same label" if tags & my_labels else "Notes"
        look = looks.get(r["note_type"] or "", dict(NOTEBOOK_TYPE_LOOK_FALLBACK))
        folder = r["folder"][1]
        docs.append({"kind": "doc", "uid": r["uid"], "title": r["title"] or "Untitled", "subtitle": folder or r["note_type"] or "",
                     "note_type": r["note_type"] or "", "icon": look["icon"], "color": look["color"], "group": group})
    order = {"Same project": 0, "Same label": 1, "Notes": 2}
    docs.sort(key=lambda d: (order[d["group"]], d["title"].lower()))
    return (items + docs)[:limit]


def list_document_entry_names(conn: sqlite3.Connection, notebook_uid: str) -> list[dict[str, Any]]:
    """The entries attached to a note with every name that links them in its text, for the dotted links."""
    rows = conn.execute(
        "SELECT t.uid, t.term, t.kind, t.aliases_json FROM notebook_glossary_terms g JOIN glossary_terms t ON t.uid = g.term_uid "
        "WHERE g.notebook_uid = ?", (notebook_uid,)).fetchall()
    out = []
    for r in rows:
        try:
            aliases = json.loads(r["aliases_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            aliases = []
        out.append({"uid": r["uid"], "kind": r["kind"], "names": [n for n in [r["term"], *aliases] if str(n).strip()]})
    return out


def detach_notebook_glossary_term(conn: sqlite3.Connection, notebook_uid: str, term_uid: str) -> None:
    """Stops linking one entry in one note; it stays off through the exclusion list."""
    remaining = [r["term_uid"] for r in conn.execute(
        "SELECT term_uid FROM notebook_glossary_terms WHERE notebook_uid = ? ORDER BY position", (notebook_uid,)) if r["term_uid"] != term_uid]
    set_notebook_glossary_terms(conn, notebook_uid, remaining)


# Close to CSL-JSON's own type vocabulary (the architecture doc's "worth
# designing columns close to CSL-JSON from the start" note) without
# adopting its full type list -- same "small, app-defined, not a DB enum
# or freeform text" treatment as `note_type`.
CITATION_TYPES = [
    ("book", "Book"),
    ("article-journal", "Journal article"),
    ("chapter", "Book chapter"),
    ("webpage", "Web page"),
    ("thesis", "Thesis"),
    ("report", "Report"),
    ("conference-paper", "Conference paper"),
    ("other", "Other"),
]


def _attach_citation_authors(row: dict[str, Any]) -> dict[str, Any]:
    """Parses `authors_json` into the list of {family, given} dicts every
    caller actually wants -- same "store JSON text, hand back a real list"
    contract `get_notebook_document_content` uses for `content_json`, just
    without that function's own need to tolerate a raw Editor.js shape."""
    try:
        row["authors"] = json.loads(row.pop("authors_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        row["authors"] = []
    return row


def format_citation_authors(authors: list[dict[str, Any]]) -> str:
    """"Family, G." per author, comma-joined -- the one place this
    rendering lives so the library table, the bibliography sidebar, and
    the bottom-of-document bibliography all show identical text for the
    same citation."""
    parts = []
    for a in authors:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family and given:
            parts.append(f"{family}, {given[0]}.")
        else:
            parts.append(family or given)
    return ", ".join(p for p in parts if p)


def format_citation_display(c: dict[str, Any]) -> str:
    """A single-line "Family, G. (Year). Title. Container." rendering,
    shared by the library table, the attach-picker's option labels, and
    the sidebar/bottom bibliography lists -- one formatting rule, not a
    copy living in each template. Missing pieces are simply omitted
    rather than left as empty punctuation (a citation mid-entry, with no
    year or container yet, still reads cleanly)."""
    bits = []
    authors = format_citation_authors(c.get("authors") or [])
    if authors:
        bits.append(authors)
    if c.get("year"):
        bits.append(f"({c['year']})")
    title = (c.get("title") or "").strip() or "Untitled"
    bits.append(f"{title}." if not title.endswith(".") else title)
    if c.get("container_title"):
        bits.append(f"{c['container_title']}.")
    return " ".join(bits)


def list_citations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM citations ORDER BY title COLLATE NOCASE ASC").fetchall()
    return [_attach_citation_authors(dict(r)) for r in rows]


def get_citation(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM citations WHERE uid = ?", (uid,)).fetchone()
    return _attach_citation_authors(dict(row)) if row else None


CITATION_EXTRA_FIELDS = ("subtitle", "edition", "volume", "issue", "pages", "publisher", "place", "isbn", "issn",
                         "accessed", "institution", "degree", "editors", "note")
_CITATION_BASE_FIELDS = ("type", "title", "authors_json", "year", "container_title", "doi", "url")


def upsert_citation(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Creates or updates a citation. `authors` (a list of {family, given}) is stored as `authors_json`.

    A field missing from `row` keeps its stored value on update."""
    now = datetime.now(timezone.utc).isoformat()
    uid = row.get("uid") or str(uuid.uuid4())
    existing = conn.execute("SELECT * FROM citations WHERE uid = ?", (uid,)).fetchone()
    values = {
        "type": row.get("type") or "book", "title": row.get("title") or "",
        "authors_json": json.dumps(row.get("authors") or []), "year": row.get("year") or "",
        "container_title": row.get("container_title") or "", "doi": row.get("doi") or "", "url": row.get("url") or "",
    }
    for name in CITATION_EXTRA_FIELDS:
        values[name] = row[name] if name in row else (existing[name] if existing else "")
        values[name] = (values[name] or "").strip()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in values) + ", updated_at = ?"
        conn.execute(f"UPDATE citations SET {sets} WHERE uid = ?", [*values.values(), now, uid])
    else:
        cols = ["uid", *values, "created_at", "updated_at"]
        conn.execute(
            f"INSERT INTO citations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [uid, *values.values(), row.get("created_at") or now, now],
        )
    conn.commit()
    return uid


def get_citation_format(conn: sqlite3.Connection) -> str:
    from ..citation_formats import DEFAULT_STYLE, STYLES

    value = get_app_meta(conn, "notebook_citation_format")
    return value if value in STYLES else DEFAULT_STYLE


def set_citation_format(conn: sqlite3.Connection, style: str) -> None:
    from ..citation_formats import STYLES

    if style in STYLES:
        set_app_meta(conn, "notebook_citation_format", style)


def delete_citation(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM citations WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM notebook_citations WHERE citation_uid = ?", (uid,))
    conn.execute("DELETE FROM glossary_term_references WHERE ref_type = 'citation' AND ref_uid = ?", (uid,))
    conn.commit()


def list_notebook_citations(conn: sqlite3.Connection, notebook_uid: str) -> list[dict[str, Any]]:
    """This document's attached citations, in the document's own order
    (not library order) -- the one query both the sidebar bibliography
    panel and the bottom read-only bibliography section use."""
    rows = conn.execute(
        "SELECT c.* FROM citations c JOIN notebook_citations nc ON nc.citation_uid = c.uid "
        "WHERE nc.notebook_uid = ? ORDER BY nc.position ASC, nc.created_at ASC",
        (notebook_uid,),
    ).fetchall()
    return [_attach_citation_authors(dict(r)) for r in rows]


def set_notebook_citations(conn: sqlite3.Connection, notebook_uid: str, citation_uids: list[str]) -> None:
    """Replaces a document's whole attached-citation list -- same
    "delete, then re-insert in the given order" convention as
    set_notebook_properties, so the attach modal's checkbox order (whatever
    order the library lists them in) becomes the stored position."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM notebook_citations WHERE notebook_uid = ?", (notebook_uid,))
    for position, citation_uid in enumerate(dict.fromkeys(citation_uids)):
        conn.execute(
            "INSERT INTO notebook_citations (notebook_uid, citation_uid, position, created_at) VALUES (?, ?, ?, ?)",
            (notebook_uid, citation_uid, position, now),
        )
    conn.commit()


def attach_notebook_citation(conn: sqlite3.Connection, notebook_uid: str, citation_uid: str, position: float = 0, created_at: str | None = None) -> None:
    """Idempotent single-row attach -- used by export.py's backup restore,
    where notebook_citations rows are restored independently of (and after)
    both the document and citation pools, unlike set_notebook_citations'
    whole-list-replace shape which would need every row collected first."""
    conn.execute(
        "INSERT OR REPLACE INTO notebook_citations (notebook_uid, citation_uid, position, created_at) "
        "VALUES (?, ?, ?, ?)",
        (notebook_uid, citation_uid, position, created_at or datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def add_notebook_citation_if_missing(conn: sqlite3.Connection, notebook_uid: str, citation_uid: str) -> None:
    """Appends one citation to a document's bibliography only if it isn't
    already attached -- never reorders or touches existing rows, unlike
    set_notebook_citations' whole-list replace. The footnote auto-add pass
    (roadmap item J's "bibliography auto-add", _rebuild_notebook_bibliography_
    from_footnotes below) is the only caller; the reverse direction (removing
    a citation from the bibliography) is deliberately never driven by this,
    per that roadmap item's own text."""
    existing = conn.execute(
        "SELECT 1 FROM notebook_citations WHERE notebook_uid = ? AND citation_uid = ?",
        (notebook_uid, citation_uid),
    ).fetchone()
    if existing:
        return
    max_position = conn.execute(
        "SELECT MAX(position) FROM notebook_citations WHERE notebook_uid = ?", (notebook_uid,)
    ).fetchone()[0]
    next_position = (max_position + 1) if max_position is not None else 0
    conn.execute(
        "INSERT INTO notebook_citations (notebook_uid, citation_uid, position, created_at) VALUES (?, ?, ?, ?)",
        (notebook_uid, citation_uid, next_position, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# Matches a footnote marker's `data-footnote-data` attribute inside
# content_json's own JSON-serialized text (static/notebook/
# notebook_footnotes.js stamps this onto each `.cdx-footnote-ref` span via
# `setAttribute("data-footnote-data", JSON.stringify(data))` -- the browser
# HTML-entity-escapes the JSON's own quotes to `&quot;` when it lands in
# `innerHTML`, so the captured group is valid JSON after `html.unescape`).
# Same "flat regex over the whole serialized dict" approach as
# `_WIKILINK_TARGET_RE` above, for the same reason: this looks for one very
# specific attribute pattern, not prose text, so it doesn't need to know
# which block type the marker ended up inside.
_FOOTNOTE_DATA_RE = re.compile(r'data-footnote-data=\\?"([^"\\]*)\\?"')


def _extract_footnote_citation_uids(content: dict[str, Any]) -> list[str]:
    """Every citation uid referenced by any footnote/endnote marker in
    `content` -- single-citation kinds (page_citation/ibidem/opere_citato/
    confer/passim) store `{citation: {uid, ...}, page}`, apud stores
    `{citations: {original: {...}, secondary: {...}}, page}` (two sources,
    both counted); Custom note markers carry no `data-footnote-data` at all
    and are silently skipped. Document order, de-duped on first appearance."""
    text = json.dumps(content)
    seen: list[str] = []

    def _add(citation: Any) -> None:
        if isinstance(citation, dict):
            uid = citation.get("uid")
            if uid and uid not in seen:
                seen.append(uid)

    for m in _FOOTNOTE_DATA_RE.finditer(text):
        try:
            data = json.loads(html.unescape(m.group(1)))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        _add(data.get("citation"))
        citations = data.get("citations")
        if isinstance(citations, dict):
            _add(citations.get("original"))
            _add(citations.get("secondary"))
    return seen


def _rebuild_notebook_bibliography_from_footnotes(conn: sqlite3.Connection, uid: str, content: dict[str, Any]) -> None:
    """Auto-add pass run on every content save (roadmap item J, session 9c)
    -- mirrors `_rebuild_notebook_links`'s "recomputed on every save" shape,
    but append-only (`add_notebook_citation_if_missing`), never removing a
    citation the user attached directly without a footnote ever referencing
    it, per that item's own text."""
    for citation_uid in _extract_footnote_citation_uids(content):
        add_notebook_citation_if_missing(conn, uid, citation_uid)


def citation_author_key(author: dict[str, Any]) -> str:
    """"Family, Given" in full (not `format_citation_authors`' abbreviated
    "Family, G." display form) -- the value used both as a filter-dropdown
    option and as the thing a selected filter is matched against, so a
    picked option always matches exactly the citations it came from."""
    family = (author.get("family") or "").strip()
    given = (author.get("given") or "").strip()
    if family and given:
        return f"{family}, {given}"
    return family or given


def list_citation_authors_in_use(conn: sqlite3.Connection) -> list[str]:
    """Every distinct author (any position, not just first) across the
    whole library -- the citations/filters modal's Author dropdown is
    built from this instead of a fixed list, same "distinct values
    actually in the data" shape as list_notebook_property_keys_in_use."""
    seen: set[str] = set()
    for c in list_citations(conn):
        for a in c["authors"]:
            key = citation_author_key(a)
            if key:
                seen.add(key)
    return sorted(seen, key=str.casefold)


def parse_citation_year(year: str) -> int | None:
    """None for blank/non-numeric years (free text -- nothing enforces a
        4-digit year) -- the one place both the Year-range filter and anything
        else that needs a real int out of this column should parse it, rather
        than each caller re-deriving its own check. 1850"), which the `except` below
        turns into the same None every other non-numeric year already got.
    """
    year = (year or "").strip()
    if not year:
        return None
    try:
        return int(year)
    except ValueError:
        return None


def citation_year_sort_key(year: str) -> tuple[int, Any]:
    """Numeric years (negative/BCE included) sort newest-first; blank/
    non-numeric years sort after all of them, alphabetically among
    themselves rather than erroring or crashing a plain string/int
    comparison. Negating a parsed int naturally orders -100 (100 BCE, more
    recent) before -500 (500 BCE) the same way it orders 2020 before
    1924 -- no separate BCE-aware branch needed."""
    parsed = parse_citation_year(year)
    if parsed is not None:
        return (0, -parsed)
    return (1, (year or "").strip().casefold())


ENTRY_KIND_DEFAULT = "Term"


def _entry_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["aliases"] = [str(x) for x in json.loads(d.pop("aliases_json", "[]") or "[]") if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        d["aliases"] = []
    d["kind"] = d.get("kind") or ENTRY_KIND_DEFAULT
    return d


def list_glossary_terms(conn: sqlite3.Connection, q: str = "", kind: str = "") -> list[dict[str, Any]]:
    """Entries, alphabetical by name. `q` is a case-insensitive match on name, alternate names or text; `kind` narrows to one kind."""
    rows = conn.execute("SELECT * FROM glossary_terms ORDER BY term COLLATE NOCASE ASC").fetchall()
    terms = [_entry_row(r) for r in rows]
    if kind:
        terms = [t for t in terms if t["kind"] == kind]
    q = (q or "").strip().casefold()
    if q:
        terms = [
            t for t in terms
            if q in t["term"].casefold() or q in t["definition"].casefold() or any(q in a.casefold() for a in t["aliases"])
        ]
    return terms


def get_glossary_term(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM glossary_terms WHERE uid = ?", (uid,)).fetchone()
    return _entry_row(row) if row else None


def upsert_glossary_term(conn: sqlite3.Connection, row: dict[str, Any]) -> str:
    """Creates or updates an entry. `kind`, `aliases` and `wiki_uid` are only written when given."""
    now = datetime.now(timezone.utc).isoformat()
    uid = row.get("uid") or str(uuid.uuid4())
    existing = conn.execute("SELECT uid FROM glossary_terms WHERE uid = ?", (uid,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE glossary_terms SET term = ?, definition = ?, updated_at = ? WHERE uid = ?",
            (row.get("term") or "", row.get("definition") or "", now, uid),
        )
    else:
        conn.execute(
            "INSERT INTO glossary_terms (uid, term, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (uid, row.get("term") or "", row.get("definition") or "", row.get("created_at") or now, now),
        )
    if row.get("kind") is not None:
        kind = (row["kind"] or "").strip() or ENTRY_KIND_DEFAULT
        ensure_entry_kind(conn, kind)
        conn.execute("UPDATE glossary_terms SET kind = ? WHERE uid = ?", (kind, uid))
    if row.get("aliases") is not None:
        aliases = [a.strip() for a in row["aliases"] if a and a.strip()]
        conn.execute("UPDATE glossary_terms SET aliases_json = ? WHERE uid = ?", (json.dumps(aliases), uid))
    if row.get("wiki_uid") is not None:
        conn.execute("UPDATE glossary_terms SET wiki_uid = ? WHERE uid = ?", (row["wiki_uid"] or "", uid))
    conn.commit()
    return uid


# Common kinds start with a fitting icon and color; any other kind gets the plain tag, and all can be changed.
_KIND_STARTER_LOOKS = {
    "person": ("user", "blue"), "people": ("users", "blue"), "place": ("map-pin", "green"), "event": ("calendar", "orange"),
    "organization": ("building", "violet"), "institution": ("building", "violet"), "concept": ("lightbulb", "amber"),
    "war": ("flag", "red"), "period": ("clock", "sand"), "country": ("flag", "sky"), "city": ("map-pin", "green"),
}


def ensure_entry_kind(conn: sqlite3.Connection, name: str) -> None:
    """A kind typed for the first time gets a default look the user can change later."""
    name = (name or "").strip()
    if not name:
        return
    if conn.execute("SELECT 1 FROM entry_kinds WHERE name = ?", (name,)).fetchone():
        return
    position = (conn.execute("SELECT COALESCE(MAX(position), 0) FROM entry_kinds").fetchone()[0] or 0) + 1
    icon, color = _KIND_STARTER_LOOKS.get(name.lower(), ("tag", "teal"))
    conn.execute("INSERT INTO entry_kinds (name, icon, color, position) VALUES (?, ?, ?, ?)", (name, icon, color, position))
    conn.commit()


def list_entry_kinds(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every kind with its look and its fields (names only, in order)."""
    ensure_entry_kind(conn, ENTRY_KIND_DEFAULT)
    rows = conn.execute("SELECT * FROM entry_kinds ORDER BY position, name COLLATE NOCASE").fetchall()
    fields: dict[str, list[str]] = {}
    for r in conn.execute("SELECT kind, name FROM entry_kind_fields ORDER BY position, rowid"):
        fields.setdefault(r["kind"], []).append(r["name"])
    return [{**dict(r), "fields": fields.get(r["name"], [])} for r in rows]


def save_entry_kind(
    conn: sqlite3.Connection, original: str, name: str, icon: str, color: str, keep_fields: list[str], new_fields: list[str]
) -> dict[str, str] | None:
    """Creates a kind (`original` empty) or updates one, renaming it everywhere when its name changes.

    Existing field names never change: only the ones in `keep_fields` stay, and `new_fields` are added.
    Returns {"field", "message"} when the input is refused."""
    name = (name or "").strip()
    if not name:
        return {"field": "name", "message": "A type needs a name"}
    if original == ENTRY_KIND_DEFAULT and name != ENTRY_KIND_DEFAULT:
        return {"field": "name", "message": f"{ENTRY_KIND_DEFAULT} is the default type and keeps its name"}
    taken = {k["name"].lower() for k in list_entry_kinds(conn) if k["name"] != original}
    if name.lower() in taken:
        return {"field": "name", "message": "A type with this name already exists"}
    existing = [k for k in list_entry_kinds(conn) if k["name"] == original]
    current_fields = existing[0]["fields"] if existing else []
    kept = [f for f in current_fields if f in set(keep_fields or [])]
    added: list[str] = []
    for f in new_fields or []:
        f = (f or "").strip()
        if f and f.lower() not in {x.lower() for x in kept + added}:
            added.append(f)
    if original and existing:
        if original != name:
            conn.execute("UPDATE entry_kinds SET name = ? WHERE name = ?", (name, original))
            conn.execute("UPDATE glossary_terms SET kind = ? WHERE kind = ?", (name, original))
            conn.execute("UPDATE entry_kind_fields SET kind = ? WHERE kind = ?", (name, original))
        conn.execute("UPDATE entry_kinds SET icon = ?, color = ? WHERE name = ?", (icon or "tag", color or "teal", name))
        conn.execute("DELETE FROM entry_kind_fields WHERE kind = ?", (name,))
    else:
        position = (conn.execute("SELECT COALESCE(MAX(position), 0) FROM entry_kinds").fetchone()[0] or 0) + 1
        conn.execute("INSERT INTO entry_kinds (name, icon, color, position) VALUES (?, ?, ?, ?)", (name, icon or "tag", color or "teal", position))
    for position, field in enumerate(kept + added):
        conn.execute("INSERT INTO entry_kind_fields (kind, name, position) VALUES (?, ?, ?)", (name, field, position))
    conn.commit()
    return None


def delete_entry_kind(conn: sqlite3.Connection, name: str) -> dict[str, str] | None:
    """Deletes a kind nobody uses; the default kind and kinds with entries stay."""
    if name == ENTRY_KIND_DEFAULT:
        return {"field": "name", "message": f"{ENTRY_KIND_DEFAULT} is the default type and cannot be deleted"}
    used = conn.execute("SELECT COUNT(*) FROM glossary_terms WHERE kind = ?", (name,)).fetchone()[0]
    if used:
        return {"field": "name", "message": f"{used} entr{'ies use' if used != 1 else 'y uses'} this type, change them first"}
    conn.execute("DELETE FROM entry_kinds WHERE name = ?", (name,))
    conn.execute("DELETE FROM entry_kind_fields WHERE kind = ?", (name,))
    conn.commit()
    return None


def set_entry_kind_look(conn: sqlite3.Connection, name: str, icon: str, color: str) -> None:
    ensure_entry_kind(conn, name)
    conn.execute("UPDATE entry_kinds SET icon = ?, color = ? WHERE name = ?", (icon or "tag", color or "teal", name))
    conn.commit()


def entry_kind_fields(conn: sqlite3.Connection, kind: str) -> list[str]:
    return next((k["fields"] for k in list_entry_kinds(conn) if k["name"] == kind), [])


def entry_field_values(conn: sqlite3.Connection, term_uid: str, kind: str) -> dict[str, str]:
    """What an entry holds for each of its kind's fields (stored as titled text boxes named like the field)."""
    stored = {s["title"]: s["body"] for s in list_glossary_sections(conn, term_uid)}
    return {name: stored.get(name, "") for name in entry_kind_fields(conn, kind)}


def entry_custom_sections(conn: sqlite3.Connection, term_uid: str, kind: str) -> list[dict[str, Any]]:
    """The titled text boxes of an entry that are not one of its kind's fields."""
    names = set(entry_kind_fields(conn, kind))
    return [s for s in list_glossary_sections(conn, term_uid) if s["title"] not in names]


def entry_kind_looks(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    return {k["name"]: {"icon": k["icon"], "color": k["color"]} for k in list_entry_kinds(conn)}


def list_entry_mentions(conn: sqlite3.Connection, term_uid: str) -> list[dict[str, Any]]:
    """The notes an entry is attached to, newest edit first."""
    rows = conn.execute(
        "SELECT d.uid, d.title, d.note_type FROM notebook_glossary_terms g JOIN notebook_documents d ON d.uid = g.notebook_uid "
        "WHERE g.term_uid = ? AND d.is_template = 0 ORDER BY d.updated_at DESC",
        (term_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_glossary_sections(conn: sqlite3.Connection, term_uid: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM glossary_term_sections WHERE term_uid = ? ORDER BY position, rowid", (term_uid,)).fetchall()
    return [dict(r) for r in rows]


def set_glossary_sections(conn: sqlite3.Connection, term_uid: str, sections: list[tuple[str, str]]) -> None:
    """Replaces a term's extra text blocks with (title, body) pairs, in order; a block with neither is dropped."""
    conn.execute("DELETE FROM glossary_term_sections WHERE term_uid = ?", (term_uid,))
    position = 0
    for title, body in sections:
        title, body = (title or "").strip(), (body or "").strip()
        if not title and not body:
            continue
        position += 1
        conn.execute(
            "INSERT INTO glossary_term_sections (uid, term_uid, title, body, position) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), term_uid, title, body, position),
        )
    conn.commit()


def restore_glossary_section(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO glossary_term_sections (uid, term_uid, title, body, position) VALUES (?, ?, ?, ?, ?)",
        (row["uid"], row["term_uid"], row.get("title") or "", row.get("body") or "", row.get("position") or 0),
    )
    conn.commit()


def delete_glossary_term(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM glossary_terms WHERE uid = ?", (uid,))
    conn.execute("DELETE FROM notebook_glossary_terms WHERE term_uid = ?", (uid,))
    conn.execute("DELETE FROM glossary_term_references WHERE term_uid = ?", (uid,))
    conn.execute("DELETE FROM glossary_term_sections WHERE term_uid = ?", (uid,))
    conn.execute("DELETE FROM notebook_glossary_excluded_terms WHERE term_uid = ?", (uid,))
    conn.commit()


def list_notebook_glossary_terms(conn: sqlite3.Connection, notebook_uid: str) -> list[dict[str, Any]]:
    """This document's attached terms, in the document's own order -- the
    one query the sidebar Glossary tab uses. Same shape as
    list_notebook_citations, plus `auto` (item H, session 7) so a caller
    can tell an auto-detected attachment apart from a manually-picked one
    without a second query."""
    rows = conn.execute(
        "SELECT g.*, ng.auto AS auto FROM glossary_terms g JOIN notebook_glossary_terms ng ON ng.term_uid = g.uid "
        "WHERE ng.notebook_uid = ? ORDER BY ng.position ASC, ng.created_at ASC",
        (notebook_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def group_entries_by_kind(conn: sqlite3.Connection, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries grouped under their kind, in the kinds' own order, each group with its icon and color."""
    out = []
    for kind in list_entry_kinds(conn):
        members = [e for e in entries if (e.get("kind") or ENTRY_KIND_DEFAULT) == kind["name"]]
        if members:
            out.append({"kind": kind["name"], "icon": kind["icon"], "color": kind["color"], "entries": members})
    return out


def set_notebook_glossary_terms(conn: sqlite3.Connection, notebook_uid: str, term_uids: list[str]) -> None:
    """Replaces a document's whole *manually*-attached term list -- same
    "delete, then re-insert in the given order" convention as
    set_notebook_citations, extended for item H (session 7, auto-detect)
    to manage the two tables that convention introduced. Every term_uid
    submitted here always lands as a manual (auto=0) row, whether it was
    previously absent, already manual, or auto-attached -- the attach
    modal checkbox always wins over whatever the text scan decided. Any
    term that was attached before this call (manually or automatically)
    but is missing from the new list is removed and recorded in
    notebook_glossary_excluded_terms, so the next content save's
    auto-detect pass (_rebuild_notebook_glossary_terms) doesn't silently
    re-add a match the user just removed -- the roadmap's "manually remove
    an auto-applied one to override a false positive" rule. A term_uid
    that IS in the new list has any existing exclusion cleared, since
    attaching it again is the user reversing that override."""
    now = datetime.now(timezone.utc).isoformat()
    new_uids = list(dict.fromkeys(term_uids))
    previously_attached = {
        row["term_uid"]
        for row in conn.execute(
            "SELECT term_uid FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,)
        ).fetchall()
    }
    conn.execute("DELETE FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,))
    for position, term_uid in enumerate(new_uids):
        conn.execute(
            "INSERT INTO notebook_glossary_terms (notebook_uid, term_uid, position, created_at, auto) "
            "VALUES (?, ?, ?, ?, 0)",
            (notebook_uid, term_uid, position, now),
        )
        conn.execute(
            "DELETE FROM notebook_glossary_excluded_terms WHERE notebook_uid = ? AND term_uid = ?",
            (notebook_uid, term_uid),
        )
    for term_uid in previously_attached - set(new_uids):
        conn.execute(
            "INSERT OR REPLACE INTO notebook_glossary_excluded_terms (notebook_uid, term_uid, created_at) "
            "VALUES (?, ?, ?)",
            (notebook_uid, term_uid, now),
        )
    conn.commit()


def attach_notebook_glossary_term(
    conn: sqlite3.Connection, notebook_uid: str, term_uid: str, position: float = 0,
    created_at: str | None = None, auto: int = 0,
) -> None:
    """Idempotent single-row attach -- used by export.py's backup restore,
    same shape as attach_notebook_citation. `auto` defaults to 0 (manual)
    for any caller that predates item H (session 7); a backup payload
    written since then carries the real stored value."""
    conn.execute(
        "INSERT OR REPLACE INTO notebook_glossary_terms (notebook_uid, term_uid, position, created_at, auto) "
        "VALUES (?, ?, ?, ?, ?)",
        (notebook_uid, term_uid, position, created_at or datetime.now(timezone.utc).isoformat(), int(auto)),
    )
    conn.commit()


def attach_notebook_glossary_excluded_term(
    conn: sqlite3.Connection, notebook_uid: str, term_uid: str, created_at: str | None = None
) -> None:
    """Idempotent single-row attach for the auto-detect override table
    (roadmap item H, session 7) -- used by export.py's backup restore,
    same shape as attach_notebook_glossary_term."""
    conn.execute(
        "INSERT OR REPLACE INTO notebook_glossary_excluded_terms (notebook_uid, term_uid, created_at) "
        "VALUES (?, ?, ?)",
        (notebook_uid, term_uid, created_at or datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


_NOTEBOOK_TEXT_SKIP_BLOCK_TYPES = {"code"}


def _extract_notebook_plain_text(content: dict[str, Any]) -> str:
    """Flattens content_json's blocks into one lowercase plain-text blob
    for glossary term-occurrence scanning (`_rebuild_notebook_glossary_
    terms` below). Unlike `_extract_wikilink_target_uids`'s flat regex over
    the *whole* serialized dict (safe there because it only looks for one
    very specific attribute pattern), term matching needs real prose text,
    not structural JSON noise -- a block's own `"type": "paragraph"` value
    could coincidentally equal a real glossary term, so this walks each
    block's `data` payload only, never its `type` field. Code blocks are
    skipped outright (source code text shouldn't trigger a glossary
    match). Inline HTML tags (bold/italic/wikilink spans Editor.js embeds
    directly in `text` fields) are stripped to a space rather than deleted
    outright, so a tag boundary can't accidentally fuse two separate words
    into one token."""
    parts: list[str] = []
    for block in content.get("blocks", []) or []:
        if not isinstance(block, dict) or block.get("type") in _NOTEBOOK_TEXT_SKIP_BLOCK_TYPES:
            continue
        _collect_block_text(block.get("data", {}), parts)
    text = _HTML_TAG_RE.sub(" ", " ".join(parts))
    return text.lower()


def _detect_glossary_term_uids(conn: sqlite3.Connection, content: dict[str, Any]) -> list[str]:
    """Every glossary term whose own text literally appears (case-
    insensitive, whole-word) in `content`'s plain text -- the scan
    `_rebuild_notebook_glossary_terms` below acts on."""
    text = _extract_notebook_plain_text(content)
    if not text.strip():
        return []
    detected = []
    for row in conn.execute("SELECT uid, term, aliases_json FROM glossary_terms").fetchall():
        try:
            aliases = json.loads(row["aliases_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            aliases = []
        names = [(row["term"] or "").strip().lower()] + [str(a).strip().lower() for a in aliases]
        if any(n and re.search(r"\b" + re.escape(n) + r"\b", text) for n in names):
            detected.append(row["uid"])
    return detected


def autofill_notebook_glossary_terms(conn: sqlite3.Connection, notebook_uid: str) -> dict[str, Any]:
    """The sidebar's Auto-fill button: attaches every glossary term found in the saved document.

    Unlike the pass on each save, an explicit Auto-fill also brings back terms the user removed
    earlier (and clears their exclusion), since pressing it asks for the full list. Returns the
    names added and how many of those were restored."""
    content = get_notebook_document_content(conn, notebook_uid)
    if content is None:
        return {"added": [], "restored": 0}
    attached = {
        row["term_uid"]
        for row in conn.execute("SELECT term_uid FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,))
    }
    excluded = {
        row["term_uid"]
        for row in conn.execute("SELECT term_uid FROM notebook_glossary_excluded_terms WHERE notebook_uid = ?", (notebook_uid,))
    }
    names = {row["uid"]: row["term"] for row in conn.execute("SELECT uid, term FROM glossary_terms")}
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT MAX(position) AS mx FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,)).fetchone()
    position = (row["mx"] if row and row["mx"] is not None else -1) + 1
    added, restored = [], 0
    for term_uid in _detect_glossary_term_uids(conn, content):
        if term_uid in attached:
            continue
        conn.execute(
            "INSERT INTO notebook_glossary_terms (notebook_uid, term_uid, position, created_at, auto) VALUES (?, ?, ?, ?, 1)",
            (notebook_uid, term_uid, position, now),
        )
        conn.execute("DELETE FROM notebook_glossary_excluded_terms WHERE notebook_uid = ? AND term_uid = ?", (notebook_uid, term_uid))
        position += 1
        restored += term_uid in excluded
        added.append(names.get(term_uid, ""))
    conn.commit()
    return {"added": added, "restored": restored}


def _rebuild_notebook_glossary_terms(conn: sqlite3.Connection, notebook_uid: str, content: dict[str, Any]) -> None:
    """Auto-attach/auto-remove pass run on every content save (roadmap item
    H, session 7) -- mirrors `_rebuild_notebook_links`'s own "recomputed on
    every save" shape, but layered onto `notebook_glossary_terms` itself
    rather than a brand-new table, since a manually-attached row (the
    existing attach modal, item F's "existing surface, not a new one"
    rule) has to live in the same join table. The `auto` column is what
    makes that safe: this function only ever inserts or deletes rows where
    auto=1, never touching a manually-attached (auto=0) row, and
    `notebook_glossary_excluded_terms` (written only by
    `set_notebook_glossary_terms`, the attach modal's own save path) is
    checked here so a term the user explicitly removed to override a
    false-positive match doesn't get silently re-attached by the very next
    save."""
    detected = set(_detect_glossary_term_uids(conn, content))
    existing = {
        row["term_uid"]: row["auto"]
        for row in conn.execute(
            "SELECT term_uid, auto FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,)
        ).fetchall()
    }
    excluded = {
        row["term_uid"]
        for row in conn.execute(
            "SELECT term_uid FROM notebook_glossary_excluded_terms WHERE notebook_uid = ?", (notebook_uid,)
        ).fetchall()
    }
    now = datetime.now(timezone.utc).isoformat()
    for term_uid, auto in existing.items():
        if auto and term_uid not in detected:
            conn.execute(
                "DELETE FROM notebook_glossary_terms WHERE notebook_uid = ? AND term_uid = ?",
                (notebook_uid, term_uid),
            )
    position_row = conn.execute(
        "SELECT MAX(position) AS mx FROM notebook_glossary_terms WHERE notebook_uid = ?", (notebook_uid,)
    ).fetchone()
    next_position = (position_row["mx"] if position_row and position_row["mx"] is not None else -1) + 1
    for term_uid in sorted(detected):
        if term_uid in existing or term_uid in excluded:
            continue
        conn.execute(
            "INSERT INTO notebook_glossary_terms (notebook_uid, term_uid, position, created_at, auto) "
            "VALUES (?, ?, ?, ?, 1)",
            (notebook_uid, term_uid, next_position, now),
        )
        next_position += 1
    conn.commit()


GLOSSARY_REFERENCE_TYPES = ("notebook", "citation")


def list_glossary_term_references(conn: sqlite3.Connection, term_uid: str) -> list[dict[str, Any]]:
    """This term's reference list, in its own order. Each row carries
    `ref_type`/`ref_uid` plus a resolved `name` (the referenced document's
    title or the referenced citation's formatted display string) so a
    caller never has to join back out to notebook_documents/citations
    itself -- a reference to a since-deleted document/citation is silently
    dropped from the result (nothing to resolve a name from, and nothing
    useful to link to), rather than rendering a broken entry."""
    rows = conn.execute(
        "SELECT ref_type, ref_uid, position, created_at FROM glossary_term_references "
        "WHERE term_uid = ? ORDER BY position ASC, created_at ASC",
        (term_uid,),
    ).fetchall()
    out = []
    for r in rows:
        row = dict(r)
        if row["ref_type"] == "notebook":
            doc = get_notebook_document(conn, row["ref_uid"])
            if doc is None:
                continue
            row["name"] = doc["title"]
        elif row["ref_type"] == "citation":
            c = get_citation(conn, row["ref_uid"])
            if c is None:
                continue
            row["name"] = format_citation_display(c)
        else:
            continue
        out.append(row)
    return out


def set_glossary_term_references(conn: sqlite3.Connection, term_uid: str, refs: list[tuple[str, str]]) -> None:
    """Replaces a term's whole reference list -- same "delete, then
    re-insert in the given order" convention as set_notebook_citations.
    `refs` is a list of (ref_type, ref_uid) pairs, already deduplicated by
    the caller's own key choice (a (type, uid) pair, not just uid -- a
    notebook uid and a citation uid are different uuid4 spaces, so
    deduping on uid alone could never actually collide, but keeping the
    pair as the identity is still the honest key for what PRIMARY KEY
    (term_uid, ref_type, ref_uid) actually enforces)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM glossary_term_references WHERE term_uid = ?", (term_uid,))
    for position, (ref_type, ref_uid) in enumerate(dict.fromkeys(refs)):
        if ref_type not in GLOSSARY_REFERENCE_TYPES:
            continue
        conn.execute(
            "INSERT INTO glossary_term_references (term_uid, ref_type, ref_uid, position, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (term_uid, ref_type, ref_uid, position, now),
        )
    conn.commit()


def attach_glossary_term_reference(conn: sqlite3.Connection, term_uid: str, ref_type: str, ref_uid: str, position: float = 0, created_at: str | None = None) -> None:
    """Idempotent single-row attach -- used by export.py's backup restore,
    same shape as attach_notebook_citation/attach_notebook_glossary_term."""
    conn.execute(
        "INSERT OR REPLACE INTO glossary_term_references (term_uid, ref_type, ref_uid, position, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (term_uid, ref_type, ref_uid, position, created_at or datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


NOTEBOOK_SIDEBAR_LAYOUTS = ("stacked", "sidebar")


def get_notebook_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM notebook_settings WHERE id = 1").fetchone()
    if row is None:
        return {"sidebar_layout": "stacked"}
    return dict(row)


def save_notebook_settings(conn: sqlite3.Connection, sidebar_layout: str) -> None:
    if sidebar_layout not in NOTEBOOK_SIDEBAR_LAYOUTS:
        sidebar_layout = "stacked"
    conn.execute(
        "INSERT INTO notebook_settings (id, sidebar_layout) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET sidebar_layout=excluded.sidebar_layout",
        (sidebar_layout,),
    )
    conn.commit()


def list_notebook_content_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """uid, title and raw content of every note (templates excluded), by title, for find and replace."""
    rows = conn.execute("SELECT uid, title, content_json FROM notebook_documents WHERE is_template = 0 ORDER BY title COLLATE NOCASE")
    return [dict(r) for r in rows]
