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

    def test_status_options_render_as_colored_pills(self, conn):
        # Direct follow-up ("status options still aren't pills") -- the
        # trigger already showed the current status as a colored pill; the
        # open panel's own options needed the same `.pill-static pill-
        # <color>` treatment, not just plain text next to a radio.
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "pill-static pill-blue" in body  # "active"'s color


class TestStatusLabelChangeListenerNotAncestorScoped:
    """Regression guard (2026-08-29, direct report: "the label inline
    editor still doesn't work") -- static/tasks_table.js's `change`
    listener used to gate the Status/Labels branches behind `target.
    matches("#tasks-body input.task-status-radio")` (an ancestor-scoped
    selector). That's only true while the dropdown is closed: app.js's
    generic `.multiselect` handling portals an *open* panel's whole
    subtree (radios/checkboxes included) out to #multiselect-portal, a
    sibling of #tasks-body, not a descendant -- so the one moment this
    branch needed to fire (a real click on an option) was exactly the
    moment its own `.matches()` check went false. No browser/JS harness in
    this suite (see this file's own header note), so this is a structural
    source check -- same style test_toast_rework.py/test_pwa_shell.py use
    for JS-only changes -- rather than a simulated click."""

    def test_status_and_label_inputs_are_not_ancestor_scoped(self):
        # Checks the actual `target.matches(...)` call sites, not just
        # "the old string doesn't appear anywhere" -- the old (buggy)
        # selector is deliberately still quoted in this file's own
        # explanatory comment above the fix, so a bare substring-absence
        # check would false-positive against that documentation.
        js = (_STATIC_DIR / "tasks_table.js").read_text(encoding="utf-8")
        assert 'target.matches("input.task-status-radio")' in js
        assert 'target.matches("input.task-label-checkbox")' in js
        assert 'target.matches("#tasks-body input.task-status-radio")' not in js
        assert 'target.matches("#tasks-body input.task-label-checkbox")' not in js


class TestInlineLabelEditKeepsRealPillColorAndIcon:
    """Regression guard (audit-fixes-2.1.md, direct report: "the pills
    revert to a blue no icon pill, even if they normally have color and
    icon. A refresh fixes this."). The label-checkbox change handler used to
    hand-build a generic `<span class="cell-tag tag-blue">Name</span>` per
    checked label with no idea of that label's real configured color/icon
    (that lookup is server-side only, in _label_pill.html's label_pill()/
    label_color()/label_icon()) -- every inline-edited pill collapsed to
    plain blue, no icon, until the next full page load re-rendered it
    correctly. Fixed to clone the real, server-rendered pill markup already
    sitting next to each checkbox in the dropdown panel (_task_row.html's
    option list also calls label_pill(name)) instead of reconstructing a
    fake one. No JS test harness in this suite (see this file's own header
    note) -- structural source check, same style as the class above."""

    def test_hardcoded_blue_pill_reconstruction_is_gone(self):
        js = (_STATIC_DIR / "tasks_table.js").read_text(encoding="utf-8")
        assert '"<span class=\\"cell-tag tag-blue\\">" + escapeHtml(name) + "</span>"' not in js
        assert "checked.map((name) =>" not in js

    def test_trigger_rebuild_clones_the_real_pill_markup(self):
        js = (_STATIC_DIR / "tasks_table.js").read_text(encoding="utf-8")
        # The fix reads each checked checkbox's own sibling `.cell-tag`
        # (the real label_pill() output already in the DOM) via
        # `.parentElement.querySelector(".cell-tag")` and reuses its
        # `outerHTML`, rather than ever calling `escapeHtml(cb.value)` to
        # build a pill from scratch (that fallback path still exists for
        # the defensive "pill not found" case, but is no longer the normal
        # path).
        assert 'cb.parentElement.querySelector(".cell-tag")' in js
        assert "pill.outerHTML" in js
