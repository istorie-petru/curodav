"""scripts/migrate_schedule_classes_to_events.py -- the 1.6 one-time
migration converting a pre-1.6 database's `schedule_classes` rows into
real recurring `events` (see db.py's removal note on that table and
schedule.py's module docstring for the model this migrates *to*). Every
other test in this suite connects to a brand-new tmp_path database via
db.connect, which never has schedule_classes at all (dropped from
SCHEMA_SQL) -- this file builds that legacy shape by hand, same idiom
test_legacy_schema_migration.py uses for the pre-Phase-1 schema."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import migrate_schedule_classes_to_events as migrate  # noqa: E402
from src import db  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        c.execute(
            "CREATE TABLE schedule_classes (uid TEXT PRIMARY KEY, day TEXT, start_time TEXT, "
            "end_time TEXT, name TEXT, acronym TEXT, class_type TEXT, professor TEXT, "
            "professor_contact_uid TEXT, room TEXT, credits REAL, parity TEXT, enrolled INTEGER, "
            "event_uid TEXT, created_at TEXT, updated_at TEXT)"
        )
        c.commit()
        yield c


def _insert_class(conn, uid="c1", **overrides):
    row = {
        "uid": uid, "day": "Tuesday", "start_time": "10:00", "end_time": "12:00",
        "name": "Algorithms", "acronym": "ALG", "class_type": "Course", "professor": "Dr. X",
        "professor_contact_uid": None, "room": "204", "credits": 6, "parity": "all",
        "enrolled": 1, "event_uid": None, "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    cols = list(row)
    conn.execute(
        f"INSERT INTO schedule_classes ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [row[c] for c in cols],
    )
    conn.commit()


class TestNoOp:
    def test_no_schedule_classes_table_is_a_no_op(self, tmp_path):
        with db.connect(tmp_path / "fresh.sqlite") as c:
            result = migrate.run_migration(c)
        assert result == {}


class TestBasicMigration:
    def test_class_becomes_a_real_recurring_event(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-12-20"})
        _insert_class(conn)

        result = migrate.run_migration(conn)
        assert result["classes_migrated"] == 1
        assert result["events_created"] == 1

        events = db.list_schedule_class_events(conn)
        assert len(events) == 1
        event = events[0]
        assert event["title"] == "Algorithms"
        assert event["location"] == "204"
        assert "FREQ=WEEKLY" in event["recurrence"]

    def test_course_fields_land_on_the_course_labels_config(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-12-20"})
        _insert_class(conn)
        migrate.run_migration(conn)

        cfg = db.get_label_config(conn, "Algorithms")
        assert cfg["course_acronym"] == "ALG"
        assert cfg["course_type"] == "Course"
        assert cfg["course_credits"] == 6

    def test_class_with_no_prior_label_gets_one_auto_provisioned(self, conn):
        _insert_class(conn)
        migrate.run_migration(conn)
        event = db.list_schedule_class_events(conn)[0]
        assert "Algorithms" in event["tags"]
        assert db.get_label_config(conn, "Algorithms")["is_project"] == 1

    def test_class_with_an_existing_course_label_reuses_it(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "is_project": 1, "created_at": _now()})
        _insert_class(conn)
        db.add_object_label(conn, "schedule_class", "c1", "CS101")

        migrate.run_migration(conn)
        event = db.list_schedule_class_events(conn)[0]
        assert "CS101" in event["tags"]
        assert "Algorithms" not in event["tags"]  # no second, auto-provisioned label

    def test_space_label_carried_over_directly(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        _insert_class(conn)
        db.add_object_label(conn, "schedule_class", "c1", "University")

        migrate.run_migration(conn)
        event = db.list_schedule_class_events(conn)[0]
        assert "University" in event["tags"]

    def test_reuses_the_existing_mirrored_event_uid(self, conn):
        # A pre-1.6 class already had its own mirrored VEVENT (event_uid)
        # sitting in `events` -- the migration should repurpose that same
        # row, not create an orphaned duplicate alongside it.
        db.upsert_event(conn, {
            "uid": "mirrored-1", "title": "Algorithms (old mirror)", "description": "",
            "status": "active", "all_day": False, "created_at": _now(), "updated_at": _now(),
        })
        _insert_class(conn, event_uid="mirrored-1")

        migrate.run_migration(conn)
        events = db.list_schedule_class_events(conn)
        assert len(events) == 1
        assert events[0]["uid"] == "mirrored-1"
        assert events[0]["title"] == "Algorithms"  # repurposed, not left stale


class TestDryRun:
    def test_dry_run_writes_nothing(self, conn):
        _insert_class(conn)
        result = migrate.run_migration(conn, dry_run=True)
        assert result["classes_migrated"] == 1
        assert db.list_schedule_class_events(conn) == []
        assert db.get_label_config(conn, "Algorithms") is None


class TestIdempotent:
    def test_second_run_does_not_duplicate_the_event(self, conn):
        db.save_schedule_settings(conn, {"semester_start": "2026-09-01", "semester_end": "2026-12-20"})
        _insert_class(conn)
        migrate.run_migration(conn)
        migrate.run_migration(conn)
        assert len(db.list_schedule_class_events(conn)) == 1

    def test_second_run_does_not_overwrite_already_backfilled_course_fields(self, conn):
        _insert_class(conn)
        migrate.run_migration(conn)
        # Simulate the course label having since been hand-edited in the app.
        db.upsert_label_config(conn, {"name": "Algorithms", "course_acronym": "EDITED"})
        migrate.run_migration(conn)
        assert db.get_label_config(conn, "Algorithms")["course_acronym"] == "EDITED"
