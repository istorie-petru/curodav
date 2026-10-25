"""A shelf a module manages is read only for everyone but that module: refused in the shared edit functions, not just hidden."""

import pytest

from src import db, modules, tags
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        db.upsert_label_config(c, {"name": "University", "color": "blue"})
        tags.add_default_tag(c, "University")
        db.upsert_label_config(c, {"name": "Home", "color": "green"})
        tags.add_default_tag(c, "Home")
        with tags.managed_writes("university"):
            tags.set_managed_by(c, "University", "university")
        yield c


def test_the_owner_may_change_its_shelf(conn):
    with tags.managed_writes("university"):
        db.upsert_label_config(conn, {"name": "University", "color": "red"})
        tags.apply_rows(conn, "University", [{"old": "University", "name": "University", "color": "red", "icon": "", "delete": False}], {"red"})
    assert db.get_label_config(conn, "University")["color"] == "red"


@pytest.mark.parametrize("action", [
    lambda c: db.upsert_label_config(c, {"name": "University", "color": "red"}),
    lambda c: db.rename_label(c, "University", "Uni"),
    lambda c: db.merge_labels(c, "University", "Home"),
    lambda c: db.merge_labels(c, "Home", "University"),
    lambda c: db.clear_label(c, "University"),
    lambda c: db.delete_label_config(c, "University"),
    lambda c: db.archive_project(c, "University"),
    lambda c: db.unarchive_label(c, "University"),
    lambda c: tags.apply_rows(c, "University", [], {"red"}),
    lambda c: tags.move_tag(c, "University", "Home"),
    lambda c: tags.restore(c, "University"),
    lambda c: tags.set_managed_by(c, "University", None),
    lambda c: db.upsert_label_config(c, {"name": "Home", "managed_by": "university"}),
])
def test_everyone_else_is_refused(conn, action):
    with pytest.raises(tags.ManagedLabelError):
        action(conn)


def test_a_different_module_is_refused_too(conn):
    with tags.managed_writes("finance"), pytest.raises(tags.ManagedLabelError):
        db.rename_label(conn, "University", "Uni")


def test_an_unmanaged_shelf_is_unaffected(conn):
    db.upsert_label_config(conn, {"name": "Home", "color": "red"})
    db.rename_label(conn, "Home", "House")
    assert db.get_label_config(conn, "House") is not None


def test_the_refusal_names_the_module_and_its_settings(conn):
    modules.register(modules.Module("university", "University", "/settings/university"))
    with pytest.raises(tags.ManagedLabelError, match="University module.*\\/settings\\/university"):
        db.rename_label(conn, "University", "Uni")


def test_the_move_check_reports_a_managed_shelf(conn):
    assert "managed" in (tags.move_error(conn, "Home", "University") or "")


def test_the_edit_modal_is_a_read_only_notice(conn):
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "scheme": "http",
                       "server": ("testserver", 80), "root_path": "", "headers": []})
    body = labels_router.edit_label_modal("University", request, conn=conn).body.decode()
    assert "read only" in body and 'id="label-form"' not in body


def test_sync_and_quick_edits_on_events_and_tasks_are_not_blocked(conn):
    from datetime import datetime, timezone

    now = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    db.upsert_event(conn, {"uid": "e1", "title": "Class", "description": "", "start_at": "2026-11-02T10:00", "end_at": "2026-11-02T11:00",
                           "all_day": 0, "status": "confirmed", "created_at": now, "tags": ["University"]})
    db.upsert_task(conn, {"uid": "t1", "title": "Read", "description": "", "status": "active", "created_at": now, "tags": ["University"]})
    tags.set_object_tags(conn, "event", "e1", ["University"])
    tags.record(conn, "task", "t1", ["University"])
    assert tags.tags_for_object(conn, "event", "e1") == ["University"]
    assert db.get_event(conn, "e1")["tags"] == ["University"]


def test_a_managed_shelf_cannot_be_moved_between_spaces_by_someone_else(conn):
    with pytest.raises(tags.ManagedLabelError):
        db.set_group_members(conn, "School", ["University"])
