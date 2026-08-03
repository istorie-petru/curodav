"""Data-layer tests for custom databases (Phase 7): schema, database/
column/row CRUD, cascade delete, and the single-cell write path."""

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


def _make_database(conn, name="Grades", **kwargs):
    now = _now()
    row = {"uid": f"db-{name.lower()}", "name": name, "created_at": now, "updated_at": now}
    row.update(kwargs)
    db.upsert_database(conn, row)
    return row["uid"]


class TestSchema:
    def test_tables_exist(self, conn):
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"databases", "database_columns", "database_rows"} <= tables


class TestDatabaseCRUD:
    def test_create_defaults(self, conn):
        uid = _make_database(conn)
        d = db.get_database(conn, uid)
        assert d["name"] == "Grades"
        assert d["color"] == "blue"
        assert d["tags"] == []
        assert d["archived_at"] is None

    def test_list_excludes_archived_by_default(self, conn):
        a = _make_database(conn, "A")
        b = _make_database(conn, "B")
        db.archive_database(conn, b, _now())
        assert {d["uid"] for d in db.list_databases(conn)} == {a}
        assert {d["uid"] for d in db.list_databases(conn, include_archived=True)} == {a, b}

    def test_archive_then_unarchive(self, conn):
        uid = _make_database(conn)
        db.archive_database(conn, uid, _now())
        assert db.get_database(conn, uid)["archived_at"] is not None
        db.unarchive_database(conn, uid)
        assert db.get_database(conn, uid)["archived_at"] is None

    def test_list_filtered_by_project(self, conn):
        a = _make_database(conn, "A", project_uid="p1")
        _make_database(conn, "B", project_uid="p2")
        assert {d["uid"] for d in db.list_databases(conn, project_uid="p1")} == {a}

    def test_delete_cascades_columns_and_rows(self, conn):
        uid = _make_database(conn)
        db.upsert_database_column(conn, {"uid": "c1", "database_uid": uid, "name": "Grade", "type": "number", "position": 0, "created_at": _now()})
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {"c1": 90}, "position": 0, "created_at": _now(), "updated_at": _now()})
        db.delete_database(conn, uid)
        assert db.get_database(conn, uid) is None
        assert db.list_database_columns(conn, uid) == []
        assert db.list_database_rows(conn, uid) == []


class TestColumns:
    def test_create_and_list_ordered_by_position(self, conn):
        uid = _make_database(conn)
        db.upsert_database_column(conn, {"uid": "c2", "database_uid": uid, "name": "B", "type": "text", "position": 1, "created_at": _now()})
        db.upsert_database_column(conn, {"uid": "c1", "database_uid": uid, "name": "A", "type": "text", "position": 0, "created_at": _now()})
        cols = db.list_database_columns(conn, uid)
        assert [c["name"] for c in cols] == ["A", "B"]

    def test_select_options_round_trip(self, conn):
        uid = _make_database(conn)
        db.upsert_database_column(conn, {
            "uid": "c1", "database_uid": uid, "name": "Status", "type": "select",
            "options": ["todo", "done"], "position": 0, "created_at": _now(),
        })
        col = db.get_database_column(conn, "c1")
        assert col["options"] == ["todo", "done"]

    def test_formula_and_summary_formula_stored(self, conn):
        uid = _make_database(conn)
        db.upsert_database_column(conn, {
            "uid": "c1", "database_uid": uid, "name": "Total", "type": "formula",
            "formula": "grade * weight", "summary_formula": "WEIGHTAVG(grade, weight)",
            "position": 0, "created_at": _now(),
        })
        col = db.get_database_column(conn, "c1")
        assert col["formula"] == "grade * weight"
        assert col["summary_formula"] == "WEIGHTAVG(grade, weight)"

    def test_next_column_position_increments(self, conn):
        uid = _make_database(conn)
        assert db.next_column_position(conn, uid) == 0
        db.upsert_database_column(conn, {"uid": "c1", "database_uid": uid, "name": "A", "type": "text", "position": 0, "created_at": _now()})
        assert db.next_column_position(conn, uid) == 1

    def test_delete_column(self, conn):
        uid = _make_database(conn)
        db.upsert_database_column(conn, {"uid": "c1", "database_uid": uid, "name": "A", "type": "text", "position": 0, "created_at": _now()})
        db.delete_database_column(conn, "c1")
        assert db.list_database_columns(conn, uid) == []


class TestRows:
    def test_create_and_get(self, conn):
        uid = _make_database(conn)
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {"c1": "90"}, "position": 0, "created_at": _now(), "updated_at": _now()})
        row = db.get_database_row(conn, "r1")
        assert row["values"] == {"c1": "90"}

    def test_list_ordered_by_position(self, conn):
        uid = _make_database(conn)
        db.upsert_database_row(conn, {"uid": "r2", "database_uid": uid, "values": {}, "position": 1, "created_at": _now(), "updated_at": _now()})
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {}, "position": 0, "created_at": _now(), "updated_at": _now()})
        rows = db.list_database_rows(conn, uid)
        assert [r["uid"] for r in rows] == ["r1", "r2"]

    def test_next_row_position_increments(self, conn):
        uid = _make_database(conn)
        assert db.next_row_position(conn, uid) == 0
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {}, "position": 0, "created_at": _now(), "updated_at": _now()})
        assert db.next_row_position(conn, uid) == 1

    def test_delete_row(self, conn):
        uid = _make_database(conn)
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {}, "position": 0, "created_at": _now(), "updated_at": _now()})
        db.delete_database_row(conn, "r1")
        assert db.get_database_row(conn, "r1") is None

    def test_set_database_row_value_updates_one_key_preserves_others(self, conn):
        uid = _make_database(conn)
        db.upsert_database_row(conn, {"uid": "r1", "database_uid": uid, "values": {"c1": "90", "c2": "A"}, "position": 0, "created_at": _now(), "updated_at": _now()})
        db.set_database_row_value(conn, "r1", "c1", "95", _now())
        row = db.get_database_row(conn, "r1")
        assert row["values"] == {"c1": "95", "c2": "A"}

    def test_set_database_row_value_on_missing_row_is_a_noop(self, conn):
        db.set_database_row_value(conn, "does-not-exist", "c1", "1", _now())  # must not raise
