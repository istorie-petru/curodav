"""Tests for the Habits/Events halves of item 19 (2026-09-26): "This is the
same Archive concept tasks already have (share it, don't duplicate). Events
must not be archivable. Habits must be archivable."

A habit is a habit-labeled task (habit_view.py's own module docstring) --
so "Habits must be archivable" reuses the exact `status='archived'` value
tasks already have (routers/tasks.py's STATUSES), not a new column like
Contacts got (see test_contacts_archive_column.py for that half). The real
gaps this closes:
  1. habit_task_form.html has no Status field at all (direct feedback,
     "habits should not have... a status dropdown") -- so there was no
     user-facing way to ever set status='archived' on a habit. Fixed with
     a dedicated Archive/Restore button + two new routes
     (archive_task/unarchive_task, routers/tasks.py) that bypass the
     generic Status field entirely.
  2. update_task's own `status` Form default used to be hardcoded
     "active" -- since habit_task_form.html never sends a status field at
     all, a plain Save on an already-archived habit would have silently
     un-archived it. Fixed by falling back to the row's own existing
     status instead of a hardcoded value, only when the field is
     genuinely absent from the request.
  3. Once archived, `habit_view.habit_items` (already, pre-existing)
     drops the habit from the main Habits page entirely -- with no
     Archive button there was previously no way to reach that state at
     all, so there was also no need for a way back. A new "Archived"
     modal (routers/habits.py) is that way back.

Events are covered by a single negative-confirmation class at the bottom:
no column, no route, no UI -- nothing to build, this just asserts the
absence stays true.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db, habit_view
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/tasks"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []})


def _habit(conn, uid, title=None, recurrence="FREQ=DAILY", status="active"):
    db.upsert_task(conn, {
        "uid": uid, "title": title or uid, "description": "", "status": status,
        "tags": ["Habit"], "recurrence": recurrence, "created_at": _now(),
    })
    return uid


class TestArchiveTaskRoute:
    """routers/tasks.py's new archive_task/unarchive_task -- generic (any
    task, not habit-specific), same `dict(existing)+one field+upsert_task`
    shape complete_task already uses."""

    def test_archive_sets_status_and_progress(self, conn):
        _habit(conn, "h1")
        resp = tasks_router.archive_task("h1", conn=conn)
        assert resp.status_code == 303
        task = db.get_task(conn, "h1")
        assert task["status"] == "archived"
        assert task["progress"] == 1.0

    def test_unarchive_restores_active(self, conn):
        _habit(conn, "h1", status="archived")
        resp = tasks_router.unarchive_task("h1", conn=conn)
        assert resp.status_code == 303
        task = db.get_task(conn, "h1")
        assert task["status"] == "active"
        assert task["progress"] == 0.0

    def test_archiving_unknown_uid_is_a_quiet_no_op(self, conn):
        tasks_router.archive_task("ghost", conn=conn)  # must not raise
        assert db.get_task(conn, "ghost") is None

    def test_dual_mode_json_response(self, conn):
        _habit(conn, "h1")
        resp = tasks_router.archive_task("h1", x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
        assert resp.body.decode() == '{"ok":true}'

    def test_works_on_a_plain_non_habit_task_too(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Plain", "description": "", "status": "active", "created_at": _now()})
        tasks_router.archive_task("t1", conn=conn)
        assert db.get_task(conn, "t1")["status"] == "archived"


class TestUpdateTaskPreservesArchivedStatus:
    """The bug item 19 fixes: habit_task_form.html sends no `status` field
    at all, so update_task's own default used to hardcode "active" --
    every plain Save on an already-archived habit silently undid the
    archive. Now it falls back to the row's own existing status instead."""

    def test_plain_habit_save_does_not_unarchive(self, conn):
        _habit(conn, "h1", title="Meditate", status="archived")
        # Simulates habit_task_form.html's own POST -- no status field.
        tasks_router.update_task(
            "h1", title="Meditate (renamed)", description="", due_at="", start_at="",
            tags="", tags_labels=["Habit"], project="", project_field="", recurrence="FREQ=DAILY",
            target_per_day="1", conn=conn,
        )
        task = db.get_task(conn, "h1")
        assert task["title"] == "Meditate (renamed)"
        assert task["status"] == "archived"

    def test_plain_tasks_generic_form_still_sets_status_explicitly(self, conn):
        # The generic task_form.html DOES send a real status field on
        # every save -- unaffected by the new fallback, which only ever
        # kicks in when the field is genuinely absent from the request.
        db.upsert_task(conn, {"uid": "t1", "title": "Plain", "description": "", "status": "archived", "created_at": _now()})
        tasks_router.update_task(
            "t1", title="Plain", description="", due_at="", start_at="", status="active",
            tags="", recurrence="", target_per_day="1", conn=conn,
        )
        assert db.get_task(conn, "t1")["status"] == "active"

    def test_brand_new_task_still_defaults_active_via_create(self, conn):
        # create_task's own status default is untouched by this fix.
        tasks_router.create_task(title="New", description="", due_at="", status="active", tags="", recurrence="", conn=conn)
        uid = db.list_tasks(conn)[0]["uid"]
        assert db.get_task(conn, uid)["status"] == "active"


