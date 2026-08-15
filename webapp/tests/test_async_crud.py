"""async-CRUD (features/async-crud.md) -- the no-full-page-reload mechanism
for task create/edit/complete/delete:

  * `GET /tasks/regions?region=table` renders the #tasks-body fragment
    shared with the full page (single source of truth), honoring the same
    query params as list_tasks so a mutation-triggered region refresh keeps
    the active filters/sort/page.
  * Every task mutation endpoint is dual-mode: its plain-HTML 303 Redirect
    by default (no-JS forms keep working), JSON when the request carries
    `X-Requested-With: fetch` (static/async_crud.js always sends it).
  * `GET /dashboard/widgets/{uid}` re-renders one plain widget's card so
    the dashboard can refresh just the task-affecting widgets.

The header-mode mutations are exercised by calling the router functions
directly with `x_requested_with="fetch"` -- the same direct-call convention
this suite uses everywhere (bypassing FastAPI's request parsing)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db
from src.routers import dashboard as dashboard_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/tasks", query_string=b"", headers=None):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": headers or [],
        }
    )


def _task(conn, uid, title=None, status="active", due_at=None, tags=None):
    db.upsert_task(
        conn,
        {
            "uid": uid,
            "title": title or uid,
            "description": "",
            "status": status,
            "due_at": due_at,
            "tags": tags or [],
            "created_at": _now(),
        },
    )


def _rows(html: str) -> set[str]:
    import re

    return set(re.findall(r'tr[^>]*data-uid="([^"]+)"', html))


class TestTasksRegionFragment:
    def test_region_table_renders_the_tasks_body_fragment(self, conn):
        _task(conn, "a1", "Alpha", due_at="2026-08-20")
        _task(conn, "a2", "Beta", status="done", due_at="2026-08-21")
        resp = tasks_router.tasks_regions(_request(), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'id="tasks-body"' in body
        assert "Alpha" in body and "Beta" in body
        assert _rows(body) == {"a1", "a2"}

    def test_region_table_matches_the_full_page_rows(self, conn):
        # The fragment must be the same single source of truth as the full
        # Table view -- same rows, same filters/sort/page honored.
        for i in range(5):
            _task(conn, f"t{i:03d}", due_at=f"2026-08-{i + 1:02d}")
        page = tasks_router.list_tasks(_request(), conn=conn)
        fragment = tasks_router.tasks_regions(_request(), conn=conn).body.decode()
        assert _rows(fragment) == {t["uid"] for t in page.context["open_tasks"]}
        assert "t001" in fragment

    def test_region_table_honors_filters_and_pagination(self, conn):
        for i in range(60):
            _task(conn, f"t{i:03d}", due_at=f"2026-08-{1 + (i % 28):02d}")
        _task(conn, "done1", status="done", due_at="2026-08-20")
        # Page 2, limit 10 -- completed tasks are never paginated, so the
        # fragment carries 10 open rows (page 2) plus done1 in the Completed
        # section below.
        resp = tasks_router.tasks_regions(_request(query_string=b"page=2&limit=10"), page=2, limit=10, conn=conn)
        body = resp.body.decode()
        rows = _rows(body)
        assert len(rows) == 11
        assert "done1" in rows
        assert len({u for u in rows if u != "done1"}) == 10

    def test_region_table_renders_pager_when_multiple_pages(self, conn):
        for i in range(25):
            _task(conn, f"t{i:03d}")
        resp = tasks_router.tasks_regions(_request(), limit=10, conn=conn)
        assert "task-pager-row" in resp.body.decode()

    def test_region_table_empty_state(self, conn):
        resp = tasks_router.tasks_regions(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="tasks-body"' in body
        assert "No tasks yet" in body

    def test_unknown_region_returns_json_400(self, conn):
        resp = tasks_router.tasks_regions(_request(), region="nope", conn=conn)
        assert resp.status_code == 400
        assert json.loads(resp.body)["error"]


class TestMutationDualMode:
    def test_create_with_fetch_header_returns_json_201(self, conn):
        resp = tasks_router.create_task(
            title="New", description="", due_at="", start_at="", status="active",
            tags="", recurrence="", x_requested_with="fetch", conn=conn,
        )
        assert resp.status_code == 201
        payload = json.loads(resp.body)
        assert payload["ok"] is True
        task = db.get_task(conn, payload["uid"])
        assert task is not None and task["title"] == "New"

    def test_create_without_fetch_header_keeps_redirect(self, conn):
        resp = tasks_router.create_task(
            title="New", description="", due_at="", status="active", tags="", recurrence="", conn=conn,
        )
        assert resp.status_code == 303
        assert len(db.list_tasks(conn)) == 1  # still created

    def test_update_with_fetch_header_returns_json(self, conn):
        _task(conn, "a1", "Old")
        resp = tasks_router.update_task(
            "a1", title="New", description="", due_at="", start_at="", status="active",
            tags="", recurrence="", x_requested_with="fetch", conn=conn,
        )
        assert resp.status_code == 200
        assert json.loads(resp.body)["ok"] is True
        assert db.get_task(conn, "a1")["title"] == "New"

    def test_complete_with_fetch_header_returns_json_and_flips_status(self, conn):
        _task(conn, "a1", "Do it")
        resp = tasks_router.complete_task("a1", x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
        assert json.loads(resp.body)["ok"] is True
        assert db.get_task(conn, "a1")["status"] == "done"

    def test_complete_without_fetch_header_keeps_redirect(self, conn):
        _task(conn, "a1", "Do it")
        resp = tasks_router.complete_task("a1", conn=conn)
        assert resp.status_code == 303
        assert db.get_task(conn, "a1")["status"] == "done"

    def test_delete_with_fetch_header_returns_json_and_removes(self, conn):
        _task(conn, "a1", "Gone")
        resp = tasks_router.delete_task("a1", x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
        assert json.loads(resp.body)["ok"] is True
        assert db.get_task(conn, "a1") is None

    def test_complete_recurring_still_writes_completion_history(self, conn):
        _task(conn, "a1", "Daily")
        db.upsert_task(conn, {**db.get_task(conn, "a1"), "recurrence": "FREQ=DAILY"})
        tasks_router.complete_task("a1", x_requested_with="fetch", conn=conn)
        assert len(db.list_task_completions(conn, "a1")) == 1

    def test_create_with_two_project_labels_errors_400_even_with_fetch_header(self, conn):
        db.upsert_label_config(conn, {"name": "P1", "is_project": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "P2", "is_project": 1, "created_at": _now()})
        with pytest.raises(HTTPException) as exc:
            tasks_router.create_task(
                title="Both", description="", due_at="", start_at="", status="active",
                tags="P1, P2", recurrence="", x_requested_with="fetch", conn=conn,
            )
        assert exc.value.status_code == 400

    def test_task_detail_delete_form_opt_into_cc_change(self, conn):
        # The detail modal's footer delete form must carry data-cc-change so
        # app.js's delete handler dispatches the event instead of reloading.
        _task(conn, "a1", "Do it")
        resp = tasks_router.task_detail("a1", _request("/tasks/a1"), conn=conn)
        body = resp.body.decode()
        assert f'action="/tasks/a1/delete"' in body
        assert 'data-cc-change="task"' in body


class TestWidgetCardRegion:
    def _seed_agenda(self, conn):
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        return next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))

    def test_renders_the_widget_card_with_task_marker(self, conn):
        ag = self._seed_agenda(conn)
        _task(conn, "a1", "Do it", due_at="2026-08-01")
        resp = dashboard_router.widget_card_region(_request("/dashboard"), ag["uid"], conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert f'id="widget-{ag["uid"]}"' in body
        assert 'data-widget-uses="tasks"' in body
        assert "Do it" in body

    def test_unknown_widget_404s(self, conn):
        with pytest.raises(HTTPException) as exc:
            dashboard_router.widget_card_region(_request("/dashboard"), "nope", conn=conn)
        assert exc.value.status_code == 404
