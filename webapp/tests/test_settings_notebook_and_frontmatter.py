"""Settings > Notebook (2026-10-02, curodav-notes STATE.md's "custom
frontmatter field schema" decision) -- the Frontmatter Fields table
(routers/notebook.py's field_settings_router) and the underlying
notebook_field_config/notebook_field_options db.py accessors. Same
Field/Type/Default/Required/Actions table + Edit-opens-a-modal shape as
Settings > Labels/Holidays (see test_settings_holidays.py for that
precedent). v1 is descriptive only -- nothing here enforces Required/
Select-options against a document's actual notebook_properties.
"""

from __future__ import annotations

import re

import pytest
from starlette.requests import Request

from src import db
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/settings/notebook"):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


class TestDbAccessors:
    def test_create_read_update_delete(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "institution", "label": "Institution", "type": "text"})
        field = db.get_notebook_field_config(conn, uid)
        assert field["key"] == "institution" and field["label"] == "Institution" and field["type"] == "text"
        assert field["options"] == []

        db.upsert_notebook_field_config(conn, {"uid": uid, "key": "institution", "label": "Place", "type": "text"})
        assert db.get_notebook_field_config(conn, uid)["label"] == "Place"

        db.delete_notebook_field_config(conn, uid)
        assert db.get_notebook_field_config(conn, uid) is None

    def test_label_defaults_to_key_when_blank(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "doi", "type": "text"})
        assert db.get_notebook_field_config(conn, uid)["label"] == "doi"

    def test_new_fields_append_after_existing_position(self, conn):
        db.upsert_notebook_field_config(conn, {"key": "a", "type": "text"})
        db.upsert_notebook_field_config(conn, {"key": "b", "type": "text"})
        fields = db.list_notebook_field_config(conn)
        # title/author/note_type (seed_builtin_notebook_fields) always sort
        # first -- negative positions -- with custom fields appended after.
        assert [f["key"] for f in fields] == ["title", "author", "note_type", "a", "b"]
        assert fields[-2]["position"] < fields[-1]["position"]

    def test_select_field_carries_its_option_list(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [
            {"value": "Draft", "color": "gray", "icon": "edit"},
            {"value": "Final", "color": "green", "icon": "check-square"},
        ])
        field = db.get_notebook_field_config(conn, uid)
        assert [o["value"] for o in field["options"]] == ["Draft", "Final"]
        assert field["options"][0]["color"] == "gray" and field["options"][0]["icon"] == "edit"

    def test_a_field_not_select_or_multiselect_has_no_options(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "due", "type": "date"})
        # Stray rows (e.g. a field switched away from Select without its
        # options being cleared) shouldn't surface -- _attach_notebook_
        # field_options gates strictly on the field's own current type.
        db.set_notebook_field_options(conn, uid, [{"value": "x"}])
        assert db.get_notebook_field_config(conn, uid)["options"] == []

    def test_blank_option_values_are_dropped(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "  "}, {"value": "Draft"}])
        assert [o["value"] for o in db.list_notebook_field_options(conn, uid)] == ["Draft"]

    def test_deleting_a_field_deletes_its_options(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "Draft"}])
        db.delete_notebook_field_config(conn, uid)
        assert db.list_notebook_field_options(conn, uid) == []

    def test_purge_all_data_clears_the_schema(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "Draft"}])
        db.purge_all_data(conn)
        assert db.list_notebook_field_config(conn) == []
        assert db.list_notebook_field_options(conn, uid) == []


