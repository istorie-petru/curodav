"""Command palette actions (plans/open.md § Command palette actions,
follow-up to the 1.2 Universal command surface): turning the picker overlay
from search-and-navigate into a real command surface. Covers the two new
endpoints (routers/search.py's `GET /api/labels` and
`POST /api/entities/{type}/{uid}/labels`) plus the `title` prefill param the
"Create task/event: '<query>'" rows need on `new_task_form`/`new_event_form`.

Completing/deleting a task/event/contact from the palette reuses the
existing `POST /{uid}/complete`/`/{uid}/delete` routes unchanged
(static/command_palette.js calls them directly) -- no new coverage needed
for those, they're already exercised by test_tasks.py/test_calendar.py/
test_contacts.py."""

from __future__ import annotations

import asyncio
import json as _json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import search as search_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, tags=None, **overrides):
    row = {"uid": uid, "title": uid, "description": "", "status": "active", "tags": tags or [], "created_at": _now()}
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _seed_event(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "start_at": "2026-08-10T09:00:00",
        "status": "active",
        "all_day": False,
        "tags": tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


def _seed_contact(conn, uid, tags=None, **overrides):
    row = {"uid": uid, "full_name": uid, "tags": tags or [], "created_at": _now()}
    row.update(overrides)
    db.upsert_contact(conn, row)
    return db.get_contact(conn, uid)


def _make_project(conn, name):
    db.upsert_label_config(
        conn, {"name": name, "is_project": 1, "start_date": None, "end_date": None, "created_at": _now()}
    )


def _seed_note(conn, uid, tags=None, **overrides):
    row = {"uid": uid, "content": uid, "tags": tags or [], "created_at": _now(), "updated_at": _now()}
    row.update(overrides)
    db.upsert_note(conn, row)
    return db.get_note(conn, uid)


def _json_request(path: str, payload: dict):
    req = Request({"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json")]})

    async def receive():
        return {"type": "http.request", "body": _json.dumps(payload).encode(), "more_body": False}

    req._receive = receive
    return req


class TestApiLabels:
    def test_lists_every_label_in_use(self, conn):
        _seed_task(conn, "t1", tags=["Work", "Home"])
        data = _json.loads(search_router.api_labels(conn=conn).body.decode())
        assert set(data["labels"]) == {"Work", "Home"}

    def test_q_filters_case_insensitively(self, conn):
        _seed_task(conn, "t1", tags=["Work", "Home"])
        data = _json.loads(search_router.api_labels(q="wo", conn=conn).body.decode())
        assert data["labels"] == ["Work"]

    def test_limit_caps_results(self, conn):
        _seed_task(conn, "t1", tags=["A", "B", "C"])
        data = _json.loads(search_router.api_labels(limit=2, conn=conn).body.decode())
        assert len(data["labels"]) == 2

    def test_no_labels_yet_returns_empty_list(self, conn):
        data = _json.loads(search_router.api_labels(conn=conn).body.decode())
        assert data["labels"] == []


class TestAddEntityLabel:
    def test_adds_a_label_to_a_task(self, conn):
        _seed_task(conn, "t1", tags=["Work"])
        resp = asyncio.run(
            search_router.add_entity_label("task", "t1", _json_request("/api/entities/task/t1/labels", {"label": "Urgent"}), conn=conn)
        )
        assert resp.status_code == 200
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["Urgent", "Work"]

    def test_adds_a_label_to_an_event(self, conn):
        _seed_event(conn, "e1", tags=[])
        resp = asyncio.run(
            search_router.add_entity_label("event", "e1", _json_request("/api/entities/event/e1/labels", {"label": "Trip"}), conn=conn)
        )
        assert resp.status_code == 200
        assert db.get_event(conn, "e1")["tags"] == ["Trip"]

    def test_adds_a_label_to_a_contact(self, conn):
        _seed_contact(conn, "c1", tags=[])
        resp = asyncio.run(
            search_router.add_entity_label(
                "contact", "c1", _json_request("/api/entities/contact/c1/labels", {"label": "Family"}), conn=conn
            )
        )
        assert resp.status_code == 200
        assert db.get_contact(conn, "c1")["tags"] == ["Family"]

    def test_adds_a_label_to_a_note(self, conn):
        # Notes (Quick Capture's !n, plans/quick-capture.md) get the same
        # Add label palette action as every other type.
        _seed_note(conn, "n1", tags=[])
        resp = asyncio.run(
            search_router.add_entity_label("note", "n1", _json_request("/api/entities/note/n1/labels", {"label": "Ideas"}), conn=conn)
        )
        assert resp.status_code == 200
        assert db.get_note(conn, "n1")["tags"] == ["Ideas"]

    def test_blank_label_is_rejected(self, conn):
        _seed_task(conn, "t1")
        resp = asyncio.run(
            search_router.add_entity_label("task", "t1", _json_request("/api/entities/task/t1/labels", {"label": "  "}), conn=conn)
        )
        assert resp.status_code == 400

    def test_unknown_uid_is_404(self, conn):
        resp = asyncio.run(
            search_router.add_entity_label("task", "nope", _json_request("/api/entities/task/nope/labels", {"label": "X"}), conn=conn)
        )
        assert resp.status_code == 404

    def test_unknown_entity_type_is_400(self, conn):
        resp = asyncio.run(
            search_router.add_entity_label(
                "widget", "w1", _json_request("/api/entities/widget/w1/labels", {"label": "X"}), conn=conn
            )
        )
        assert resp.status_code == 400

    def test_second_project_label_on_a_task_is_rejected(self, conn):
        # 1.5's single-project-per-task guard (db.MultipleProjectLabelsError)
        # applies here exactly like it does to the bulk "Add label" endpoint
        # -- the palette's own label-assign action is a fourth write path
        # onto the same task.tags column, not a bypass of the rule.
        _make_project(conn, "Alpha")
        _make_project(conn, "Beta")
        _seed_task(conn, "t1", tags=["Alpha"])
        resp = asyncio.run(
            search_router.add_entity_label("task", "t1", _json_request("/api/entities/task/t1/labels", {"label": "Beta"}), conn=conn)
        )
        assert resp.status_code == 400
        assert db.get_task(conn, "t1")["tags"] == ["Alpha"]


class TestCreateFromPaletteTitlePrefill:
    def test_new_task_form_prefills_title(self, conn):
        req = Request({"type": "http", "method": "GET", "path": "/tasks/new", "headers": []})
        body = tasks_router.new_task_form(req, title="Buy milk", conn=conn).body.decode()
        assert 'value="Buy milk"' in body

    def test_new_task_form_blank_title_is_still_blank(self, conn):
        req = Request({"type": "http", "method": "GET", "path": "/tasks/new", "headers": []})
        body = tasks_router.new_task_form(req, conn=conn).body.decode()
        assert 'name="title" required value=""' in body

    def test_new_event_form_prefills_title(self, conn):
        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        body = calendar_router.new_event_form(req, title="Dentist", conn=conn).body.decode()
        assert 'value="Dentist"' in body
