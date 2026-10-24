"""Label modal: a new label gets its same-named tag once, extra tags are made in the modal, nothing is synced."""

import pytest
from fastapi import HTTPException

from src import db, tags
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _create(conn, name, **kw):
    labels_router.create_label(new_name=name, color=kw.get("color", "red"), icon=kw.get("icon", "home"), label_group="",
                               description="", role="none", page_fields="", deadline_date="", page_type="",
                               agenda_widget="", tasks_widget="", contacts_widget="", notebook_widget="",
                               sidebar_pin="", widget_pin="", auto_labels=None, tag_rows=[], conn=conn)


def test_new_label_gets_one_default_tag_with_its_look(conn):
    _create(conn, "Kitchen")
    assert [(t["name"], t["label_name"], t["color"], t["icon"]) for t in tags.tags_of_label(conn, "Kitchen")] == [
        ("Kitchen", "Kitchen", "red", "home")]


def _rows(*rows):
    return [dict(old="", name="", color="gray", icon="", delete=False) | r for r in rows]


def _update(conn, name, rows):
    labels_router.update_label(name, new_name=name, color="red", icon="home", label_group="", description="", role=None,
                               page_fields="", deadline_date="", page_type="", agenda_widget="", tasks_widget="",
                               contacts_widget="", notebook_widget="", sidebar_pin="", widget_pin="", auto_labels=None,
                               tag_rows=rows, request=None, conn=conn)


def test_label_name_cannot_reuse_a_tag_name(conn):
    _create(conn, "Kitchen")
    _update(conn, "Kitchen", _rows({"name": "Salt"}))
    with pytest.raises(HTTPException):
        _create(conn, "Salt")


def test_tags_are_edited_inside_the_label_form_and_keep_one(conn):
    _create(conn, "Kitchen")
    _update(conn, "Kitchen", _rows({"name": "Salt", "color": "blue"}))
    with pytest.raises(HTTPException):
        _update(conn, "Kitchen", _rows({"name": "salt"}))
    tags.set_object_tags(conn, "task", "t1", ["Salt"])
    _update(conn, "Kitchen", _rows({"old": "Salt", "name": "Pepper", "color": "green"}))
    assert tags.tags_for_object(conn, "task", "t1") == ["Pepper"]
    _update(conn, "Kitchen", _rows({"old": "Pepper", "delete": True}))
    assert tags.tags_for_object(conn, "task", "t1") == []
    with pytest.raises(HTTPException):
        _update(conn, "Kitchen", _rows({"old": "Kitchen", "delete": True}))


def test_renaming_the_label_changes_neither_tag_names_nor_looks(conn):
    _create(conn, "Kitchen")
    db.rename_label(conn, "Kitchen", "Galley")
    assert [(t["name"], t["label_name"]) for t in tags.tags_of_label(conn, "Galley")] == [("Kitchen", "Galley")]


def test_deleting_a_label_removes_its_tags_and_merging_moves_them(conn):
    _create(conn, "A")
    _create(conn, "B")
    tags.set_object_tags(conn, "task", "t1", ["A"])
    db.merge_labels(conn, "A", "B")
    assert {t["name"] for t in tags.tags_of_label(conn, "B")} == {"A", "B"}
    db.delete_label_config(conn, "B")
    assert tags.list_tags(conn) == [] and tags.tags_for_object(conn, "task", "t1") == []


def test_tag_filter_matches_links_and_falls_back_to_the_default_tag(conn):
    _create(conn, "Kitchen")
    _update(conn, "Kitchen", _rows({"name": "Salt"}))
    db.upsert_task(conn, {"uid": "a", "title": "Linked", "description": "", "status": "active", "tags": ["Kitchen"], "created_at": "2026-01-01", "updated_at": "2026-01-01"})
    db.upsert_task(conn, {"uid": "b", "title": "Plain", "description": "", "status": "active", "tags": ["Kitchen"], "created_at": "2026-01-01", "updated_at": "2026-01-01"})
    tags.set_object_tags(conn, "task", "a", ["Salt"])
    items = db.list_tasks(conn)
    by_uid = {t["uid"]: t for t in items}
    assert [u for u, t in by_uid.items() if tags.matcher(conn, "task", ["Salt"])(t)] == ["a"]
    # "b" has no tag links yet, so it counts as carrying the default tag of its label; "a" is tagged Salt only
    assert [u for u, t in by_uid.items() if tags.matcher(conn, "task", ["Kitchen"])(t)] == ["b"]


def test_filter_items_swap_labels_for_tags_and_keep_groups(conn):
    _create(conn, "Kitchen")
    tags.add_default_tag(conn, "Kitchen")
    conn.execute("INSERT INTO label_tags (name, label_name) VALUES ('Salt', 'Kitchen')")
    tags.set_object_tags(conn, "contact", "c1", ["Salt"])
    base = [{"value": "group:Home", "name": "Home", "section": "group"}, {"value": "Kitchen", "name": "Kitchen", "section": "label"}]
    assert [(i["name"], i["section"]) for i in tags.filter_items(conn, "contact", base)] == [("Home", "group"), ("Kitchen", "label"), ("Salt", "label")]


def test_label_list_shows_active_by_default_and_archived_on_request(conn):
    from starlette.requests import Request

    from src.routers import labels as labels_router_mod

    _create(conn, "Live")
    _create(conn, "Old")
    db.archive_project(conn, "Old")

    def names(query=b""):
        request = Request({"type": "http", "method": "GET", "path": "/settings/labels", "query_string": query, "headers": [], "app": None})
        return [l["name"] for l in labels_router_mod._labels_context(conn, request)["labels"]]

    assert names() == ["Live"] and names(b"show=archived") == ["Old"] and sorted(names(b"show=all")) == ["Live", "Old"]


def test_tags_view_lists_every_tag_with_its_label_and_usage(conn):
    from starlette.requests import Request

    from src.routers import taxonomy

    _create(conn, "Kitchen")
    _update(conn, "Kitchen", _rows({"name": "Salt", "color": "blue"}))
    tags.set_object_tags(conn, "task", "t1", ["Salt"])
    request = Request({"type": "http", "method": "GET", "path": "/settings/tags", "query_string": b"", "headers": [], "app": None})
    body = taxonomy.manage_tags(request, conn=conn).body.decode()
    assert "Salt" in body and "Kitchen" in body and "Used in 1 item" in body and 'href="/settings/tags"' in body


def test_label_page_with_several_tags_groups_open_tasks_by_tag(conn):
    from starlette.requests import Request

    from src.routers import label_pages

    _create(conn, "Kitchen")
    _update(conn, "Kitchen", _rows({"name": "Salt", "color": "blue"}))
    for uid, title in (("a", "Season"), ("b", "Plain")):
        db.upsert_task(conn, {"uid": uid, "title": title, "description": "", "status": "active", "tags": ["Kitchen"],
                              "created_at": "2026-01-01", "updated_at": "2026-01-01"})
    tags.set_object_tags(conn, "task", "a", ["Salt"])
    request = Request({"type": "http", "method": "GET", "path": "/labels/Kitchen", "query_string": b"", "headers": [], "app": None})
    ctx = label_pages.label_page("Kitchen", request, conn=conn).context
    assert [(g[0]["name"], [t["title"] for t in g[1]]) for g in ctx["ov_by_tag"]] == [("Kitchen", ["Plain"]), ("Salt", ["Season"])]
