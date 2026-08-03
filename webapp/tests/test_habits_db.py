"""Data-layer tests for habit tracking (Phase 6): schema, CRUD,
archive/delete cascade, entry upsert/toggle, and the date->value lookup
the heatmap/streak builders read from."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_habit(conn, name="Read", **kwargs):
    now = _now()
    row = {"uid": f"habit-{name.lower()}", "name": name, "created_at": now, "updated_at": now}
    row.update(kwargs)
    db.upsert_habit(conn, row)
    return row["uid"]


class TestSchema:
    def test_tables_exist(self, conn):
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"habits", "habit_entries"} <= tables


class TestHabitCRUD:
    def test_create_defaults(self, conn):
        uid = _make_habit(conn, "Meditate")
        h = db.get_habit(conn, uid)
        assert h["name"] == "Meditate"
        assert h["color"] == "blue"
        assert h["target_per_day"] == 1
        assert h["tags"] == []
        assert h["archived_at"] is None

    def test_create_with_tags_and_project(self, conn):
        uid = _make_habit(conn, "Study", tags=["uni"], project_uid="p1", target_per_day=2, color="purple")
        h = db.get_habit(conn, uid)
        assert h["tags"] == ["uni"]
        assert h["project_uid"] == "p1"
        assert h["target_per_day"] == 2
        assert h["color"] == "purple"

    def test_list_habits_excludes_archived_by_default(self, conn):
        a = _make_habit(conn, "A")
        b = _make_habit(conn, "B")
        db.archive_habit(conn, b, _now())
        assert {h["uid"] for h in db.list_habits(conn)} == {a}
        assert {h["uid"] for h in db.list_habits(conn, include_archived=True)} == {a, b}

    def test_archive_then_unarchive(self, conn):
        uid = _make_habit(conn, "A")
        db.archive_habit(conn, uid, _now())
        assert db.get_habit(conn, uid)["archived_at"] is not None
        db.unarchive_habit(conn, uid)
        assert db.get_habit(conn, uid)["archived_at"] is None

    def test_list_habits_filtered_by_project(self, conn):
        a = _make_habit(conn, "A", project_uid="p1")
        _make_habit(conn, "B", project_uid="p2")
        result = db.list_habits(conn, project_uid="p1")
        assert {h["uid"] for h in result} == {a}

    def test_delete_cascades_entries(self, conn):
        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 1, None, _now())
        db.delete_habit(conn, uid)
        assert db.get_habit(conn, uid) is None
        assert db.list_habit_entries(conn, uid) == []


class TestHabitEntries:
    def test_upsert_creates_then_updates_same_row(self, conn):
        uid = _make_habit(conn, "Water", target_per_day=8)
        db.upsert_habit_entry(conn, uid, "2026-08-01", 3, "3 glasses", _now())
        entry = db.get_habit_entry(conn, uid, "2026-08-01")
        assert entry["value"] == 3
        assert entry["note"] == "3 glasses"
        first_uid = entry["uid"]

        db.upsert_habit_entry(conn, uid, "2026-08-01", 8, "all done", _now())
        entry2 = db.get_habit_entry(conn, uid, "2026-08-01")
        assert entry2["value"] == 8
        assert entry2["uid"] == first_uid  # same row, not a duplicate
        assert len(db.list_habit_entries(conn, uid)) == 1

    def test_delete_entry(self, conn):
        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 1, None, _now())
        db.delete_habit_entry(conn, uid, "2026-08-01")
        assert db.get_habit_entry(conn, uid, "2026-08-01") is None

    def test_toggle_creates_then_removes(self, conn):
        uid = _make_habit(conn, "A")
        now_logged = db.toggle_habit_entry(conn, uid, "2026-08-01", _now())
        assert now_logged is True
        assert db.get_habit_entry(conn, uid, "2026-08-01")["value"] == 1

        now_logged2 = db.toggle_habit_entry(conn, uid, "2026-08-01", _now())
        assert now_logged2 is False
        assert db.get_habit_entry(conn, uid, "2026-08-01") is None

    def test_list_entries_date_range_filter(self, conn):
        uid = _make_habit(conn, "A")
        for d in ("2026-07-28", "2026-07-30", "2026-08-02"):
            db.upsert_habit_entry(conn, uid, d, 1, None, _now())
        in_range = db.list_habit_entries(conn, uid, start="2026-07-29", end="2026-08-01")
        assert [e["date"] for e in in_range] == ["2026-07-30"]

    def test_entries_by_date_lookup(self, conn):
        uid = _make_habit(conn, "A")
        db.upsert_habit_entry(conn, uid, "2026-08-01", 5, None, _now())
        db.upsert_habit_entry(conn, uid, "2026-08-02", 0, None, _now())
        lookup = db.habit_entries_by_date(conn, uid)
        assert lookup == {"2026-08-01": 5, "2026-08-02": 0}

    def test_backfill_past_date(self, conn):
        uid = _make_habit(conn, "A")
        past = (datetime.now(timezone.utc) - timedelta(days=100)).date().isoformat()
        db.upsert_habit_entry(conn, uid, past, 1, "backfilled", _now())
        assert db.get_habit_entry(conn, uid, past)["value"] == 1
