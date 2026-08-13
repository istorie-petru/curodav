"""1.5 slice ("Tasks page as a table groupable by project", see
plans/open-priority.md § Task model / plans/roadmap.md's 1.5 row):
`GET /tasks?group_by=project` (`routers/tasks.py::list_tasks`,
`_group_tasks_by_project`). Covers: default (no `group_by`) is unchanged,
grouping clusters correctly with a "No project" bucket, completed tasks
still appear (grouped) below open ones, existing filters combine with
grouping, and sort order is preserved within each group."""

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


class TestDefaultUngroupedUnchanged:
    def test_no_group_by_param_behaves_exactly_as_before(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "b1", tags=[])

        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["group_by"] == "none"
        assert resp.context["open_groups"] is None
        assert resp.context["completed_groups"] is None
        assert {t["uid"] for t in resp.context["open_tasks"]} == {"a1", "b1"}

    def test_explicit_group_by_none_same_as_default(self, conn):
        _task(conn, "a1")
        resp = tasks_router.list_tasks(_request(), group_by="none", conn=conn)
        assert resp.context["open_groups"] is None


class TestGroupByProject:
    def test_clusters_tasks_under_their_project_label(self, conn):
        _project(conn, "Alpha")
        _project(conn, "Beta")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "a2", tags=["Alpha"])
        _task(conn, "b1", tags=["Beta"])

        resp = tasks_router.list_tasks(_request(), group_by="project", conn=conn)
        groups = resp.context["open_groups"]
        by_name = {g["name"]: {t["uid"] for t in g["tasks"]} for g in groups}
        assert by_name == {"Alpha": {"a1", "a2"}, "Beta": {"b1"}}

    def test_no_project_bucket_for_tasks_without_a_project_label(self, conn):
        # A plain Space label (generate_space=1) is explicitly *not* the
        # pre-1.3 "course/list label" fallback project_label_for otherwise
        # treats as a project when nothing is_project=1 -- see
        # db.project_label_for's own docstring -- so tagging a task with
        # one keeps it in the "No project" bucket, same as no label at all.
        db.upsert_label_config(conn, {"name": "SomeSpace", "generate_space": 1, "created_at": _now()})
        _project(conn, "Alpha")
        _task(conn, "a1", tags=["Alpha"])
        _task(conn, "loose1", tags=[])
        _task(conn, "loose2", tags=["SomeSpace"])

        resp = tasks_router.list_tasks(_request(), group_by="project", conn=conn)
        groups = resp.context["open_groups"]
        no_project = [g for g in groups if g["name"] is None]
        assert len(no_project) == 1
        assert {t["uid"] for t in no_project[0]["tasks"]} == {"loose1", "loose2"}

    def test_no_project_bucket_sorted_last(self, conn):
        _project(conn, "Zeta")
        _task(conn, "z1", tags=["Zeta"])
        _task(conn, "loose1", tags=[])

        resp = tasks_router.list_tasks(_request(), group_by="project", conn=conn)
        names = [g["name"] for g in resp.context["open_groups"]]
        assert names == ["Zeta", None]

    def test_named_groups_sorted_alphabetically_case_insensitive(self, conn):
        _project(conn, "banana")
        _project(conn, "Apple")
        _project(conn, "cherry")
        _task(conn, "t1", tags=["banana"])
        _task(conn, "t2", tags=["Apple"])
        _task(conn, "t3", tags=["cherry"])

        resp = tasks_router.list_tasks(_request(), group_by="project", conn=conn)
        names = [g["name"] for g in resp.context["open_groups"]]
        assert names == ["Apple", "banana", "cherry"]

    def test_completed_tasks_still_appear_grouped_below_open(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a_open", tags=["Alpha"], status="active")
        _task(conn, "a_done", tags=["Alpha"], status="done")
        _task(conn, "loose_done", tags=[], status="archived")

        resp = tasks_router.list_tasks(_request(), group_by="project", conn=conn)
        open_groups = resp.context["open_groups"]
        completed_groups = resp.context["completed_groups"]
        assert {t["uid"] for g in open_groups for t in g["tasks"]} == {"a_open"}
        completed_by_name = {g["name"]: {t["uid"] for t in g["tasks"]} for g in completed_groups}
        assert completed_by_name == {"Alpha": {"a_done"}, None: {"loose_done"}}

    def test_existing_filters_combine_with_grouping(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a1", tags=["Alpha"], status="active")
        _task(conn, "a2", tags=["Alpha"], status="waiting")
        _task(conn, "loose1", tags=[], status="active")

        resp = tasks_router.list_tasks(_request(), group_by="project", status_filter="waiting", conn=conn)
        groups = resp.context["open_groups"]
        all_uids = {t["uid"] for g in groups for t in g["tasks"]}
        assert all_uids == {"a2"}

    def test_sort_order_preserved_within_each_group(self, conn):
        _project(conn, "Alpha")
        _task(conn, "a_z", tags=["Alpha"], title="Zebra")
        _task(conn, "a_a", tags=["Alpha"], title="Apple")
        _task(conn, "a_m", tags=["Alpha"], title="Mango")

        resp = tasks_router.list_tasks(_request(), group_by="project", sort="title", dir="asc", conn=conn)
        groups = resp.context["open_groups"]
        alpha = next(g for g in groups if g["name"] == "Alpha")
        assert [t["uid"] for t in alpha["tasks"]] == ["a_a", "a_m", "a_z"]

        resp_desc = tasks_router.list_tasks(_request(), group_by="project", sort="title", dir="desc", conn=conn)
        alpha_desc = next(g for g in resp_desc.context["open_groups"] if g["name"] == "Alpha")
        assert [t["uid"] for t in alpha_desc["tasks"]] == ["a_z", "a_m", "a_a"]


class TestGroupByHelperDirect:
    def test_helper_used_by_route_matches_project_label_for(self, conn):
        _project(conn, "Solo")
        _task(conn, "t1", tags=["Solo"])
        _task(conn, "t2", tags=[])
        tasks = db.list_tasks(conn)
        groups = tasks_router._group_tasks_by_project(conn, tasks)
        by_name = {g["name"]: {t["uid"] for t in g["tasks"]} for g in groups}
        assert by_name == {"Solo": {"t1"}, None: {"t2"}}
