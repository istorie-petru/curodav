"""2026-09-26 (Peter): labels, groups and projects become separate things in
the UI -- standalone groups (their own table, may be empty) with view +
edit modals and their own settings page; Settings > Projects apart from
Settings > Labels; no Role on the label form (a label becomes a project
only through the one-way Convert action); the label form's page modules as
dropdowns."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db
from src.routers import label_pages
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _req(path="/", referer=""):
    headers = [(b"referer", referer.encode())] if referer else []
    return Request({"type": "http", "method": "GET", "path": path, "headers": headers, "query_string": b"",
                    "scheme": "http", "server": ("testserver", 80), "root_path": ""})


class TestStandaloneGroups:
    def test_label_group_creates_a_row_and_empty_groups_survive(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "created_at": _now()})
        assert db.get_group(conn, "uni")["name"] == "Uni"  # case-insensitive
        db.upsert_label_config(conn, {"name": "Maths", "label_group": None})
        assert [g["name"] for g in db.list_groups(conn)] == ["Uni"]
        assert db.list_groups(conn)[0]["labels"] == []

    def test_create_rejects_blank_and_duplicate(self, conn):
        db.create_group(conn, "Uni")
        with pytest.raises(ValueError):
            db.create_group(conn, "uni")
        with pytest.raises(ValueError):
            db.create_group(conn, "   ")

    def test_backfill_carries_the_old_app_meta_look(self, conn):
        conn.execute("INSERT INTO label_config (name, label_group) VALUES ('Run', 'Health')")
        db.set_app_meta(conn, "group_style:Health", json.dumps({"icon": "heart", "color": "red"}))
        conn.execute("DELETE FROM label_groups")
        db.backfill_group_rows(conn)
        assert db.get_group_style(conn, "Health") == {"icon": "heart", "color": "red"}

    def test_rename_moves_the_row_and_merge_drops_it(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "created_at": _now()})
        db.set_group_style(conn, "Uni", "book", "teal")
        assert db.rename_group(conn, "Uni", "School") == "School"
        assert db.get_group(conn, "Uni") is None and db.get_group_style(conn, "School")["icon"] == "book"
        db.create_group(conn, "Work")
        db.rename_group(conn, "School", "work")
        assert [g["name"] for g in db.list_groups(conn)] == ["Work"]
        assert db.group_member_names(conn, "Work") == ["Maths"]

    def test_delete_keeps_its_labels_ungrouped(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "created_at": _now()})
        label_pages.delete_group("Uni", conn=conn)
        assert db.get_group(conn, "Uni") is None
        assert db.get_label_config(conn, "Maths")["label_group"] is None
        assert db.get_label_config(conn, "Maths") is not None

    def test_create_route_with_members(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "created_at": _now()})
        resp = label_pages.create_group(new_name="Uni", color="teal", icon="book", members=["Maths"], conn=conn)
        assert resp.headers["location"] == "/settings/groups"
        assert db.group_member_names(conn, "Uni") == ["Maths"]
        with pytest.raises(HTTPException):
            label_pages.create_group(new_name="group:x", color="teal", icon="", members=[], conn=conn)

    def test_update_from_settings_stays_on_settings(self, conn):
        db.create_group(conn, "Uni")
        resp = label_pages.update_group("Uni", color="gray", icon="", new_name="", members=[], members_submitted="",
                                        request=_req("/groups/Uni/update", "http://testserver/settings/groups"),
                                        conn=conn)
        assert resp.headers["location"] == "/settings/groups"


class TestGroupModalsAndPages:
    def test_view_modal(self, conn):
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "created_at": _now()})
        db.set_group_style(conn, "Uni", None, "teal")
        body = label_pages.group_view_modal("Uni", _req("/groups/Uni/view"), conn=conn).body.decode()
        assert "var(--cal-accent-teal)" in body and 'href="#icon-layers"' in body  # default glyph
        assert 'href="/groups/Uni/edit"' in body and "Maths" in body

    def test_edit_modal_has_look_banner_and_cancel_to_view(self, conn):
        db.create_group(conn, "Uni")
        body = label_pages.edit_group_modal("Uni", _req("/groups/Uni/edit"), conn=conn).body.decode()
        assert 'id="look-group-form"' in body and "look-side-btn" in body
        assert "/banners/editor?scope=group%3AUni" in body
        assert '<a href="/groups/Uni/view" class="btn ghost" data-modal>' in body
        assert "field-hint" not in body

    def test_new_modal_has_no_banner_button(self, conn):
        body = label_pages.new_group_modal(_req("/groups/new"), conn=conn).body.decode()
        assert 'action="/groups/create"' in body and "look-side-btn" not in body

    def test_empty_group_has_a_page(self, conn):
        db.create_group(conn, "Uni")
        resp = label_pages.group_page("Uni", _req("/groups/Uni"), conn=conn)
        assert resp.status_code == 200

    def test_settings_groups_page_lists_empty_groups(self, conn):
        db.create_group(conn, "Uni")
        body = label_pages.manage_groups(_req("/settings/groups"), conn=conn).body.decode()
        assert 'data-group-name="Uni"' in body and "Empty" in body and 'href="/groups/new"' in body


class TestShelvesHaveNoProjectMode:
    def test_shelf_form_has_a_deadline_and_no_role_or_auto_shelves(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "created_at": _now()})
        body = labels_router.edit_label_modal("Gym", _req("/settings/labels/Gym/edit"), conn=conn).body.decode()
        assert 'name="deadline_date"' in body and 'name="role"' not in body and 'name="auto_labels"' not in body
        assert "Edit shelf" in body

    def test_shelf_rows_have_no_convert_action(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "created_at": _now()})
        body = labels_router.manage_labels(_req("/settings/labels"), conn=conn).body.decode()
        assert "convert-to-project" not in body

    def test_create_redirects_to_shelves_and_old_projects_page_to_tags(self, conn):
        resp = labels_router.create_label(new_name="Thesis", color="blue", icon="", label_group="", conn=conn)
        assert resp.headers["location"] == "/settings/labels"
        assert labels_router.projects_settings_redirect().headers["location"] == "/settings/tags"


class TestModuleDropdowns:
    def test_page_sections_and_show_in_are_dropdowns(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "sidebar_pin": 1, "tasks_widget": 1, "agenda_widget": 0,
                                      "contacts_widget": 0, "notebook_widget": 0, "created_at": _now()})
        body = labels_router.edit_label_modal("Gym", _req("/settings/labels/Gym/edit"), conn=conn).body.decode()
        assert 'data-ms-label="page"' not in body and 'data-ms-label="sections"' in body and 'data-ms-label="show in"' in body
        assert '<span class="ms-summary">Tasks</span>' in body
        assert '<span class="ms-summary">Sidebar</span>' in body
        assert 'class="field-toggle"' not in body
        assert re.search(r'name="sidebar_pin" value="1"[^>]*\bchecked', body)
        assert not re.search(r'name="widget_pin" value="1"[^>]*\bchecked', body)


class TestDuplicate:
    """Duplicate opens the new-item modal already filled with an existing
    item's settings; nothing is created until the user saves."""

    def test_label_copy_prefills_the_new_form_and_creates_nothing(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "color": "red", "icon": "heart", "description": "Lifting", "created_at": _now()})
        body = labels_router.new_label_modal(_req("/settings/labels/new"), copy="Gym", conn=conn).body.decode()
        assert 'value="Gym copy"' in body and "Lifting" in body
        assert [c["name"] for c in db.list_labels(conn)] == ["Gym"]

    def test_group_copy_keeps_the_look_but_not_the_labels(self, conn):
        db.create_group(conn, "Uni", "heart", "red")
        db.upsert_label_config(conn, {"name": "Maths", "label_group": "Uni", "created_at": _now()})
        body = label_pages.new_group_modal(_req("/groups/new"), copy="Uni", conn=conn).body.decode()
        assert 'value="Uni copy"' in body
        assert [g["name"] for g in db.list_groups(conn)] == ["Uni"]
        assert not re.search(r'name="members"[^>]*value="Maths"[^>]*checked', body)


class TestRowActions:
    def test_rows_offer_duplicate_and_archive(self, conn):
        from src.routers import taxonomy

        db.upsert_label_config(conn, {"name": "Gym", "created_at": _now()})
        rows = json.loads(taxonomy.taxonomy_rows(_req("/"), view="labels", conn=conn).body)["rows"]
        assert 'href="/settings/labels/new?copy=Gym"' in rows
        assert 'action="/labels/Gym/archive"' in rows

    def test_fetch_archive_returns_no_content(self, conn):
        db.upsert_label_config(conn, {"name": "Gym", "created_at": _now()})
        assert label_pages.archive_label("Gym", x_requested_with="fetch", conn=conn).status_code == 204
        assert db.get_label_config(conn, "Gym")["archived_at"]
        assert label_pages.unarchive_label("Gym", x_requested_with="fetch", conn=conn).status_code == 204
        assert not db.get_label_config(conn, "Gym")["archived_at"]
