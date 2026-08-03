"""Tests for routers/tags.py's write-through behavior (Phase 2 of the
projects/tags rework) -- the part that actually matters: rename/merge/
delete must rewrite tags_json on every affected task/event/contact AND
push that through the CalDAV/CardDAV bridge, not just this app's SQLite
cache (see the router's module docstring for why). Calls the router
functions directly (bypassing FastAPI's dependency injection, which is
just wiring) with a fake bridge that mimics save_*_row's real contract
(return the row, unchanged) without needing a live Radicale server --
that live round-trip is covered separately by test_caldav_bridge_live.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import tags as tags_router


class FakeBridge:
    """save_*_row's real implementations write to Radicale and return the
    row with href/etag/calendar_path filled in; callers here only care
    that (a) it was called with the right data and (b) it hands back
    something upsert-able, so returning the row unchanged is a faithful
    enough stand-in for this router's own logic, which never reads
    href/etag itself."""

    def __init__(self):
        self.task_calls = []
        self.event_calls = []
        self.contact_calls = []

    def save_task_row(self, row):
        self.task_calls.append(dict(row))
        return row

    def save_event_row(self, row):
        self.event_calls.append(dict(row))
        return row

    def save_contact_row(self, row):
        self.contact_calls.append(dict(row))
        return row


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


@pytest.fixture()
def bridge():
    return FakeBridge()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, tags):
    db.upsert_task(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "tasks", "title": uid,
        "description": "", "status": "active", "tags": tags, "created_at": _now(),
    })


def _seed_event(conn, uid, tags):
    db.upsert_event(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "calendar", "title": uid,
        "description": "", "status": "active", "all_day": 0, "tags": tags, "created_at": _now(),
    })


def _seed_contact(conn, uid, tags):
    db.upsert_contact(conn, {
        "uid": uid, "href": f"/{uid}", "addressbook_path": "contacts", "full_name": uid,
        "tags": tags, "created_at": _now(),
    })


class TestCreateTag:
    def test_creates(self, conn):
        tags_router.create_tag(name="urgent", color="red", group_uid="", conn=conn)
        tag = db.get_tag_by_name(conn, "urgent")
        assert tag is not None
        assert tag["color"] == "red"

    def test_duplicate_name_is_a_noop_not_a_crash(self, conn):
        tags_router.create_tag(name="urgent", color="red", group_uid="", conn=conn)
        tags_router.create_tag(name="Urgent", color="blue", group_uid="", conn=conn)
        assert len(db.list_tags(conn)) == 1
        assert db.get_tag_by_name(conn, "urgent")["color"] == "red"


class TestEditTagRename:
    def test_rename_writes_through_task_event_contact(self, conn, bridge):
        tags_router.create_tag(name="uni", color="blue", group_uid="", conn=conn)
        tag = db.get_tag_by_name(conn, "uni")
        _seed_task(conn, "t1", ["uni", "keep"])
        _seed_event(conn, "e1", ["uni"])
        _seed_contact(conn, "c1", ["uni"])

        tags_router.edit_tag(tag["uid"], name="university", color="blue", group_uid="", bridge=bridge, conn=conn)

        assert db.get_task(conn, "t1")["tags"] == ["university", "keep"]
        assert db.get_event(conn, "e1")["tags"] == ["university"]
        assert db.get_contact(conn, "c1")["tags"] == ["university"]
        assert db.get_tag_by_name(conn, "university") is not None
        assert db.get_tag_by_name(conn, "uni") is None
        # Confirms the write actually went through the bridge, not just db.py.
        assert len(bridge.task_calls) == 1
        assert len(bridge.event_calls) == 1
        assert len(bridge.contact_calls) == 1

    def test_rename_untouched_objects_not_written(self, conn, bridge):
        tags_router.create_tag(name="uni", color="blue", group_uid="", conn=conn)
        tag = db.get_tag_by_name(conn, "uni")
        _seed_task(conn, "t1", ["unrelated"])

        tags_router.edit_tag(tag["uid"], name="university", color="blue", group_uid="", bridge=bridge, conn=conn)

        assert bridge.task_calls == []
        assert db.get_task(conn, "t1")["tags"] == ["unrelated"]

    def test_case_only_rename_does_not_require_a_write(self, conn, bridge):
        tags_router.create_tag(name="uni", color="blue", group_uid="", conn=conn)
        tag = db.get_tag_by_name(conn, "uni")
        _seed_task(conn, "t1", ["uni"])

        tags_router.edit_tag(tag["uid"], name="UNI", color="blue", group_uid="", bridge=bridge, conn=conn)

        # Case-insensitive-equal names don't trigger a rewrite pass -- the
        # registry name updates but nothing needed to change on tasks.
        assert bridge.task_calls == []
        assert db.get_tag(conn, tag["uid"])["name"] == "UNI"

    def test_rename_colliding_with_existing_tag_merges_instead(self, conn, bridge):
        tags_router.create_tag(name="uni", color="blue", group_uid="", conn=conn)
        tags_router.create_tag(name="university", color="green", group_uid="", conn=conn)
        uni = db.get_tag_by_name(conn, "uni")
        _seed_task(conn, "t1", ["uni"])

        tags_router.edit_tag(uni["uid"], name="university", color="blue", group_uid="", bridge=bridge, conn=conn)

        # "uni" got merged into the pre-existing "university" tag rather
        # than raising a unique-constraint error the user can't act on.
        assert db.get_tag_by_name(conn, "uni") is None
        assert db.get_tag_by_name(conn, "university") is not None
        assert db.get_task(conn, "t1")["tags"] == ["university"]


class TestMergeTag:
    def test_merge_deduplicates(self, conn, bridge):
        tags_router.create_tag(name="hw", color="blue", group_uid="", conn=conn)
        tags_router.create_tag(name="homework", color="green", group_uid="", conn=conn)
        hw = db.get_tag_by_name(conn, "hw")
        homework = db.get_tag_by_name(conn, "homework")
        _seed_task(conn, "t1", ["hw", "homework"])  # already carries both

        tags_router.merge_tag(hw["uid"], dest_uid=homework["uid"], bridge=bridge, conn=conn)

        assert db.get_task(conn, "t1")["tags"] == ["homework"]
        assert db.get_tag_by_name(conn, "hw") is None

    def test_merge_repoints_source_tag_across_types(self, conn, bridge):
        tags_router.create_tag(name="a", color="blue", group_uid="", conn=conn)
        tags_router.create_tag(name="b", color="green", group_uid="", conn=conn)
        a = db.get_tag_by_name(conn, "a")
        b = db.get_tag_by_name(conn, "b")
        _seed_task(conn, "t1", ["a"])
        _seed_event(conn, "e1", ["a"])
        _seed_contact(conn, "c1", ["a"])

        tags_router.merge_tag(a["uid"], dest_uid=b["uid"], bridge=bridge, conn=conn)

        assert db.get_task(conn, "t1")["tags"] == ["b"]
        assert db.get_event(conn, "e1")["tags"] == ["b"]
        assert db.get_contact(conn, "c1")["tags"] == ["b"]


class TestDeleteTag:
    def test_delete_strips_from_every_object_and_removes_registry(self, conn, bridge):
        tags_router.create_tag(name="temp", color="blue", group_uid="", conn=conn)
        temp = db.get_tag_by_name(conn, "temp")
        _seed_task(conn, "t1", ["temp", "keep"])
        _seed_event(conn, "e1", ["temp"])

        tags_router.delete_tag(temp["uid"], bridge=bridge, conn=conn)

        assert db.get_tag(conn, temp["uid"]) is None
        assert db.get_task(conn, "t1")["tags"] == ["keep"]
        assert db.get_event(conn, "e1")["tags"] == []

    def test_delete_tag_not_used_anywhere_is_still_removed_from_registry(self, conn, bridge):
        tags_router.create_tag(name="unused", color="blue", group_uid="", conn=conn)
        unused = db.get_tag_by_name(conn, "unused")
        tags_router.delete_tag(unused["uid"], bridge=bridge, conn=conn)
        assert db.get_tag(conn, unused["uid"]) is None
        assert bridge.task_calls == []
        assert bridge.event_calls == []
        assert bridge.contact_calls == []


class TestTagGroups:
    def test_create_and_assign(self, conn):
        tags_router.create_tag_group(name="Academic", conn=conn)
        group = db.list_tag_groups(conn)[0]
        tags_router.create_tag(name="exam", color="blue", group_uid=group["uid"], conn=conn)
        tag = db.get_tag_by_name(conn, "exam")
        assert tag["group_uid"] == group["uid"]

    def test_delete_group_ungroups_tags(self, conn):
        tags_router.create_tag_group(name="Academic", conn=conn)
        group = db.list_tag_groups(conn)[0]
        tags_router.create_tag(name="exam", color="blue", group_uid=group["uid"], conn=conn)
        tags_router.delete_tag_group(group["uid"], conn=conn)
        tag = db.get_tag_by_name(conn, "exam")
        assert tag["group_uid"] is None
