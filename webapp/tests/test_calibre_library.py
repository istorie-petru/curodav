"""The Calibre-compatible library Curodav writes: Calibre's own schema, folder layout and metadata.opf, read back by real Calibre."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import subprocess

import pytest
from PIL import Image

from src import calibre_library as cl

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 60), (10, 120, 200)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture()
def lib(tmp_path):
    cl.create(tmp_path / "library")
    return cl.Library(tmp_path / "library")


def _meta(**fields) -> cl.BookMeta:
    base = dict(title="The Left Hand of Darkness", authors=["Ursula K. Le Guin"], author_sorts=["Le Guin, Ursula K."], pubdate="1969",
                publisher="Ace", isbn="978-0-441-47812-5", tags=["sf", "classic"], series="Hainish", series_index=4, rating=10,
                comments="Winter.", languages=["eng"])
    base.update(fields)
    return cl.BookMeta(**base)


def test_title_sort_moves_a_leading_article_to_the_end():
    assert cl.title_sort("The Left Hand of Darkness") == "Left Hand of Darkness, The"
    assert cl.title_sort("Anathem") == "Anathem"


def test_path_names_drop_accents_and_unsafe_characters_as_calibre_does():
    assert cl.safe_name("Mâna stângă: a întunericului/test?") == "Mana stanga_ a intunericului_test_"


def test_a_new_library_has_calibres_schema_and_version(lib):
    with sqlite3.connect(lib.db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == cl.USER_VERSION
        assert conn.execute("SELECT count(*) FROM library_id").fetchone()[0] == 1


def test_a_book_is_written_with_its_folder_files_cover_and_opf(lib):
    book = lib.add_book(_meta())
    lib.add_format(book, PDF, "pdf")
    lib.set_cover(book, _jpeg())
    b = lib.book(book)
    assert b["path"] == "Ursula K. Le Guin/The Left Hand of Darkness (1)"
    assert (b["authors"], b["author_sorts"], b["isbn"], b["tags"], b["series"], b["rating"]) == (
        ["Ursula K. Le Guin"], ["Le Guin, Ursula K."], "9780441478125", ["classic", "sf"], "Hainish", 10)
    assert b["formats"][0]["path"].read_bytes() == PDF
    assert b["cover"].is_file()
    opf = (lib.folder / b["path"] / "metadata.opf").read_text()
    assert b["uuid"] in opf and "<dc:subject>sf</dc:subject>" in opf and 'href="cover.jpg"' in opf


def test_a_new_title_moves_the_folder_and_renames_the_files(lib):
    book = lib.add_book(_meta())
    lib.add_format(book, PDF, "pdf")
    lib.update_book(book, _meta(title="The Dispossessed", tags=["sf"]))
    b = lib.book(book)
    assert b["path"] == "Ursula K. Le Guin/The Dispossessed (1)"
    assert b["formats"][0]["path"].name == "The Dispossessed - Ursula K. Le Guin.pdf" and b["formats"][0]["path"].is_file()
    assert not (lib.folder / "Ursula K. Le Guin/The Left Hand of Darkness (1)").exists()
    with sqlite3.connect(lib.db_path) as conn:
        assert [r[0] for r in conn.execute("SELECT name FROM tags")] == ["sf"]


def test_deleting_a_book_removes_its_folder_and_unused_names(lib):
    book = lib.add_book(_meta())
    lib.add_format(book, PDF, "pdf")
    lib.delete_book(book)
    assert lib.books() == []
    assert not (lib.folder / "Ursula K. Le Guin").exists()
    with sqlite3.connect(lib.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM authors").fetchone()[0] == 0


def test_an_unknown_file_type_is_refused(lib):
    book = lib.add_book(_meta())
    with pytest.raises(cl.CalibreError):
        lib.add_format(book, b"MZ", "exe")


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("calibredb") is None, reason="Calibre is not installed")
def test_calibre_itself_reads_and_checks_a_library_curodav_wrote(lib, tmp_path):
    first = lib.add_book(_meta())
    lib.add_format(first, PDF, "pdf")
    lib.set_cover(first, _jpeg())
    second = lib.add_book(_meta(title="Vagabond, Vol. 1", authors=["Takehiko Inoue"], author_sorts=["Inoue, Takehiko"], series="", tags=["manga"], rating=0))
    lib.add_format(second, b"PK\x03\x04", "cbz")
    lib.update_book(first, _meta(title="The Dispossessed"))
    env = {"HOME": str(tmp_path), "CALIBRE_CONFIG_DIRECTORY": str(tmp_path / "calibre-config"), "PATH": "/usr/bin:/bin"}
    listed = subprocess.run(["calibredb", "--library-path", str(lib.folder), "list", "--for-machine", "--fields", "title,authors,formats,identifiers,tags,uuid"],
                            capture_output=True, text=True, timeout=120, env=env)
    assert listed.returncode == 0, listed.stderr
    books = {b["uuid"]: b for b in json.loads(listed.stdout)}
    assert books[first]["title"] == "The Dispossessed" and books[first]["identifiers"] == {"isbn": "9780441478125"}
    assert books[second]["authors"] == "Takehiko Inoue" and books[second]["formats"][0].endswith(".cbz")
    check = subprocess.run(["calibredb", "--library-path", str(lib.folder), "check_library", "--csv"], capture_output=True, text=True, timeout=120, env=env)
    assert check.returncode == 0, check.stderr
    problems = [line for line in check.stdout.splitlines() if line.strip() and not line.startswith("Vacuuming")]
    assert problems == [], check.stdout


# Curodav entries kept in the library

from src import db, media_books  # noqa: E402
from src.routers import notebook as notebook_router  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        assert media_books.set_library_path(c, str(tmp_path / "books")) is None
        yield c


class _File:
    def __init__(self, data: bytes, filename: str):
        self.filename = filename
        self.file = io.BytesIO(data)


def _save_book(conn, **form):
    args = dict(type="book", year="1974", container_title="", author_family=["Le Guin"], author_given=["Ursula K."], edition_uid="",
                ed_source="none", ed_publisher="Harper", ed_isbn="9780060512750", x_requested_with="fetch", conn=conn)
    args.update(form)
    return json.loads(notebook_router.create_citation(title="The Dispossessed", **args).body)["uid"]


def test_an_empty_folder_becomes_a_library_and_a_full_one_is_refused(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        (tmp_path / "busy").mkdir()
        (tmp_path / "busy" / "notes.txt").write_text("x")
        assert "other files" in media_books.set_library_path(c, str(tmp_path / "busy"))
        assert media_books.set_library_path(c, "relative/path") == "Give the full path of the folder"


def test_a_saved_book_becomes_a_calibre_book_with_its_uploaded_file(conn):
    uid = _save_book(conn, ed_source="local", file=_File(b"PK\x03\x04epub", "dispossessed.epub"), keywords="sf, utopia")
    [edition] = db.list_editions(conn, uid)
    assert (edition["source"], edition["file_label"]) == ("local", "EPUB")
    b = media_books.library(conn).book(edition["calibre_uuid"])
    assert (b["title"], b["authors"], b["author_sorts"], b["publisher"], b["isbn"], b["tags"]) == (
        "The Dispossessed", ["Ursula K. Le Guin"], ["Le Guin, Ursula K."], "Harper", "9780060512750", ["sf", "utopia"])
    path, name, mime = media_books.file_for(conn, edition["uid"])
    assert path.read_bytes() == b"PK\x03\x04epub" and mime == "application/epub+zip"


def test_a_file_type_calibre_does_not_keep_is_refused(conn):
    resp = notebook_router.create_citation(title="X", type="book", year="", container_title="", author_family=[], author_given=[], edition_uid="",
                                           ed_source="local", ed_year="2000", file=_File(b"MZ", "setup.exe"), x_requested_with="fetch", conn=conn)
    assert resp.status_code == 422


def test_films_stay_out_of_the_book_library(conn):
    notebook_router.create_citation(title="Dune", type="film", year="2021", container_title="", author_family=[], author_given=[], x_requested_with="fetch", conn=conn)
    assert media_books.library(conn).books() == []


def test_deleting_the_entry_deletes_its_calibre_book(conn):
    uid = _save_book(conn, ed_source="local", file=_File(b"%PDF-1.4", "a.pdf"))
    notebook_router.delete_citation(uid, x_requested_with="fetch", conn=conn)
    assert media_books.library(conn).books() == []


def test_books_already_in_the_library_are_added_once(conn):
    lib = media_books.library(conn)
    lib.add_format(lib.add_book(cl.BookMeta(title="Vagabond 1", authors=["Takehiko Inoue"], tags=["manga"], rating=8)), b"PK", "cbz")
    lib.add_book(cl.BookMeta(title="Capital", authors=["Karl Marx"], pubdate="1867"))
    assert media_books.import_plan(conn)["new"].__len__() == 2
    assert media_books.import_books(conn) == 2
    assert media_books.import_books(conn) == 0
    by_title = {c["title"]: c for c in db.list_citations(conn)}
    assert by_title["Vagabond 1"]["type"] == "manga" and by_title["Vagabond 1"]["score"] == 80.0
    assert by_title["Capital"]["authors"] == [{"family": "Marx", "given": "Karl"}]


def test_files_in_the_old_store_move_into_the_library(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "Old book", "type": "book"})
        edition = db.save_edition(c, uid, {"year": "1990"})
        assert db.set_edition_file(c, edition, b"%PDF-1.4 old", "old.pdf") is None
        old_path = db.edition_file_path(c, edition)
        media_books.set_library_path(c, str(tmp_path / "books"))
        assert len(media_books.legacy_files(c)) == 1
        assert media_books.move_legacy_files(c) == (1, [])
        assert not old_path.exists()
        assert media_books.file_for(c, edition)[0].read_bytes() == b"%PDF-1.4 old"


def test_choosing_the_folder_writes_the_books_already_in_curodav(tmp_path):
    from src.routers import media as media_router

    with db.connect(tmp_path / "cache.sqlite") as c:
        db.upsert_citation(c, {"title": "Capital", "type": "book", "authors": [{"family": "Marx", "given": "Karl"}]})
        db.upsert_citation(c, {"title": "Dune", "type": "film"})
        body = json.loads(media_router.save_book_library(path=str(tmp_path / "books"), x_requested_with="fetch", conn=c).body)
        assert body["written"] == 1
        assert [b["title"] for b in media_books.library(c).books()] == ["Capital"]
        assert media_books.push_all(c) == 0


def test_edits_made_in_calibre_are_read_back(conn):
    uid = _save_book(conn, keywords="sf")
    media_books.pull(conn, force=True)
    [edition] = db.list_editions(conn, uid)
    lib = media_books.library(conn)
    lib.update_book(edition["calibre_uuid"], cl.BookMeta(title="The Dispossessed: An Ambiguous Utopia", authors=["Ursula K. Le Guin"],
                                                         author_sorts=["Le Guin, Ursula K."], pubdate="1974", publisher="Harper & Row",
                                                         isbn="9780060125639", tags=["sf", "anarchism"], rating=8, comments="<p>Two worlds.</p>"))
    assert media_books.pull(conn)["updated"] == 1
    c = db.get_citation(conn, uid)
    assert (c["title"], c["subtitle"], c["keywords"], c["summary"], c["score"]) == ("The Dispossessed", "An Ambiguous Utopia", ["anarchism", "sf"], "Two worlds.", 80.0)
    assert (c["publisher"], c["isbn"]) == ("Harper & Row", "9780060125639")
    assert media_books.pull(conn) == {"updated": 0, "unlinked": 0, "added": 0}


def test_a_book_deleted_or_added_in_calibre_is_noticed(conn):
    uid = _save_book(conn)
    [edition] = db.list_editions(conn, uid)
    lib = media_books.library(conn)
    lib.delete_book(edition["calibre_uuid"])
    lib.add_book(cl.BookMeta(title="Anathem", authors=["Neal Stephenson"]))
    result = media_books.pull(conn)
    assert (result["unlinked"], result["added"]) == (1, 1)
    assert db.list_editions(conn, uid)[0]["calibre_uuid"] == ""
    assert "Anathem" in [c["title"] for c in db.list_citations(conn)]


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("calibredb") is None, reason="Calibre is not installed")
def test_an_edit_made_with_calibre_itself_is_read_back(conn, tmp_path):
    uid = _save_book(conn)
    media_books.pull(conn, force=True)
    [edition] = db.list_editions(conn, uid)
    lib = media_books.library(conn)
    book_id = str(lib.book(edition["calibre_uuid"])["id"])
    env = {"HOME": str(tmp_path), "CALIBRE_CONFIG_DIRECTORY": str(tmp_path / "calibre-config"), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(["calibredb", "--library-path", str(lib.folder), "set_metadata", book_id, "--field", "tags:sf,classic", "--field", "publisher:Avon"],
                          capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr
    assert media_books.pull(conn)["updated"] == 1
    c = db.get_citation(conn, uid)
    assert (c["keywords"], c["publisher"]) == (["classic", "sf"], "Avon")


def test_the_installer_folder_becomes_the_library_on_first_use(tmp_path, monkeypatch):
    folder = tmp_path / "srv-library"
    folder.mkdir()
    monkeypatch.setenv(media_books.ENV_PATH, str(folder))
    with db.connect(tmp_path / "c.sqlite") as c:
        assert media_books.library(c) is not None and (folder / "metadata.db").is_file()
