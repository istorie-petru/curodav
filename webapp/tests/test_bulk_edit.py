"""Bulk edit from a bulk-select selection: only the fields filled in change."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task(conn, uid, **extra):
    row = {"uid": uid, "title": uid, "description": "", "status": "active", "tags": [], "created_at": _now()}
    row.update(extra)
    db.upsert_task(conn, row)


def _contact(conn, uid, **extra):
    row = {"uid": uid, "full_name": uid, "org": None, "tags": [], "created_at": _now(), "updated_at": _now()}
    row.update(extra)
    db.upsert_contact(conn, row)


def _request(path):
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b"",
                    "scheme": "http", "server": ("testserver", 80), "root_path": ""})


def _edit_tasks(conn, uids, **fields):
    args = {"status": "", "start_at": "", "due_at": "", "recurrence": "", "add_tag": "", "remove_tag": ""} | fields
    return tasks_router.bulk_edit(uids=uids, x_requested_with=None, conn=conn, **args)


def _edit_contacts(conn, uids, **fields):
    args = {"add_tag": "", "remove_tag": "", "org": ""} | fields
    return contacts_router.bulk_edit(uids=uids, x_requested_with=None, conn=conn, **args)


class TestTasksBulkEdit:
    def test_sets_only_the_filled_fields_on_every_selected_task(self, conn):
        _task(conn, "t1", due_at="2026-10-01", tags=["Work"])
        _task(conn, "t2", tags=["Work"])
        _edit_tasks(conn, ["t1", "t2"], status="waiting", due_at="2026-11-01")
        for uid in ("t1", "t2"):
            row = db.get_task(conn, uid)
            assert row["status"] == "waiting"
            assert row["due_at"].startswith("2026-11-01")
            assert row["tags"] == ["Work"]

    def test_blank_fields_change_nothing(self, conn):
        _task(conn, "t1", due_at="2026-10-01", status="in_progress")
        _edit_tasks(conn, ["t1"])
        row = db.get_task(conn, "t1")
        assert row["status"] == "in_progress"
        assert row["due_at"].startswith("2026-10-01")

    def test_adds_and_removes_a_label(self, conn):
        _task(conn, "t1", tags=["Old"])
        _edit_tasks(conn, ["t1"], add_tag="New", remove_tag="Old")
        assert db.get_task(conn, "t1")["tags"] == ["New"]

    def test_sets_and_clears_recurrence(self, conn):
        _task(conn, "t1")
        _task(conn, "t2", recurrence="FREQ=DAILY")
        _edit_tasks(conn, ["t1"], recurrence="FREQ=WEEKLY")
        _edit_tasks(conn, ["t2"], recurrence="none")
        assert db.get_task(conn, "t1")["recurrence"] == "FREQ=WEEKLY"
        assert not db.get_task(conn, "t2")["recurrence"]

    def test_modal_lists_every_editable_field(self, conn):
        body = tasks_router.bulk_edit_modal("t1,t2", _request("/tasks/bulk-edit-modal"), conn=conn).body.decode()
        assert "Edit 2 tasks" in body
        for name in ("status", "start_at", "due_at", "recurrence", "add_tag", "remove_tag"):
            assert f'name="{name}"' in body


class TestContactsBulkEdit:
    def test_sets_org_and_one_label_on_every_selected_contact(self, conn):
        _contact(conn, "c1", tags=["Old"])
        _contact(conn, "c2")
        _edit_contacts(conn, ["c1", "c2"], add_tag="Work", org="Acme")
        for uid in ("c1", "c2"):
            row = db.get_contact(conn, uid)
            assert row["org"] == "Acme"
            assert row["tags"] == ["Work"]

    def test_blank_fields_change_nothing(self, conn):
        _contact(conn, "c1", org="Acme", tags=["Work"])
        _edit_contacts(conn, ["c1"])
        row = db.get_contact(conn, "c1")
        assert row["org"] == "Acme" and row["tags"] == ["Work"]

    def test_modal_lists_the_fields(self, conn):
        body = contacts_router.bulk_edit_modal("c1", _request("/contacts/bulk-edit-modal"), conn=conn).body.decode()
        assert "Edit 1 contact" in body
        for name in ("add_tag", "remove_tag", "org"):
            assert f'name="{name}"' in body


class TestLabelsBulkEdit:
    def test_sets_the_color_on_every_selected_label(self, conn):
        from src.routers import labels as labels_router

        for name in ("A", "B"):
            db.upsert_label_config(conn, {"name": name, "color": "blue", "created_at": _now()})
        labels_router.bulk_edit_labels(uids=["A", "B"], color="red", conn=conn)
        assert db.get_label_config(conn, "A")["color"] == "red"
        assert db.get_label_config(conn, "B")["color"] == "red"

    def test_a_label_with_no_settings_row_gets_one(self, conn):
        from src.routers import labels as labels_router

        labels_router.bulk_edit_labels(uids=["Fresh"], color="green", conn=conn)
        assert db.get_label_config(conn, "Fresh")["color"] == "green"

    def test_blank_color_changes_nothing(self, conn):
        from src.routers import labels as labels_router

        db.upsert_label_config(conn, {"name": "A", "color": "blue", "created_at": _now()})
        labels_router.bulk_edit_labels(uids=["A"], color="", conn=conn)
        assert db.get_label_config(conn, "A")["color"] == "blue"
