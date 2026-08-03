"""Tests for routers/databases.py: CRUD, column management (including
reordering), row/cell editing, and -- the part that actually matters --
that formula and summary-formula columns are correctly computed per
request from live data, never stored. No bridge/Radicale dependency;
databases are entirely local."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import databases as databases_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_database(conn, name="Test"):
    databases_router.create_database(name=name, description="", color="blue", icon="", tags="", project_uid="", conn=conn)
    return next(d for d in db.list_databases(conn) if d["name"] == name)["uid"]


class TestCreateEditDatabase:
    def test_create_seeds_one_default_column(self, conn):
        uid = _make_database(conn, "Grades")
        cols = db.list_database_columns(conn, uid)
        assert len(cols) == 1
        assert cols[0]["name"] == "Name"

    def test_create_registers_tags(self, conn):
        databases_router.create_database(name="Grades", description="", color="purple", icon="", tags="school, grades", project_uid="", conn=conn)
        assert db.get_tag_by_name(conn, "school") is not None
        assert db.get_tag_by_name(conn, "grades") is not None

    def test_blank_name_is_a_noop(self, conn):
        databases_router.create_database(name="  ", description="", color="blue", icon="", tags="", project_uid="", conn=conn)
        assert db.list_databases(conn) == []

    def test_edit_updates_fields(self, conn):
        uid = _make_database(conn, "Grades")
        databases_router.edit_database(uid, name="Renamed", description="desc", color="green", icon="📊", tags="", project_uid="", conn=conn)
        d = db.get_database(conn, uid)
        assert d["name"] == "Renamed"
        assert d["description"] == "desc"
        assert d["color"] == "green"


class TestArchiveDelete:
    def test_archive_hides_from_list(self, conn):
        uid = _make_database(conn)
        databases_router.archive_database(uid, conn=conn)
        assert db.list_databases(conn) == []

    def test_delete_cascades(self, conn):
        uid = _make_database(conn)
        col = db.list_database_columns(conn, uid)[0]
        databases_router.add_row(uid, conn=conn)
        databases_router.delete_database(uid, conn=conn)
        assert db.get_database(conn, uid) is None
        assert db.list_database_columns(conn, uid) == []
        assert db.list_database_rows(conn, uid) == []


class TestColumns:
    def test_add_text_column(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="Notes", type="text", formula="", summary_formula="", options="", conn=conn)
        cols = db.list_database_columns(conn, uid)
        assert any(c["name"] == "Notes" and c["type"] == "text" for c in cols)

    def test_add_select_column_with_options(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="Status", type="select", formula="", summary_formula="", options="todo, done", conn=conn)
        col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Status")
        assert col["options"] == ["todo", "done"]

    def test_add_formula_column(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="Total", type="formula", formula="grade * weight", summary_formula="", options="", conn=conn)
        col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Total")
        assert col["formula"] == "grade * weight"

    def test_edit_column(self, conn):
        uid = _make_database(conn)
        col_uid = db.list_database_columns(conn, uid)[0]["uid"]
        databases_router.edit_column(uid, col_uid, name="Full Name", type="text", formula="", summary_formula="", options="", conn=conn)
        assert db.get_database_column(conn, col_uid)["name"] == "Full Name"

    def test_delete_column(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="Extra", type="text", formula="", summary_formula="", options="", conn=conn)
        extra = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Extra")
        databases_router.delete_column(uid, extra["uid"], conn=conn)
        assert not any(c["uid"] == extra["uid"] for c in db.list_database_columns(conn, uid))

    def test_move_column_left_and_right(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="B", type="text", formula="", summary_formula="", options="", conn=conn)
        databases_router.add_column(uid, name="C", type="text", formula="", summary_formula="", options="", conn=conn)
        cols = db.list_database_columns(conn, uid)
        assert [c["name"] for c in cols] == ["Name", "B", "C"]

        c_uid = next(c["uid"] for c in cols if c["name"] == "C")
        databases_router.move_column(uid, c_uid, direction="left", conn=conn)
        cols = db.list_database_columns(conn, uid)
        assert [c["name"] for c in cols] == ["Name", "C", "B"]

        databases_router.move_column(uid, c_uid, direction="left", conn=conn)
        cols = db.list_database_columns(conn, uid)
        assert [c["name"] for c in cols] == ["C", "Name", "B"]

        # already leftmost -- moving further left is a no-op, not an error
        databases_router.move_column(uid, c_uid, direction="left", conn=conn)
        cols = db.list_database_columns(conn, uid)
        assert [c["name"] for c in cols] == ["C", "Name", "B"]


class TestRowsAndCells:
    def test_add_row_and_edit_cell(self, conn):
        uid = _make_database(conn)
        databases_router.add_row(uid, conn=conn)
        row = db.list_database_rows(conn, uid)[0]
        name_col = db.list_database_columns(conn, uid)[0]
        databases_router.set_cell(uid, row["uid"], name_col["uid"], value="Alice", conn=conn)
        assert db.get_database_row(conn, row["uid"])["values"][name_col["uid"]] == "Alice"

    def test_checkbox_cell_normalizes_to_bool(self, conn):
        uid = _make_database(conn)
        databases_router.add_column(uid, name="Done", type="checkbox", formula="", summary_formula="", options="", conn=conn)
        col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Done")
        databases_router.add_row(uid, conn=conn)
        row = db.list_database_rows(conn, uid)[0]
        databases_router.set_cell(uid, row["uid"], col["uid"], value="on", conn=conn)
        assert db.get_database_row(conn, row["uid"])["values"][col["uid"]] is True

    def test_delete_row(self, conn):
        uid = _make_database(conn)
        databases_router.add_row(uid, conn=conn)
        row = db.list_database_rows(conn, uid)[0]
        databases_router.delete_row(uid, row["uid"], conn=conn)
        assert db.list_database_rows(conn, uid) == []


class TestGradeTrackingScenario:
    """End-to-end scenario matching the driving feature request: a class
    (project) has a database of assignments with grade/weight columns and
    a WEIGHTAVG summary formula for the final grade."""

    def _setup(self, conn):
        uid = _make_database(conn, "Databases 101 Grades")
        cols = db.list_database_columns(conn, uid)
        name_col = cols[0]
        databases_router.add_column(uid, name="grade", type="number", formula="", summary_formula="WEIGHTAVG(grade, weight)", options="", conn=conn)
        databases_router.add_column(uid, name="weight", type="number", formula="", summary_formula="", options="", conn=conn)
        grade_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "grade")
        weight_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "weight")

        for name, grade, weight in [("Midterm", "85", "30"), ("Final", "90", "50"), ("Homework", "70", "20")]:
            databases_router.add_row(uid, conn=conn)
        rows = db.list_database_rows(conn, uid)
        data = [("Midterm", "85", "30"), ("Final", "90", "50"), ("Homework", "70", "20")]
        for row, (name, grade, weight) in zip(rows, data):
            databases_router.set_cell(uid, row["uid"], name_col["uid"], value=name, conn=conn)
            databases_router.set_cell(uid, row["uid"], grade_col["uid"], value=grade, conn=conn)
            databases_router.set_cell(uid, row["uid"], weight_col["uid"], value=weight, conn=conn)
        return uid, grade_col

    def test_summary_formula_computes_weighted_average(self, conn):
        uid, grade_col = self._setup(conn)
        columns = db.list_database_columns(conn, uid)
        rows = db.list_database_rows(conn, uid)
        summary = databases_router._summary_row(columns, rows)
        assert summary is not None
        expected = (85 * 30 + 90 * 50 + 70 * 20) / (30 + 50 + 20)
        assert round(summary[grade_col["uid"]]["value"], 6) == round(expected, 6)
        assert summary[grade_col["uid"]]["error"] is None

    def test_database_detail_route_includes_summary(self, conn):
        from starlette.requests import Request

        uid, grade_col = self._setup(conn)
        req = Request({"type": "http", "method": "GET", "path": f"/databases/{uid}", "headers": []})
        resp = databases_router.database_detail(uid, req, conn=conn)
        assert resp.status_code == 200
        assert resp.context["summary"] is not None

    def test_formula_column_computed_per_row(self, conn):
        uid = _make_database(conn, "Weighted rows")
        cols = db.list_database_columns(conn, uid)
        name_col = cols[0]
        databases_router.add_column(uid, name="grade", type="number", formula="", summary_formula="", options="", conn=conn)
        databases_router.add_column(uid, name="weight", type="number", formula="", summary_formula="", options="", conn=conn)
        databases_router.add_column(uid, name="Weighted", type="formula", formula="grade * weight", summary_formula="", options="", conn=conn)
        grade_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "grade")
        weight_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "weight")
        weighted_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Weighted")

        databases_router.add_row(uid, conn=conn)
        row = db.list_database_rows(conn, uid)[0]
        databases_router.set_cell(uid, row["uid"], grade_col["uid"], value="10", conn=conn)
        databases_router.set_cell(uid, row["uid"], weight_col["uid"], value="3", conn=conn)

        columns = db.list_database_columns(conn, uid)
        rows = db.list_database_rows(conn, uid)
        computed = databases_router._computed_rows(columns, rows)
        assert computed[0]["cells"][weighted_col["uid"]]["value"] == 30
        assert computed[0]["cells"][weighted_col["uid"]]["is_formula"] is True

    def test_formula_error_does_not_crash_the_page(self, conn):
        from starlette.requests import Request

        uid = _make_database(conn, "Broken formula")
        databases_router.add_column(uid, name="Bad", type="formula", formula="1 / 0", summary_formula="", options="", conn=conn)
        databases_router.add_row(uid, conn=conn)
        req = Request({"type": "http", "method": "GET", "path": f"/databases/{uid}", "headers": []})
        resp = databases_router.database_detail(uid, req, conn=conn)
        assert resp.status_code == 200
        bad_col = next(c for c in db.list_database_columns(conn, uid) if c["name"] == "Bad")
        cell = resp.context["computed_rows"][0]["cells"][bad_col["uid"]]
        assert cell["value"] is None
        assert cell["error"]
