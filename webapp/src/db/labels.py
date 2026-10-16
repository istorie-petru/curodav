"""Labels, groups, projects and the object-label links.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from .core import MultipleProjectLabelsError, _mirror_legacy_module_fields, get_app_meta, set_app_meta


_LABEL_MODULE_COLUMNS = (
    ("sidebar_pin", "INTEGER NOT NULL DEFAULT 0"),
    ("widget_pin", "INTEGER NOT NULL DEFAULT 0"),
    ("has_deadline", "INTEGER NOT NULL DEFAULT 0"),
    ("deadline_date", "TEXT"),
    ("page_type", "TEXT NOT NULL DEFAULT 'sections'"),
    ("agenda_widget", "INTEGER NOT NULL DEFAULT 1"),
    ("tasks_widget", "INTEGER NOT NULL DEFAULT 1"),
    ("contacts_widget", "INTEGER NOT NULL DEFAULT 1"),
    ("notebook_widget", "INTEGER NOT NULL DEFAULT 1"),
    ("auto_labels", "TEXT"),
)


def _attach_tags(conn: sqlite3.Connection, object_type: str, d: dict[str, Any]) -> dict[str, Any]:
    """Phase 2 (label-space rework): `tags` is no longer a stored JSON
    column on events/tasks/contacts/habits -- it's queried live from
    `object_labels` at read time and attached under the same `tags` key
    every template/ical_rows.py/vcard_rows.py caller already reads, so
    none of those callers needed to change. See
    features/architecture.md §2 item 2."""
    d["tags"] = list_labels_for_object(conn, object_type, d["uid"])
    return d


def _attach_tags_bulk(
    conn: sqlite3.Connection, object_type: str, dicts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Batch form of `_attach_tags` -- one `IN (...)` query for the whole
        result set instead of one `list_labels_for_object` call per row. Every
        `list_*` function that returns more than one row should call this
        instead of looping `_attach_tags` per row. Mutates and returns `dicts` in place, same
        "attach in place" contract `_attach_tags` already has, so callers that
        build a list comprehension around it don't need to change shape.
    """
    if not dicts:
        return dicts
    ids = [d["uid"] for d in dicts]
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT object_id, label_name FROM object_labels "
        f"WHERE object_type = ? AND object_id IN ({placeholders}) "
        "ORDER BY label_name COLLATE NOCASE",
        (object_type, *ids),
    ).fetchall()
    by_id: dict[str, list[str]] = {}
    for r in rows:
        by_id.setdefault(r["object_id"], []).append(r["label_name"])
    for d in dicts:
        d["tags"] = by_id.get(d["uid"], [])
    return dicts


def _reject_multiple_project_labels(conn: sqlite3.Connection, tags: list[str], noun: str = "task") -> None:
    project_names = {cfg["name"] for cfg in list_project_labels(conn)}
    selected = sorted({t for t in tags if t in project_names}, key=str.lower)
    if len(selected) > 1:
        raise MultipleProjectLabelsError(selected, noun)


def project_picker_context(conn: sqlite3.Connection) -> dict[str, Any]:
    """Context for the task/event forms' Project dropdown. Projects are still stored as labels; the forms just
        split them out of the Labels picker because assigning a project means
        something different from tagging.

        `project_items` is the dropdown's options: "No project" first, then
        every open project. `project_names` is every project label, archived
        ones included. The template uses it to find the item's current project
        and to keep projects out of the Labels picker, and it adds an archived
        project back as an option when that's the current value, so saving an
        old item doesn't silently drop it.
    """
    projects = list_project_labels(conn)
    return {
        "project_items": [{"uid": "", "name": "No project"}]
        + [
            {
                "uid": p["name"], "name": p["name"],
                **({"data": {"deadline": p["deadline_date"]}} if p.get("has_deadline") and p.get("deadline_date") else {}),
            }
            for p in projects if not p.get("archived_at")
        ],
        "project_names": [p["name"] for p in projects],
    }


def apply_project_choice(conn: sqlite3.Connection, tags: list[str], project: str | None) -> list[str]:
    """The Project dropdown's value folded back into an item's label list:
    every project label is dropped from `tags`, then the chosen one (if any,
    and only if it really is a project label) is added. Makes the dropdown
    the one authority over which project an item has. A project name typed
    into the Labels picker's "new label" box is dropped rather than creating
    a second project."""
    project_names = {cfg["name"] for cfg in list_project_labels(conn)}
    kept = [t for t in tags if t not in project_names]
    project = (project or "").strip()
    if project and project in project_names:
        kept.append(project)
    return kept


def list_object_label_names(conn: sqlite3.Connection, object_type: str) -> list[str]:
    """Distinct labels in use on every object of `object_type` -- the
    generic form of what list_contact_tag_names has done since Phase 7
    (Contacts' tag filter). Case-preserving on first occurrence, deduped
    case-insensitively, sorted case-insensitively -- object_labels' PK is
    exact-string, so "University" and "university" are two distinct rows
    there; this collapses them the same way list_tag_names_in_use always
    has. Reused by the Phase 9b toolbar rework for the Tasks and Calendar
    (event) label filters, which follow the exact same chip-based pattern
    Contacts pioneered."""
    rows = conn.execute(
        "SELECT DISTINCT label_name FROM object_labels WHERE object_type = ? ORDER BY label_name COLLATE NOCASE",
        (object_type,),
    ).fetchall()
    seen: dict[str, str] = {}
    for r in rows:
        seen.setdefault(r["label_name"].strip().lower(), r["label_name"])
    return sorted(seen.values(), key=str.lower)


