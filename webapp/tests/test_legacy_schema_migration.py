"""Regression test for a real live bug (2026-08-07): a user with a
pre-label-space-rework `cache.sqlite` (from before Phase 1 of
plans/label-space-rework.md) hit `sqlite3.IntegrityError: NOT NULL
constraint failed: events.href` trying to create an event, because the
old `href`/`etag`/collection-path columns are still physically present
on an existing database (deliberately -- scripts/migrate_labels.py needs
to read the collection-path columns to backfill labels) but were
originally declared NOT NULL with no default, and current upsert_event/
upsert_task/upsert_contact correctly stop supplying a value for them.

Every other test in this suite connects to a brand-new tmp_path database
via `db.connect`, which always gets the *current* `SCHEMA_SQL` -- none of
them ever exercise what an actual pre-migration database on disk looks
like, which is exactly why this bug shipped unnoticed. This file
constructs that legacy shape by hand (raw SQL, bypassing db.connect's
own schema) to close that gap."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def legacy_conn(tmp_path):
    """A raw connection to a hand-built pre-Phase-1 events/tasks/contacts
    schema -- NOT NULL href/etag/collection-path, no object_labels/
    label_config at all (those didn't exist yet either), one legacy row
    per table so we can assert the migration preserves it."""
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE events (
            uid TEXT PRIMARY KEY,
            href TEXT NOT NULL,
            etag TEXT NOT NULL,
            calendar_path TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            start_at TEXT,
            end_at TEXT,
            all_day INTEGER NOT NULL DEFAULT 0,
            location TEXT,
            meeting_url TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            recurrence TEXT,
            exdates_json TEXT NOT NULL DEFAULT '[]',
            reminders_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE tasks (
            uid TEXT PRIMARY KEY,
            href TEXT NOT NULL,
            etag TEXT NOT NULL,
            calendar_path TEXT NOT NULL,
            list_path TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            start_at TEXT,
            due_at TEXT,
            priority INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            progress REAL,
            parent_uid TEXT,
            recurrence TEXT,
            exdates_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE contacts (
            uid TEXT PRIMARY KEY,
            href TEXT NOT NULL,
            etag TEXT NOT NULL,
            addressbook_path TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '',
            org TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX idx_events_start ON events(start_at);
        CREATE INDEX idx_tasks_status ON tasks(status);
        """
    )
    now = _now()
    conn.execute(
        "INSERT INTO events (uid, href, etag, calendar_path, title, created_at, updated_at) "
        "VALUES ('e-legacy', '/cal/e-legacy.ics', '\"abc123\"', 'calendar', 'Legacy Event', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO tasks (uid, href, etag, calendar_path, list_path, title, created_at, updated_at) "
        "VALUES ('t-legacy', '/tasks/t-legacy.ics', '\"def456\"', 'calendar', 'tasks', 'Legacy Task', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO contacts (uid, href, etag, addressbook_path, full_name, created_at, updated_at) "
        "VALUES ('c-legacy', '/contacts/c-legacy.vcf', '\"ghi789\"', 'contacts', 'Legacy Contact', ?, ?)",
        (now, now),
    )
    conn.commit()
    yield conn
    conn.close()


class TestLegacyNotNullRelaxed:
    def test_events_href_no_longer_blocks_insert(self, legacy_conn):
        db.init_schema(legacy_conn)
        # The exact real-world failure: creating a new event the current
        # way (no href/etag/calendar_path supplied at all) must succeed
        # against a database that still physically has those columns.
        db.upsert_event(legacy_conn, {
            "uid": "e-new", "title": "New Event", "description": "", "status": "active",
            "all_day": 0, "created_at": _now(), "updated_at": _now(),
        })
        assert db.get_event(legacy_conn, "e-new") is not None

    def test_tasks_href_no_longer_blocks_insert(self, legacy_conn):
        db.init_schema(legacy_conn)
        db.upsert_task(legacy_conn, {
            "uid": "t-new", "title": "New Task", "description": "", "status": "active",
            "created_at": _now(), "updated_at": _now(),
        })
        assert db.get_task(legacy_conn, "t-new") is not None

    def test_contacts_href_no_longer_blocks_insert(self, legacy_conn):
        db.init_schema(legacy_conn)
        db.upsert_contact(legacy_conn, {
            "uid": "c-new", "full_name": "New Contact", "created_at": _now(), "updated_at": _now(),
        })
        assert db.get_contact(legacy_conn, "c-new") is not None

    def test_legacy_row_data_is_preserved_not_dropped(self, legacy_conn):
        # scripts/migrate_labels.py needs calendar_path/list_path/
        # addressbook_path's *values* to still be there -- this migration
        # must relax the constraint, not destroy the data.
        db.init_schema(legacy_conn)
        row = legacy_conn.execute("SELECT * FROM events WHERE uid = 'e-legacy'").fetchone()
        assert row["href"] == "/cal/e-legacy.ics"
        assert row["calendar_path"] == "calendar"
        assert row["title"] == "Legacy Event"

        row = legacy_conn.execute("SELECT * FROM tasks WHERE uid = 't-legacy'").fetchone()
        assert row["href"] == "/tasks/t-legacy.ics"
        assert row["list_path"] == "tasks"

        row = legacy_conn.execute("SELECT * FROM contacts WHERE uid = 'c-legacy'").fetchone()
        assert row["href"] == "/contacts/c-legacy.vcf"
        assert row["addressbook_path"] == "contacts"

    def test_indexes_survive_the_rebuild(self, legacy_conn):
        db.init_schema(legacy_conn)
        names = {
            row[0] for row in legacy_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
            ).fetchall()
        }
        assert "idx_events_start" in names

    def test_idempotent_second_call_is_a_no_op(self, legacy_conn):
        db.init_schema(legacy_conn)
        db.upsert_event(legacy_conn, {
            "uid": "e-new2", "title": "Another", "description": "", "status": "active",
            "all_day": 0, "created_at": _now(), "updated_at": _now(),
        })
        # Re-running init_schema (happens on every db.connect()/request in
        # the real app) must not error and must not lose the row just
        # written or the original legacy row.
        db.init_schema(legacy_conn)
        assert db.get_event(legacy_conn, "e-new2") is not None
        assert db.get_event(legacy_conn, "e-legacy") is not None

    def test_fresh_database_is_unaffected(self, tmp_path):
        # A brand-new database (current SCHEMA_SQL, no legacy NOT NULL
        # columns at all) must not trigger the rebuild path -- confirms
        # _relax_legacy_not_null's guard actually guards.
        with db.connect(tmp_path / "fresh.sqlite") as conn:
            db.upsert_event(conn, {
                "uid": "e1", "title": "T", "description": "", "status": "active",
                "all_day": 0, "created_at": _now(), "updated_at": _now(),
            })
            assert db.get_event(conn, "e1") is not None