class TestHabitFormArchiveButton:
    def test_not_archived_habit_offers_archive_button(self, conn):
        _habit(conn, "h1", title="Meditate")
        body = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert 'action="/tasks/h1/archive"' in body
        assert 'action="/tasks/h1/unarchive"' not in body
        assert "Archive habit" in body

    def test_archived_habit_offers_restore_button(self, conn):
        _habit(conn, "h1", title="Meditate", status="archived")
        body = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert 'action="/tasks/h1/unarchive"' in body
        assert 'action="/tasks/h1/archive"' not in body
        assert "Restore habit" in body

    def test_still_no_visible_status_field(self, conn):
        # The Archive button must not reintroduce the generic Status
        # dropdown this form deliberately has none of.
        _habit(conn, "h1", title="Meditate")
        body = tasks_router.edit_task_form("h1", _request("/tasks/h1/edit"), conn=conn).body.decode()
        assert 'name="status"' not in body

    def test_new_habit_form_has_no_archive_button_yet(self, conn):
        body = tasks_router.new_task_form(_request("/tasks/new?habit=1"), habit="1", conn=conn).body.decode()
        assert "Archive habit" not in body
        assert "Restore habit" not in body


class TestHabitItemsExcludesArchived:
    """Pre-existing behavior (habit_view.py's own `_INACTIVE_STATUSES`),
    confirmed here as the reason a "way back" (the Archived modal below)
    is needed at all -- an archived habit isn't just de-prioritized, it's
    completely gone from the main page."""

    def test_archived_habit_missing_from_habit_items(self, conn):
        _habit(conn, "h1", title="Meditate")
        _habit(conn, "h2", title="Old habit", status="archived")
        items = habit_view.habit_items(conn)
        assert [h["uid"] for h in items] == ["h1"]

    def test_archiving_a_habit_removes_it_from_the_habits_page(self, conn):
        _habit(conn, "h1", title="Meditate")
        body = habits_router.habits_page(_request("/habits"), conn=conn).body.decode()
        assert "Meditate" in body
        tasks_router.archive_task("h1", conn=conn)
        body = habits_router.habits_page(_request("/habits"), conn=conn).body.decode()
        assert "Meditate" not in body


class TestArchivedHabitsModal:
    def test_lists_archived_habits_sorted_by_title(self, conn):
        _habit(conn, "h1", title="Zzz", status="archived")
        _habit(conn, "h2", title="Aaa", status="archived")
        _habit(conn, "h3", title="Still active")
        resp = habits_router.archived_modal(_request("/habits/archived"), conn=conn)
        assert [h["title"] for h in resp.context["archived"]] == ["Aaa", "Zzz"]

    def test_empty_state_when_nothing_archived(self, conn):
        _habit(conn, "h1", title="Meditate")
        body = habits_router.archived_modal(_request("/habits/archived"), conn=conn).body.decode()
        assert "No archived habits." in body

    def test_rendered_row_has_a_restore_form(self, conn):
        _habit(conn, "h1", title="Old habit", status="archived")
        body = habits_router.archived_modal(_request("/habits/archived"), conn=conn).body.decode()
        assert "Old habit" in body
        assert 'action="/tasks/h1/unarchive"' in body
        assert 'data-cc-change="task"' in body

    def test_restoring_brings_it_back_to_the_main_page(self, conn):
        _habit(conn, "h1", title="Old habit", status="archived")
        tasks_router.unarchive_task("h1", conn=conn)
        body = habits_router.habits_page(_request("/habits"), conn=conn).body.decode()
        assert "Old habit" in body
        modal_body = habits_router.archived_modal(_request("/habits/archived"), conn=conn).body.decode()
        assert "Old habit" not in modal_body

    def test_habits_page_links_to_the_archived_modal(self, conn):
        body = habits_router.habits_page(_request("/habits"), conn=conn).body.decode()
        assert 'href="/habits/archived"' in body
        assert "data-modal" in body


class TestEventsMustNotBeArchivable:
    """The item's other explicit constraint: "Events must not be
    archivable." Confirms the absence stays true -- no column, no route,
    no UI -- rather than building anything new."""

    def test_events_table_has_no_archived_column(self):
        import pathlib
        import re

        db_py = (pathlib.Path(__file__).resolve().parent.parent / "src" / "db.py").read_text()
        events_table = re.search(r"CREATE TABLE IF NOT EXISTS events \((.*?)\n\);", db_py, re.DOTALL)
        assert events_table is not None
        assert "archived_at" not in events_table.group(1)

    def test_no_archive_route_for_events(self):
        from src.routers import calendar as calendar_router

        assert not hasattr(calendar_router, "archive_event")
        assert not hasattr(calendar_router, "unarchive_event")

    def test_event_status_values_never_include_archived(self, conn):
        db.upsert_event(conn, {
            "uid": "e1", "title": "Meeting", "description": "", "start_at": _now(), "end_at": None,
            "all_day": False, "status": "active", "tags": [], "created_at": _now(), "updated_at": _now(),
        })
        # Nothing in the event form/routes ever writes "archived" -- this
        # is a plain regression check that the value stays whatever it
        # was created with, not evidence of a rejection mechanism (there
        # is deliberately none -- events just never expose the choice).
        assert db.get_event(conn, "e1")["status"] == "active"
