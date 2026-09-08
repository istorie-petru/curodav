"""2026-08-28 "major rework" session (item 3): the Tasks Table view's
grouping is now always on, fixed order -- Project (alphabetical, one group
per project label) -> Habits -> Unassigned -> Completed (most-recent-first,
always last). Every non-Completed group is due-date ascending. This
replaces the 1.5 slice's opt-in `?group_by=project` toggle entirely (see
this file's own pre-rework history in git log) -- `_group_tasks_by_project`
is gone, folded into `_build_task_groups`, which now also owns the
Habits/Unassigned/Completed groups."""

from __future__ import annotations

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


def _request(query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/tasks",
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _project(conn, name, start_date="2026-08-01", end_date="2026-09-01"):
    db.upsert_label_config(
        conn,
        {"name": name, "is_project": 1, "start_date": start_date, "end_date": end_date, "created_at": _now()},
    )


def _task(conn, uid, tags=None, status="active", due_at=None, title=None):
    db.upsert_task(
        conn,
        {
            "uid": uid, "title": title or uid, "description": "", "status": status,
            "tags": tags or [], "created_at": _now(), "due_at": due_at,
        },
    )


def _group(groups, kind, name=None):
    for g in groups:
        if g["kind"] == kind and (name is None or g["name"] == name):
            return g
    raise AssertionError(f"no group kind={kind} name={name} in {[ (g['kind'], g['name']) for g in groups ]}")


class TestFixedGroupOrder:
    def test_project_habits_unassigned_completed_in_that_order(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "loose1", tags=[])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        kinds = [g["kind"] for g in resp.context["groups"]]
        assert kinds == ["project", "habits", "unassigned", "completed"]

    def test_multiple_projects_stay_alphabetical_before_habits(self, conn):
        _project(conn, "banana")
        _project(conn, "Apple")
        _task(conn, "t1", tags=["banana"])
        _task(conn, "t2", tags=["Apple"])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        groups = resp.context["groups"]
        names = [g["name"] for g in groups]
        assert names[:2] == ["Apple", "banana"]
        assert names[2:] == ["Habits", "Unassigned", "Completed"]


class TestProjectGrouping:
    def test_clusters_open_tasks_under_their_project_label(self, conn):
        _project(conn, "Alpha")
        _project(conn, "Beta")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "a2", tags=["Alpha"])
        _task(conn, "b1", tags=["Beta"])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        groups = resp.context["groups"]
        assert {t["uid"] for t in _group(groups, "project", "Alpha")["tasks"]} == {"a1", "a2"}
        assert {t["uid"] for t in _group(groups, "project", "Beta")["tasks"]} == {"b1"}

    def test_task_with_no_project_label_lands_in_unassigned(self, conn):
        db.upsert_label_config(conn, {"name": "SomeSpace", "generate_space": 1, "created_at": _now()})
        _project(conn, "Alpha")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "loose1", tags=[])
        _task(conn, "loose2", tags=["SomeSpace"])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        unassigned = _group(resp.context["groups"], "unassigned")
        assert {t["uid"] for t in unassigned["tasks"]} == {"loose1", "loose2"}

    def test_named_groups_sorted_alphabetically_case_insensitive(self, conn):
        _project(conn, "banana")
        _project(conn, "Apple")
        _project(conn, "cherry")
        _task(conn, "t1", tags=["banana"])
        _task(conn, "t2", tags=["Apple"])
        _task(conn, "t3", tags=["cherry"])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        project_names = [g["name"] for g in resp.context["groups"] if g["kind"] == "project"]
        assert project_names == ["Apple", "banana", "cherry"]

    def test_group_is_due_date_ascending(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a_z", tags=["Alpha"], title="Zebra", due_at="2026-09-03")
        _task(conn, "a_a", tags=["Alpha"], title="Apple", due_at="2026-09-01")
        _task(conn, "a_m", tags=["Alpha"], title="Mango", due_at="2026-09-02")

        resp = tasks_router.list_tasks(_request(), conn=conn)
        alpha = _group(resp.context["groups"], "project", "Alpha")
        assert [t["uid"] for t in alpha["tasks"]] == ["a_a", "a_m", "a_z"]


class TestCompletedGroup:
    def test_completed_tasks_pulled_out_of_their_project_group(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a_open", tags=["Alpha"], status="active")
        _task(conn, "a_done", tags=["Alpha"], status="done")
        _task(conn, "loose_done", tags=[], status="archived")

        resp = tasks_router.list_tasks(_request(), conn=conn)
        groups = resp.context["groups"]
        alpha = _group(groups, "project", "Alpha")
        assert {t["uid"] for t in alpha["tasks"]} == {"a_open"}
        completed = _group(groups, "completed")
        assert {t["uid"] for t in completed["tasks"]} == {"a_done", "loose_done"}

    def test_completed_group_is_always_last(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a_done", tags=["Alpha"], status="done")

        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.context["groups"][-1]["kind"] == "completed"

    def test_completed_group_is_most_recent_first(self, conn):
        db.upsert_task(conn, {
            "uid": "old", "title": "old", "description": "", "status": "done",
            "tags": [], "created_at": _now(), "updated_at": "2026-01-01T00:00:00+00:00",
        })
        db.upsert_task(conn, {
            "uid": "new", "title": "new", "description": "", "status": "done",
            "tags": [], "created_at": _now(), "updated_at": "2026-06-01T00:00:00+00:00",
        })

        resp = tasks_router.list_tasks(_request(), conn=conn)
        completed = _group(resp.context["groups"], "completed")
        assert [t["uid"] for t in completed["tasks"]] == ["new", "old"]


class TestBuildTaskGroupsHelperDirect:
    def test_helper_matches_project_label_for(self, conn):
        _project(conn, "Solo")
        _task(conn, "t1", tags=["Solo"])
        _task(conn, "t2", tags=[])
        tasks = db.list_tasks(conn)
        groups = tasks_router._build_task_groups(conn, tasks, [])
        assert {t["uid"] for t in _group(groups, "project", "Solo")["tasks"]} == {"t1"}
        assert {t["uid"] for t in _group(groups, "unassigned")["tasks"]} == {"t2"}
