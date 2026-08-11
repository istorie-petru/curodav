#!/usr/bin/env python3
"""Phase 1 (label-space rework) migration: backfill `object_labels` from
everything that used to express organization before this phase --
tags_json, and (for a database file that still physically carries them,
see db.py's Phase 1 comments) the old `calendars`/`task_lists`/
`addressbooks` collection registries and `project_groups`/`projects`.

See features/architecture.md §3 Phase 1 ("Migration script") and §6
("Still open" / the UID-collision sanity check) for the full spec this
implements.

What this does, in order:

  1. Sanity check (§6): before treating "which collection an object used
     to be in" as safe-to-collapse information, verify no uid is shared
     across more than one of the three object-type pools (tasks/events/
     contacts). SQLite's own PRIMARY KEY already makes a same-type
     collision (e.g. two events both named "e1") structurally impossible
     -- the one collision shape this schema *can* actually represent is
     the same uid string being used for objects of two different types
     (e.g. a task "x" and an event "x"), which would previously have
     been kept apart by living in genuinely different CalDAV/CardDAV
     resource types/collections. Since `object_labels` keys off
     (object_type, object_id, label_name) this isn't strictly unsafe --
     object_type keeps them apart -- but it's exactly the kind of latent
     data-quality landmine §6 asks to be caught and surfaced before this
     migration runs, not silently ignored. Found: abort (nonzero exit),
     print every colliding uid and which object types it spans.
  2. Tags -> labels: every distinct tag name in tasks/events/contacts'
     tags_json becomes a label; each row that carried it gets an
     object_labels row.
  3. Old collections (`calendars`/`task_lists`/`addressbooks`, read
     directly via raw SQL -- these tables/columns are no longer part of
     db.py's own schema for a *new* database, but a database file that
     predates Phase 1 still physically has them, see db.py's Phase 1
     comments) -> one label per collection *name*, deduped case-
     insensitively across all three collection types (a calendar and a
     task list that happened to share a name become one label, not two).
     Every object whose legacy calendar_path/list_path/addressbook_path
     pointed at that collection gets tagged with the label.
  4. `project_groups`/`projects` -> one label per name (same cross-table
     dedupe as step 3), applied to every object reachable through the
     project's linked collections (a task list/calendar/addressbook whose
     project_uid pointed at it) -- and, for a project's own group, the
     group's label is applied to the same objects via the project.
     `schedule_classes` is not migrated to a label here (it isn't an
     object_labels object_type; Phase 4 addresses Schedule).
  5. `label_config` rows carry the old color forward for every label
     created in steps 3-4 (collections/projects/groups had colors; tags
     did not, so no label_config row is created for a tag-only label --
     it just gets db.py's own default color when first configured).

Idempotent: every write is an INSERT OR IGNORE (object_labels) or an
upsert that only fills in a color if one isn't already set (label_config)
-- safe to re-run. `--dry-run` computes and prints the same counts
without writing anything (runs inside a transaction that's rolled back).

Usage:
    python scripts/migrate_labels.py [--db-path PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent / "src"))
sys.path.insert(0, str(_THIS_DIR.parent))

from src import db  # noqa: E402


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# --------------------------------------------------------------------- #
# Step 1: UID-collision sanity check (§6)
# --------------------------------------------------------------------- #


def find_cross_type_uid_collisions(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """uid -> sorted list of object_types (>=2 entries) that both claim
    it. Pure/side-effect-free so it's directly unit-testable without a
    populated object_labels table."""
    owners: dict[str, set[str]] = defaultdict(set)
    for object_type, table in (("task", "tasks"), ("event", "events"), ("contact", "contacts")):
        if not _table_exists(conn, table):
            continue
        for row in conn.execute(f"SELECT uid FROM {table}"):
            owners[row[0]].add(object_type)
    return {uid: sorted(types) for uid, types in owners.items() if len(types) > 1}


# --------------------------------------------------------------------- #
# Step 2: tags_json -> labels
# --------------------------------------------------------------------- #


def _migrate_tags(conn: sqlite3.Connection, counts: dict, dry_run: bool) -> None:
    for object_type, table in (("task", "tasks"), ("event", "events"), ("contact", "contacts")):
        if not _table_exists(conn, table) or "tags_json" not in _columns(conn, table):
            # A current-schema db.py table has no `tags_json` column at
            # all (Phase 2 dropped it -- every task/event/contact upsert
            # already writes straight to object_labels, see db.py's
            # upsert_task/upsert_event/upsert_contact) -- nothing to
            # backfill from here except a genuinely pre-Phase-2 database
            # that still physically carries the column.
            continue
        for uid, tags_json in conn.execute(f"SELECT uid, tags_json FROM {table}"):
            try:
                tags = json.loads(tags_json or "[]")
            except (TypeError, ValueError):
                tags = []
            for tag in tags or []:
                tag = str(tag).strip()
                if not tag:
                    continue
                counts["labels_seen"].add(tag)
                counts[f"object_labels_from_tags_{table}"] += 1
                if not dry_run:
                    db.add_object_label(conn, object_type, uid, tag)


# --------------------------------------------------------------------- #
# Step 3: old calendars/task_lists/addressbooks -> labels
# --------------------------------------------------------------------- #

# (collection table, its color/name columns, the object table it owned,
# the object type, and the legacy FK column on that object table)
_COLLECTION_SOURCES = [
    ("calendars", "events", "event", "calendar_path"),
    ("task_lists", "tasks", "task", "list_path"),
    ("addressbooks", "contacts", "contact", "addressbook_path"),
]


def _migrate_collections(conn: sqlite3.Connection, counts: dict, dry_run: bool) -> dict[str, str]:
    """Returns collection_uid -> resolved label name (case-insensitively
    deduped across all three collection types), for step 4 to reuse when
    resolving a project's linked collections."""
    label_by_collection_uid: dict[str, str] = {}
    seen_lower: dict[str, str] = {}  # lowercased name -> canonical label name

    for coll_table, obj_table, object_type, fk_col in _COLLECTION_SOURCES:
        if not _table_exists(conn, coll_table) or not _table_exists(conn, obj_table):
            continue
        obj_cols = _columns(conn, obj_table)
        if fk_col not in obj_cols:
            # This object table has already been fully migrated off the
            # legacy column (e.g. re-run after a manual ALTER) -- nothing
            # left to backfill from for this source.
            continue
        for row in conn.execute(f"SELECT uid, name, color FROM {coll_table}"):
            coll_uid, name, color = row[0], row[1], row[2]
            name = (name or coll_uid).strip()
            key = name.lower()
            label_name = seen_lower.setdefault(key, name)
            label_by_collection_uid[coll_uid] = label_name
            counts["labels_seen"].add(label_name)
            counts["collections_migrated"] += 1
            if not dry_run:
                _ensure_label_color(conn, label_name, color)

            members = conn.execute(
                f"SELECT uid FROM {obj_table} WHERE {fk_col} = ?", (coll_uid,)
            ).fetchall()
            for (obj_uid,) in members:
                counts[f"object_labels_from_collections_{obj_table}"] += 1
                if not dry_run:
                    db.add_object_label(conn, object_type, obj_uid, label_name)

    return label_by_collection_uid


