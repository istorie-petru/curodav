#!/usr/bin/env python3
"""Spaces -- labels-as-membership rework, slice 6 (final slice, 2026-09-14):
strips legacy direct Space-label tagging left over from before slice 3.

Before slice 3, a Space's own generated page (`routers/spaces.py::
_label_scope`) aggregated tasks/events/contacts (and habits, via their
`project_uid` -> `object_labels` folding, see db.py's
`_apply_tags_and_project`) that were DIRECTLY tagged with the Space's own
label name -- e.g. an item tagged "University" itself, not one of
University's child labels like "Historiography". Slice 3 changed that
page to aggregate via child-label membership only; a direct tag on a
Space's own name is now "unread but not gone" (plans/open.md's own
framing) -- dead-but-visible data: the label pill would still show
elsewhere in the UI (a task's label chips, the tag picker) even though
the item no longer appears on the Space's own page at all.

This script finds every such row -- for every `generate_space=1` label,
every `object_labels` row whose `label_name` is that Space's own name --
and removes it, via `db.clear_label` (the same "remove from everything"
primitive Settings > Labels' own per-row/bulk Delete/Clear buttons use),
scoped to one Space's own name per call rather than the whole label's
removal (clear_label already only ever deletes by exact `label_name`, so
a Space's own name and any of its child labels' names are never at risk
of collision here -- they're always different strings).

Deliberately does NOT touch `label_config.label_group`'s now-unused
legacy text values (slice 1 stopped writing them, slice 2's Settings >
Labels no longer reads them) -- per open.md's own slice 6 description,
leaving them alone is the cheapest safe option; nothing in the UI reads
that column after slice 2, so a stale value there is harmless the same
way a label_config row with nothing pointing at it already is (§0.1).

Idempotent: a Space with no direct-tag rows left (including a second run
right after the first) reports 0 removed and touches nothing. `--dry-run`
counts without writing (db.clear_label is simply never called).

Usage:
    python scripts/migrate_spaces_direct_tags.py [--db-path PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent / "src"))
sys.path.insert(0, str(_THIS_DIR.parent))

from src import db  # noqa: E402


def run_migration(conn, dry_run: bool = False) -> dict:
    """Returns `{"per_space_removed": {space_name: count, ...}, "total_removed": N}`
    -- only Spaces with at least one direct-tag row appear in
    `per_space_removed` (a clean/already-migrated Space contributes
    nothing to either, so a fully-migrated database's re-run reports an
    empty dict / 0, not a zero-entry per Space)."""
    per_space_removed: dict[str, int] = {}
    total_removed = 0
    for space in db.list_space_labels(conn):
        name = space["name"]
        (removed,) = conn.execute(
            "SELECT COUNT(*) FROM object_labels WHERE label_name = ?", (name,)
        ).fetchone()
        if not removed:
            continue
        per_space_removed[name] = removed
        total_removed += removed
        if not dry_run:
            db.clear_label(conn, name)
    return {"per_space_removed": per_space_removed, "total_removed": total_removed}


def _print_summary(result: dict, dry_run: bool) -> None:
    verb = "Would remove" if dry_run else "Removed"
    if not result["per_space_removed"]:
        print("No legacy direct Space-label tags found -- nothing to do.")
        return
    print(f"{'[dry run] ' if dry_run else ''}Migration summary:")
    for name, count in sorted(result["per_space_removed"].items()):
        print(f"  {verb} {count} direct tag(s) of Space {name!r}")
    print(f"  {verb} {result['total_removed']} row(s) total across {len(result['per_space_removed'])} Space(s)")


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
