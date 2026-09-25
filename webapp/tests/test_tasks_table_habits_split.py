"""2026-08-29 (STATE.md backlog item 9, direct follow-up): Habits moved out
of the shared `#task-table` into its own `#habits-table` with its own
header row, and gained the same double-click-to-edit title inline_edit.js
already gave plain tasks. Since 2026-09-24 every habit row is a
habit-labeled task (the standalone Habit entity, and its own update-field
endpoint, were removed); since habits H2 (same day) the Habits table left
the Tasks page entirely for /habits -- what's left here covers the main
task table's own shape (test_habits_page.py covers the new page)."""

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


def _seed_habit(conn, uid, title):
    """A habit is a habit-labeled task (the standalone Habit entity these
    tests used to seed was removed 2026-09-24)."""
    db.save_task_habit_settings(conn, "Habit")
    db.upsert_task(
        conn,
        {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Habit"],
         "recurrence": "FREQ=DAILY", "created_at": _now()},
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

    def test_habits_table_is_hidden_when_there_are_no_habits_yet(self, conn):
        # 2026-09-07 (direct report: "the habits or completed tables
        # should appear only if there is data") -- reverses the
        # 2026-08-29 decision this test used to encode (see git history
        # for that version): _build_task_groups always appends a Habits
        # group regardless of whether there are any habits, which used to
        # mean an empty "Habits (0)" table with a header row and no data
        # rows rendered unconditionally. Direct instruction now is the
        # opposite -- hide it when there's nothing to show, same as any
        # other empty section. The "+ Add habit" affordance that lived in
        # this table's header is gone along with it in the empty case;
        # creating a first habit still works via the sidebar's global
        # quick-add / task creation's own habit toggle, just not from a
        # dedicated empty table anymore.
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert 'id="habits-table"' not in body


class TestGroupNameAndAddButtonInTableHeader:
    """2026-08-29 direct follow-up: "instead of a separate row for add
    task, have a + button ... on the group label name row" put each
    group's name/count/`+` on its own `.task-section-divider` <tr>.
    2026-08-30, same day: Habits (only ever one group) dropped that row
    entirely, folding its name+count+`+` into its own table's <thead>
    instead -- then a further same-day direct follow-up ("I like how the
    habits table looks... make the same style for all") applied that same
    shape to Project/Unassigned/Completed too, so every group's `<thead>`
    carried its own name+count and its own `+`.

    2026-09-03 direct follow-up ("don't repeat column headers, say them
    once -- don't group tasks by label any more, make one single big
    table"): Project/Unassigned/Completed's own per-group `.card`+
    `<table>`+`<thead>` (and their per-group `+`) are gone -- collapsed
    into one `#task-table` with one plain Title/Status/Date/Labels
    `<thead>` and one flat `<tbody>` (routers/tasks.py's `groups` context
    is unchanged -- see test_tasks_grouping.py -- only this template's
    rendering of it changed). _tasks_toolbar.html briefly grew a single
    "+ Task nou" header button the same day to replace the removed
    per-group links, then direct follow-up removed that too -- task
    creation from this page now relies entirely on the sidebar's own
    global quick-add and the command palette. Habits keeps its own
    separate table/header/`+` exactly as before -- it was never part of
    this complaint (see this class's -- and _tasks_body.html's own --
    reasoning: it's a different set of columns for a different kind of
    row, not "grouping tasks by label")."""

    def test_no_task_add_row_left_in_either_table(self, conn):
        _seed_habit(conn, "h1", "Meditate")
        _seed_task(conn, "t1")
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "task-add-row" not in body
        assert "task-section-divider" not in body

    def test_task_table_has_exactly_one_plain_header_no_group_names(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1})
        _seed_task(conn, "t1", tags=["Garden"])
        _seed_task(conn, "t2", tags=[])
        db.upsert_task(conn, dict(db.get_task(conn, "t2"), status="done"))
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        task_table = body.split('id="task-table"', 1)[1].split('id="habits-table"')[0]
        # Exactly one <thead> in the task table's own region -- not one per
        # group -- and the column labels appear only that once.
        assert task_table.count("<thead>") == 1
        assert task_table.count(">Title<") == 1
        assert task_table.count(">Status<") == 1
        assert task_table.count(">Date<") == 1
        assert task_table.count(">Labels<") == 1
        # No more per-group name+count header text anywhere.
        assert "Garden (1)" not in body
        assert "Unassigned (1)" not in body
        assert "Completed (1)" not in body

    def test_project_and_unassigned_tasks_share_the_one_table(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1})
        _seed_task(conn, "a1", tags=["Garden"])
        _seed_task(conn, "loose1", tags=[])
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        task_table = body.split('id="task-table"', 1)[1].split('task-table-habits')[0]
        assert "a1" in task_table
        assert "loose1" in task_table
        # Only one <table> element opens in this region (the merged one).
        assert task_table.count("<table") == 1

    def test_no_per_group_add_task_link_left_anywhere(self, conn):
        # 2026-09-03 direct follow-up: the single "+ Task nou" header
        # button this test used to require (added the same day the
        # per-group "+" links were removed) was itself removed a moment
        # later, direct request -- task creation from this page now falls
        # back entirely to the sidebar's global quick-add/command palette.
        # This test keeps only the half of the original assertion that
        # still holds: no per-group `?project=` add link ever came back.
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1})
        _seed_task(conn, "t1", tags=["Garden"])
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        assert "/tasks/new?project=Garden" not in body


    def test_completed_tasks_render_dimmed_in_the_same_table_no_own_header(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "is_project": 1})
        _seed_task(conn, "open1", tags=["Garden"])
        _seed_task(conn, "done1", tags=["Garden"])
        db.upsert_task(conn, dict(db.get_task(conn, "done1"), status="done"))
        body = tasks_router.list_tasks(_request(), conn=conn).body.decode()
        task_table = body.split('id="task-table"', 1)[1].split('id="habits-table"')[0]
        assert "open1" in task_table
        assert "done1" in task_table
        assert task_table.count("<thead>") == 1  # still just the one shared header
        after_uid = task_table.split('data-uid="done1"', 1)[1]
        done_row_open_tag = after_uid.split(">", 1)[0]
        assert "task-row-completed" in done_row_open_tag


