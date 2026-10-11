"""Numbered migrations run once, in order, safely twice, and back up the database before dropping data."""

from __future__ import annotations

import sqlite3

import pytest

from src import db, migrations


def _legacy(path):
    """A database as the previous release left it: the Required column present and no template flag."""
    with db.connect(path) as conn:
        conn.execute("ALTER TABLE notebook_field_config ADD COLUMN required INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE notebook_documents DROP COLUMN is_template")
        conn.execute("DROP TABLE schema_migrations")
        conn.commit()


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_a_new_database_records_every_migration(tmp_path):
    with db.connect(tmp_path / "a.sqlite") as conn:
        assert [r[0] for r in conn.execute("SELECT number FROM schema_migrations ORDER BY number")] == [m.number for m in migrations.MIGRATIONS]


def test_migrations_apply_to_a_copy_of_the_previous_schema(tmp_path):
    path = tmp_path / "old.sqlite"
    _legacy(path)
    with db.connect(path) as conn:
        assert "required" not in _columns(conn, "notebook_field_config")
        assert "is_template" in _columns(conn, "notebook_documents")


def test_running_twice_applies_nothing_the_second_time(tmp_path):
    with db.connect(tmp_path / "a.sqlite") as conn:
        assert migrations.run(conn) == []


def test_every_migration_is_safe_to_run_again_by_itself(tmp_path):
    with db.connect(tmp_path / "a.sqlite") as conn:
        for migration in migrations.MIGRATIONS:
            migration.apply(conn)


def test_a_destructive_migration_copies_the_database_first(tmp_path):
    path = tmp_path / "old.sqlite"
    _legacy(path)
    with db.connect(path):
        pass
    backups = list(tmp_path.glob("old.sqlite.before-migration-0002-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as old:
        assert "required" in _columns(old, "notebook_field_config")


def test_numbers_are_unique_and_in_order():
    numbers = [m.number for m in migrations.MIGRATIONS]
    assert numbers == sorted(set(numbers)) and numbers[0] == 1
