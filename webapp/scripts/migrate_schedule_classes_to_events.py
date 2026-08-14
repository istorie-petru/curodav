#!/usr/bin/env python3
"""1.6 (Schedule & recurrence rework) migration: convert every row still
physically sitting in a pre-1.6 database's `schedule_classes` table into a
real recurring `events` row -- see `db.py`'s removal note on that table
and `schedule.py`'s module docstring for the model this migrates *to*. A
brand-new database never has `schedule_classes` at all (dropped from
SCHEMA_SQL); this script is a no-op on one.

What this does, per schedule_classes row:

  1. Resolves the class's course label -- reads its existing
     object_labels rows (object_type='schedule_class', still intact,
     `db.project_label_for` untouched by 1.6) the exact way the pre-1.6
     app already determined "the" project label for a class. A class with
     no label at all gets one auto-provisioned from its own `name`, same
     fallback `routers/schedule.py::create_class` uses today.
  2. Backfills that course label's `label_config` row with the class's
     acronym/class_type/credits/professor_contact_uid -- the four facts
     that used to live on the class row itself and now live on the course
     label instead (see `db.py`'s `label_config` CREATE TABLE comment).
     Only fills in a field that's still unset on the label (first
     migrated meeting for a given course wins, same "don't flip-flop"
     rule `migrate_labels.py::_ensure_label_color` uses) -- if two
     meetings of the same course ever disagreed on credits/acronym/type/
     professor (only possible via direct DB edits; the app itself always
     kept them in lockstep across a course's meetings once 1.6 shipped),
     the first one migrated wins and the rest are silently consistent
     with it from then on.
  3. Builds the real recurring event via `schedule.build_class_event_row`
     off the class's own day/start_time/end_time/parity/name/room/
     enrolled, using this database's current `schedule_settings`/
     `schedule_holidays` (unaffected by 1.6, still the source of semester
     bounds and holiday exclusions). Reuses the class's already-mirrored
     `event_uid` as the new event's uid when one exists (repurposing that
     row rather than leaving it an orphaned duplicate); falls back to the
     class's own `uid` if the class was never successfully mirrored
     before (e.g. semester dates were never configured pre-1.6).
  4. Tags the new event with the per-install Schedule system label
     (`schedule_settings.schedule_label`, default 'Schedule'), the
     resolved course label, and any Space label (`generate_space=1`) the
     class already carried directly.

Idempotent: re-running after a successful migration is a no-op for
already-migrated rows (`db.upsert_event`/`db.upsert_label_config` are both
plain upserts, and course-field backfill only fills genuinely-unset
fields) -- safe to re-run. `--dry-run` computes and prints the same counts
without writing anything.

Leaves `schedule_classes`/its rows physically on disk afterward, same
"never force-drop old data automatically" convention as every other
removal in `db.py` -- nothing in the app reads it anymore once this has
run; delete the table by hand later if you want the disk space back.

Usage:
    python scripts/migrate_schedule_classes_to_events.py [--db-path PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent / "src"))
sys.path.insert(0, str(_THIS_DIR.parent))

from src import db, schedule  # noqa: E402


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_COURSE_FIELDS = {
    "acronym": "course_acronym",
    "class_type": "course_type",
    "credits": "course_credits",
    "professor_contact_uid": "course_professor_contact_uid",
}


def _resolve_course_label(conn: sqlite3.Connection, cls: dict[str, Any], counts: dict, dry_run: bool) -> str:
    existing = db.project_label_for(conn, "schedule_class", cls["uid"])
    if existing:
        return existing
    label_name = (cls.get("name") or cls["uid"]).strip() or cls["uid"]
    counts["course_labels_auto_provisioned"] += 1
    if not dry_run:
        db.upsert_label_config(
            conn,
            {"name": label_name, "color": "blue", "icon": "book-open", "is_project": 1, "created_at": _now()},
        )
    return label_name


def _backfill_course_fields(conn: sqlite3.Connection, label_name: str, cls: dict[str, Any], counts: dict, dry_run: bool) -> None:
    current = db.get_label_config(conn, label_name) or {}
    updates: dict[str, Any] = {}
    for old_key, new_key in _COURSE_FIELDS.items():
        if current.get(new_key):
            continue  # already set by an earlier-migrated meeting of this same course
        value = cls.get(old_key)
        if value:
            updates[new_key] = value
    if not updates:
        return
    counts["course_fields_backfilled"] += len(updates)
    if not dry_run:
        db.upsert_label_config(conn, {"name": label_name, **updates})


def run_migration(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    counts: dict = defaultdict(int)
    if not _table_exists(conn, "schedule_classes"):
        return dict(counts)

    settings = db.get_schedule_settings(conn)
    holidays = db.list_holidays(conn)
    schedule_label = settings.get("schedule_label") or "Schedule"

    rows = conn.execute("SELECT * FROM schedule_classes").fetchall()
    for row in rows:
        cls = dict(row)
        cls["enrolled"] = bool(cls.get("enrolled", 1))
        counts["classes_migrated"] += 1

        label_name = _resolve_course_label(conn, cls, counts, dry_run)
        _backfill_course_fields(conn, label_name, cls, counts, dry_run)

        space_labels = [
            name for name in db.list_labels_for_object(conn, "schedule_class", cls["uid"])
            if name != label_name and (db.get_label_config(conn, name) or {}).get("generate_space")
        ]

        event_uid = cls.get("event_uid") or cls["uid"] or str(uuid.uuid4())
        if not dry_run:
            event_row = schedule.build_class_event_row(
                {
                    "uid": event_uid,
                    "day": cls["day"],
                    "start_time": cls["start_time"],
                    "end_time": cls["end_time"],
                    "title": cls.get("name") or "Class",
                    "room": cls.get("room"),
                    "parity": cls.get("parity") or "all",
                    "enrolled": cls["enrolled"],
                },
                settings,
                holidays,
            )
            db.upsert_event(conn, event_row)
            db.set_object_labels(conn, "event", event_uid, [schedule_label, label_name, *space_labels])
        counts["events_created"] += 1

    return dict(counts)


def _print_summary(result: dict, dry_run: bool) -> None:
    if not result:
        print("No schedule_classes table found -- nothing to migrate.")
        return
    verb = "Would migrate" if dry_run else "Migrated"
    print(f"{'[dry run] ' if dry_run else ''}Migration summary:")
    for key in sorted(result):
        print(f"  {verb} {result[key]} -- {key}")


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