# --------------------------------------------------------------------- #
# Object labels (Phase 1, label-space rework) -- the one join table
# labels use. `object_type` is 'task'|'event'|'contact' for now (more
# types land in later phases). No surrogate id/lifecycle -- see
# features/architecture.md §0.1: a label is just a name rows point
# at, "deleting" one is just no row pointing at it anymore.
# --------------------------------------------------------------------- #


def add_object_label(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str) -> None:
    label_name = (label_name or "").strip()
    if not label_name:
        return
    conn.execute(
        "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
        (object_type, object_id, label_name),
    )
    conn.commit()


def remove_object_label(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str) -> None:
    conn.execute(
        "DELETE FROM object_labels WHERE object_type = ? AND object_id = ? AND label_name = ?",
        (object_type, object_id, label_name),
    )
    conn.commit()


def set_object_labels(conn: sqlite3.Connection, object_type: str, object_id: str, label_names: list[str]) -> None:
    """Replaces every label currently on (object_type, object_id) with
        exactly `label_names` -- the common "save this object's label picker"
        write shape, one transaction instead of a diff of adds/removes.
        A label that is new on the object brings along its auto labels
        (see `get_auto_labels`); labels already on the object do not, so a
        label removed by hand stays removed on later saves.
    """
    previous = {n.lower() for n in list_labels_for_object(conn, object_type, object_id)}
    conn.execute(
        "DELETE FROM object_labels WHERE object_type = ? AND object_id = ?", (object_type, object_id)
    )
    seen: set[str] = set()
    queue = [(n or "").strip() for n in label_names or []]
    while queue:
        name = queue.pop(0)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        name = _resolve_label_name(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            (object_type, object_id, name),
        )
        if name.lower() not in previous:
            queue.extend(get_auto_labels(conn, name))
    conn.commit()


