"""1.9 slice ("Pagination / collapsible sections", Phase B of webapp
usability -- see plans/open.md § Webapp usability + DAVx5 mobile hosting,
plans/roadmap.md's 1.9 row): `GET /tasks?page=&limit=` paginates the Table
view's Open section (`routers/tasks.py::list_tasks`). Covers: default
behavior is unchanged (no params == page 1, everything that fits), slicing
is correct across pages, out-of-range/invalid page and limit values are
clamped rather than erroring, completed tasks are never paginated,
pagination composes with existing filters/sort, and grouped mode
(`group_by=project`) disables pagination entirely (documented scope cut)."""

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


def _many_tasks(conn, n, prefix="t", **kw):
    for i in range(n):
        _task(conn, f"{prefix}{i:03d}", **kw)


class TestDefaultUnchanged:
    def test_no_params_is_page_one_paginated(self, conn):
        _many_tasks(conn, 5)
        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["page"] == 1
        assert resp.context["paginated"] is True
        assert resp.context["open_total"] == 5
        assert resp.context["total_pages"] == 1
        assert {t["uid"] for t in resp.context["open_tasks"]} == {f"t{i:03d}" for i in range(5)}

    def test_default_limit_is_fifty(self, conn):
        _many_tasks(conn, 60)
        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.context["limit"] == 50
        assert resp.context["total_pages"] == 2
        assert len(resp.context["open_tasks"]) == 50


class TestSlicing:
    def test_second_page_gets_remainder(self, conn):
        _many_tasks(conn, 60)
        resp = tasks_router.list_tasks(_request(), page=2, limit=50, conn=conn)
        assert len(resp.context["open_tasks"]) == 10

    def test_pages_partition_all_tasks_with_no_overlap(self, conn):
        _many_tasks(conn, 25)
        page1 = tasks_router.list_tasks(_request(), page=1, limit=10, conn=conn)
        page2 = tasks_router.list_tasks(_request(), page=2, limit=10, conn=conn)
        page3 = tasks_router.list_tasks(_request(), page=3, limit=10, conn=conn)
        uids1 = {t["uid"] for t in page1.context["open_tasks"]}
        uids2 = {t["uid"] for t in page2.context["open_tasks"]}
        uids3 = {t["uid"] for t in page3.context["open_tasks"]}
        assert len(uids1) == 10 and len(uids2) == 10 and len(uids3) == 5
        assert uids1 | uids2 | uids3 == {f"t{i:03d}" for i in range(25)}
        assert not (uids1 & uids2) and not (uids2 & uids3) and not (uids1 & uids3)


class TestClamping:
    def test_page_beyond_last_clamps_to_last_page(self, conn):
        _many_tasks(conn, 5)
        resp = tasks_router.list_tasks(_request(), page=999, limit=2, conn=conn)
        assert resp.context["page"] == 3  # ceil(5/2)
        assert len(resp.context["open_tasks"]) == 1

    def test_page_zero_or_negative_clamps_to_one(self, conn):
        _many_tasks(conn, 3)
        resp = tasks_router.list_tasks(_request(), page=0, limit=10, conn=conn)
        assert resp.context["page"] == 1
        resp = tasks_router.list_tasks(_request(), page=-5, limit=10, conn=conn)
        assert resp.context["page"] == 1

    def test_limit_below_floor_clamps_up(self, conn):
        _many_tasks(conn, 3)
        resp = tasks_router.list_tasks(_request(), limit=0, conn=conn)
        assert resp.context["limit"] == 1
        resp = tasks_router.list_tasks(_request(), limit=-5, conn=conn)
        assert resp.context["limit"] == 1

    def test_limit_above_ceiling_clamps_down(self, conn):
        _many_tasks(conn, 3)
        resp = tasks_router.list_tasks(_request(), limit=100000, conn=conn)
        assert resp.context["limit"] == 200

    def test_empty_list_is_one_total_page_not_zero(self, conn):
        resp = tasks_router.list_tasks(_request(), conn=conn)
        assert resp.context["total_pages"] == 1
        assert resp.context["open_total"] == 0


class TestCompletedNeverPaginated:
    def test_completed_tasks_all_present_regardless_of_page(self, conn):
        _many_tasks(conn, 5, status="active")
        _many_tasks(conn, 30, prefix="done", status="done")
        resp = tasks_router.list_tasks(_request(), page=1, limit=2, conn=conn)
        assert len(resp.context["open_tasks"]) == 2
        assert len(resp.context["completed_tasks"]) == 30


class TestComposesWithFiltersAndSort:
    def test_pagination_applies_after_filter_and_sort(self, conn):
        _task(conn, "hi1", title="alpha", status="active")
        _task(conn, "hi2", title="beta", status="active")
        _task(conn, "hi3", title="gamma", status="active")
        _task(conn, "other", title="delta", status="waiting")

        resp = tasks_router.list_tasks(
            _request(), status_filter="active", sort="title", dir="asc", page=1, limit=2, conn=conn
        )
        titles = [t["title"] for t in resp.context["open_tasks"]]
        assert titles == ["alpha", "beta"]
        assert resp.context["open_total"] == 3
        assert resp.context["total_pages"] == 2


class TestGroupedModeDisablesPagination:
    def test_group_by_project_ignores_page_and_limit(self, conn):
        _project(conn, "Alpha")
        _many_tasks(conn, 5, prefix="a", tags=["Alpha"])

        resp = tasks_router.list_tasks(_request(), group_by="project", page=1, limit=2, conn=conn)
        assert resp.context["paginated"] is False
        assert resp.context["page"] == 1
        assert resp.context["total_pages"] == 1
        groups = resp.context["open_groups"]
        assert sum(len(g["tasks"]) for g in groups) == 5


class TestWorkHoursOnlyAttachedToRenderedRows:
    def test_hours_present_on_paged_open_and_all_completed(self, conn):
        _many_tasks(conn, 5, status="active")
        _task(conn, "done1", status="done")
        resp = tasks_router.list_tasks(_request(), page=1, limit=2, conn=conn)
        for t in resp.context["open_tasks"]:
            assert "work_hours" in t
        for t in resp.context["completed_tasks"]:
            assert "work_hours" in t
