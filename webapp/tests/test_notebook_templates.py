"""Notebook templates: notes marked as templates stay out of every note list and live on the Templates page."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import dashboard as dashboard_router
from src.routers import notebook as router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/notebook/templates"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _note(conn, uid, title="Note", template=False, **extra):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": title, "content_json": '{"blocks": []}', "document_type": "full", "note_type": "",
        "is_template": 1 if template else 0, "created_at": now, "updated_at": now, **extra})


def _save(conn, uid, **overrides):
    form = dict(title="T", note_type="", note_type_new="", tags_labels=[], kind="", property_key=[],
                property_value=[], typed={}, x_requested_with=None)
    form.update(overrides)
    return router.update_document_properties(uid, conn=conn, **form)


def test_marking_a_note_as_a_template_removes_its_labels(conn):
    _note(conn, "d", tags=["History"])
    _save(conn, "d", tags_labels=["History"], kind="template")
    doc = db.get_notebook_document(conn, "d")
    assert doc["is_template"] == 1 and doc["tags"] == []


def test_a_template_can_be_turned_back_into_an_ordinary_note(conn):
    _note(conn, "d", template=True)
    _save(conn, "d", tags_labels=["History"], kind="note")
    doc = db.get_notebook_document(conn, "d")
    assert doc["is_template"] == 0 and doc["tags"] == ["History"]


def test_templates_are_hidden_from_note_lists_search_and_links(conn):
    _note(conn, "n", "Plain note")
    _note(conn, "t", "Meeting template", template=True)
    assert [d["uid"] for d in db.list_notebook_documents(conn)] == ["n"]
    assert [d["uid"] for d in db.list_notebook_documents(conn, scope="templates")] == ["t"]
    assert {d["uid"] for d in db.list_notebook_documents(conn, scope="all")} == {"n", "t"}
    assert [d["uid"] for d in db.search_notebook_documents(conn, "")] == ["n"]


def test_templates_do_not_count_in_the_browse_page(conn):
    _note(conn, "n")
    _note(conn, "t", template=True)
    ctx = router._notebook_browse_context(conn, _request("/notebook"), "", "", "", "updated", limit=50)
    assert ctx["total_documents"] == 1


def test_search_contents_skips_templates(conn):
    _note(conn, "n", content_json=json.dumps({"blocks": [{"type": "paragraph", "data": {"text": "needle"}}]}))
    _note(conn, "t", template=True, content_json=json.dumps({"blocks": [{"type": "paragraph", "data": {"text": "needle"}}]}))
    assert [h["uid"] for h in router._find_hits(conn, "needle", False, False)] == ["n"]


def test_templates_page_lists_only_templates(conn):
    _note(conn, "n", "Plain note")
    _note(conn, "t", "Meeting template", template=True)
    body = router.templates_page(_request(), conn=conn).body.decode()
    assert "Meeting template" in body and "Plain note" not in body


def test_new_template_is_created_from_the_templates_page(conn):
    resp = router.create_template(conn=conn)
    uid = resp.headers["location"].rsplit("/", 1)[1]
    assert resp.status_code in (201, 303) and db.get_notebook_document(conn, uid)["is_template"] == 1


def test_the_all_scope_used_by_backups_includes_templates(conn):
    _note(conn, "t", template=True)
    assert [d["is_template"] for d in db.list_notebook_documents(conn, scope="all")] == [1]


def test_deleting_a_field_removes_it_from_templates_only(conn):
    uid = db.upsert_notebook_field_config(conn, {"key": "year_ab12", "label": "Year", "type": "number"})
    _note(conn, "t", "Template", template=True, properties=[{"key": "year_ab12", "value": "1999"}])
    _note(conn, "n", "Note", properties=[{"key": "year_ab12", "value": "2001"}])
    assert [t["title"] for t in db.list_templates_using_field(conn, "year_ab12")] == ["Template"]
    db.delete_notebook_field_config(conn, uid)
    assert db.get_notebook_document(conn, "t")["properties"] == []
    assert db.get_notebook_document(conn, "n")["properties"][0]["value"] == "2001"


def test_field_delete_warning_lists_the_templates_using_it(conn):
    uid = db.upsert_notebook_field_config(conn, {"key": "year_ab12", "label": "Year", "type": "number"})
    _note(conn, "t", "Meeting template", template=True, properties=[{"key": "year_ab12", "value": "1999"}])
    body = router.edit_notebook_field_modal(uid, _request(), conn=conn).body.decode()
    assert "Meeting template" in body



def _create(conn, **kw):
    form = dict(label="", template_uid="", title="", open_note="", typed={}, x_requested_with=None)
    form.update(kw)
    return router.create_document(conn=conn, **form)


def _uid(resp):
    return resp.headers["location"].rsplit("/", 1)[1]


def _person_template(conn):
    db.upsert_notebook_field_config(conn, {"key": "year_ab12", "label": "Year", "type": "number"})
    _note(conn, "t", "Person", template=True, note_type="person",
          content_json='{"blocks": [{"type": "paragraph", "data": {"text": "Born:"}}]}',
          properties=[{"key": "year_ab12", "value": "1900"}, {"key": "Source", "value": "Wikipedia"}])


def test_a_blank_note_is_created_as_before(conn):
    doc = db.get_notebook_document(conn, _uid(_create(conn)))
    assert doc["title"] == "Untitled" and doc["note_type"] == "" and doc["properties"] == [] and not doc["is_template"]


def test_a_note_from_a_template_gets_its_body_type_and_edited_values(conn):
    _person_template(conn)
    doc = db.get_notebook_document(conn, _uid(_create(
        conn, template_uid="t", title="Ada", typed={"field__year_ab12": ["1815"]})))
    assert doc["title"] == "Ada" and doc["note_type"] == "person" and not doc["is_template"]
    assert "Born:" in doc["content_json"]
    assert {p["key"]: p["value"] for p in doc["properties"]} == {"year_ab12": "1815", "Source": "Wikipedia"}


def test_a_cleared_template_value_is_left_out(conn):
    _person_template(conn)
    doc = db.get_notebook_document(conn, _uid(_create(conn, template_uid="t", typed={"field__year_ab12": [""]})))
    assert [p["key"] for p in doc["properties"]] == ["Source"]


def test_an_invalid_value_blocks_creation(conn):
    _person_template(conn)
    resp = _create(conn, template_uid="t", typed={"field__year_ab12": ["soon"]})
    assert resp.status_code == 422 and len(db.list_notebook_documents(conn)) == 0


def test_a_note_from_a_template_keeps_the_label_it_was_created_under(conn):
    _person_template(conn)
    doc = db.get_notebook_document(conn, _uid(_create(conn, template_uid="t", label="History")))
    assert doc["tags"] == ["History"]


def test_the_creation_modal_offers_blank_first_and_every_template(conn):
    _person_template(conn)
    body = router.new_note_modal(_request("/notebook/new"), conn=conn).body.decode()
    assert "Blank note" in body and "Person" in body and 'name="title"' in body


def test_choosing_a_template_returns_its_fields_prefilled(conn):
    _person_template(conn)
    body = router.new_note_fields(_request("/notebook/new/fields"), template="t", conn=conn).body.decode()
    assert 'name="field__year_ab12"' in body and 'value="1900"' in body
    blank = router.new_note_fields(_request("/notebook/new/fields"), template="", conn=conn).body.decode()
    assert 'name="field__year_ab12"' in blank and 'value="1900"' not in blank


def test_the_creation_modal_asks_to_open_the_new_note(conn):
    uid = _uid(_create(conn, open_note="1", x_requested_with="fetch"))
    assert db.get_notebook_document(conn, uid) is not None


def test_a_new_note_can_be_given_type_labels_project_and_frontmatter_up_front(conn):
    db.upsert_notebook_field_config(conn, {"key": "author", "label": "Author", "type": "text"})
    doc = db.get_notebook_document(conn, _uid(_create(
        conn, title="Chapter 1", note_type="wiki", tags_labels=["History", "Draft"],
        typed={"field__author": ["Ada"]})))
    assert doc["title"] == "Chapter 1" and doc["note_type"] == "wiki" and sorted(doc["tags"]) == ["Draft", "History"]
    assert {p["key"]: p["value"] for p in doc["properties"]} == {"author": "Ada"}


def test_a_typed_new_note_type_wins_and_a_template_type_is_only_the_starting_choice(conn):
    _person_template(conn)
    assert db.get_notebook_document(conn, _uid(_create(conn, template_uid="t", note_type="", note_type_new="Idea")))["note_type"] == "Idea"
    assert db.get_notebook_document(conn, _uid(_create(conn, template_uid="t", note_type="")))["note_type"] == ""
    assert db.get_notebook_document(conn, _uid(_create(conn, template_uid="t")))["note_type"] == "person"


def test_frontmatter_fields_outside_the_template_can_be_filled_too(conn):
    _person_template(conn)
    db.upsert_notebook_field_config(conn, {"key": "author", "label": "Author", "type": "text"})
    doc = db.get_notebook_document(conn, _uid(_create(conn, template_uid="t", typed={"field__author": ["Ada"], "field__year_ab12": ["1815"]})))
    assert {p["key"]: p["value"] for p in doc["properties"]}["author"] == "Ada"


def test_the_new_note_form_offers_labels_project_type_and_frontmatter(conn):
    db.upsert_notebook_field_config(conn, {"key": "author", "label": "Author", "type": "text"})
    body = router.new_note_modal(_request("/notebook/new"), conn=conn).body.decode()
    for marker in ('name="title"', 'name="note_type"', 'name="tags_labels"', 'name="field__author"', 'name="template_uid"'):
        assert marker in body


def test_the_sidebar_new_modal_has_a_note_tab_that_defaults_on_notebook_pages(conn):
    from src.routers import dashboard
    body = dashboard.quick_add_form(_request("/quick/add"), default_tab="note", conn=conn).body.decode()
    assert 'data-quick-add-tab="note"' in body and 'id="notebook-new-form"' in body
