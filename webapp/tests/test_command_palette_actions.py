"""Command palette actions (plans/open.md § Command palette actions,
follow-up to the 1.2 Universal command surface): turning the picker overlay
from search-and-navigate into a real command surface. Covers the `title`
prefill param the "Create task/event: '<query>'" rows need on
`new_task_form`/`new_event_form`.

Completing/deleting a task/event/contact from the palette reuses the
existing `POST /{uid}/complete`/`/{uid}/delete` routes unchanged
(static/command_palette.js calls them directly) -- no new coverage needed
for those, they're already exercised by test_tasks.py/test_calendar.py/
test_contacts.py.

The palette's own label-assign sub-mode ("Add label" per-row action,
`GET /api/labels`/`POST /api/entities/{type}/{uid}/labels`) was removed
2026-09-24 (direct request, "search window simplification": "remove the
Add label and Delete buttons from the search window") along with the two
endpoints that existed only to serve it -- this file's own TestApiLabels/
TestAddEntityLabel classes went with them."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


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
