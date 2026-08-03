"""Data-layer tests for dashboard widgets (Phase 8): CRUD, config
round-trip, ordering, and the swap-based reorder primitive."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_widget(conn, type="today_agenda", **kwargs):
    row = {"uid": f"w-{type}-{kwargs.get('title', '')}", "type": type, "title": None, "config": {}, "position": 0, "created_at": _now()}
    row.update(kwargs)
    db.upsert_dashboard_widget(conn, row)
    return row["uid"]


class TestCRUD:
    def test_create_and_get(self, conn):
        uid = _make_widget(conn, "today_agenda", config={"project_uid": "p1", "tags": ["uni"]})
        w = db.get_dashboard_widget(conn, uid)
        assert w["type"] == "today_agenda"
        assert w["config"] == {"project_uid": "p1", "tags": ["uni"]}

    def test_list_ordered_by_position(self, conn):
        _make_widget(conn, "b", title="b", position=1)
        _make_widget(conn, "a", title="a", position=0)
        widgets = db.list_dashboard_widgets(conn)
        assert [w["type"] for w in widgets] == ["a", "b"]

    def test_next_position_increments(self, conn):
        assert db.next_dashboard_widget_position(conn) == 0
        _make_widget(conn, "a", position=0)
        assert db.next_dashboard_widget_position(conn) == 1

    def test_delete(self, conn):
        uid = _make_widget(conn)
        db.delete_dashboard_widget(conn, uid)
        assert db.get_dashboard_widget(conn, uid) is None

    def test_edit_preserves_uid_updates_config(self, conn):
        uid = _make_widget(conn, config={"tags": []})
        w = db.get_dashboard_widget(conn, uid)
        w["config"] = {"tags": ["urgent"]}
        db.upsert_dashboard_widget(conn, w)
        assert db.get_dashboard_widget(conn, uid)["config"] == {"tags": ["urgent"]}


class TestReorder:
    def test_swap_positions(self, conn):
        a = _make_widget(conn, "a", title="a", position=0)
        b = _make_widget(conn, "b", title="b", position=1)
        db.swap_dashboard_widget_positions(conn, a, b)
        widgets = db.list_dashboard_widgets(conn)
        assert [w["uid"] for w in widgets] == [b, a]

    def test_swap_with_missing_widget_is_a_noop(self, conn):
        a = _make_widget(conn, "a", position=0)
        db.swap_dashboard_widget_positions(conn, a, "does-not-exist")  # must not raise
        assert db.get_dashboard_widget(conn, a)["position"] == 0
