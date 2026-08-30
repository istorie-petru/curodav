"""2026-08-29 (STATE.md backlog item 9, direct follow-up): Habits moved out
of the shared `#task-table` into its own `#habits-table` with its own
header row, and gained the same double-click-to-edit title inline_edit.js
already gave plain tasks -- a standalone Habit *entity* needed its own
`update-field` endpoint for that (its uid lives in `habits`, not `tasks`)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import habits as habits_router
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


def _request():
    return Request({"type": "http", "method": "GET", "path": "/tasks", "headers": []})


class TestHabitsOwnTable:
    def test_habits_render_in_a_separate_table_with_their_own_header(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Meditate", "created_at": _now()})
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'id="task-table"' in body
        assert 'id="habits-table"' in body
        # The habits table's own header names what its columns actually
        # are, not the task table's Status/Date/Scheduled labels.
        habits_table = body.split('id="habits-table"', 1)[1]
        assert ">Check-in<" in habits_table.split("</table>")[0]
        assert ">Cadence<" in habits_table.split("</table>")[0]
        assert ">Streak<" in habits_table.split("</table>")[0]

    def test_habits_table_is_always_present_even_with_no_habits_yet(self, conn):
        # The "+ Add habit" affordance needs somewhere to live even before
        # any habit exists -- same "always show the group" behavior the
        # combined table had before the split.
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'id="habits-table"' in body
        assert "Add habit" in body

    def test_habit_entity_row_is_in_the_habits_table_not_the_task_table(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Meditate", "created_at": _now()})
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        task_table = body.split('id="task-table"', 1)[1].split('id="habits-table"')[0]
        habits_table = body.split('id="habits-table"', 1)[1]
        assert "Meditate" not in task_table
        assert "Meditate" in habits_table
        assert "t1" in task_table


class TestGroupNameAndAddButtonInTableHeader:
    """2026-08-29 direct follow-up: "instead of a separate row for add
    task, have a + button ... on the group label name row" put each
    group's name/count/`+` on its own `.task-section-divider` <tr>.
    2026-08-30, same day: Habits (only ever one group) dropped that row
    entirely, folding its name+count+`+` into its own table's <thead>
    instead -- then a further same-day direct follow-up ("I like how the
    habits table looks... make the same style for all") applied that same
    shape to Project/Unassigned/Completed too. Every group's `<thead>` now
    carries its own name+count in place of a generic "Title" label, and
    its own `+` (task/habit groups only) in the trailing header cell --
    there is no more `.task-section-divider` row anywhere on this page."""

    def test_no_task_add_row_left_in_either_table(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Meditate", "created_at": _now()})
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "task-add-row" not in body
        assert "task-section-divider" not in body

    def test_unassigned_group_name_and_add_link_are_in_its_header(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        header = body.split(">Unassigned (1)<", 1)[1].split("</thead>")[0]
        assert 'href="/tasks/new"' in header
        assert 'title="Add task"' in header

    def test_project_group_name_and_add_link_are_in_its_header(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1})
        _seed_task(conn, "t1", tags=["Garden"])
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        header = body.split(">Garden (1)<", 1)[1].split("</thead>")[0]
        assert "/tasks/new?project=Garden" in header

    def test_habits_group_name_and_add_link_are_in_its_header(self, conn):
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        habits_table = body.split('id="habits-table"', 1)[1]
        assert ">Habits (0)<" in habits_table.split("</thead>")[0]
        header = habits_table.split("</thead>")[0]
        assert 'href="/tasks/new?habit=1"' in header
        assert 'title="Add habit"' in header

    def test_completed_group_header_has_no_add_link(self, conn):
        _seed_task(conn, "t1")
        db.upsert_task(conn, dict(db.get_task(conn, "t1"), status="done"))
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        header = body.split(">Completed (1)<", 1)[1].split("</thead>")[0]
        assert "icon-btn" not in header


class TestHabitRowTitleInlineEdit:
    def test_habit_entity_title_is_double_click_editable(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Meditate", "created_at": _now()})
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'data-uid="h1" data-field="title" data-kind="entity"' in body

    def test_habit_labeled_task_title_carries_kind_task(self, conn):
        db.save_task_habit_settings(conn, "Habit")
        db.upsert_task(
            conn,
            {"uid": "ht1", "title": "Stretch", "description": "", "status": "active", "tags": ["Habit"],
             "recurrence": "FREQ=DAILY", "created_at": _now()},
        )
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'data-uid="ht1" data-field="title" data-kind="task"' in body


class TestHabitEntityUpdateField:
    def test_renames_a_standalone_habit(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Old name", "created_at": _now()})
        resp = asyncio.run(habits_router.update_field("h1", _json_request({"field": "title", "value": "New name"}), conn=conn))
        assert resp.status_code == 200
        assert db.get_habit(conn, "h1")["name"] == "New name"

    def test_trims_the_new_name(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Old", "created_at": _now()})
        asyncio.run(habits_router.update_field("h1", _json_request({"field": "title", "value": "  Padded  "}), conn=conn))
        assert db.get_habit(conn, "h1")["name"] == "Padded"

    def test_rejects_a_blank_name(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Old", "created_at": _now()})
        resp = asyncio.run(habits_router.update_field("h1", _json_request({"field": "title", "value": "   "}), conn=conn))
        assert resp.status_code == 400
        assert db.get_habit(conn, "h1")["name"] == "Old"

    def test_rejects_an_unknown_field(self, conn):
        db.upsert_habit(conn, {"uid": "h1", "name": "Old", "created_at": _now()})
        resp = asyncio.run(habits_router.update_field("h1", _json_request({"field": "color", "value": "red"}), conn=conn))
        assert resp.status_code == 400

    def test_404s_for_a_missing_habit(self, conn):
        resp = asyncio.run(habits_router.update_field("nope", _json_request({"field": "title", "value": "x"}), conn=conn))
        assert resp.status_code == 404
