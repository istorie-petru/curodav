"""Tests for modal-input-design Phase B: task_form.html/event_form.html/
contact_form.html/habit_form.html's Labels field, and tasks_list.html's
bulk-tag picker, reworked from a free-text `tags` input + `<datalist>` into
the same chip multiselect (checkbox-dropdown) pattern Phase A already used
for the widget builder's Labels field (see
test_phase10_customize_modal.py). A label's own name IS its identity (no
separate uid, see object_labels' natural-key design), so the checkboxes are
named `tags_labels` and folded server-side into the legacy comma-separated
`tags` string via routers/dashboard.py's `_combine_tags` -- reused here via
a cross-router import (`from . import dashboard as dashboard_router`),
following the same convention routers/labels.py already uses to reach
routers/dashboard.py's other private helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
from src.routers import habits as habits_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _seed_task(conn, uid, **overrides):
    row = {"uid": uid, "title": uid, "description": "", "status": "active", "created_at": _now()}
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _seed_event(conn, uid, **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "start_at": "2026-08-10T09:00:00",
        "status": "active", "all_day": False, "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


def _seed_contact(conn, uid, **overrides):
    row = {"uid": uid, "full_name": uid, "created_at": _now(), "updated_at": _now()}
    row.update(overrides)
    db.upsert_contact(conn, row)
    return db.get_contact(conn, uid)


def _seed_habit(conn, uid, **overrides):
    row = {"uid": uid, "name": uid, "color": "blue", "target_per_day": 1, "created_at": _now(), "updated_at": _now()}
    row.update(overrides)
    db.upsert_habit(conn, row)
    return db.get_habit(conn, uid)


class TestFormsRenderChipMultiselectNotTextInput:
    def test_task_form_has_no_tag_input(self, conn):
        _seed_task(conn, "t1", tags=["Work", "Urgent"])
        resp = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="tag-input"' not in body
        assert 'name="tags_labels" value="Work"' in body
        assert 'name="tags_labels" value="Urgent"' in body
        assert 'checked' in body  # at least one checkbox pre-checked

    def test_event_form_has_no_tag_input(self, conn):
        _seed_event(conn, "e1", tags=["Lecture"])
        resp = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="tag-input"' not in body
        assert 'name="tags_labels" value="Lecture"' in body

    def test_contact_form_has_no_tag_input(self, conn):
        _seed_contact(conn, "c1", tags=["Professor"])
        resp = contacts_router.edit_contact_form("c1", _request("/contacts/c1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="tag-input"' not in body
        assert 'name="tags_labels" value="Professor"' in body

    def test_habit_form_has_no_tag_input(self, conn):
        _seed_habit(conn, "h1", tags=["Health"])
        resp = habits_router.edit_habit_form("h1", _request("/habits/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="tag-input"' not in body
        assert 'name="tags_labels" value="Health"' in body

    def test_new_task_form_lists_existing_labels_unchecked(self, conn):
        _seed_task(conn, "t1", tags=["Existing"])
        resp = tasks_router.new_task_form(_request("/tasks/new"), conn=conn)
        body = resp.body.decode()
        assert 'name="tags_labels" value="Existing"' in body


class TestCreateWithTwoLabelsStoresBoth:
    def test_create_task_with_two_labels(self, conn):
        tasks_router.create_task(
            title="Water plants", description="", due_at="", status="active",
            tags="", tags_labels=["Home", "Chores"], recurrence="", conn=conn,
        )
        task = next(t for t in db.list_tasks(conn) if t["title"] == "Water plants")
        assert sorted(task["tags"]) == ["Chores", "Home"]

    def test_create_event_with_two_labels(self, conn):
        calendar_router.create_event(
            title="Standup", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="", tags_labels=["Work", "Daily"],
            recurrence="", reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn,
        )
        events = [e for e in db.list_events(conn, start="2026-01-01", end="2026-12-31") if e["title"] == "Standup"]
        assert sorted(events[0]["tags"]) == ["Daily", "Work"]

    def test_create_contact_with_two_labels(self, conn):
        asyncio.run(contacts_router.create_contact(
            full_name="Grace Hopper", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address="",
            tags="", tags_labels=["Professor", "CS"], notes="", photo=None, conn=conn,
        ))
        row = db.list_contacts(conn)[0]
        assert sorted(row["tags"]) == ["CS", "Professor"]

    def test_create_habit_with_two_labels(self, conn):
        habits_router.create_habit(
            name="Study", description="", color="purple", icon="",
            target_per_day="1", tags="", tags_labels=["Uni", "Focus"], project_uid="", conn=conn,
        )
        h = next(x for x in db.list_habits(conn) if x["name"] == "Study")
        assert sorted(h["tags"]) == ["Focus", "Uni"]


class TestEditAddOrRemoveLabel:
    def test_update_task_adds_and_removes_labels(self, conn):
        _seed_task(conn, "t1", tags=["Old"])
        tasks_router.update_task(
            uid="t1", title="t1", description="", due_at="", start_at="",
            status="active", tags="", tags_labels=["New"], recurrence="", conn=conn,
        )
        assert db.get_task(conn, "t1")["tags"] == ["New"]

    def test_update_event_adds_and_removes_labels(self, conn):
        _seed_event(conn, "e1", tags=["Old"])
        calendar_router.update_event(
            uid="e1", title="e1", description="", start_at="2026-08-10T09:00", end_at="",
            all_day="", location="", meeting_url="", tags="", tags_labels=["New"],
            recurrence="", reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn,
        )
        assert db.get_event(conn, "e1")["tags"] == ["New"]

    def test_update_contact_adds_and_removes_labels(self, conn):
        _seed_contact(conn, "c1", tags=["Old"])
        asyncio.run(contacts_router.update_contact(
            uid="c1", full_name="c1", title="", org="",
            phone_type=[], phone_value=[], email_type=[], email_value=[], website_type=[], website_url=[], address="",
            tags="", tags_labels=["New"], notes="", photo=None, remove_photo="", conn=conn,
        ))
        assert db.get_contact(conn, "c1")["tags"] == ["New"]

    def test_edit_habit_adds_and_removes_labels(self, conn):
        _seed_habit(conn, "h1", tags=["Old"])
        habits_router.edit_habit(
            "h1", name="h1", description="", color="blue", icon="",
            target_per_day="1", tags="", tags_labels=["New"], project_uid="", conn=conn,
        )
        assert db.get_habit(conn, "h1")["tags"] == ["New"]


def _json_request(payload: dict):
    import json as _json

    req = Request({"type": "http", "method": "POST", "path": "/tasks/bulk", "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestTasksListBulkTagPickerRendersChipMultiselect:
    def test_bulk_actions_bar_has_no_bulk_tag_text_input(self, conn):
        _seed_task(conn, "t1", tags=["Existing"])
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        assert 'id="bulk-tag-input"' not in body
        assert 'id="bulk-tag-picker"' in body
        assert 'name="bulk_tag_names" value="Existing"' in body


class TestBulkTagActionSemanticsPreserved:
    """tasks_list.html's bulk-tag Add/Remove buttons apply a *delta*
    (add/remove this label to/from every selected row), not a replace --
    this must stay true after the input becomes a chip multiselect that can
    submit several label names in one request instead of just one."""

    def test_bulk_add_multiple_labels_in_one_call(self, conn):
        _seed_task(conn, "t1", tags=["Keep"])
        _seed_task(conn, "t2", tags=[])
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1", "t2"], "tags": ["A", "B"], "mode": "add"}),
            conn=conn,
        ))
        assert resp.status_code == 200
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["A", "B", "Keep"]
        assert sorted(db.get_task(conn, "t2")["tags"]) == ["A", "B"]

    def test_bulk_remove_multiple_labels_in_one_call(self, conn):
        _seed_task(conn, "t1", tags=["A", "B", "Keep"])
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1"], "tags": ["A", "B"], "mode": "remove"}),
            conn=conn,
        ))
        assert resp.status_code == 200
        assert db.get_task(conn, "t1")["tags"] == ["Keep"]

    def test_legacy_singular_tag_key_still_works(self, conn):
        # Backward compatibility: any stale client still posting the old
        # {"tag": "X", "mode": "add"} shape (pre chip-multiselect) keeps
        # working unchanged.
        _seed_task(conn, "t1", tags=[])
        asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1"], "tag": "Solo", "mode": "add"}),
            conn=conn,
        ))
        assert db.get_task(conn, "t1")["tags"] == ["Solo"]

    def test_missing_tags_and_tag_is_an_error(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(tasks_router.bulk_action(
            _json_request({"action": "tag", "uids": ["t1"], "mode": "add"}),
            conn=conn,
        ))
        assert resp.status_code == 400


class TestDirectCallsWithoutTagsLabelsStillWork:
    """Pre-existing tests/callers that call these router functions directly
    (bypassing FastAPI's real request parsing) without passing tags_labels
    at all must keep working -- Form([])'s default outside of real request
    handling is a FastAPI marker object, not an actual list, which
    _combine_tags defensively coerces back to []."""

    def test_create_task_without_tags_labels_kwarg(self, conn):
        tasks_router.create_task(
            title="Plain", description="", due_at="", status="active",
            tags="Legacy", recurrence="", conn=conn,
        )
        task = next(t for t in db.list_tasks(conn) if t["title"] == "Plain")
        assert task["tags"] == ["Legacy"]
