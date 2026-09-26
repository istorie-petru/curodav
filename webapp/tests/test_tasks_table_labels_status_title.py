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

    def test_labels_cell_is_plain_read_only_pills(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "t1", "description": "", "status": "active", "tags": ["Alpha"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "t2", "description": "", "status": "active", "tags": [], "created_at": _now()})
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "task-labels-select" not in body
        assert "task-label-checkbox" not in body
        assert '<div class="cell-tags">' in body
        assert ">No labels<" in body

    def test_title_is_a_double_click_editable_link(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "data-inline-edit-linked" in body
        assert 'data-field="title"' in body
        assert 'data-type="text"' in body

    def test_status_options_render_as_colored_pills(self, conn):
        # Direct follow-up ("status options still aren't pills") -- the
        # trigger already showed the current status as a colored pill; the
        # open panel's own options needed the same `.pill-static pill-
        # <color>` treatment, not just plain text next to a radio.
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "pill-static pill-blue" in body  # "active"'s color


class TestStatusChangeListenerNotAncestorScoped:
    """Regression guard (2026-08-29, direct report: "the label inline
    editor still doesn't work") -- static/tasks_table.js's `change`
    listener used to gate the Status branch behind `target.
    matches("#tasks-body input.task-status-radio")` (an ancestor-scoped
    selector). That's only true while the dropdown is closed: app.js's
    generic `.multiselect` handling portals an *open* panel's whole
    subtree (radios included) out to #multiselect-portal, a sibling of
    #tasks-body, not a descendant -- so the one moment this branch needed
    to fire (a real click on an option) was exactly the moment its own
    `.matches()` check went false. No browser/JS harness in this suite
    (see this file's own header note), so this is a structural source
    check -- same style test_toast_rework.py/test_pwa_shell.py use for
    JS-only changes -- rather than a simulated click. (The Labels branch
    this guard also covered is gone entirely, 2026-09-26 -- "labels
    should not be inline editable" -- not just re-scoped.)"""

    def test_status_input_is_not_ancestor_scoped(self):
        # Checks the actual `target.matches(...)` call site, not just "the
        # old string doesn't appear anywhere" -- the old (buggy) selector
        # is deliberately still quoted in this file's own explanatory
        # comment above the fix, so a bare substring-absence check would
        # false-positive against that documentation.
        js = (_STATIC_DIR / "tasks_table.js").read_text(encoding="utf-8")
        assert 'target.matches("input.task-status-radio")' in js
        assert 'target.matches("#tasks-body input.task-status-radio")' not in js
        assert "task-label-checkbox" not in js
