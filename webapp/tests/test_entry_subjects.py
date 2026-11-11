"""Entries are filed under a subject: a coloured pill made in the Notebook settings, shown in the Entries page groups and the API."""

from __future__ import annotations

import pytest

from src import api_service, api_write, db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def _entry(conn, name, kind, subject=None):
    return db.upsert_glossary_term(conn, {"term": name, "kind": kind, "subject": subject})


def test_subjects_are_created_renamed_and_only_deleted_when_unused(conn):
    assert db.save_entry_subject(conn, "", "Archeology", "amber") is None
    assert db.save_entry_subject(conn, "", "archeology", "blue")["field"] == "name"
    assert db.save_entry_subject(conn, "", "  ", "blue")["field"] == "name"
    uid = _entry(conn, "Schliemann", "Person", "Archeology")
    assert db.save_entry_subject(conn, "Archeology", "Archaeology", "red") is None
    assert db.get_glossary_term(conn, uid)["subject"] == "Archaeology"
    assert db.list_entry_subjects(conn) == [{"name": "Archaeology", "color": "red", "used": 1}]
    assert "1 entry uses" in db.delete_entry_subject(conn, "Archaeology")["message"]
    db.upsert_glossary_term(conn, {"uid": uid, "term": "Schliemann", "subject": ""})
    assert db.delete_entry_subject(conn, "Archaeology") is None and db.list_entry_subjects(conn) == []


def test_a_subject_typed_on_an_entry_is_created_with_the_stored_spelling(conn):
    db.save_entry_subject(conn, "", "Ancient Greece", "blue")
    uid = _entry(conn, "Pericles", "Person", "ancient greece")
    assert db.get_glossary_term(conn, uid)["subject"] == "Ancient Greece"
    _entry(conn, "Knossos", "Place", "Minoans")
    assert {s["name"] for s in db.list_entry_subjects(conn)} == {"Ancient Greece", "Minoans"}


def test_the_entries_page_groups_by_kind_then_subject_with_no_subject_last(conn):
    _entry(conn, "Schliemann", "Person", "Archeology")
    _entry(conn, "Pericles", "Person", "Ancient Greece")
    _entry(conn, "Hypatia", "Person")
    _entry(conn, "Stratigraphy", "Term", "Archeology")
    groups = db.group_entries_by_kind_and_subject(conn, db.list_glossary_terms(conn))
    assert [(g["kind"], g["subject"], [e["term"] for e in g["entries"]]) for g in groups] == [
        ("Term", "Archeology", ["Stratigraphy"]),
        ("Person", "Ancient Greece", ["Pericles"]), ("Person", "Archeology", ["Schliemann"]), ("Person", "", ["Hypatia"])]
    assert [e["term"] for e in db.list_glossary_terms(conn, subject="archeology")] == ["Schliemann", "Stratigraphy"]


def test_an_update_without_a_subject_keeps_it_and_the_api_reads_and_writes_it(conn):
    uid = api_write.save_entry(conn, name="Pericles", kind="Person", subject="Ancient Greece")["uid"]
    api_write.save_entry(conn, uid=uid, definition="Athenian statesman")
    assert api_service.get_entry(conn, uid)["subject"] == "Ancient Greece"
    assert [e["name"] for e in api_service.list_entries(conn, subject="Ancient Greece")] == ["Pericles"]
    assert api_service.list_entry_subjects(conn) == [{"name": "Ancient Greece", "color": "teal", "entries": 1}]
    api_write.save_entry(conn, uid=uid, subject="")
    assert api_service.get_entry(conn, uid)["subject"] is None
