"""An attached file can name its language; reading aloud and Calibre follow it."""

import pytest

from src import book_speech, db
from src.routers import notebook


@pytest.fixture
def conn(tmp_path):
    with db.connect(tmp_path / "t.db") as c:
        yield c


def test_language_codes_are_normalised_and_mapped_to_calibre():
    assert book_speech.language_code("ro-RO") == "ro" and book_speech.language_code("RON") == "ro" and book_speech.language_code("klingon") == ""
    assert book_speech.to_calibre("ro") == ["ron"] and book_speech.to_calibre("") == []
    assert book_speech.from_calibre(["xx", "fra"]) == "fr" and book_speech.from_calibre([]) == ""


def test_the_edition_form_saves_and_clears_the_language_without_touching_other_saves(conn):
    uid = db.upsert_citation(conn, {"title": "Ion", "type": "book", "authors": []})
    edition = db.save_edition(conn, uid, {"publisher": "X"})
    notebook._write_edition(conn, uid, edition, {"publisher": "X", "language": "ro"}, "local", None, "")
    assert db.get_edition(conn, edition)["language"] == "ro"
    db.save_edition(conn, uid, {"publisher": "Y"}, edition)  # another kind of save leaves it alone
    assert db.get_edition(conn, edition)["language"] == "ro"
    notebook._write_edition(conn, uid, edition, {"publisher": "Y", "language": ""}, "local", None, "")
    assert db.get_edition(conn, edition)["language"] == ""
    db.set_edition_language(conn, edition, "not a language")
    assert db.get_edition(conn, edition)["language"] == ""


def test_the_language_goes_to_calibre_and_an_unnamed_one_leaves_calibres_own(conn):
    from src import media_books

    uid = db.upsert_citation(conn, {"title": "Ion", "type": "book", "authors": []})
    edition = db.save_edition(conn, uid, {})
    db.set_edition_language(conn, edition, "ro")
    meta = media_books.meta_for(conn, db.get_citation_raw(conn, uid), db.get_edition(conn, edition))
    assert meta.languages == ["ron"]
    db.set_edition_language(conn, edition, "")
    assert media_books.meta_for(conn, db.get_citation_raw(conn, uid), db.get_edition(conn, edition)).languages == []


def test_a_library_entry_keeps_a_space_that_follows_renames_and_filters_the_list(conn):
    db.ensure_group(conn, "Reading")
    uid = db.upsert_citation(conn, {"title": "Ion", "type": "book", "authors": [], "space": "Reading", "keywords": ["classic"]})
    other = db.upsert_citation(conn, {"title": "Dune", "type": "book", "authors": []})
    assert db.get_citation_raw(conn, uid)["space"] == "Reading" and db.get_citation_raw(conn, other)["space"] == ""
    db.upsert_citation(conn, {"uid": uid, "title": "Ion", "type": "book", "authors": []})  # a save without it keeps it
    assert db.get_citation_raw(conn, uid)["space"] == "Reading"
    assert [c["title"] for c in db.page_citations(conn, spaces=["reading"])["items"]] == ["Ion"]
    from src import library_query

    assert library_query.parse("space:Reading ion", {})["spaces"] == ["Reading"]
    db.rename_group(conn, "Reading", "Books")
    assert db.get_citation_raw(conn, uid)["space"] == "Books"
    db.delete_group(conn, "Books")
    assert db.get_citation_raw(conn, uid)["space"] == ""
    assert db.keyword_options(conn) == ["classic"]

