"""A project's auto labels are added to an item when the project is newly added to it."""

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _project(conn, name="ABC", auto=("MNP",)):
    db.upsert_label_config(conn, {"name": name, "is_project": 1})
    db.upsert_label_config(conn, {"name": "MNP"})
    db.set_auto_labels(conn, name, list(auto))


def _event(conn):
    db.upsert_event(conn, {"uid": "e1", "title": "XYZ", "description": "", "all_day": 0, "status": "active", "tags": [],
                           "created_at": datetime.now(timezone.utc).isoformat()})


def test_adding_the_project_adds_its_auto_labels(conn):
    _project(conn)
    _event(conn)
    db.set_object_labels(conn, "event", "e1", ["ABC"])
    assert sorted(db.list_labels_for_object(conn, "event", "e1")) == ["ABC", "MNP"]


def test_a_label_removed_by_hand_stays_removed_on_later_saves(conn):
    _project(conn)
    _event(conn)
    db.set_object_labels(conn, "event", "e1", ["ABC"])
    db.set_object_labels(conn, "event", "e1", ["ABC"])
    assert sorted(db.list_labels_for_object(conn, "event", "e1")) == ["ABC"]


def test_auto_labels_follow_a_rename_and_never_include_the_project_itself(conn):
    _project(conn)
    db.set_auto_labels(conn, "ABC", ["ABC", "MNP"])
    assert db.get_auto_labels(conn, "ABC") == ["MNP"]
    db.rename_label(conn, "MNP", "QRS")
    assert db.get_auto_labels(conn, "ABC") == ["QRS"]


def test_the_json_route_lists_them(conn):
    _project(conn)
    assert labels_router.auto_labels_json("ABC", conn=conn).body == b'["MNP"]'
