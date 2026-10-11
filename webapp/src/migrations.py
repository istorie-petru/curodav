"""Numbered, idempotent schema migrations (rules/backend-conventions.md, rule 3).

Each migration runs once, in order, on startup, and is safe to run twice. A migration that drops or reshapes data
is marked destructive: the database file is copied next to itself first. Released migrations are never edited;
a change is a new migration. Steps older than this runner still live in `db.init_schema`.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    apply: Callable[[sqlite3.Connection], None]
    destructive: bool = False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _note_templates(conn: sqlite3.Connection) -> None:
    if "is_template" not in _columns(conn, "notebook_documents"):
        conn.execute("ALTER TABLE notebook_documents ADD COLUMN is_template INTEGER NOT NULL DEFAULT 0")


def _field_config_without_required(conn: sqlite3.Connection) -> None:
    if "required" in _columns(conn, "notebook_field_config"):
        conn.execute("ALTER TABLE notebook_field_config DROP COLUMN required")


def _finance_tables(conn: sqlite3.Connection) -> None:
    from . import finance

    finance.ensure_schema(conn)


MIGRATIONS: list[Migration] = [
    Migration(1, "notebook documents get an is_template flag", _note_templates),
    Migration(2, "frontmatter fields lose the required column", _field_config_without_required, destructive=True),
    Migration(3, "finance accounts, transactions and tags", _finance_tables),
    Migration(4, "finance scheduled transactions", _finance_tables),
    Migration(5, "finance scheduled transaction tags", _finance_tables),
]


def _database_file(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]) if row and row[2] else None


def _backup(conn: sqlite3.Connection, number: int) -> None:
    source = _database_file(conn)
    if source is None or not source.exists():
        return
    conn.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(source, source.with_name(f"{source.name}.before-migration-{number:04d}-{stamp}"))


def pending(conn: sqlite3.Connection) -> list[Migration]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = {row[0] for row in conn.execute("SELECT number FROM schema_migrations")}
    return [m for m in MIGRATIONS if m.number not in done]


def run(conn: sqlite3.Connection) -> list[int]:
    """Applies every pending migration in order and returns the numbers applied."""
    applied = []
    for migration in pending(conn):
        if migration.destructive and _has_data(conn):
            _backup(conn, migration.number)
        migration.apply(conn)
        conn.execute("INSERT INTO schema_migrations (number, name, applied_at) VALUES (?, ?, ?)",
                     (migration.number, migration.name, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        applied.append(migration.number)
    return applied


def _has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'notebook_field_config'").fetchone() is not None
