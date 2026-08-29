"""2026-08-29 (STATE.md backlog item 9, "Tasks table view, several changes
bundled together"): Status and Labels become checkbox-dropdown cells
(_task_row.html) instead of a native <select>/read-only pills, Title
becomes double-click-to-edit inline (static/inline_edit.js), the Due
column header is renamed "Date", and the date-picker's Apply button is
gone in date mode. The markup/JS side of this isn't exercised by this
Python suite (no JS test harness -- see plans/STATE.md's own note on that),
but the router contract each cell's JS ultimately calls through
(POST /tasks/{uid}/update-field) is, plus the rendered HTML each new cell
produces."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, tags=None):
    db.upsert_task(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": "active", "tags": tags or [], "created_at": _now()},
    )


def _json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/x",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


def _request(path="/tasks"):
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


class TestUpdateFieldTags:
    """The Labels column's checkbox dropdown re-posts the row's whole new
    tag set on every toggle (routers/tasks.py's update_field, field="tags")
    -- a replace, not an add/remove delta."""

    def test_tags_is_now_inline_editable(self):
        assert "tags" in tasks_router._UPDATABLE_FIELDS

    def test_replaces_the_full_tag_list(self, conn):
        _seed_task(conn, "t1", tags=["Old"])
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": ["New", "Second"]}), conn=conn))
        assert resp.status_code == 200
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["New", "Second"]

    def test_empty_list_clears_all_tags(self, conn):
        _seed_task(conn, "t1", tags=["Old"])
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": []}), conn=conn))
        assert resp.status_code == 200
        assert db.get_task(conn, "t1")["tags"] == []

    def test_rejects_a_non_list_value(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": "NotAList"}), conn=conn))
        assert resp.status_code == 400

    def test_blank_and_non_string_entries_are_dropped(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": ["Real", "  ", "", 5]}), conn=conn))
        assert resp.status_code == 200
        assert db.get_task(conn, "t1")["tags"] == ["Real"]

    def test_rejects_a_second_project_label(self, conn):
        # Same 1.5 single-project-per-task guard the create/edit forms and
        # bulk "Add label" already get -- surfaced as a plain 400 here too
        # rather than a silent 500 or partial write.
        db.upsert_label_config(conn, {"name": "ProjA", "is_project": 1})
        db.upsert_label_config(conn, {"name": "ProjB", "is_project": 1})
        _seed_task(conn, "t1", tags=["ProjA"])
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": ["ProjA", "ProjB"]}), conn=conn))
        assert resp.status_code == 400
        assert db.get_task(conn, "t1")["tags"] == ["ProjA"]  # rejected before writing


class TestUpdateFieldTitleRejectsBlank:
    def test_blank_title_is_rejected(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "title", "value": "   "}), conn=conn))
        assert resp.status_code == 400
        assert db.get_task(conn, "t1")["title"] == "t1"

    def test_title_is_trimmed(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "title", "value": "  New title  "}), conn=conn))
        assert resp.status_code == 200
        assert db.get_task(conn, "t1")["title"] == "New title"


class TestTableMarkup:
    def test_due_column_header_renamed_to_date(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert ">Date</th>" in body
        assert ">Due</th>" not in body

    def test_status_is_a_dropdown_not_a_native_select(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'class="pill-select pill-' not in body  # old native <select> pill is gone
        assert "task-status-select" in body
        assert 'class="task-status-radio"' in body

    def test_labels_cell_is_an_editable_checkbox_dropdown(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Alpha"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "t2", "description": "", "status": "active", "tags": [], "created_at": _now()})
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "task-labels-select" in body
        assert 'class="task-label-checkbox"' in body
        assert 'value="Alpha" checked' in body

    def test_title_is_a_double_click_editable_link(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "data-inline-edit-linked" in body
        assert 'data-field="title"' in body
        assert 'data-type="text"' in body
