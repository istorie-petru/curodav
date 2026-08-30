"""GET /projects/{name} -- the real project page rebuilt 2026-08-30 (see
routers/projects.py's module docstring): a Kanban board of every task
carrying the project's label (columns = status), with an upcoming-events
card above it. Replaces the 2026-08-15..2026-08-30 redirect stub;
plans/STATE.md backlog item 9 ("Projects page -- view-like, not
dashboard-like").

Direct-call pattern (bare `Request({...})`, no ASGI app) follows
test_phase2_labels.py's own TestGeneratedSpacePage -- TemplateResponse
exposes its render context via `.context`, so assertions read the same
data the template would."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/projects/Trip"):
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


def _promote(conn, name="Trip", start="2026-01-01", end="2026-12-31"):
    db.upsert_label_config(
        conn, {"name": name, "is_project": 1, "start_date": start, "end_date": end, "created_at": _now()}
    )


def _task(conn, uid, tags, status="active", due_at=None):
    db.upsert_task(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": status, "tags": tags, "created_at": _now(), "due_at": due_at},
    )


def _event(conn, uid, tags, start_at):
    db.upsert_event(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": "active", "all_day": 0, "tags": tags,
         "start_at": start_at, "created_at": _now()},
    )


class TestNotAProjectRedirects:
    def test_plain_label_redirects_to_its_label_page(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        resp = projects_router.project_detail("Plain", _request("/projects/Plain"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Plain"

    def test_unknown_label_redirects_too(self, conn):
        resp = projects_router.project_detail("Ghost", _request("/projects/Ghost"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Ghost"

    def test_demoted_project_redirects(self, conn):
        _promote(conn, "Trip")
        projects_router.demote("Trip", conn=conn)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Trip"


class TestKanbanBoard:
    def test_renders_a_project_with_no_tasks(self, conn):
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["project"]["name"] == "Trip"
        assert resp.context["board_statuses"] == ["active", "in_progress", "waiting", "done"]
        assert all(resp.context["columns"][s] == [] for s in resp.context["board_statuses"])

    def test_tasks_bucket_by_status(self, conn):
        _promote(conn, "Trip")
        _task(conn, "t1", ["Trip"], status="active")
        _task(conn, "t2", ["Trip"], status="in_progress")
        _task(conn, "t3", ["Trip"], status="done")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        columns = resp.context["columns"]
        assert [t["uid"] for t in columns["active"]] == ["t1"]
        assert [t["uid"] for t in columns["in_progress"]] == ["t2"]
        assert [t["uid"] for t in columns["done"]] == ["t3"]

    def test_archived_tasks_are_excluded_from_the_board(self, conn):
        _promote(conn, "Trip")
        _task(conn, "t1", ["Trip"], status="archived")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert "archived" not in resp.context["board_statuses"]
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert "t1" not in all_uids

    def test_tasks_from_other_projects_are_excluded(self, conn):
        _promote(conn, "Trip")
        _promote(conn, "Other", start="2026-01-01", end="2026-12-31")
        _task(conn, "t1", ["Trip"], status="active")
        _task(conn, "t2", ["Other"], status="active")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"t1"}

    def test_habit_tagged_tasks_are_excluded(self, conn):
        # list_tasks_sharing_labels excludes the configured habit label,
        # same exclusion the "link an existing task" pool already applies
        # -- a habit is never a Kanban card.
        _promote(conn, "Trip")
        habit_label = db.get_task_habit_settings(conn)["habit_label"]
        _task(conn, "h1", ["Trip", habit_label], status="active")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert "h1" not in all_uids


class TestUpcomingEventsCard:
    def test_no_events_renders_empty(self, conn):
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["events"] == []

    def test_only_future_events_tagged_with_the_project_show(self, conn):
        _promote(conn, "Trip")
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        _event(conn, "e_future", ["Trip"], future)
        _event(conn, "e_past", ["Trip"], past)
        _event(conn, "e_other_project", ["Other"], future)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [e["uid"] for e in resp.context["events"]] == ["e_future"]

    def test_events_are_sorted_soonest_first(self, conn):
        _promote(conn, "Trip")
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        _event(conn, "e_later", ["Trip"], later)
        _event(conn, "e_soon", ["Trip"], soon)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [e["uid"] for e in resp.context["events"]] == ["e_soon", "e_later"]

    def test_capped_at_eight(self, conn):
        _promote(conn, "Trip")
        for i in range(10):
            when = (datetime.now(timezone.utc) + timedelta(days=i + 1)).isoformat()
            _event(conn, f"e{i}", ["Trip"], when)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert len(resp.context["events"]) == 8