def _ensure_label_color(conn: sqlite3.Connection, label_name: str, color: str | None) -> None:
    """Only sets the color if this label has no label_config row yet --
    a label discovered again via a second, differently-colored source
    (e.g. also matches a project name) keeps whichever color it was
    first given, rather than flip-flopping on migration order."""
    if not color:
        return
    existing = db.get_label_config(conn, label_name)
    if existing is not None:
        return
    db.upsert_label_config(conn, {"name": label_name, "color": color})


# --------------------------------------------------------------------- #
# Step 4: project_groups/projects -> labels
# --------------------------------------------------------------------- #


def _mark_generate_space(conn: sqlite3.Connection, label_name: str) -> None:
    """Every label migrated from a `project_groups` row (a former Space)
    gets `generate_space=1` -- see features/architecture.md §3 Phase 2
    item 1. Doesn't touch color/icon/etc. -- upsert_label_config only
    updates the fields it's given, and only fills in defaults for the
    rest if the label has no row yet."""
    db.upsert_label_config(conn, {"name": label_name, "generate_space": 1})


def _migrate_projects(
    conn: sqlite3.Connection,
    counts: dict,
    dry_run: bool,
    label_by_collection_uid: dict[str, str],
) -> dict[str, str]:
    """Returns project_uid -> resolved label name (including projects that
    have no group), for step 5 (habits/schedule_classes/databases,
    Phase 2) to reuse -- those three tables link to a project directly via
    their own `project_uid`, not through a task_list/calendar/addressbook."""
    if not _table_exists(conn, "projects"):
        return {}

    seen_lower: dict[str, str] = {}
    # Labels from step 3 already occupy part of the shared name space --
    # dedupe against those too, not just against each other, so e.g. a
    # project named the same as an old calendar collapses onto that one
    # label instead of minting a near-duplicate.
    for name in label_by_collection_uid.values():
        seen_lower.setdefault(name.lower(), name)

    group_label: dict[str, str] = {}
    if _table_exists(conn, "project_groups"):
        for uid, name, color in conn.execute("SELECT uid, name, color FROM project_groups"):
            name = (name or uid).strip()
            label_name = seen_lower.setdefault(name.lower(), name)
            group_label[uid] = label_name
            counts["labels_seen"].add(label_name)
            counts["groups_migrated"] += 1
            if not dry_run:
                _ensure_label_color(conn, label_name, color)
                _mark_generate_space(conn, label_name)

    project_cols = _columns(conn, "projects")
    has_group_uid = "group_uid" in project_cols
    label_by_project_uid: dict[str, str] = {}
    for row in conn.execute("SELECT uid, name, color, " + ("group_uid" if has_group_uid else "uid") + " FROM projects"):
        proj_uid, name, color, group_uid = row[0], row[1], row[2], (row[3] if has_group_uid else None)
        name = (name or proj_uid).strip()
        label_name = seen_lower.setdefault(name.lower(), name)
        label_by_project_uid[proj_uid] = label_name
        counts["labels_seen"].add(label_name)
        counts["projects_migrated"] += 1
        if not dry_run:
            _ensure_label_color(conn, label_name, color)

        # Every object in a collection linked to this project gets both
        # the project's own label and (if the project belongs to a
        # group/space) that group's label -- direct assignment only, no
        # transitive "generate_space" behavior (that's Phase 3).
        applicable_labels = [label_name]
        if group_uid and group_uid in group_label:
            applicable_labels.append(group_label[group_uid])

        for coll_table, obj_table, object_type, _fk_col in _COLLECTION_SOURCES:
            if not _table_exists(conn, coll_table):
                continue
            coll_cols = _columns(conn, coll_table)
            if "project_uid" not in coll_cols:
                continue
            linked = conn.execute(
                f"SELECT uid FROM {coll_table} WHERE project_uid = ?", (proj_uid,)
            ).fetchall()
            for (coll_uid,) in linked:
                if not _table_exists(conn, obj_table):
                    continue
                fk_col = {"calendars": "calendar_path", "task_lists": "list_path", "addressbooks": "addressbook_path"}[coll_table]
                if fk_col not in _columns(conn, obj_table):
                    continue
                members = conn.execute(
                    f"SELECT uid FROM {obj_table} WHERE {fk_col} = ?", (coll_uid,)
                ).fetchall()
                for (obj_uid,) in members:
                    for lbl in applicable_labels:
                        counts[f"object_labels_from_projects_{obj_table}"] += 1
                        if not dry_run:
                            db.add_object_label(conn, object_type, obj_uid, lbl)

    return label_by_project_uid


