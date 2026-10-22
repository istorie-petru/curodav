"""The header bar's view switch: the lists each page family offers and the pages that carry them."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from src import db
from src.header_views import header_views
from src.routers import calendar as calendar_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/tasks/board"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


class TestHeaderViews:
    def test_tasks_offer_list_board_and_habits(self):
        views = header_views("tasks", "board")
        assert [v["label"] for v in views] == ["List", "Board", "Habits"]
        assert [v["key"] for v in views if v["active"]] == ["board"]

    def test_calendar_views_keep_the_label_filter(self):
        views = header_views("calendar", "plan", "Uni", "2026-10-22")
        urls = {v["key"]: v["url"] for v in views}
        assert urls["day"] == "/calendar/day/2026-10-22?label=Uni"
        assert urls["plan"] == "/calendar/week?label=Uni"

    def test_scope_views_skip_the_agenda_when_the_page_is_already_one(self):
        assert [v["key"] for v in header_views("scope", "overview", "/", agenda=False)] == ["overview", "board"]
        assert [v["key"] for v in header_views("scope", "overview", "/labels/Gym")] == ["overview", "agenda", "board"]

    def test_unknown_kind_has_no_views(self):
        assert header_views("settings", "x") == []


class TestPagesCarryTheirViews:
    def test_tasks_board_lists_open_tasks_by_status(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "Write", "description": "", "status": "in_progress", "tags": [],
                              "created_at": "2026-10-22T09:00:00+00:00"})
        body = tasks_router.board_view(_request(), conn=conn).body.decode()
        assert 'id="kanban-board"' in body and "Write" in body
        assert 'class="header-view active" href="/tasks/board"' in body
        assert 'class="header-add"' in body

    def test_planner_is_the_plan_view_of_calendar(self, conn):
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert 'class="header-view active" href="/calendar/week"' in body
        assert ">4 weeks<" in body and ">Day<" in body

    def test_the_sidebar_no_longer_has_new_search_planner_or_habits(self, conn):
        body = tasks_router.board_view(_request(), conn=conn).body.decode()
        sidebar = body[body.index('class="tabbar"'):body.index("</nav>", body.index('class="tabbar"'))]
        assert "sidebar-quick-add" not in sidebar and 'data-tab="search"' not in sidebar
        assert 'data-tab="calendar_week"' not in sidebar and 'data-tab="habits"' not in sidebar
