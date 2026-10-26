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


def test_a_database_migrated_by_a_newer_release_is_refused_untouched(tmp_path):
    path = tmp_path / "new.sqlite"
    with db.connect(path) as conn:
        conn.execute("INSERT INTO schema_migrations (number, name, applied_at) VALUES (999, 'from the future', 'x')")
        conn.commit()
    with pytest.raises(migrations.MigrationError, match="newer release"):
        with db.connect(path):
            pass
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE number = 999").fetchone()[0] == 1


def test_a_failing_migration_rolls_back_is_not_recorded_and_names_the_backup(tmp_path, monkeypatch):
    path = tmp_path / "a.sqlite"
    with db.connect(path) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE number = 35")
        conn.commit()

    def boom(conn):
        conn.execute("CREATE TABLE half_done (x)")
        raise ValueError("disk on fire")

    monkeypatch.setattr(migrations, "MIGRATIONS", [m if m.number != 35 else migrations.Migration(35, "boom", boom, destructive=True) for m in migrations.MIGRATIONS])
    with sqlite3.connect(path) as conn:
        with pytest.raises(migrations.MigrationError, match=r"Migration 35 \(boom\) failed: disk on fire.*before-migration-0035"):
            migrations.run(conn)
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'half_done'").fetchone()
        assert 35 not in {r[0] for r in conn.execute("SELECT number FROM schema_migrations")}
    assert any(".before-migration-0035-" in f.name for f in tmp_path.iterdir())


def test_the_backup_holds_what_was_still_in_the_wal(tmp_path):
    path = tmp_path / "a.sqlite"
    with db.connect(path) as conn:
        conn.execute("CREATE TABLE marker (v)")
        conn.execute("INSERT INTO marker VALUES ('kept')")
        conn.commit()
        backup = migrations._backup(conn, 1)
    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT v FROM marker").fetchone()[0] == "kept"


def test_the_dry_run_migrates_a_copy_and_leaves_the_database_alone(tmp_path):
    path = tmp_path / "a.sqlite"
    with db.connect(path) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE number = 36")
        conn.execute("ALTER TABLE university_milestones DROP COLUMN end_day")
        conn.commit()
    listing = lambda: sorted(f.name for f in tmp_path.iterdir() if not f.name.endswith(("-wal", "-shm")))  # noqa: E731
    before, files = path.read_bytes(), listing()
    assert migrations.dry_run(path) == [36]
    assert path.read_bytes() == before and listing() == files
    with sqlite3.connect(path) as conn:
        assert 36 not in {r[0] for r in conn.execute("SELECT number FROM schema_migrations")}


def test_the_check_command_reports_success_and_failure(tmp_path, capsys):
    path = tmp_path / "a.sqlite"
    with db.connect(path):
        pass
    assert migrations.main(["check", str(path)]) == 0 and "nothing pending" in capsys.readouterr().out
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO schema_migrations (number, name, applied_at) VALUES (999, 'x', 'x')")
    assert migrations.main(["check", str(path)]) == 1 and "ahead" in capsys.readouterr().err