# --------------------------------------------------------------------- #
# Step 5 (Phase 2): habits/schedule_classes/databases -> object_labels,
# via their own `project_uid` FK column (unlike task_lists/calendars/
# addressbooks, these three tables link to a project directly, not
# through a separate collection table).
# --------------------------------------------------------------------- #

_PROJECT_LINKED_SOURCES = [
    ("habits", "habit"),
    ("schedule_classes", "schedule_class"),
    ("databases", "database"),
]


def _migrate_project_linked_objects(
    conn: sqlite3.Connection,
    counts: dict,
    dry_run: bool,
    label_by_project_uid: dict[str, str],
) -> None:
    if not label_by_project_uid:
        return
    for table, object_type in _PROJECT_LINKED_SOURCES:
        if not _table_exists(conn, table):
            continue
        cols = _columns(conn, table)
        if "project_uid" not in cols:
            # Already migrated off the legacy column (e.g. a re-run after
            # this app's own upsert_habit/upsert_database/
            # set_schedule_class_project started writing object_labels
            # directly instead) -- nothing left to backfill from here.
            continue
        for uid, project_uid in conn.execute(f"SELECT uid, project_uid FROM {table} WHERE project_uid IS NOT NULL"):
            label_name = label_by_project_uid.get(project_uid)
            if not label_name:
                continue
            counts[f"object_labels_from_project_link_{table}"] += 1
            if not dry_run:
                # A project link is just a real tag now, uniformly across
                # schedule_class/habit/database (corrected 2026-08-06 --
                # habits/databases previously got a separate pseudo
                # object_type here; that made their project invisible to
                # any label page's aggregation, see db.py's
                # project_label_for docstring). The course/project label's
                # generated page discovers the object via direct
                # object_labels membership, same as any other tag.
                db.add_object_label(conn, object_type, uid, label_name)


