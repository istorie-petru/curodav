"""plans/ui-cleanup-2026-09.md item 14, slice 1 (2026-09-24): one frontend
habit shape (habit_view.habit_items), sourced from habit-labeled tasks --
the standalone Habit entity is gone. Regression guard for the gap that
motivated it: the Dashboard's Habit Check-in widget only read the entity
table, so a habit made through the UI's only creation path (a habit-
labeled task) never appeared there."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src import db, habit_view
from src.routers import dashboard as dashboard_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _habit(conn, uid, title, target=1, status="active", tags=("Habit",)):
    db.save_task_habit_settings(conn, "Habit")
    db.upsert_task(
        conn,
        {"uid": uid, "title": title, "description": "", "status": status, "tags": list(tags),
         "recurrence": "FREQ=DAILY", "target_per_day": target, "created_at": _now()},
    )


class TestHabitItems:
    def test_only_habit_labeled_active_tasks(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "h2", "Stretch", status="done")
        db.upsert_task(conn, {"uid": "t1", "title": "Plain", "description": "", "status": "active",
                              "tags": [], "created_at": _now()})
        assert [h["uid"] for h in habit_view.habit_items(conn)] == ["h1"]

    def test_shape_and_urls(self, conn):
        _habit(conn, "h1", "Water", target=8)
        today = date(2026, 9, 24)
        db.upsert_task_completion(conn, "h1", "2026-09-23", _now(), value=8)
        db.upsert_task_completion(conn, "h1", "2026-09-24", _now(), value=3)
        item = habit_view.habit_items(conn, today)[0]
        assert item["is_quantity"] is True
        assert (item["today_value"], item["next_value"], item["target"]) == (3, 4, 8)
        assert item["current_streak"] == 2
        assert item["recurrence_label"] == "Daily"
        assert item["toggle_url"] == "/tasks/h1/completion/2026-09-24/toggle"
        assert item["plus_url"] == "/tasks/h1/completions"
        assert item["detail_url"] == "/tasks/h1"


class TestCheckinWidget:
    def test_widget_lists_habit_tasks(self, conn):
        _habit(conn, "h1", "Read")
        data = dashboard_router._render_habit_checkin(conn, {})
        assert [r["uid"] for r in data["rows"]] == ["h1"]

    def test_widget_renders_task_completion_endpoints(self, conn):
        _habit(conn, "h1", "Read")
        _habit(conn, "h2", "Water", target=8)
        tpl = dashboard_router.templates.env.get_template("_widget_habit_checkin.html")
        html = tpl.render(data=dashboard_router._render_habit_checkin(conn, {}))
        today = date.today().isoformat()
        assert f'action="/tasks/h1/completion/{today}/toggle"' in html
        assert 'action="/tasks/h2/completions"' in html
        assert f'name="completion_date" value="{today}"' in html
        assert "/habits/" not in html


class TestHabitUrlsRedirect:
    @pytest.mark.parametrize("path", ["/habits", "/habits/abc", "/habits/new", "/habits/abc/edit"])
    def test_old_urls_redirect_to_tasks(self, path, tmp_path, monkeypatch):
        monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cache.sqlite"))
        from src.main import app

        resp = TestClient(app).get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"
