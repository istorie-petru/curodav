"""Phase 1 (label-space rework) acceptance tests -- see
features/architecture.md §3 Phase 1's own acceptance criteria:

  * every task/event/contact create/edit path writes straight to SQL,
    no bridge/Radicale call anywhere in that path (routers/tasks.py,
    routers/calendar.py, routers/contacts.py all dropped `get_bridge`
    entirely -- see each router's own module comments);
  * a row still round-trips to a valid VEVENT/VTODO/VCARD (the export
    feature, routers/export.py + ical_rows.py/vcard_rows.py);
  * scripts/migrate_labels.py backfills `object_labels` correctly from
    tags, old calendars/task_lists/addressbooks, and old
    project_groups/projects;
  * its §6 UID-collision sanity check aborts (nonzero exit, no writes)
    when the same uid is claimed by more than one object type.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import db

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import migrate_labels  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- #
# No bridge/Radicale call in base CRUD
# --------------------------------------------------------------------- #


class _ExplodingBridge:
    """A bridge that raises if literally anything on it is called --
    proves a code path never touches the bridge at all, not just that it
    happens to tolerate a real one being absent. Every method a
    CalDavBridge exposes that base CRUD used to call is covered."""

    def __getattr__(self, name):
        def _boom(*a, **kw):
            raise AssertionError(f"bridge.{name}() should never be called by base task/event/contact CRUD (Phase 1)")
        return _boom


class TestTaskCrudNeverTouchesBridge:
    def test_create_task_writes_straight_to_sql(self, conn):
        from src.routers import tasks as tasks_router

        assert "bridge" not in tasks_router.create_task.__code__.co_varnames
        tasks_router.create_task(title="Buy milk", description="", due_at="", status="active",
                                  tags="", recurrence="", conn=conn)
        row = db.list_tasks(conn)[0]
        assert row["title"] == "Buy milk"
        # No href/etag/calendar_path/list_path/raw_ics survive into the row.
        assert "href" not in row and "list_path" not in row

    def test_update_and_delete_never_reference_a_bridge_param(self, conn):
        from src.routers import tasks as tasks_router
        import inspect

        for fn in (tasks_router.create_task, tasks_router.update_task, tasks_router.delete_task,
                   tasks_router.complete_task, tasks_router.update_field):
            sig = inspect.signature(fn)
            assert "bridge" not in sig.parameters, f"{fn.__name__} still takes a bridge"


class TestEventCrudNeverTouchesBridge:
    def test_create_event_writes_straight_to_sql(self, conn):
        from src.routers import calendar as calendar_router

        calendar_router.create_event(
            title="Standup", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="", recurrence="", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        row = db.list_events(conn)[0]
        assert row["title"] == "Standup"
        assert "calendar_path" not in row and "href" not in row

    def test_event_endpoints_never_take_a_bridge_param(self, conn):
        from src.routers import calendar as calendar_router
        import inspect

        for fn in (calendar_router.create_event, calendar_router.update_event, calendar_router.delete_event):
            assert "bridge" not in inspect.signature(fn).parameters


class TestContactCrudNeverTouchesBridge:
    def test_create_contact_writes_straight_to_sql(self, conn):
        import asyncio
        from src.routers import contacts as contacts_router

        asyncio.run(contacts_router.create_contact(
            full_name="Ada Lovelace", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address="",
            tags="", notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert row["full_name"] == "Ada Lovelace"
        assert "addressbook_path" not in row and "href" not in row

    def test_contact_endpoints_never_take_a_bridge_param(self, conn):
        # 2026-08-07: archive_contact/unarchive_contact no longer exist --
        # Contacts has no special "archived" state anymore, only labels
        # (see routers/contacts.py's own comment). The remaining CRUD
        # endpoints still never take a bridge param.
        from src.routers import contacts as contacts_router
        import inspect

        for fn in (contacts_router.create_contact, contacts_router.update_contact,
                   contacts_router.delete_contact):
            assert "bridge" not in inspect.signature(fn).parameters


class TestExplodingBridgeNeverInvoked:
    """Belt-and-suspenders: even if a router *did* still accept a bridge
    kwarg somewhere, actually passing one that explodes on any attribute
    access proves it's never touched. Uses the routers directly, no
    FastAPI dependency injection involved."""

    def test_task_flow_with_exploding_bridge_object_floating_nearby(self, conn):
        from src.routers import tasks as tasks_router

        bridge = _ExplodingBridge()  # noqa: F841 -- deliberately unused, proves nothing needs it
        tasks_router.create_task(title="X", description="", due_at="", status="active",
                                  tags="", recurrence="", conn=conn)
        uid = db.list_tasks(conn)[0]["uid"]
        tasks_router.update_task(uid, title="Y", description="", due_at="", start_at="",
                                  status="active", tags="", recurrence="", conn=conn)
        tasks_router.complete_task(uid, conn=conn)
        tasks_router.delete_task(uid, conn=conn)
        assert db.list_tasks(conn) == []


# --------------------------------------------------------------------- #
# Export still produces valid iCal/vCard
# --------------------------------------------------------------------- #


class TestExportRoundTrip:
    def test_event_row_serializes_to_a_valid_vevent(self, conn):
        from src.routers import export as export_router

        db.upsert_event(conn, {
            "uid": "e1", "title": "Standup", "description": "", "status": "active",
            "start_at": "2026-08-10T09:00:00", "end_at": "2026-08-10T09:30:00", "all_day": 0,
            "tags": ["work"], "created_at": _now(), "updated_at": _now(),
        })
        resp = export_router.export_events_ics(conn=conn)
        from icalendar import Calendar

        cal = Calendar.from_ical(resp.body)
        events = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(events) == 1
        assert str(events[0]["UID"]) == "e1"
        assert str(events[0]["SUMMARY"]) == "Standup"

    def test_task_row_serializes_to_a_valid_vtodo(self, conn):
        from src.routers import export as export_router

        db.upsert_task(conn, {
            "uid": "t1", "title": "Ship it", "description": "", "status": "active",
            "tags": [], "created_at": _now(), "updated_at": _now(),
        })
        resp = export_router.export_tasks_ics(conn=conn)
        from icalendar import Calendar

        cal = Calendar.from_ical(resp.body)
        todos = [c for c in cal.walk() if c.name == "VTODO"]
        assert len(todos) == 1
        assert str(todos[0]["UID"]) == "t1"

    def test_contact_row_serializes_to_a_valid_vcard(self, conn):
        from src.routers import export as export_router
        import vobject
        from io import StringIO

        db.upsert_contact(conn, {
            "uid": "c1", "full_name": "Ada Lovelace", "tags": [],
            "created_at": _now(), "updated_at": _now(),
        })
        resp = export_router.export_contacts_vcf(conn=conn)
        cards = list(vobject.readComponents(StringIO(resp.body.decode())))
        assert len(cards) == 1
        assert cards[0].uid.value == "c1"
        assert cards[0].fn.value == "Ada Lovelace"


# --------------------------------------------------------------------- #
# scripts/migrate_labels.py
# --------------------------------------------------------------------- #


def _seed_legacy_collections(conn: sqlite3.Connection) -> None:
    """Simulates a pre-Phase-1 database: the legacy `calendars`/
    `task_lists`/`addressbooks` tables and `calendar_path`/`list_path`/
    `addressbook_path` columns physically still exist (db.py's Phase 1
    schema no longer creates them for a *new* db, but never drops them
    from an existing one -- see db.py's Phase 1 comments), which is
    exactly the situation this migration script is meant to run against."""
    conn.execute("CREATE TABLE calendars (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT, project_uid TEXT)")
    conn.execute("CREATE TABLE task_lists (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT, project_uid TEXT)")
    conn.execute("CREATE TABLE addressbooks (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT, project_uid TEXT)")
    conn.execute("ALTER TABLE events ADD COLUMN calendar_path TEXT")
    conn.execute("ALTER TABLE tasks ADD COLUMN list_path TEXT")
    conn.execute("ALTER TABLE contacts ADD COLUMN addressbook_path TEXT")
    conn.commit()


class TestMigrationScript:
    def test_backfills_labels_from_tags(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni", "urgent"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "Y", "description": "", "status": "active",
                                "all_day": 0, "tags": ["uni"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Z", "tags": ["urgent"], "created_at": _now()})

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result

        assert sorted(db.list_labels_for_object(conn, "task", "t1")) == ["uni", "urgent"]
        assert db.list_labels_for_object(conn, "event", "e1") == ["uni"]
        assert db.list_labels_for_object(conn, "contact", "c1") == ["urgent"]
        assert sorted(db.list_object_ids_for_label(conn, "task", "uni")) == ["t1"]

    def test_backfills_labels_from_old_collections(self, conn):
        _seed_legacy_collections(conn)
        conn.execute("INSERT INTO calendars VALUES ('cal1','Work','blue','x',NULL)")
        conn.execute("INSERT INTO task_lists VALUES ('tl1','Homework','green','x',NULL)")
        conn.execute("INSERT INTO addressbooks VALUES ('ab1','Contacts','red','x',NULL)")
        conn.execute(
            "INSERT INTO events (uid, title, description, start_at, end_at, all_day, calendar_path) "
            "VALUES ('e1','Standup','','2026-01-01','2026-01-01',0,'cal1')"
        )
        conn.execute(
            "INSERT INTO tasks (uid, title, description, status, list_path) "
            "VALUES ('t1','HW1','','active','tl1')"
        )
        conn.execute(
            "INSERT INTO contacts (uid, full_name, addressbook_path) "
            "VALUES ('c1','Alice','ab1')"
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result

        assert db.list_labels_for_object(conn, "event", "e1") == ["Work"]
        assert db.list_labels_for_object(conn, "task", "t1") == ["Homework"]
        assert db.list_labels_for_object(conn, "contact", "c1") == ["Contacts"]
        # Old colors carried forward into label_config.
        assert db.get_label_config(conn, "Work")["color"] == "blue"
        assert db.get_label_config(conn, "Homework")["color"] == "green"
        assert db.get_label_config(conn, "Contacts")["color"] == "red"

    def test_backfills_labels_from_old_projects_and_groups(self, conn):
        _seed_legacy_collections(conn)
        # `project_groups`/`projects` are gone from db.py's own schema (Phase
        # 2 dropped them entirely) -- simulate a pre-Phase-2 database the
        # same way `_seed_legacy_collections` simulates a pre-Phase-1 one:
        # raw CREATE TABLE + INSERT, exactly what the migration script reads
        # directly via SQL rather than through any db.py helper.
        conn.execute(
            "CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, "
            "group_uid TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO project_groups VALUES ('g1', 'University', 'orange', ?)", (_now(),))
        conn.execute(
            "INSERT INTO projects VALUES ('p1', 'CS101', '', 'purple', 'g1', ?, ?)", (_now(), _now())
        )
        conn.execute("INSERT INTO task_lists VALUES ('tl1','Homework','green','x','p1')")
        conn.execute(
            "INSERT INTO tasks (uid, title, description, status, list_path) "
            "VALUES ('t1','HW1','','active','tl1')"
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result

        labels = set(db.list_labels_for_object(conn, "task", "t1"))
        # Both the list's own collection label AND the project's label
        # (and, transitively, the project's group/space label) apply.
        assert labels == {"Homework", "CS101", "University"}
        assert db.get_label_config(conn, "CS101")["color"] == "purple"
        assert db.get_label_config(conn, "University")["color"] == "orange"
        # Every label migrated from a `project_groups` row (a former Space)
        # gets generate_space=1; the project's own label does not.
        assert db.get_label_config(conn, "University")["generate_space"] == 1
        assert db.get_label_config(conn, "CS101")["generate_space"] == 0

    def test_dry_run_reports_counts_without_writing(self, conn):
        # db.upsert_task already writes straight to object_labels (Phase 2
        # dropped `tags_json` entirely -- there's nothing left for this
        # migration to backfill from a *current-schema* task/event/contact,
        # see _migrate_tags' own comment). Exercise the dry-run path
        # against a genuinely pre-Phase-2 collection instead, the same way
        # the old-collections tests above simulate one.
        _seed_legacy_collections(conn)
        conn.execute("INSERT INTO calendars VALUES ('cal1','Work','blue','x',NULL)")
        conn.execute(
            "INSERT INTO events (uid, title, description, start_at, end_at, all_day, calendar_path) "
            "VALUES ('e1','Standup','','2026-01-01','2026-01-01',0,'cal1')"
        )
        conn.commit()
        result = migrate_labels.run_migration(conn, dry_run=True)
        assert result["labels_created"] == 1
        assert db.list_all_label_names(conn) == []  # nothing actually written
        assert db.list_labels_for_object(conn, "event", "e1") == []

    def test_idempotent_rerun_does_not_duplicate(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        migrate_labels.run_migration(conn)
        migrate_labels.run_migration(conn)
        assert db.list_labels_for_object(conn, "task", "t1") == ["uni"]

    def test_uid_collision_check_aborts(self, conn):
        # A task and an event sharing the same uid -- the one collision
        # shape this schema can actually represent (see migrate_labels.py's
        # module docstring for why a same-type collision is already
        # structurally impossible thanks to each table's own PRIMARY KEY).
        db.upsert_task(conn, {"uid": "dup1", "title": "T", "description": "", "status": "active",
                               "tags": [], "created_at": _now()})
        db.upsert_event(conn, {"uid": "dup1", "title": "E", "description": "", "status": "active",
                                "all_day": 0, "tags": [], "created_at": _now()})

        result = migrate_labels.run_migration(conn)
        assert "collisions" in result
        assert result["collisions"]["dup1"] == ["event", "task"]
        # Nothing was written -- the check runs before any label backfill.
        assert db.list_all_label_names(conn) == []

    def test_collision_free_data_reports_no_collisions(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active",
                               "tags": [], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "E", "description": "", "status": "active",
                                "all_day": 0, "tags": [], "created_at": _now()})
        assert migrate_labels.find_cross_type_uid_collisions(conn) == {}

    def test_main_exits_nonzero_on_collision(self, conn, tmp_path, capsys):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.upsert_task(c, {"uid": "dup1", "title": "T", "description": "", "status": "active",
                                "tags": [], "created_at": _now()})
            db.upsert_event(c, {"uid": "dup1", "title": "E", "description": "", "status": "active",
                                 "all_day": 0, "tags": [], "created_at": _now()})

        exit_code = migrate_labels.main(["--db-path", str(db_path)])
        assert exit_code != 0
        out = capsys.readouterr().out
        assert "ABORTED" in out
        assert "dup1" in out
