"""1.5 slice (single-project-per-task, plans/open-priority.md § Task model):
"A task may belong to exactly one project label and may additionally carry
any number of ordinary labels -- never multiple projects at once." Covers
the enforcement point (db.upsert_task's tags argument ->
db.MultipleProjectLabelsError), the three write paths that can hand a task
two project labels (create form, edit form, bulk "Add label"), and that a
pre-existing task with multiple project labels is left alone unless
something writes new tags for it."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_project(conn, name):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": None, "end_date": None, "created_at": _now()},
    )


def _seed_task(conn, uid, **overrides):
    row = {"uid": uid, "title": uid, "description": "", "status": "active", "created_at": _now()}
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _json_request(payload: dict):
    import json as _json

    req = Request({"type": "http", "method": "POST", "path": "/tasks/bulk", "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestDbUpsertTaskRejectsTwoProjectLabels:
    def test_two_project_labels_at_once_raises(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        with pytest.raises(db.MultipleProjectLabelsError):
            db.upsert_task(
                conn,
                {"uid": "t1", "title": "t1", "description": "", "status": "active",
                 "tags": ["Alpha", "Beta"], "created_at": _now()},
            )
        # Rejected before anything was written -- the task doesn't exist at all.
        assert db.get_task(conn, "t1") is None

    def test_one_project_label_plus_ordinary_labels_is_fine(self, conn):
        _make_project(conn, "Alpha")
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active",
             "tags": ["Alpha", "Urgent", "Home"], "created_at": _now()},
        )
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["Alpha", "Home", "Urgent"]

    def test_no_project_label_at_all_is_fine(self, conn):
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active",
             "tags": ["Urgent", "Home"], "created_at": _now()},
        )
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["Home", "Urgent"]

    def test_tags_none_skips_the_check_entirely(self, conn):
        # Any caller that doesn't touch labels (tags=None / omitted) must
        # never trip this -- e.g. complete_task's dict(existing) round-trip
        # when the row already has no "tags" key set explicitly.
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        db.upsert_task(
            conn,
            {"uid": "t1", "title": "t1", "description": "", "status": "active", "created_at": _now()},
        )
        assert db.get_task(conn, "t1") is not None


class TestPreexistingMultiProjectDataIsNotCorrupted:
    """A task that already carries two project labels (e.g. from a
    pre-1.5 data state / direct DB edit) must not be silently stripped by
    this change -- enforcement is a write-boundary check only, on calls
    that pass a new `tags` list."""

    def test_direct_db_write_bypassing_upsert_task_is_left_alone(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        now = _now()
        conn.execute(
            "INSERT INTO tasks (uid, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, '', 'active', ?, ?)",
            ("legacy1", "Legacy task", now, now),
        )
        conn.execute(
            "INSERT INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            ("task", "legacy1", "Alpha"),
        )
        conn.execute(
            "INSERT INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
            ("task", "legacy1", "Beta"),
        )
        conn.commit()
        task = db.get_task(conn, "legacy1")
        assert sorted(task["tags"]) == ["Alpha", "Beta"]

        # Reading it back and re-saving *without* changing tags (tags=None)
        # must not touch/strip the pre-existing double-project label set.
        row = dict(task)
        row.pop("tags", None)
        row["title"] = "Legacy task (renamed)"
        db.upsert_task(conn, row)
        assert sorted(db.get_task(conn, "legacy1")["tags"]) == ["Alpha", "Beta"]

    def test_but_the_next_real_label_edit_on_it_is_still_enforced(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        now = _now()
        conn.execute(
            "INSERT INTO tasks (uid, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, '', 'active', ?, ?)",
            ("legacy2", "Legacy task 2", now, now),
        )
        for name in ("Alpha", "Beta"):
            conn.execute(
                "INSERT INTO object_labels (object_type, object_id, label_name) VALUES (?, ?, ?)",
                ("task", "legacy2", name),
            )
        conn.commit()
        task = db.get_task(conn, "legacy2")
        row = dict(task)  # this dict's "tags" is ["Alpha", "Beta"] -- still both, unchanged
        with pytest.raises(db.MultipleProjectLabelsError):
            db.upsert_task(conn, row)


class TestCreateTaskFormRejectsTwoProjectLabels:
    def test_create_task_with_two_project_labels_is_rejected(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        with pytest.raises(HTTPException) as excinfo:
            tasks_router.create_task(
                title="New task", description="", due_at="", status="active",
                tags="", tags_labels=["Alpha", "Beta"], recurrence="", conn=conn,
            )
        assert excinfo.value.status_code == 400
        assert "one project label" in excinfo.value.detail
        assert not any(t["title"] == "New task" for t in db.list_tasks(conn))

    def test_create_task_with_one_project_label_plus_ordinary_label_works(self, conn):
        _make_project(conn, "Alpha")
        tasks_router.create_task(
            title="New task", description="", due_at="", status="active",
            tags="", tags_labels=["Alpha", "Urgent"], recurrence="", conn=conn,
        )
        task = next(t for t in db.list_tasks(conn) if t["title"] == "New task")
        assert sorted(task["tags"]) == ["Alpha", "Urgent"]


class TestUpdateTaskFormRejectsAddingASecondProjectLabel:
    def test_editing_an_existing_task_to_add_a_second_project_label_is_rejected(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        _seed_task(conn, "t1", tags=["Alpha"])
        with pytest.raises(HTTPException) as excinfo:
            tasks_router.update_task(
                uid="t1", title="t1", description="", due_at="", start_at="",
                status="active", tags="", tags_labels=["Alpha", "Beta"], recurrence="", conn=conn,
            )
        assert excinfo.value.status_code == 400
        # Rejected before the write -- the task's labels are untouched.
        assert db.get_task(conn, "t1")["tags"] == ["Alpha"]


class TestBulkAddLabelRejectsASecondProjectLabel:
    def test_bulk_add_label_rejects_when_task_already_has_a_project_label(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        _seed_task(conn, "t1", tags=["Alpha"])
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1"], "tags": ["Beta"], "mode": "add"}),
            conn=conn,
        ))
        assert resp.status_code == 400
        assert db.get_task(conn, "t1")["tags"] == ["Alpha"]

    def test_bulk_add_label_still_succeeds_for_tasks_without_a_conflict(self, conn):
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        _seed_task(conn, "t1", tags=["Alpha"])  # would conflict
        _seed_task(conn, "t2", tags=[])  # no conflict
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1", "t2"], "tags": ["Beta"], "mode": "add"}),
            conn=conn,
        ))
        assert resp.status_code == 400  # overall response still flags the failure
        assert db.get_task(conn, "t1")["tags"] == ["Alpha"]  # rejected, unchanged
        assert db.get_task(conn, "t2")["tags"] == ["Beta"]  # applied, no conflict

    def test_bulk_add_ordinary_label_alongside_existing_project_label_still_works(self, conn):
        _make_project(conn, "Alpha")
        _seed_task(conn, "t1", tags=["Alpha"])
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1"], "tags": ["Urgent"], "mode": "add"}),
            conn=conn,
        ))
        assert resp.status_code == 200
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["Alpha", "Urgent"]
