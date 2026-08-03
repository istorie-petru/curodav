"""Data-layer tests for the projects/tags rework, Phase 1 (schema +
repository functions only -- no routers/UI yet, see plans/... for the
phase ordering). Covers: schema init on a fresh DB, tag/project CRUD,
usage-count computation from tasks/events/contacts.tags_json, the
COALESCE-preserving upsert behavior for task_lists/calendars/addressbooks'
project_uid column, archive/unarchive semantics, and merge."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSchemaInit:
    def test_new_tables_exist(self, conn):
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"tags", "tag_groups", "projects", "project_groups"} <= tables

    def test_project_uid_columns_added_to_existing_tables(self, conn):
        for table in ("task_lists", "calendars", "addressbooks", "schedule_classes"):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            assert "project_uid" in cols, table

    def test_reinit_on_already_migrated_db_is_a_noop(self, tmp_path):
        # init_schema must be safe to call twice (every connect() call does
        # this) -- specifically the _ensure_column calls for project_uid,
        # which would raise "duplicate column name" if not idempotent.
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path):
            pass
        with db.connect(db_path):
            pass


class TestTags:
    def test_upsert_and_get(self, conn):
        db.upsert_tag(conn, {"uid": "t1", "name": "urgent", "color": "red", "created_at": _now()})
        tag = db.get_tag(conn, "t1")
        assert tag["name"] == "urgent"
        assert tag["color"] == "red"

    def test_get_by_name_case_insensitive(self, conn):
        db.upsert_tag(conn, {"uid": "t1", "name": "Writing", "color": "blue", "created_at": _now()})
        assert db.get_tag_by_name(conn, "writing")["uid"] == "t1"
        assert db.get_tag_by_name(conn, "WRITING")["uid"] == "t1"

    def test_duplicate_name_case_insensitive_raises(self, conn):
        import sqlite3

        db.upsert_tag(conn, {"uid": "t1", "name": "exam", "color": "blue", "created_at": _now()})
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert_tag(conn, {"uid": "t2", "name": "Exam", "color": "green", "created_at": _now()})

    def test_usage_count_across_tasks_events_contacts(self, conn):
        db.upsert_tag(conn, {"uid": "t1", "name": "uni", "color": "blue", "created_at": _now()})
        db.upsert_task(conn, {"uid": "task1", "href": "/task1", "calendar_path": "tasks", "title": "HW", "description": "", "status": "active", "tags": ["uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "task2", "href": "/task2", "calendar_path": "tasks", "title": "HW2", "description": "", "status": "active", "tags": ["Uni"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "ev1", "href": "/ev1", "calendar_path": "calendar", "title": "Lecture", "description": "", "status": "active", "all_day": 0, "tags": ["uni"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "href": "/c1", "addressbook_path": "contacts", "full_name": "Prof X", "tags": ["uni"], "created_at": _now()})
        tags = db.list_tags(conn)
        by_name = {t["name"]: t for t in tags}
        assert by_name["uni"]["usage_count"] == 4

    def test_list_tag_names_in_use_unions_registry_and_actual_usage(self, conn):
        db.upsert_tag(conn, {"uid": "t1", "name": "registered-only", "color": "blue", "created_at": _now()})
        db.upsert_task(conn, {"uid": "task1", "href": "/task1", "calendar_path": "tasks", "title": "X", "description": "", "status": "active", "tags": ["used-only"], "created_at": _now()})
        names = db.list_tag_names_in_use(conn)
        assert "registered-only" in names
        assert "used-only" in names

    def test_delete_tag_does_not_touch_task_tags_json(self, conn):
        db.upsert_tag(conn, {"uid": "t1", "name": "keep-me", "color": "blue", "created_at": _now()})
        db.upsert_task(conn, {"uid": "task1", "href": "/task1", "calendar_path": "tasks", "title": "X", "description": "", "status": "active", "tags": ["keep-me"], "created_at": _now()})
        db.delete_tag(conn, "t1")
        assert db.get_tag(conn, "t1") is None
        assert db.get_task(conn, "task1")["tags"] == ["keep-me"]

    def test_tag_groups(self, conn):
        db.upsert_tag_group(conn, {"uid": "g1", "name": "Academic", "created_at": _now()})
        db.upsert_tag(conn, {"uid": "t1", "name": "exam", "color": "blue", "group_uid": "g1", "created_at": _now()})
        assert db.get_tag(conn, "t1")["group_uid"] == "g1"
        db.delete_tag_group(conn, "g1")
        assert db.get_tag(conn, "t1")["group_uid"] is None
        assert db.list_tag_groups(conn) == []


class TestProjects:
    def test_upsert_and_get(self, conn):
        db.upsert_project(conn, {
            "uid": "p1", "name": "University", "description": "School stuff",
            "color": "purple", "icon": "🎓", "created_at": _now(), "updated_at": _now(),
        })
        p = db.get_project(conn, "p1")
        assert p["name"] == "University"
        assert p["icon"] == "🎓"
        assert p["archived_at"] is None

    def test_list_projects_excludes_archived_by_default(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "A", "created_at": _now(), "updated_at": _now()})
        db.upsert_project(conn, {"uid": "p2", "name": "B", "created_at": _now(), "updated_at": _now()})
        db.archive_project(conn, "p2", _now())
        active = db.list_projects(conn)
        assert {p["uid"] for p in active} == {"p1"}
        everything = db.list_projects(conn, include_archived=True)
        assert {p["uid"] for p in everything} == {"p1", "p2"}

    def test_archive_then_unarchive(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "A", "created_at": _now(), "updated_at": _now()})
        db.archive_project(conn, "p1", _now())
        assert db.get_project(conn, "p1")["archived_at"] is not None
        db.unarchive_project(conn, "p1")
        assert db.get_project(conn, "p1")["archived_at"] is None

    def test_project_is_archived_check(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "A", "created_at": _now(), "updated_at": _now()})
        assert db.project_is_archived(conn, "p1") is False
        assert db.project_is_archived(conn, None) is False
        assert db.project_is_archived(conn, "does-not-exist") is False
        db.archive_project(conn, "p1", _now())
        assert db.project_is_archived(conn, "p1") is True

    def test_delete_project_unassigns_linked_lists_not_deletes_them(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.ensure_default_task_list(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, "p1")
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] == "p1"
        db.delete_project(conn, "p1")
        assert db.get_project(conn, "p1") is None
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] is None

    def test_merge_projects_repoints_lists_and_deletes_source(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "Old", "created_at": _now(), "updated_at": _now()})
        db.upsert_project(conn, {"uid": "p2", "name": "New", "created_at": _now(), "updated_at": _now()})
        db.ensure_default_task_list(conn)
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, "p1")
        db.merge_projects(conn, "p1", "p2")
        assert db.get_project(conn, "p1") is None
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] == "p2"

    def test_project_groups(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "School", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        assert db.get_project(conn, "p1")["group_uid"] == "g1"
        db.delete_project_group(conn, "g1")
        assert db.get_project(conn, "p1")["group_uid"] is None


class TestProjectUidLinkColumnsPreservedAcrossUnrelatedUpserts:
    """The whole point of the COALESCE trick: renaming/recoloring a list
    through the existing edit flow (which never mentions project_uid at
    all) must not silently unlink it from its project."""

    def test_task_list_rename_preserves_project_link(self, conn):
        db.ensure_default_task_list(conn)
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, "p1")
        # Simulates routers/task_lists.py's edit_task_list, which never
        # passes project_uid at all.
        db.upsert_task_list(conn, {"uid": db.DEFAULT_TASK_LIST_UID, "name": "Renamed", "color": "green"})
        tl = db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)
        assert tl["name"] == "Renamed"
        assert tl["project_uid"] == "p1"

    def test_calendar_recolor_preserves_project_link(self, conn):
        db.ensure_default_calendar(conn)
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.set_calendar_project(conn, db.DEFAULT_CALENDAR_UID, "p1")
        db.upsert_calendar(conn, {"uid": db.DEFAULT_CALENDAR_UID, "name": "Personal", "color": "red"})
        assert db.get_calendar(conn, db.DEFAULT_CALENDAR_UID)["project_uid"] == "p1"

    def test_addressbook_recolor_preserves_project_link(self, conn):
        db.ensure_default_addressbook(conn)
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.set_addressbook_project(conn, db.DEFAULT_ADDRESSBOOK_UID, "p1")
        db.upsert_addressbook(conn, {"uid": db.DEFAULT_ADDRESSBOOK_UID, "name": "Contacts", "color": "yellow"})
        assert db.get_addressbook(conn, db.DEFAULT_ADDRESSBOOK_UID)["project_uid"] == "p1"

    def test_explicit_unassign_via_setter(self, conn):
        db.ensure_default_task_list(conn)
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, "p1")
        db.set_task_list_project(conn, db.DEFAULT_TASK_LIST_UID, None)
        assert db.get_task_list(conn, db.DEFAULT_TASK_LIST_UID)["project_uid"] is None