def get_auto_labels(conn: sqlite3.Connection, name: str) -> list[str]:
    """Labels a label applies automatically when it is added to an item."""
    row = conn.execute("SELECT auto_labels FROM label_config WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    try:
        names = json.loads(row["auto_labels"]) if row and row["auto_labels"] else []
    except (TypeError, ValueError):
        return []
    return [n for n in names if isinstance(n, str) and n.strip()]


def set_auto_labels(conn: sqlite3.Connection, name: str, labels: list[str]) -> None:
    clean = []
    for n in labels if isinstance(labels, (list, tuple)) else []:
        n = (n or "").strip()
        if n and n.lower() != name.lower() and n.lower() not in {c.lower() for c in clean}:
            clean.append(n)
    conn.execute("UPDATE label_config SET auto_labels = ? WHERE name = ?", (json.dumps(clean) if clean else None, name))
    conn.commit()


def _resolve_label_name(conn: sqlite3.Connection, name: str) -> str:
    """Maps a submitted label string through the
        abbreviation -> full-name synonym table, returning `name` unchanged
        when it isn't one. Rules, all deliberate:
          * A string that's already a real label always wins -- a label
            literally named e.g. "ABC" beats another label's "ABC"
            abbreviation, so an abbreviation can never shadow a genuine label.
          * The match is case-insensitive (labels are deduped
            case-insensitively everywhere, see effective_label_config_ci).
          * Only a *unique* abbreviation resolves -- if two config rows carry
            the same abbreviation (or it collides case-insensitively), the
            string is passed through untouched rather than guessing which
            label the user meant.
    """
    known = {n.lower() for n in list_all_label_names(conn)}
    known |= {r["name"].lower() for r in conn.execute("SELECT name FROM label_config").fetchall()}
    if name.lower() in known:
        return name
    rows = conn.execute(
        "SELECT name FROM label_config "
        "WHERE abbreviation IS NOT NULL AND abbreviation != '' AND abbreviation = ? COLLATE NOCASE",
        (name,),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["name"]
    return name


def resolve_capture_label(conn: sqlite3.Connection, name: str) -> str:
    """Quick Capture's label resolution -- deliberately separate from
        `_resolve_label_name` above (that one only ever resolves an explicit
        `label_config.abbreviation` synonym; this is the spec's own
        approximate-matching pipeline for a capture's `#label` tokens, which
        have no such config row backing them):

          1. Exact match (case-insensitive) against every label already in
             use always wins -- "a label is first matched ... using an exact
             match."
          2. Exact match against a previously-learned alias (`label_aliases`)
             -- a typo already corrected once resolves instantly without
             recomputing the fuzzy match below.
          3. A close-but-not-exact match against every label in use
             (`difflib.get_close_matches`, cutoff 0.8 -- high on purpose, so
             only genuine near-typos resolve, e.g. "uunniversity"/
             "universitty"/"unisity" -> "university" from the spec's own
             examples, not merely related words) is picked automatically ("a
             very close match may be resolved automatically") and persisted
             as a new alias.
          4. Otherwise `name` is returned unchanged -- a genuinely new label,
             "preserving the ability to create genuinely new labels."

        Simplification, noted deliberately: the spec also describes an
        "uncertain match ... suggested for correction" tier sitting between
        (3) and (4), reviewed interactively before being accepted. Quick
        Capture v1 has no such review step (a capture is a single fire-and-
        forget submission, not a multi-turn form) -- step 3's automatic
        resolution doubles as the "user correction" step 4 of the spec
        describes recording into the alias table, since there's no separate
        moment where a person explicitly confirms it. A future interactive
        capture flow could split this back into two real tiers without
        changing the alias table's shape.
    """
    import difflib

    existing = list_all_label_names(conn)
    lower_map = {n.lower(): n for n in existing}
    if name.lower() in lower_map:
        return lower_map[name.lower()]

    alias_row = conn.execute(
        "SELECT canonical_name FROM label_aliases WHERE alias = ?", (name.lower(),)
    ).fetchone()
    if alias_row:
        return alias_row["canonical_name"]

    if existing:
        matches = difflib.get_close_matches(name.lower(), list(lower_map.keys()), n=1, cutoff=0.8)
        if matches:
            canonical = lower_map[matches[0]]
            conn.execute(
                "INSERT OR REPLACE INTO label_aliases (alias, canonical_name, created_at) VALUES (?, ?, ?)",
                (name.lower(), canonical, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return canonical

    return name


def list_labels_for_object(conn: sqlite3.Connection, object_type: str, object_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT label_name FROM object_labels WHERE object_type = ? AND object_id = ? ORDER BY label_name COLLATE NOCASE",
        (object_type, object_id),
    ).fetchall()
    return [r["label_name"] for r in rows]


def list_object_ids_for_label(conn: sqlite3.Connection, object_type: str, label_name: str) -> list[str]:
    rows = conn.execute(
        "SELECT object_id FROM object_labels WHERE object_type = ? AND label_name = ?",
        (object_type, label_name),
    ).fetchall()
    return [r["object_id"] for r in rows]


def list_all_label_names(conn: sqlite3.Connection) -> list[str]:
    """Every distinct label name currently in use, across every object
    type -- powers a flat "manage labels" list without needing every
    label to also have a label_config row (see that table's own comment)."""
    rows = conn.execute("SELECT DISTINCT label_name FROM object_labels ORDER BY label_name COLLATE NOCASE").fetchall()
    return [r["label_name"] for r in rows]


def list_all_known_label_names(conn: sqlite3.Connection) -> list[str]:
    """Every label name known to the system -- the union of labels in use
        (object_labels) and labels with config (label_config). Used for the
        label picker dropdowns so a label created in the manage page appears
        immediately even before it's applied to anything.
    """
    from .tasks import get_task_habit_settings
    names = set(list_all_label_names(conn))
    names |= {r["name"] for r in conn.execute("SELECT name FROM label_config").fetchall()}
    habit_label = get_task_habit_settings(conn)["habit_label"]
    system_names = {"birthday", (habit_label or "").strip().lower()}
    names = {n for n in names if n.lower() not in system_names}
    return sorted(names, key=str.lower)


def list_tag_names_in_use(conn: sqlite3.Connection) -> list[str]:
    """Phase 2 (label-space rework): the old tag registry is gone --
    labels are the only vocabulary now. Returns all known label names
    (from both object_labels and label_config) so the chip multiselect
    dropdown includes labels created in the manage page before they're
    applied to any object."""
    return list_all_known_label_names(conn)


_LABEL_CONFIG_DEFAULTS: dict[str, Any] = {
    "color": "blue",
    "icon": None,
    "description": None,
    "parent_name": None,
    "label_group": None,
    "generate_space": 0,
    "dashboard_preset_json": None,
    "abbreviation": None,
    "is_project": 0,
    "start_date": None,
    "end_date": None,
    "archived_at": None,
    "created_at": None,
    "sidebar_pin": 0,
    "widget_pin": 0,
    "has_deadline": 0,
    "deadline_date": None,
    "page_type": "sections",
    "agenda_widget": 1,
    "tasks_widget": 1,
    "contacts_widget": 1,
    "notebook_widget": 1,
    "auto_labels": None,
}

# The labels-as-modules boolean flags -- normalized to 0/1 on write and to
# bool on read, same as generate_space/is_project.
_LABEL_MODULE_FLAGS = (
    "sidebar_pin", "widget_pin", "has_deadline",
    "agenda_widget", "tasks_widget", "contacts_widget", "notebook_widget",
)


def get_label_config(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM label_config WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def effective_label_config(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    """A label's config with every default filled in -- a label with zero
    label_config rows (mentioned only via object_labels) still fully
    works, per the table's own "sparse, optional" contract."""
    return _effective_label_config(get_label_config(conn, name), name)


def effective_label_config_ci(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    """Case-insensitive variant of `effective_label_config` -- labels are
    deduplicated case-insensitively (`set_object_labels`), so a config row
    can legitimately sit under casing that differs from the tag text that
    asks about it; callers doing config lookups off raw label strings (e.g.
    routers/timeline.py resolving a block's color/icon from a task's tag)
    use this instead of the exact-match form."""
    row = conn.execute(
        "SELECT * FROM label_config WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return _effective_label_config(dict(row) if row else None, name)


def _effective_label_config(row: dict[str, Any] | None, name: str) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(row) if row else {"name": name}
    for key, default in _LABEL_CONFIG_DEFAULTS.items():
        cfg.setdefault(key, default)
    cfg["generate_space"] = bool(cfg.get("generate_space"))
    cfg["is_project"] = bool(cfg.get("is_project"))
    for flag in _LABEL_MODULE_FLAGS:
        cfg[flag] = bool(cfg.get(flag))
    cfg["is_archived"] = bool(cfg.get("archived_at"))
    # `uid` mirrors `name` -- a label has no surrogate id (its name IS its
    # identity, see the label_config table comment), but templates that
    # used to render a project/space's `.uid` in a link/form field (e.g.
    # `/labels/{{ label.uid }}`) can keep doing exactly that unchanged.
    cfg["uid"] = cfg["name"]
    return cfg


def upsert_label_config(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """Partial-field upsert -- any field not present in `row` keeps its
    existing value (or the default, for a brand-new label_config row),
    same "only touch what you're told to" convention as every setter in
    this file."""
    from .pages import PAGE_TYPES
    cols = (
        "name", "color", "icon", "description", "parent_name", "label_group",
        "generate_space", "dashboard_preset_json", "abbreviation",
        "is_project", "start_date", "end_date", "archived_at",
        "created_at", *(c for c, _ in _LABEL_MODULE_COLUMNS),
    )
    existing = get_label_config(conn, row["name"]) or {}
    data = dict(row)
    for flag in ("generate_space", "is_project", *_LABEL_MODULE_FLAGS):
        if flag in data:
            data[flag] = 1 if data[flag] else 0
    for key, default in _LABEL_CONFIG_DEFAULTS.items():
        data.setdefault(key, existing.get(key, default))
    _mirror_legacy_module_fields(row, existing, data)
    if "has_dashboard" in row and "page_type" not in row:
        data["page_type"] = "dashboard" if row["has_dashboard"] else "sections"
    if data.get("page_type") not in PAGE_TYPES:
        data["page_type"] = "sections"
    data["label_group"] = ensure_group(conn, data.get("label_group"))
    conn.execute(
        f"INSERT INTO label_config ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(name) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "name"),
        [data.get(c) for c in cols],
    )
    conn.commit()


_LABEL_MODULES_BACKFILLED_KEY = "label_modules_backfilled"


_SPACES_TO_GROUPS_KEY = "label_modules_spaces_to_groups"


def migrate_spaces_to_groups(conn: sqlite3.Connection) -> None:
    """One-time: Spaces stop being
        a kind of label. A Space was always "this group of labels" in practice,
        and the group itself (label_group, set by backfill_label_modules)
        now gets its own page at /groups/<name>. For every generate_space=1
        label:

        parent_name is cleared everywhere, because label_group replaced it.
        Idempotent through its own app_meta marker. Runs after
        backfill_label_modules, so every Space already has label_group set.
    """
    from .pages import _page_banner_key, group_page_key
    if get_app_meta(conn, _SPACES_TO_GROUPS_KEY):
        return
    spaces = conn.execute(
        "SELECT name, label_group FROM label_config WHERE generate_space = 1"
    ).fetchall()
    for sp in spaces:
        name = sp["name"]
        group = (sp["label_group"] or "").strip() or name
        key = group_page_key(group)
        rows = conn.execute(
            "SELECT uid, config_json FROM dashboard_widgets WHERE label_name = ?", (name,)
        ).fetchall()
        has_group_widgets = conn.execute(
            "SELECT 1 FROM dashboard_widgets WHERE label_name = ? LIMIT 1", (key,)
        ).fetchone()
        if rows and not has_group_widgets:
            for r in rows:
                try:
                    cfg = json.loads(r["config_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    cfg = {}
                if cfg.get("label_name") == name:
                    cfg["label_name"] = key
                conn.execute(
                    "UPDATE dashboard_widgets SET label_name = ?, config_json = ? WHERE uid = ?",
                    (key, json.dumps(cfg), r["uid"]),
                )
            set_app_meta(conn, f"dashboard_label_{key}_seeded_v1", "1")
        banner = get_app_meta(conn, _page_banner_key(name))
        if banner and not get_app_meta(conn, _page_banner_key(key)):
            set_app_meta(conn, _page_banner_key(key), banner)
        conn.execute(
            "UPDATE label_config SET generate_space = 0, page_type = 'sections', label_group = ? WHERE name = ?",
            (group, name),
        )
    conn.execute("UPDATE label_config SET parent_name = NULL WHERE parent_name IS NOT NULL")
    set_app_meta(conn, _SPACES_TO_GROUPS_KEY, "1")


def backfill_label_modules(conn: sqlite3.Connection) -> None:
    """One-time: fills the new
        per-label module fields from the Space/Project model they replace, so
        that when later slices switch the UI over, what's visible stays the same:

        - label_group: a Space's children take the Space's name, and the Space
          itself takes its own name. That group was the Space. A label with no
          Space keeps whatever free-text label_group it already had.
        - sidebar_pin: everything the sidebar shows today, which is Spaces,
          the children of real Spaces, and projects.
        - widget_pin: Spaces and projects (the "Spaces & Projects" widget).
        - page_type: Spaces, projects, and any label whose page already has
          its own widgets.
        - has_deadline/deadline_date: a project's end_date.
        - agenda/tasks/contacts_widget: all on, matching the plain label page
          they replace (Agenda + Contacts + Kanban).

        Idempotent through its own app_meta marker.
    """
    from .contacts import _fix_contacts_widget_default
    _fix_contacts_widget_default(conn)
    if get_app_meta(conn, _LABEL_MODULES_BACKFILLED_KEY):
        return
    rows = [dict(r) for r in conn.execute("SELECT * FROM label_config").fetchall()]
    spaces = {r["name"] for r in rows if r.get("generate_space")}
    with_widgets = {
        r["label_name"]
        for r in conn.execute("SELECT DISTINCT label_name FROM dashboard_widgets WHERE label_name IS NOT NULL")
    }
    for r in rows:
        is_space = bool(r.get("generate_space"))
        is_project = bool(r.get("is_project"))
        parent = r.get("parent_name") if r.get("parent_name") in spaces else None
        group = r["name"] if is_space else (parent or r.get("label_group"))
        has_deadline = is_project and bool(r.get("end_date"))
        conn.execute(
            "UPDATE label_config SET label_group = ?, sidebar_pin = ?, widget_pin = ?, "
            "page_type = ?, has_deadline = ?, deadline_date = ? WHERE name = ?",
            (
                group,
                1 if (is_space or is_project or parent) else 0,
                1 if (is_space or is_project) else 0,
                "dashboard" if (is_space or is_project or r["name"] in with_widgets) else "sections",
                1 if has_deadline else 0,
                r.get("end_date") if has_deadline else None,
                r["name"],
            ),
        )
    set_app_meta(conn, _LABEL_MODULES_BACKFILLED_KEY, "1")


def list_labels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every label currently known -- the union of every distinct
    object_labels.label_name and every label_config row (a label can exist
    purely as config with nothing pointing at it yet, or purely as usage
    with no config row at all) -- each with its effective config plus a
    live `usage_count` across every object type. Powers the "manage
    labels" list (routers/labels.py)."""
    names = set(list_all_label_names(conn))
    names |= {r["name"] for r in conn.execute("SELECT name FROM label_config").fetchall()}
    counts: dict[str, int] = {
        r["label_name"]: r["c"]
        for r in conn.execute("SELECT label_name, COUNT(*) c FROM object_labels GROUP BY label_name").fetchall()
    }
    result = []
    for name in sorted(names, key=str.lower):
        cfg = effective_label_config(conn, name)
        cfg["usage_count"] = counts.get(name, 0)
        result.append(cfg)
    return result


GROUP_KEY_PREFIX = "group:"


def list_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every group,
        sorted by name, each with its `icon`/`color` and its member labels'
        effective configs.
    """
    groups: dict[str, dict[str, Any]] = {}
    for r in conn.execute("SELECT * FROM label_groups ORDER BY name COLLATE NOCASE").fetchall():
        groups[r["name"].lower()] = {"name": r["name"], "labels": [], "icon": r["icon"] or None,
                                     "color": r["color"] or "gray", "created_at": r["created_at"]}
    rows = conn.execute(
        "SELECT name, label_group FROM label_config WHERE TRIM(COALESCE(label_group, '')) != '' "
        "ORDER BY name COLLATE NOCASE"
    ).fetchall()
    for r in rows:
        g = groups.get(r["label_group"].strip().lower())
        if g is not None:
            g["labels"].append(effective_label_config(conn, r["name"]))
    return list(groups.values())


def label_filter_items(conn: sqlite3.Connection, label_names: list[str], *, lowercase_values: bool = False) -> list[dict[str, str]]:
    """Options for a label filter dropdown: the groups that have a member
    among `label_names` first (value `group:<name>`), then the labels. Each
    carries a `section` so the dropdown can draw a divider between them."""
    present = {n.lower() for n in label_names}
    items = []
    for g in list_groups(conn):
        if any(lbl["name"].lower() in present for lbl in g["labels"]):
            items.append({"value": f"{GROUP_KEY_PREFIX}{g['name']}".lower() if lowercase_values else f"{GROUP_KEY_PREFIX}{g['name']}",
                          "name": g["name"], "section": "group"})
    items += [{"value": n.lower() if lowercase_values else n, "name": n, "section": "label"} for n in label_names]
    return items


def expand_label_filter(conn: sqlite3.Connection, values) -> set[str]:
    """Lowercase label names a filter selection stands for: a `group:<name>`
    value stands for every label in that group, anything else for itself."""
    out: set[str] = set()
    for v in values:
        v = (v or "").strip()
        if v.lower().startswith(GROUP_KEY_PREFIX):
            g = get_group(conn, v[len(GROUP_KEY_PREFIX):])
            out |= {n.lower() for n in group_member_names(conn, g["name"])} if g else set()
        elif v:
            out.add(v.lower())
    return out


def get_group(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """One group's row (case-insensitive name), or None."""
    r = conn.execute("SELECT * FROM label_groups WHERE name = ?", ((name or "").strip(),)).fetchone()
    return dict(r) if r else None


def ensure_group(conn: sqlite3.Connection, name: str | None) -> str | None:
    """Creates the group if it doesn't exist yet and returns its stored
    spelling (typing a new group name on a label creates it, as before).
    The caller commits."""
    name = (name or "").strip()
    if not name:
        return None
    existing = get_group(conn, name)
    if existing:
        return existing["name"]
    legacy = _legacy_group_style(conn, name)
    conn.execute(
        "INSERT INTO label_groups (name, icon, color, created_at) VALUES (?, ?, ?, ?)",
        (name, legacy.get("icon"), legacy.get("color") or "gray", datetime.now(timezone.utc).isoformat()),
    )
    return name


def backfill_group_rows(conn: sqlite3.Connection) -> None:
    """Every group a label names gets a label_groups row, carrying its old
    app_meta look. Cheap and idempotent (runs on every connect; a restored
    backup's labels get their groups back the same way)."""
    for r in conn.execute(
        "SELECT DISTINCT TRIM(label_group) AS g FROM label_config WHERE TRIM(COALESCE(label_group, '')) != ''"
    ).fetchall():
        ensure_group(conn, r["g"])


def _group_style_key(group: str) -> str:
    return f"group_style:{(group or '').strip()}"


def _legacy_group_style(conn: sqlite3.Connection, group: str) -> dict[str, Any]:
    raw = get_app_meta(conn, _group_style_key(group))
    try:
        return (json.loads(raw) or {}) if raw else {}
    except ValueError:
        return {}


def get_group_style(conn: sqlite3.Connection, group: str) -> dict[str, Any]:
    """A group's own icon + color. `icon` None = the default group glyph; `color` defaults to gray."""
    row = get_group(conn, group) or {}
    return {"icon": row.get("icon") or None, "color": row.get("color") or "gray"}


GROUP_DEFAULT_ICON = "layers"


def set_group_style(conn: sqlite3.Connection, group: str, icon: str | None, color: str | None) -> None:
    ensure_group(conn, group)
    conn.execute("UPDATE label_groups SET icon = ?, color = ? WHERE name = ?", (icon or None, color or "gray", group.strip()))
    conn.commit()


def create_group(conn: sqlite3.Connection, name: str, icon: str | None = None, color: str | None = None) -> str:
    """A new, empty group (Settings > Groups). Raises ValueError if the
    name is blank or taken (case-insensitively)."""
    name = " ".join((name or "").split())[:60]
    if not name:
        raise ValueError("A group needs a name.")
    if get_group(conn, name):
        raise ValueError(f"A group named {name} already exists.")
    ensure_group(conn, name)
    conn.execute("UPDATE label_groups SET icon = ?, color = ? WHERE name = ?", (icon or None, color or "gray", name))
    conn.commit()
    return name


def delete_group(conn: sqlite3.Connection, name: str) -> None:
    """Deletes a group: its labels become ungrouped (they are kept), its
    row goes. Its page storage (dashboard, banner) is left, the same
    "harmless leftover" rule rename_group's merge follows."""
    name = (name or "").strip()
    conn.execute("UPDATE label_config SET label_group = NULL WHERE TRIM(COALESCE(label_group, '')) = ? COLLATE NOCASE", (name,))
    conn.execute("DELETE FROM label_groups WHERE name = ?", (name,))
    conn.commit()


def group_member_names(conn: sqlite3.Connection, group: str) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM label_config WHERE TRIM(COALESCE(label_group, '')) = ? COLLATE NOCASE ORDER BY name COLLATE NOCASE",
        ((group or "").strip(),),
    ).fetchall()
    return [r["name"] for r in rows]


def rename_group(conn: sqlite3.Connection, old: str, new: str) -> str:
    """Renames a group. A group is
        only the text in its labels' label_group, plus per-page storage keyed
        by group_page_key and its look in app_meta -- all three move with it.

        Renaming onto another existing group (case-insensitively) merges: the
        members join that group and keep ITS dashboard and look; the old
        group's own storage is left as is (nothing points at it any more, the
        same "harmless leftover" rule clear_label follows) rather than deleted.
        Returns the group's resulting name (the existing group's own spelling on
        a merge).
    """
    from .pages import _move_page_storage, group_page_key
    old = (old or "").strip()
    new = (new or "").strip()
    if not old or not new or old == new:
        return old
    existing = {g["name"].lower(): g["name"] for g in list_groups(conn) if g["name"] != old}
    target = existing.get(new.lower())
    conn.execute(
        "UPDATE label_config SET label_group = ? WHERE TRIM(COALESCE(label_group, '')) = ? COLLATE NOCASE",
        (target or new, old),
    )
    if target is None:
        _move_page_storage(conn, group_page_key(old), group_page_key(new))
        conn.execute("UPDATE label_groups SET name = ? WHERE name = ?", (new, old))
    else:
        conn.execute("DELETE FROM label_groups WHERE name = ?", (old,))
    conn.commit()
    return target or new


def set_group_members(conn: sqlite3.Connection, group: str, members: list[str]) -> None:
    """Makes exactly `members` the group's labels: each named
        label gets label_group = group (moving it out of any other group -- a
        label is in at most one), and a current member not in the list leaves
        the group. Names without a label_config row get one, the same way
        archiving a usage-only label does.
    """
    group = (group or "").strip()
    wanted = [m.strip() for m in members if m and m.strip()]
    ensure_group(conn, group)
    for name in group_member_names(conn, group):
        if name not in wanted:
            conn.execute("UPDATE label_config SET label_group = NULL WHERE name = ?", (name,))
    for name in wanted:
        if not get_label_config(conn, name):
            upsert_label_config(conn, {"name": name, "created_at": datetime.now(timezone.utc).isoformat()})
        conn.execute("UPDATE label_config SET label_group = ? WHERE name = ?", (group, name))
    conn.commit()


def list_project_labels(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every label with is_project=1 -- the Projects page's own listing
    (routers/projects.py). Independent of generate_space: a project can
    also be a Space (or not), the two toggles are orthogonal (§ Project-
    enabled label stack: "the label stays usable across the rest of the
    application")."""
    rows = conn.execute(
        "SELECT * FROM label_config WHERE is_project = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [effective_label_config(conn, r["name"]) for r in rows]


def project_status(conn: sqlite3.Connection, cfg: dict[str, Any], today: date | None = None) -> str:
    """Computed lifecycle state -- Open / Pending / Pending Archiving /
        Archived (§ Project lifecycle). Only `archived_at` is stored (the
        user's explicit confirmation); the other three states are derived at
        read time from task completion + end_date, same "computed, not
        stored" treatment as Importance/Urgency, because both inputs change
        underneath the label without the label itself being edited.

        - Archived: `archived_at` is set (explicit user confirmation only --
          neither the end date passing nor every task completing gets here by
          itself).
        - Open: at least one incomplete task, or no tasks at all (a project
          with no work yet hasn't reached a completion point to leave Open
          from).
        - Pending: every task is completed (and there's at least one), but
          today is still before the deadline -- completed early.
        - Pending Archiving: every task is completed and today is on/after
          the deadline (or there's no deadline) -- ready for the user to
          confirm closure.

        labels-as-modules slice b: reads the generic
        `deadline_date` (when `has_deadline` is on) instead of a project's
        `end_date`, so this works for any label with a deadline, not only
        is_project ones.
    """
    from .tasks import list_tasks
    if cfg.get("archived_at"):
        return "Archived"
    tasks = [t for t in list_tasks(conn) if cfg["name"] in (t.get("tags") or [])]
    # ("done", "archived") mirrors routers/tasks.py's DONE_STATUSES --
    # duplicated here rather than imported to avoid a routers -> db ->
    # routers import cycle (db.py has no dependency on routers/*).
    if not tasks or any(t.get("status") not in ("done", "archived") for t in tasks):
        return "Open"
    deadline = cfg.get("deadline_date") if cfg.get("has_deadline") else None
    if today is None:
        today = date.today()
    if deadline and today < date.fromisoformat(deadline):
        return "Pending"
    return "Pending Archiving"


def archive_project(conn: sqlite3.Connection, name: str) -> None:
    """The explicit user confirmation that closes a project (Pending
    Archiving -> Archived). Never automatic -- see project_status."""
    conn.execute(
        "UPDATE label_config SET archived_at = ? WHERE name = ?",
        (datetime.now(timezone.utc).isoformat(), name),
    )
    conn.commit()


def unarchive_label(conn: sqlite3.Connection, name: str) -> None:
    """Undoes archive_project -- the label goes back to its computed
    Open/Pending/Pending Archiving status."""
    conn.execute("UPDATE label_config SET archived_at = NULL WHERE name = ?", (name,))
    conn.commit()


def label_selector_scope(conn: sqlite3.Connection, key: str) -> list[str] | None:
    """The label names a Labels picker should offer while the user is on
        one page. Since slice c that group is the text label_group:
        a group's page offers its members, and a label's page offers the
        members of its group. None means unscoped: Home, or a label with no
        group.
    """
    from .pages import group_from_page_key
    group = group_from_page_key(key)
    if group is None:
        group = (effective_label_config(conn, key).get("label_group") or "").strip() or None
    if not group:
        return None
    return group_member_names(conn, group)


def rename_label(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    """Renames a label everywhere in one transaction: every object_labels
    row that named it, the label_config row itself, and any child label's
    parent_name. A rename that collides (case-insensitively, but not
    identical) with a different existing label merges into it instead
    (mirrors the old tag-rename behavior) rather than raising a
    unique-constraint error a plain form can't act on -- see merge_labels
    below for the actual merge semantics."""
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name or old_name == new_name:
        return
    if old_name.lower() == new_name.lower():
        # Case-only rename -- same logical label, just a different display
        # casing -- rewrite everywhere but never treat it as a merge.
        conn.execute("UPDATE object_labels SET label_name = ? WHERE label_name = ?", (new_name, old_name))
        conn.execute("UPDATE label_config SET name = ? WHERE name = ?", (new_name, old_name))
        conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (new_name, old_name))
        _rename_in_auto_labels(conn, old_name, new_name)
        conn.commit()
        return
    collision = new_name.lower() in {n.lower() for n in list_all_label_names(conn)} or bool(get_label_config(conn, new_name))
    if collision:
        merge_labels(conn, old_name, new_name)
        return
    conn.execute("UPDATE object_labels SET label_name = ? WHERE label_name = ?", (new_name, old_name))
    conn.execute("UPDATE label_config SET name = ? WHERE name = ?", (new_name, old_name))
    conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (new_name, old_name))
    _rename_in_auto_labels(conn, old_name, new_name)
    conn.commit()


def _rename_in_auto_labels(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    for row in conn.execute("SELECT name, auto_labels FROM label_config WHERE auto_labels IS NOT NULL").fetchall():
        names = get_auto_labels(conn, row["name"])
        if old_name in names:
            conn.execute(
                "UPDATE label_config SET auto_labels = ? WHERE name = ?",
                (json.dumps([new_name if n == old_name else n for n in names]), row["name"]),
            )


def merge_labels(conn: sqlite3.Connection, source_name: str, dest_name: str) -> None:
    """Unions `source_name`'s object_labels membership onto `dest_name`
    (deduplicated -- an object carrying both already is untouched),
    repoints any child label (parent_name == source_name) onto dest, and
    removes source's own label_config row if it had one -- `object_labels`
    rows are the only "membership" a label has, so once those are
    repointed the source label has nothing left pointing at it, same
    "deleting" semantics as every other label removal in this app (§0.1)."""
    if source_name == dest_name:
        return
    rows = conn.execute(
        "SELECT object_type, object_id FROM object_labels WHERE label_name = ?", (source_name,)
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            (r["object_type"], r["object_id"], dest_name),
        )
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (source_name,))
    conn.execute("UPDATE label_config SET parent_name = ? WHERE parent_name = ?", (dest_name, source_name))
    conn.execute("DELETE FROM label_config WHERE name = ?", (source_name,))
    conn.commit()
    from .notebook import enforce_one_label_and_project

    enforce_one_label_and_project(conn)


def clear_label(conn: sqlite3.Connection, name: str) -> None:
    """The "remove from everything" action (§0.1) -- strips this label
        from every object currently carrying it. Deliberately does NOT delete
        the label_config row -- a stale config row with nothing pointing at it
        is harmless (per the plan), and there is no delete-a-label endpoint at
        all in this app.
    """
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (name,))
    conn.commit()


def delete_label_config(conn: sqlite3.Connection, name: str) -> None:
    """Calling only `clear_label` (strips membership, leaves the config row
        on purpose -- see its own docstring) therefore left the label sitting
        right back in the table at "Not used" the moment the page reloaded --
        Delete redirected successfully but visibly did nothing, which is
        exactly the reported bug. `merge_labels` already treats "membership
        repointed + config row dropped" as "the same 'deleting' semantics as
        every other label removal in this app" for its own source label; this
        is that same pair of statements with no destination to repoint onto.
    """
    conn.execute("DELETE FROM object_labels WHERE label_name = ?", (name,))
    conn.execute("DELETE FROM label_config WHERE name = ?", (name,))
    conn.commit()


def project_label_for(conn: sqlite3.Connection, object_type: str, object_id: str) -> str | None:
    """The one label treated as "the project" for this object. Deliberately
        a *derived view* over the object's real `object_labels` rows, not a
        separately tracked field -- there is no "this label is special, it's
        THE project" category (see features/architecture.md §0.1/§2: a label
        is a label, full stop).

        1.3 (Project-enabled label stack) supersedes the old heuristic here:
        a label explicitly marked is_project=1 now wins outright, since a
        label can finally say "I'm the project" instead of it being inferred.
        Falls back to the pre-1.3 heuristic (the attached label whose config
        has generate_space=0 -- a course/list label, not a Space) only when
        nothing attached is explicitly project-enabled, so data written before
        1.3 (nothing has is_project=1 yet) keeps behaving exactly as before
        until the user actually promotes a label to a project.
    """
    names = sorted(list_labels_for_object(conn, object_type, object_id), key=str.lower)
    configs = {name: get_label_config(conn, name) for name in names}
    for name in names:
        cfg = configs.get(name)
        if cfg and cfg.get("is_project"):
            return name
    for name in names:
        cfg = configs.get(name)
        if not (cfg and cfg.get("generate_space")):
            return name
    return None


def project_label_config_for(
    conn: sqlite3.Connection, object_type: str, object_id: str
) -> dict[str, Any] | None:
    """The project label's *effective config* (every default filled in, so
        `name`/`icon`/`color` are all present) for an object, or None if it has
        no project label. Thin wrapper over `project_label_for` +
        `effective_label_config` so a planning grid's "Unscheduled work" panel
        can render the project pill without
        re-deriving the lookup at each of its three call sites. The returned
        dict is the label's config, not a name string -- callers that only
        needed the name (the older panel items) can read `["name"]` off it.
    """
    name = project_label_for(conn, object_type, object_id)
    if name is None:
        return None
    return effective_label_config(conn, name)


def set_object_project_label_uniform(conn: sqlite3.Connection, object_type: str, object_id: str, label_name: str | None) -> None:
    """Write path for project_label_for: replace whichever non-Space label
    this object currently carries with `label_name` (or just remove it, if
    None/""), leaving any Space labels (generate_space=1) already on the
    object untouched -- same rule set_schedule_class_project has always
    used, now shared by habit/database too instead of each having its own
    variant."""
    current = project_label_for(conn, object_type, object_id)
    if current:
        remove_object_label(conn, object_type, object_id, current)
    if label_name:
        add_object_label(conn, object_type, object_id, label_name)


def label_is_carried(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM object_labels WHERE label_name = ? LIMIT 1", (name,)).fetchone() is not None


def label_usage_count(conn: sqlite3.Connection, name: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM object_labels WHERE label_name = ?", (name,)).fetchone()[0]


def label_group_by_name(conn: sqlite3.Connection) -> dict[str, str]:
    """Every configured label name with its group ('' when ungrouped)."""
    return {r["name"]: (r["label_group"] or "").strip() for r in conn.execute("SELECT name, label_group FROM label_config")}
