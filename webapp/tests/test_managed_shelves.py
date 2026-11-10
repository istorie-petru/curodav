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
        with tags.managed_writes("academic"):
            tags.set_managed_by(c, "University", "academic")
        yield c


def test_the_owner_may_change_its_shelf(conn):
    with tags.managed_writes("academic"):
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
    lambda c: db.upsert_label_config(c, {"name": "Home", "managed_by": "academic"}),
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
    modules.register(modules.Module("academic", "Academic", "/settings/academic"))
    with pytest.raises(tags.ManagedLabelError, match="Academic module.*\\/settings\\/academic"):
        db.rename_label(conn, "University", "Uni")


def test_the_move_check_reports_a_managed_shelf(conn):
    assert "managed" in (tags.move_error(conn, "Home", "University") or "")


def _request():
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def test_the_edit_modal_is_the_shelf_form_with_a_read_only_tag_list(conn):
    body = labels_router.edit_label_modal("University", _request(), conn=conn).body.decode()
    assert 'id="label-form"' in body and "data-tag-add" not in body and 'name="tag_idx"' not in body and "data-tag-remove" not in body


def test_saving_the_shelf_changes_its_look_and_name_but_not_its_tags(conn):
    conn.execute("INSERT INTO university_semesters (uid, shelf_name, name, created_at) VALUES ('s1', 'University', 'S1', '2026-10-01')")
    labels_router.update_label("University", new_name="Uni", color="red", icon="", label_group="", description="", conn=conn, request=None, tag_rows=[])
    assert db.get_label_config(conn, "Uni")["color"] == "red"
    assert db.get_label_config(conn, "Uni")["managed_by"] == "academic"
    assert [t["name"] for t in tags.tags_of_label(conn, "Uni")] == ["University"]
    assert conn.execute("SELECT shelf_name FROM university_semesters").fetchone()[0] == "Uni"


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


def test_a_linked_contact_comes_with_its_photo_url_only_when_it_has_a_photo(conn):
    conn.execute("INSERT INTO contacts (uid, full_name, photo_b64, photo_type, photo_version) VALUES ('c1', 'Ana', 'AAAA', 'JPEG', 'v1')")
    conn.execute("INSERT INTO contacts (uid, full_name) VALUES ('c2', 'Bob')")
    for uid in ("c1", "c2"):
        conn.execute("INSERT INTO object_contacts (object_type, object_id, contact_uid) VALUES ('event', 'e9', ?)", (uid,))
    ana, bob = db.list_object_contacts(conn, "event", "e9")
    assert ana["photo_url"] == "/contacts/c1/photo?v=v1" and "photo_url" not in bob and "photo_b64" not in ana