# --------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------- #


def run_migration(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Runs every step against an already-open connection. Every actual
    write goes through db.py's own helpers (add_object_label,
    upsert_label_config), which each commit their own row -- on
    `dry_run=True` those calls are simply never made (every step below is
    guarded), so there is nothing to roll back; the counters still
    reflect exactly what *would* have been written. Returns the counts
    dict, or `{"collisions": {...}}` if the §6 sanity check aborted."""
    collisions = find_cross_type_uid_collisions(conn)
    if collisions:
        return {"collisions": collisions}

    counts: dict = defaultdict(int)
    counts["labels_seen"] = set()

    _migrate_tags(conn, counts, dry_run)
    label_by_collection_uid = _migrate_collections(conn, counts, dry_run)
    label_by_project_uid = _migrate_projects(conn, counts, dry_run, label_by_collection_uid)
    _migrate_project_linked_objects(conn, counts, dry_run, label_by_project_uid)

    counts["labels_created"] = len(counts.pop("labels_seen"))
    return dict(counts)


def _print_summary(result: dict, dry_run: bool) -> None:
    if "collisions" in result:
        print("ABORTED -- UID collisions found across object types (§6 sanity check):")
        for uid, types in sorted(result["collisions"].items()):
            print(f"  uid={uid!r} claimed by: {', '.join(types)}")
        print(
            "\nResolve these (rename/merge the colliding objects) before "
            "re-running this migration -- refusing to silently merge or "
            "overwrite data."
        )
        return

    label = "Would create" if dry_run else "Created"
    verb = "Would insert" if dry_run else "Inserted"
    print(f"{'[dry run] ' if dry_run else ''}Migration summary:")
    print(f"  {label} {result.get('labels_created', 0)} distinct label(s)")
    for key, value in sorted(result.items()):
        if key in ("labels_created",):
            continue
        print(f"  {verb} {value} object_labels row(s) -- {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to cache.sqlite (defaults to the app's configured db_path, CC_DB_PATH env var, or ~/.command_center_web/cache.sqlite)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report counts without writing anything"
    )
    args = parser.parse_args(argv)

    if args.db_path is not None:
        db_path = args.db_path
    else:
        from src.config import load_settings

        db_path = load_settings().db_path

    if not db_path.exists():
        print(f"No database at {db_path} -- nothing to migrate.")
        return 0

    with db.connect(db_path) as conn:
        result = run_migration(conn, dry_run=args.dry_run)

    _print_summary(result, args.dry_run)
    return 1 if "collisions" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
