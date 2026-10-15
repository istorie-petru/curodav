"""A note has at most one project and one label; the migration trims older notes and keeps a report."""

import json

import pytest

from src import db, migrations


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _project(conn, name):
    db.upsert_label_config(conn, {"name": name, "is_project": True})


def _note(conn, uid, tags):
    db.upsert_notebook_document(conn, {"uid": uid, "title": uid, "content_json": "{}", "document_type": "full", "note_type": "", "tags": tags, "created_at": "2026-10-01", "updated_at": "2026-10-01"})


def test_saving_a_note_keeps_only_its_first_label(conn):
    _note(conn, "n1", ["History", "Reading"])
    assert db.get_notebook_document(conn, "n1")["tags"] == ["History"]


def test_enforcement_reports_what_it_drops_in_attach_order(conn):
    db.set_object_labels(conn, "notebook", "n2", ["Zeta", "Alpha"])
    conn.execute("INSERT INTO notebook_documents (uid, title) VALUES ('n2', 'Two labels')")
    report = db.enforce_one_label_and_project(conn)
    assert report == [{"uid": "n2", "title": "Two labels", "kept": ["Zeta"], "dropped": ["Alpha"]}]
    assert db.get_notebook_document(conn, "n2")["tags"] == ["Zeta"]


def test_the_migration_stores_a_report_for_the_notebook_home(conn):
    db.set_object_labels(conn, "notebook", "n3", ["One", "Two"])
    conn.execute("INSERT INTO notebook_documents (uid, title) VALUES ('n3', 'Three')")
    migrations._notes_have_one_label_and_project(conn)
    assert json.loads(db.get_app_meta(conn, "notebook_label_report"))[0]["dropped"] == ["Two"]


def test_a_note_keeps_one_project_and_one_label_together(conn):
    _project(conn, "Thesis")
    _project(conn, "Paper")
    _note(conn, "n4", ["Reading", "Thesis", "Paper", "History"])
    assert sorted(db.get_notebook_document(conn, "n4")["tags"]) == ["Reading", "Thesis"]


def _folders(conn):
    return {(f["kind"], f["name"]): f["count"] for row in db.list_notebook_folders(conn).values() for f in row}


def test_a_note_is_in_its_project_folder_not_also_its_label_folder(conn):
    _project(conn, "Thesis")
    _note(conn, "a", ["Thesis", "Reading"])
    _note(conn, "b", ["Reading"])
    _note(conn, "c", [])
    assert _folders(conn) == {("project", "Thesis"): 1, ("label", "Reading"): 1, ("unfiled", ""): 1}


def test_an_archived_project_sends_its_notes_back_to_their_label_folder(conn):
    _project(conn, "Thesis")
    _note(conn, "a", ["Thesis", "Reading"])
    _note(conn, "b", ["Thesis"])
    db.upsert_label_config(conn, {"name": "Thesis", "archived_at": "2026-10-01"})
    assert _folders(conn) == {("label", "Reading"): 1, ("unfiled", ""): 1}


def test_folders_list_projects_before_labels_and_unfiled_last(conn):
    _project(conn, "Thesis")
    _note(conn, "a", ["Thesis"])
    _note(conn, "b", ["Zeta"])
    _note(conn, "c", ["Alpha"])
    _note(conn, "d", [])
    folders = db.list_notebook_folders(conn)
    assert [f["name"] for f in folders["projects"]] == ["Thesis"]
    assert [f["name"] for f in folders["labels"]] == ["Alpha", "Zeta", ""]


def test_a_folder_pages_its_notes_and_shows_the_first_line_as_subtitle(conn):
    for i in range(5):
        db.upsert_notebook_document(conn, {"uid": f"n{i}", "title": f"Note {i}", "document_type": "full", "note_type": "",
            "content_json": json.dumps({"blocks": [{"type": "header", "data": {"text": "Head", "level": 2}}, {"type": "paragraph", "data": {"text": "First <b>line</b> here"}}]}),
            "tags": ["Reading"], "created_at": f"2026-10-0{5 - i}", "updated_at": f"2026-10-0{i + 1}"})
    page, total = db.list_notebook_folder_documents(conn, "label", "Reading", limit=2, offset=0)
    assert total == 5 and [r["title"] for r in page] == ["Note 0", "Note 1"]  # newest created first
    edited, _ = db.list_notebook_folder_documents(conn, "label", "Reading", sort="updated", limit=2, offset=0)
    assert [r["title"] for r in edited] == ["Note 4", "Note 3"]
    assert page[0]["subtitle"] == "First line here"
