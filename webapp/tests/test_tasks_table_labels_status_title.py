"""2026-08-29 (STATE.md backlog item 9, "Tasks table view, several changes
bundled together"): Status becomes a checkbox-dropdown cell (_task_row.html)
instead of a native <select>, Title becomes double-click-to-edit inline
(static/inline_edit.js), the Due column header is renamed "Date", and the
date-picker's Apply button is gone in date mode. Labels also briefly became
an editable checkbox dropdown that same slice -- reverted 2026-09-26
(Peter: "labels should not be inline editable") back to plain read-only
pills; edit_task_form (the task detail modal) is the only way to change a
task's labels again. The markup/JS side of this isn't exercised by this
Python suite (no JS test harness -- see plans/STATE.md's own note on that),
but the router contract each cell's JS ultimately calls through
(POST /tasks/{uid}/update-field) is, plus the rendered HTML each cell
produces."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import tasks as tasks_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


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


class TestUpdateFieldTagsIsNoLongerInlineEditable:
    """2026-09-26 (Peter: "labels should not be inline editable") --
    `tags` was briefly in `_UPDATABLE_FIELDS` (2026-08-29 - 2026-09-26);
    posting it now gets the same generic "not inline-editable" rejection
    any other unknown field would."""

    def test_tags_is_not_in_updatable_fields(self):
        assert "tags" not in tasks_router._UPDATABLE_FIELDS

    def test_posting_tags_is_rejected(self, conn):
        _seed_task(conn, "t1", tags=["Old"])
        resp = asyncio.run(tasks_router.update_field("t1", _json_request({"field": "tags", "value": ["New"]}), conn=conn))
        assert resp.status_code == 400
        assert db.get_task(conn, "t1")["tags"] == ["Old"]  # unchanged


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
    def test_only_the_status_is_edited_inline(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        for marker in ("inline-date", "data-inline-edit"):
            assert marker not in body
        assert "task-status-select" in body and 'class="task-status-radio"' in body

    def test_a_row_reads_title_then_date_then_labels_then_status_beside_the_menu(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Pay rent", "description": "", "status": "active", "due_at": "2026-09-01",
                              "tags": ["Home"], "created_at": _now()})
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        row = body.split('data-uid="t1"', 1)[1]
        order = [row.index(m) for m in ('task-row-title', 'task-row-date', 'task-row-tags', 'task-status-select', 'action-menu')]
        assert order == sorted(order)

    def test_labels_cell_is_plain_read_only_pills(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Alpha"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "t2", "description": "", "status": "active", "tags": [], "created_at": _now()})
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "task-labels-select" not in body
        assert "task-label-checkbox" not in body
        assert 'class="task-row-tags"' in body
        assert "No tag" in body

    def test_the_title_opens_the_view_modal(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'href="/tasks/t1" data-modal' in body

    def test_status_options_render_as_colored_pills(self, conn):
        # Direct follow-up ("status options still aren't pills") -- the
        # trigger already showed the current status as a colored pill; the
        # open panel's own options needed the same `.pill-static pill-
        # <color>` treatment, not just plain text next to a radio.
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "pill-static pill-blue" in body  # "active"'s color, shown as a plain pill