class TestNotebookSidebarLayoutSetting:
    """2026-10-04 direct request -- the Document editor's "sidebar layout"
    preference (db.notebook_settings, a plain id=1 singleton same shape as
    task_habit_settings). 'stacked' is the default; 'sidebar' is the only
    other valid value, confirmed directly that mobile in that mode shows
    the editor body only (no drawer/stacked fallback)."""

    def test_defaults_to_stacked_with_no_row(self, conn):
        assert db.get_notebook_settings(conn)["sidebar_layout"] == "stacked"

    def test_save_then_get_round_trips(self, conn):
        db.save_notebook_settings(conn, "sidebar")
        assert db.get_notebook_settings(conn)["sidebar_layout"] == "sidebar"

    def test_save_is_idempotent_on_repeat_calls(self, conn):
        db.save_notebook_settings(conn, "sidebar")
        db.save_notebook_settings(conn, "stacked")
        assert db.get_notebook_settings(conn)["sidebar_layout"] == "stacked"

    def test_unknown_value_falls_back_to_stacked(self, conn):
        # Same defensive-fallback convention as save_task_habit_settings'
        # own blank-string guard -- a bogus/stale value from a future
        # removed option shouldn't wedge the page into neither branch.
        db.save_notebook_settings(conn, "bogus")
        assert db.get_notebook_settings(conn)["sidebar_layout"] == "stacked"

    def test_settings_page_reflects_the_saved_value(self, conn):
        db.save_notebook_settings(conn, "sidebar")
        body = notebook_router.settings_notebook(_request(), conn=conn).body.decode()
        assert re.search(r'value="sidebar"[^>]*\bchecked', body)

    def test_save_route_redirects_to_settings_notebook(self, conn):
        resp = notebook_router.save_notebook_layout(sidebar_layout="sidebar", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/notebook"
        assert db.get_notebook_settings(conn)["sidebar_layout"] == "sidebar"


class TestSettingsNotebookPage:
    def test_renders_with_breadcrumb_and_active_tab(self, conn):
        resp = notebook_router.settings_notebook(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_notebook"
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]
        assert 'href="/settings"' in resp.body.decode()

    def test_builtin_fields_always_appear_even_with_no_custom_fields(self, conn):
        # 2026-10-02 direct request: "all frontmatter should always appear
        # in the settings" -- title/author/note_type are seeded by
        # seed_builtin_notebook_fields, so the "no fields at all" empty
        # state this page used to have is no longer reachable.
        body = notebook_router.settings_notebook(_request(), conn=conn).body.decode()
        body = notebook_router.settings_notebook(_request(), conn=conn).body.decode()
        assert "No frontmatter fields defined yet" not in body
        assert 'href="/settings/notebook/new"' in body
        assert "Title" in body and "Author" in body and "Type" in body

    def test_lists_existing_fields_as_rows_with_edit_buttons(self, conn):
        db.upsert_notebook_field_config(conn, {"key": "institution", "label": "Institution", "type": "text", "default_value": "UBB"})
        body = notebook_router.settings_notebook(_request(), conn=conn).body.decode()
        assert "Institution" in body and "text" in body and "UBB" in body
        assert "Edit field" in body and "Delete field" in body


class TestOldFrontmatterUrl:
    def test_redirects_to_the_notebook_page(self):
        resp = notebook_router.settings_frontmatter()
        assert resp.status_code == 303 and resp.headers["location"] == "/settings/notebook"


class TestFieldModal:
    def test_new_modal_has_every_type_and_no_options_section_prefilled_open(self, conn):
        body = notebook_router.new_notebook_field_modal(_request("/settings/notebook/new"), conn=conn).body.decode()
        for _, t_label in db.NOTEBOOK_FIELD_TYPES:
            assert t_label in body
        assert 'data-field-type="text"' in body

    def test_edit_modal_prefills_the_field_and_its_options(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "label": "Status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "Draft", "color": "orange", "icon": "flag"}])
        body = notebook_router.edit_notebook_field_modal(uid, _request(f"/settings/notebook/{uid}/edit"), conn=conn).body.decode()
        assert 'data-field-type="select"' in body
        assert 'value="Draft"' in body
        assert f'id="field-option-color-proxy-1" name="option_color" value="orange"' in body
        assert f'id="field-option-icon-proxy-1" name="option_icon" value="flag"' in body

    def test_unknown_uid_redirects_to_the_list(self, conn):
        resp = notebook_router.edit_notebook_field_modal("nope", _request(), conn=conn)
        assert resp.status_code == 303 and resp.headers["location"] == "/settings/notebook"


def _custom_fields(conn):
    """Every list_notebook_field_config() result excluding the always-
    present builtins -- what used to be "every field" before
    seed_builtin_notebook_fields started seeding title/author/note_type."""
    return [f for f in db.list_notebook_field_config(conn) if not f["builtin"]]


def _with_types(conn, *types):
    for i, t in enumerate(types):
        db.upsert_notebook_document(conn, {"uid": f"t{i}", "title": t, "content_json": "{}", "document_type": "full",
                                           "note_type": t, "created_at": "x", "updated_at": "x"})


class TestCreateUpdateDelete:
    def test_create_a_text_field(self, conn):
        resp = notebook_router.create_notebook_field(label="Institution", type="text", default_value="UBB", conn=conn)
        assert resp.status_code == 303 and resp.headers["location"] == "/settings/notebook"
        fields = _custom_fields(conn)
        assert len(fields) == 1
        assert re.fullmatch(r"institution_[a-z0-9]{4}", fields[0]["key"]) and fields[0]["default_value"] == "UBB"

    def test_blank_label_is_rejected_without_creating_a_row(self, conn):
        notebook_router.create_notebook_field(label="   ", type="text", conn=conn)
        assert _custom_fields(conn) == []

    def test_generated_names_are_unique_for_the_same_label(self, conn):
        for _ in range(3):
            notebook_router.create_notebook_field(label="Birth date", type="date", conn=conn)
        keys = [f["key"] for f in _custom_fields(conn)]
        assert len(set(keys)) == 3 and all(k.startswith("birth_date_") for k in keys)

    def test_renaming_a_field_keeps_its_stored_name(self, conn):
        notebook_router.create_notebook_field(label="Birth date", type="date", conn=conn)
        field = _custom_fields(conn)[0]
        notebook_router.update_notebook_field(field["uid"], label="Born", type="date", conn=conn)
        renamed = db.get_notebook_field_config(conn, field["uid"])
        assert renamed["label"] == "Born" and renamed["key"] == field["key"]

    def test_field_modal_has_no_stored_name_or_required_checkbox(self, conn):
        body = notebook_router.new_notebook_field_modal(_request("/settings/notebook/new"), conn=conn).body.decode()
        assert 'name="key"' not in body and 'name="required"' not in body

    def test_create_a_select_field_with_options(self, conn):
        notebook_router.create_notebook_field(
            label="Status", type="select",
            option_value=["Draft", "Final"], option_color=["gray", "green"], option_icon=["edit", "check-square"],
            conn=conn,
        )
        field = _custom_fields(conn)[0]
        assert [o["value"] for o in field["options"]] == ["Draft", "Final"]
        assert field["options"][1]["color"] == "green"

    def test_update_switches_type_and_replaces_options(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "Draft"}])
        notebook_router.update_notebook_field(
            uid, label="Status", type="select",
            option_value=["Final"], option_color=["green"], option_icon=[""],
            conn=conn,
        )
        field = db.get_notebook_field_config(conn, uid)
        assert [o["value"] for o in field["options"]] == ["Final"]

    def test_switching_away_from_select_clears_its_options(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "select"})
        db.set_notebook_field_options(conn, uid, [{"value": "Draft"}])
        notebook_router.update_notebook_field(uid, label="Status", type="text", conn=conn)
        assert db.get_notebook_field_config(conn, uid)["options"] == []

    def test_delete_removes_the_field(self, conn):
        uid = db.upsert_notebook_field_config(conn, {"key": "status", "type": "text"})
        resp = notebook_router.delete_notebook_field(uid, conn=conn)
        assert resp.status_code == 303
        assert db.get_notebook_field_config(conn, uid) is None


