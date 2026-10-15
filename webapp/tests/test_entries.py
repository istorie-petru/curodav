"""Entries: glossary terms with a kind, alternate names and a wiki note."""

import pytest

from src import db, migrations


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def test_an_entry_defaults_to_the_term_kind(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Entropy", "definition": "Disorder"})
    assert db.get_glossary_term(conn, uid)["kind"] == "Term"


def test_a_new_kind_is_created_with_a_default_look(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Berlin", "definition": "City", "kind": "Place"})
    assert db.get_glossary_term(conn, uid)["kind"] == "Place"
    assert "Place" in db.entry_kind_looks(conn) and db.entry_kind_looks(conn)["Place"]["icon"]


def test_alternate_names_and_the_wiki_note_are_stored(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Karl Marx", "definition": "x", "aliases": ["Marx", " "], "wiki_uid": "wiki1"})
    entry = db.get_glossary_term(conn, uid)
    assert entry["aliases"] == ["Marx"] and entry["wiki_uid"] == "wiki1"


def test_saving_an_entry_without_a_kind_keeps_its_kind(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Berlin", "definition": "City", "kind": "Place"})
    db.upsert_glossary_term(conn, {"uid": uid, "term": "Berlin", "definition": "Capital"})
    assert db.get_glossary_term(conn, uid)["kind"] == "Place"


def test_the_list_can_be_narrowed_by_kind_and_found_by_an_alternate_name(conn):
    db.upsert_glossary_term(conn, {"term": "Karl Marx", "definition": "x", "kind": "Person", "aliases": ["Marx"]})
    db.upsert_glossary_term(conn, {"term": "Entropy", "definition": "y"})
    assert [e["term"] for e in db.list_glossary_terms(conn, kind="Person")] == ["Karl Marx"]
    assert [e["term"] for e in db.list_glossary_terms(conn, q="marx")] == ["Karl Marx"]


def test_an_alternate_name_in_a_note_attaches_the_entry(conn):
    import json

    uid = db.upsert_glossary_term(conn, {"term": "Karl Marx", "definition": "x", "aliases": ["Marx"]})
    content = {"blocks": [{"type": "paragraph", "data": {"text": "Marx argued otherwise"}}]}
    assert uid in db._detect_glossary_term_uids(conn, content)


def test_migration_turns_old_terms_into_terms_of_kind_term(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE glossary_terms (uid TEXT PRIMARY KEY, term TEXT NOT NULL DEFAULT '', definition TEXT NOT NULL DEFAULT '', created_at TEXT, updated_at TEXT)")
    old.execute("INSERT INTO glossary_terms (uid, term) VALUES ('t1', 'Old term')")
    migrations._glossary_terms_become_entries(old)
    migrations._glossary_terms_become_entries(old)
    assert old.execute("SELECT kind, aliases_json, wiki_uid FROM glossary_terms").fetchone() == ("Term", "[]", "")
    assert old.execute("SELECT name FROM entry_kinds").fetchall() == [("Term",)]


def test_mentions_list_the_notes_an_entry_is_attached_to(conn):
    uid = db.upsert_glossary_term(conn, {"term": "Entropy", "definition": "x"})
    db.upsert_notebook_document(conn, {"uid": "n1", "title": "Physics", "document_type": "full", "note_type": "", "content_json": "{}", "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    db.attach_notebook_glossary_term(conn, "n1", uid)
    assert [m["title"] for m in db.list_entry_mentions(conn, uid)] == ["Physics"]


def _request(path="/"):
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def test_the_entries_list_is_grouped_by_kind(conn):
    from src.routers import notebook as router

    db.upsert_glossary_term(conn, {"term": "Entropy", "definition": "Disorder"})
    db.upsert_glossary_term(conn, {"term": "Berlin", "definition": "City", "kind": "Place"})
    groups = router.glossary_library(_request(), conn=conn).context["groups"]
    assert [(g["kind"], [e["term"] for e in g["entries"]]) for g in groups] == [("Term", ["Entropy"]), ("Place", ["Berlin"])]


def test_creating_an_entry_saves_kind_alternate_names_and_wiki_note(conn):
    from src.routers import notebook as router

    router.create_glossary_term(term="Karl Marx", definition="Philosopher", kind="Person", aliases="Marx, K. Marx", wiki_uid="w1",
                                reference_keys=[], section_title=[], section_body=[], x_requested_with=None, conn=conn)
    entry = db.list_glossary_terms(conn)[0]
    assert (entry["kind"], entry["aliases"], entry["wiki_uid"]) == ("Person", ["Marx", "K. Marx"], "w1")


def test_the_view_modal_shows_where_an_entry_is_mentioned_and_its_wiki_note(conn):
    from src.routers import notebook as router

    db.upsert_notebook_document(conn, {"uid": "w1", "title": "Marx wiki", "document_type": "full", "note_type": "", "content_json": "{}", "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    db.upsert_notebook_document(conn, {"uid": "n1", "title": "Lecture", "document_type": "full", "note_type": "", "content_json": "{}", "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    uid = db.upsert_glossary_term(conn, {"term": "Karl Marx", "definition": "x", "wiki_uid": "w1"})
    db.attach_notebook_glossary_term(conn, "n1", uid)
    body = router.entry_view_modal(uid, _request(), conn=conn).body.decode()
    assert "Marx wiki" in body and "Lecture" in body


def test_the_hover_card_shows_kind_text_and_a_read_more_link(conn):
    from src.routers import notebook as router

    uid = db.upsert_glossary_term(conn, {"term": "Berlin", "definition": "A city", "kind": "Place"})
    body = router.entry_card(uid, _request(), conn=conn).body.decode()
    assert "Berlin" in body and "Place" in body and "A city" in body and f"/notebook/glossary/{uid}" in body


def test_a_kind_typed_in_the_form_creates_that_kind(conn):
    from src.routers import notebook as router

    router.create_glossary_term(term="Verdun", definition="Battle", kind="", kind_new="Battle", aliases="", wiki_uid="",
                                reference_keys=[], section_title=[], section_body=[], x_requested_with=None, conn=conn)
    assert db.list_glossary_terms(conn)[0]["kind"] == "Battle"


def _note(conn, uid, title, tags=(), note_type=""):
    db.upsert_notebook_document(conn, {"uid": uid, "title": title, "document_type": "full", "note_type": note_type, "content_json": "{}",
                                       "tags": list(tags), "created_at": "2026-10-01", "updated_at": "2026-10-01"})


def test_the_picker_offers_entries_first_then_same_project_same_label_and_the_rest(conn):
    db.upsert_label_config(conn, {"name": "Thesis", "is_project": True})
    _note(conn, "me", "Current", ["Thesis", "Reading"])
    _note(conn, "a", "Zeta in project", ["Thesis"])
    _note(conn, "b", "Beta label", ["Reading"])
    _note(conn, "c", "Alpha other")
    db.upsert_glossary_term(conn, {"term": "Alphabet", "definition": "x", "kind": "Term"})
    found = db.search_link_targets(conn, "", exclude_uid="me")
    assert [(i["group"], i["title"]) for i in found] == [
        ("Entries", "Alphabet"), ("Same project", "Zeta in project"), ("Same label", "Beta label"), ("Notes", "Alpha other")]


def test_the_picker_narrows_by_typing_and_finds_entries_by_alternate_name(conn):
    _note(conn, "n1", "Marxism notes")
    db.upsert_glossary_term(conn, {"term": "Karl Marx", "definition": "x", "aliases": ["Marx"]})
    assert [i["title"] for i in db.search_link_targets(conn, "marx")] == ["Karl Marx", "Marxism notes"]
    assert [i["title"] for i in db.search_link_targets(conn, "marx", kinds="doc")] == ["Marxism notes"]


def test_detaching_an_entry_from_a_note_keeps_it_off(conn):
    _note(conn, "n1", "Lecture")
    uid = db.upsert_glossary_term(conn, {"term": "Entropy", "definition": "x", "aliases": ["disorder"]})
    db.attach_notebook_glossary_term(conn, "n1", uid)
    assert db.list_document_entry_names(conn, "n1")[0]["names"] == ["Entropy", "disorder"]
    db.detach_notebook_glossary_term(conn, "n1", uid)
    assert db.list_document_entry_names(conn, "n1") == []
    db.set_notebook_document_content(conn, "n1", {"blocks": [{"type": "paragraph", "data": {"text": "Entropy again"}}]})
    assert db.list_document_entry_names(conn, "n1") == []


def test_common_kinds_start_with_a_fitting_icon(conn):
    db.upsert_glossary_term(conn, {"term": "Berlin", "definition": "x", "kind": "Place"})
    assert db.entry_kind_looks(conn)["Place"]["icon"] == "map-pin"


def _kinds(conn):
    return {k["name"]: k for k in db.list_entry_kinds(conn)}


def test_a_new_type_has_a_look_and_fields_with_fixed_names(conn):
    assert db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born", "Died", "born"]) is None
    kind = _kinds(conn)["Person"]
    assert (kind["icon"], kind["color"], kind["fields"]) == ("user", "blue", ["Born", "Died"])


def test_existing_field_names_cannot_change_but_can_be_dropped_and_new_ones_added(conn):
    db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born", "Died"])
    db.save_entry_kind(conn, "Person", "Person", "user", "blue", ["Born", "Renamed"], ["Known for"])
    assert _kinds(conn)["Person"]["fields"] == ["Born", "Known for"]


def test_renaming_a_type_renames_it_on_its_entries_and_fields(conn):
    db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born"])
    uid = db.upsert_glossary_term(conn, {"term": "Ada", "definition": "x", "kind": "Person"})
    db.save_entry_kind(conn, "Person", "People", "users", "blue", ["Born"], [])
    assert db.get_glossary_term(conn, uid)["kind"] == "People" and _kinds(conn)["People"]["fields"] == ["Born"]
    assert "Person" not in _kinds(conn)


def test_type_names_must_be_unique_and_the_default_type_is_kept(conn):
    db.save_entry_kind(conn, "", "Person", "user", "blue", [], [])
    assert db.save_entry_kind(conn, "", "person", "user", "blue", [], [])["field"] == "name"
    assert db.save_entry_kind(conn, "", " ", "user", "blue", [], [])["field"] == "name"
    assert db.save_entry_kind(conn, "Term", "Word", "tag", "teal", [], []) is not None
    assert db.delete_entry_kind(conn, "Term") is not None


def test_a_type_with_entries_cannot_be_deleted_but_an_unused_one_can(conn):
    db.save_entry_kind(conn, "", "Person", "user", "blue", [], [])
    db.upsert_glossary_term(conn, {"term": "Ada", "definition": "x", "kind": "Person"})
    assert "uses" in db.delete_entry_kind(conn, "Person")["message"]
    db.save_entry_kind(conn, "", "Empty", "tag", "teal", [], [])
    assert db.delete_entry_kind(conn, "Empty") is None and "Empty" not in _kinds(conn)


def test_an_entry_form_saves_the_fields_of_its_type_and_the_view_shows_them(conn):
    from src.routers import notebook as router

    db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born", "Died"])
    router.create_glossary_term(term="Ada", definition="", kind="Person", kind_new="", aliases="", wiki_uid="", reference_keys=[],
                                section_title=["Born", "Own note"], section_body=["ignored", "kept"],
                                kfields={"kfield:Person:Born": "1815", "kfield:Person:Died": "", "kfield:Other:Born": "no"},
                                x_requested_with=None, conn=conn)
    uid = db.list_glossary_terms(conn)[0]["uid"]
    assert db.entry_field_values(conn, uid, "Person") == {"Born": "1815", "Died": ""}
    assert [s["title"] for s in db.entry_custom_sections(conn, uid, "Person")] == ["Own note"]
    body = router.entry_view_modal(uid, _request(), conn=conn).body.decode()
    assert "1815" in body and "Born" in body and "Own note" in body


def test_the_entry_edit_modal_offers_the_fields_of_each_type(conn):
    from src.routers import notebook as router

    db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born"])
    body = router.new_glossary_term_modal(_request(), conn=conn).body.decode()
    assert 'name="kfield:Person:Born"' in body


def test_the_sidebar_groups_a_notes_entries_by_type(conn):
    from src.routers import notebook as router

    db.upsert_notebook_document(conn, {"uid": "d", "title": "D", "document_type": "full", "note_type": "", "content_json": "{}", "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    for term, kind in (("Berlin", "Place"), ("Entropy", "Term"), ("Ada", "Person")):
        db.attach_notebook_glossary_term(conn, "d", db.upsert_glossary_term(conn, {"term": term, "definition": "", "kind": kind}))
    body = router.document_entries_list("d", _request(), conn=conn).body.decode()
    assert body.index("Term") < body.index("Place") < body.index("Person")  # the order the types were made in
    assert "Berlin" in body and "Ada" in body


def test_the_settings_page_lists_the_types_and_the_modal_opens(conn):
    from src.routers import notebook as router

    db.save_entry_kind(conn, "", "Person", "user", "blue", [], ["Born"])
    assert "Person" in router.settings_notebook(_request("/settings/notebook"), conn=conn).body.decode()
    modal = router.edit_entry_kind_modal(_request(), name="Person", conn=conn).body.decode()
    assert 'value="Born"' in modal and "readonly" in modal
