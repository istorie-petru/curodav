"""A note carries any number of tags of its one space; folders are the spaces, with the tags as sub-folders."""

import json

import pytest

from src import db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        db.ensure_group(c, "Reading")
        db.upsert_label_config(c, {"name": "Reading", "label_group": "Reading"})
        db.upsert_label_config(c, {"name": "History", "label_group": "Reading"})
        yield c


def _note(conn, uid, tags, **extra):
    db.upsert_notebook_document(conn, {"uid": uid, "title": uid, "content_json": "{}", "document_type": "full", "note_type": "", "tags": tags,
                                       "created_at": "2026-10-01", "updated_at": "2026-10-01", **extra})


def test_a_note_keeps_all_its_tags_and_sits_in_their_space(conn):
    _note(conn, "n1", ["History", "Reading"])
    assert db.get_notebook_document(conn, "n1")["tags"] == ["History", "Reading"]
    assert db.notebook_folder_of(conn, "n1") == ("space", "Reading")


def test_a_note_with_no_space_is_unfiled_and_folders_list_spaces_first(conn):
    _note(conn, "n1", ["History"])
    _note(conn, "n2", [])
    counts = {(f["kind"], f["name"]): f["count"] for f in db.list_notebook_folders(conn)["spaces"]}
    assert counts == {("space", "Reading"): 1, ("unfiled", ""): 1}


def test_a_folder_pages_its_notes_and_shows_the_first_line_as_subtitle(conn):
    for i in range(5):
        db.upsert_notebook_document(conn, {"uid": f"n{i}", "title": f"Note {i}", "document_type": "full", "note_type": "",
            "content_json": json.dumps({"blocks": [{"type": "header", "data": {"text": "Head", "level": 2}}, {"type": "paragraph", "data": {"text": "First <b>line</b> here"}}]}),
            "tags": ["Reading"], "created_at": f"2026-10-0{5 - i}", "updated_at": f"2026-10-0{i + 1}"})
    page, total = db.list_notebook_folder_documents(conn, "space", "Reading", limit=2, offset=0)
    assert total == 5 and [r["title"] for r in page] == ["Note 0", "Note 1"]  # newest created first
    edited, _ = db.list_notebook_folder_documents(conn, "space", "Reading", sort="updated", limit=2, offset=0)
    assert [r["title"] for r in edited] == ["Note 4", "Note 3"]
    assert page[0]["subtitle"] == "First line here"