class TestBuiltinFields:
    """title/author/note_type (2026-10-02 direct request: "all frontmatter
    should always appear in the settings... nothing about them can be
    changed besides the display name"... "note_type should appear because
    i want to change icon and color") -- seed_builtin_notebook_fields'
    rows, and the lock enforcement in update_notebook_field/
    delete_notebook_field."""

    def test_seeded_once_on_connect(self, conn):
        fields = {f["key"]: f for f in db.list_notebook_field_config(conn)}
        assert set(fields) == {"title", "author", "note_type"}
        assert fields["title"]["builtin"] == 1 and fields["title"]["type"] == "text"
        assert fields["author"]["builtin"] == 1 and fields["author"]["type"] == "text"
        assert fields["note_type"]["builtin"] == 1 and fields["note_type"]["type"] == "select"
        assert fields["note_type"]["options"] == []

    def test_a_note_type_typed_on_a_note_becomes_a_user_type(self, conn):
        db.upsert_notebook_document(conn, {"uid": "d", "title": "T", "content_json": "{}", "document_type": "full",
                                           "note_type": "person", "created_at": "x", "updated_at": "x"})
        options = db.get_notebook_field_config(conn, db.BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"])["options"]
        assert [o["value"] for o in options] == ["person"]

    def test_reconnecting_does_not_reseed_over_user_edits(self, conn, tmp_path):
        # Re-running seed_builtin_notebook_fields (e.g. a second db.connect()
        # against the same file) must not clobber a color the user already
        # picked -- the whole reason this is app_meta-guarded.
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"]
        _with_types(conn, "person")
        field = db.get_notebook_field_config(conn, uid)
        opts = [{"value": o["value"], "color": "pink" if o["value"] == "person" else o["color"], "icon": o["icon"]} for o in field["options"]]
        db.set_notebook_field_options(conn, uid, opts)
        db.seed_builtin_notebook_fields(conn)  # idempotent re-run
        assert db.notebook_note_type_looks(conn)["person"]["color"] == "pink"

    def test_update_only_changes_the_label_for_title(self, conn):
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["title"]
        notebook_router.update_notebook_field(
            uid, label="Document Title", type="number", default_value="x", conn=conn,
        )
        field = db.get_notebook_field_config(conn, uid)
        assert field["label"] == "Document Title"
        assert field["key"] == "title" and field["type"] == "text"
        assert field["default_value"] is None

    def test_update_note_type_only_repaints_existing_options(self, conn):
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"]
        _with_types(conn, "person", "city")
        before = db.get_notebook_field_config(conn, uid)["options"]
        values_before = [o["value"] for o in before]
        # Submit a tampered value list (fewer rows, different values,
        # extra row) alongside new colors -- only the colors/icons should
        # land, positionally, on the field's own existing option order.
        new_colors = ["magenta"] * len(before)
        new_icons = [o["icon"] for o in before]
        notebook_router.update_notebook_field(
            uid, label="Type", type="select",
            option_value=["not", "a", "real", "list"], option_color=new_colors, option_icon=new_icons,
            conn=conn,
        )
        after = db.get_notebook_field_config(conn, uid)["options"]
        assert [o["value"] for o in after] == values_before
        assert all(o["color"] == "magenta" for o in after)

    def test_delete_is_refused_for_builtin_fields(self, conn):
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["author"]
        resp = notebook_router.delete_notebook_field(uid, conn=conn)
        assert resp.status_code == 303
        assert db.get_notebook_field_config(conn, uid) is not None

    def test_settings_table_has_no_delete_button_for_builtins(self, conn):
        body = notebook_router.settings_notebook(_request(), conn=conn).body.decode()
        assert "/settings/notebook/builtin-title/delete" not in body
        assert "/settings/notebook/builtin-title/edit" in body

    def test_edit_modal_locks_type_and_default(self, conn):
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["author"]
        body = notebook_router.edit_notebook_field_modal(uid, _request(f"/settings/notebook/{uid}/edit"), conn=conn).body.decode()
        assert 'name="default_value"' in body and "readonly" in body
        # No Delete button for a builtin field's own modal footer.
        assert "/settings/notebook/builtin-author/delete" not in body

    def test_note_type_edit_modal_has_locked_values_and_live_look_pickers(self, conn):
        uid = db.BUILTIN_NOTEBOOK_FIELD_UIDS["note_type"]
        _with_types(conn, "person")
        body = notebook_router.edit_notebook_field_modal(uid, _request(f"/settings/notebook/{uid}/edit"), conn=conn).body.decode()
        assert "notebook-field-option-value" in body  # locked value span, not an input
        assert 'name="option_value"' not in body
        assert 'data-repeatable-add="notebook-field-option-rows"' not in body
        assert "look-trigger" in body  # the Look pickers stay interactive


class TestHubCategory:
    def test_notebook_is_a_settings_hub_category(self):
        from src.routers import settings as settings_router
        urls = {c["url"] for c in settings_router.HUB_CATEGORIES}
        assert "/settings/notebook" in urls and "/settings/frontmatter" not in urls
