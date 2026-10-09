"""The Contacts field on tasks and events: link table, cascade, and the
contact's own list of what it is involved in."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _contact(conn, uid, name):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_contact(conn, {"uid": uid, "full_name": name, "created_at": now, "updated_at": now})


def _task(conn, uid, title):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_task(conn, {
        "uid": uid, "title": title, "description": "", "status": "active", "progress": 0, "tags": [],
        "created_at": now, "updated_at": now,
    })


def test_a_task_keeps_its_contacts_and_replaces_them_on_save(conn):
    _contact(conn, "c1", "Dana")
    _contact(conn, "c2", "Fox")
    _task(conn, "t1", "Call them")
    db.set_object_contacts(conn, "task", "t1", ["c1", "c2", "c1"])
    assert [c["full_name"] for c in db.list_object_contacts(conn, "task", "t1")] == ["Dana", "Fox"]
    db.set_object_contacts(conn, "task", "t1", ["c2"])
    assert [c["uid"] for c in db.list_object_contacts(conn, "task", "t1")] == ["c2"]


def test_unknown_and_draft_contacts_are_ignored(conn):
    _task(conn, "t1", "Call them")
    draft = db.create_contact_draft(conn)
    db.set_object_contacts(conn, "task", "t1", ["nope", draft])
    assert db.list_object_contacts(conn, "task", "t1") == []


def test_the_contact_lists_what_it_is_involved_in(conn):
    _contact(conn, "c1", "Dana")
    _task(conn, "t1", "Call them")
    db.set_object_contacts(conn, "task", "t1", ["c1"])
    involved = db.list_contact_objects(conn, "c1")
    assert [t["title"] for t in involved["tasks"]] == ["Call them"]
    assert involved["events"] == []


def test_deleting_a_contact_removes_its_links(conn):
    _contact(conn, "c1", "Dana")
    _task(conn, "t1", "Call them")
    db.set_object_contacts(conn, "task", "t1", ["c1"])
    db.delete_contact(conn, "c1")
    assert db.list_object_contacts(conn, "task", "t1") == []


def test_a_typed_name_creates_a_contact_or_reuses_one_by_name(conn):
    _contact(conn, "c1", "Amy Adams")
    uids = db.resolve_contact_entries(conn, ["c1", "amy adams", "Zed Zane", "", "3f2b8c1e-1111-4222-8333-444455556666"])
    assert uids[0] == "c1" and uids[1] == "c1"
    created = db.get_contact(conn, uids[2])
    assert created["full_name"] == "Zed Zane"
    assert len(uids) == 3
