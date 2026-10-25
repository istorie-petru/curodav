#!/usr/bin/env python3
"""Dry run of migration 26 (task and event links get a kind): reports how many links exist and which kind each takes,
on a read-only copy of the database. Changes nothing.

Usage: python scripts/links_dry_run.py [--db-path PATH]   (defaults to the app's configured database)
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    args = parser.parse_args()
    from src.config import load_settings

    source = args.db_path or load_settings().db_path
    if not Path(source).exists():
        print(f"No database at {source}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.sqlite"
        shutil.copy2(source, copy)
        conn = sqlite3.connect(copy)
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'event_task_relations'").fetchone():
            print("No links table yet: nothing to migrate.")
            return 0
        from src.db.tasks import plan_link_kinds

        columns = {r[1] for r in conn.execute("PRAGMA table_info(event_task_relations)")}
        if "kind" not in columns:
            conn.execute("ALTER TABLE event_task_relations ADD COLUMN kind TEXT")
        plan = plan_link_kinds(conn)
    print(f"Links: {plan['links']}. Work sessions: {plan['work_session']}. Related: {plan['related']}. "
          f"Exam: {plan['exam']}. Already named: {plan['already_set']}.")
    print("The migration copies the database next to itself first and changes only the new kind column; hours, difficulty and titles are untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
