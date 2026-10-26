"""The citation library at scale: search, keyset paging, duplicates, stored PDFs and deleting an entry in use.

Protects the library page and every picker that reads citations. Breaking it makes a 10,000-entry library slow or
lose entries between pages, and lets a delete or a missing file go unnoticed. Helps the user and the next developer.
"""

from __future__ import annotations

import json
import time

import pytest

from src import db, migrations
from src.routers import notebook as notebook_router

COUNT = 10_000
YEARS = ["", "1850", "1999", "2010", "2024", "ca. 1900"]


def _generated_rows():
    for i in range(COUNT):
        yield (f"c{i:05d}", "book" if i % 3 else "article-journal", f"Title {i % 500:03d} volume {i}",
               json.dumps([{"family": f"Family{i % 97}", "given": "Ana"}]), YEARS[i % len(YEARS)], "2026-10-26T00:00:00")


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    with db.connect(tmp_path_factory.mktemp("big") / "cache.sqlite") as c:
        c.executemany("INSERT INTO citations (uid, type, title, authors_json, year, created_at) VALUES (?, ?, ?, ?, ?, ?)", list(_generated_rows()))
        c.commit()
        yield c


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _walk(conn, **kwargs):
    seen, after, pages = [], "", 0
    while True:
        page = db.page_citations(conn, after=after, **kwargs)
        seen += [c["uid"] for c in page["items"]]
        pages += 1
        after = page["next"]
        if not after:
            return seen, pages


def test_keyset_paging_visits_every_entry_once_in_title_order(big):
    seen, pages = _walk(big)
    assert len(seen) == COUNT and len(set(seen)) == COUNT
    assert pages == COUNT // db.citation_library.PAGE_SIZE
    titles = [r[0].casefold() for r in big.execute("SELECT title FROM citations ORDER BY title COLLATE NOCASE, uid")]
    assert [big.execute("SELECT title FROM citations WHERE uid = ?", (u,)).fetchone()[0].casefold() for u in seen[:200]] == titles[:200]


@pytest.mark.parametrize("sort", ["type", "year", "author"])
def test_every_sort_pages_without_losing_or_repeating_entries(big, sort):
    seen, _ = _walk(big, sort=sort, sort2="title")
    assert len(seen) == COUNT and len(set(seen)) == COUNT


def test_deep_page_and_search_stay_fast_on_ten_thousand_entries(big):
    start = time.perf_counter()
    first = db.page_citations(big)
    last_cursor = ""
    for _ in range(150):
        last_cursor = db.page_citations(big, after=last_cursor)["next"]
    db.page_citations(big, q="volume 7777")
    assert time.perf_counter() - start < 2
    assert first["total"] == COUNT


def test_search_matches_title_and_author_prefixes(big):
    assert [c["uid"] for c in db.page_citations(big, q="volume 7777")["items"]] == ["c07777"]
    assert db.page_citations(big, q="family96 ana")["total"] == len([i for i in range(COUNT) if i % 97 == 96])


def test_search_ignores_punctuation_that_is_fts_syntax(big):
    assert db.page_citations(big, q='"title* (')["total"] > 0
    assert db.page_citations(big, q="")["total"] == COUNT


def test_filters_combine_type_author_and_year_range(big):
    page = db.page_citations(big, types=["article-journal"], authors=["Family5, Ana"], year_lo=1990, year_hi=2011)
    expected = [i for i in range(COUNT) if i % 3 == 0 and i % 97 == 5 and YEARS[i % 6] in ("1999", "2010")]
    assert page["total"] == len(expected)


def test_search_index_follows_edits_and_deletes(conn):
    uid = db.upsert_citation(conn, {"title": "Alpha Study", "authors": [{"family": "Kafka", "given": "Franz"}]})
    assert db.page_citations(conn, q="kafka")["total"] == 1
    db.upsert_citation(conn, {"uid": uid, "title": "Beta Study", "authors": []})
    assert db.page_citations(conn, q="kafka")["total"] == 0
    assert db.page_citations(conn, q="beta")["total"] == 1
    db.delete_citation(conn, uid)
    assert db.page_citations(conn, q="beta")["total"] == 0


def test_migration_indexes_entries_that_already_exist(conn):
    conn.execute("INSERT INTO citations (uid, title) VALUES ('old', 'Legacy Treatise')")
    conn.execute("DELETE FROM citations_fts")
    conn.commit()
    assert db.page_citations(conn, q="legacy")["total"] == 0
    migrations._citations_search_and_files(conn)
    migrations._citations_search_and_files(conn)
    assert db.page_citations(conn, q="legacy")["total"] == 1


def test_duplicate_is_found_by_doi_isbn_or_title_year_author(conn):
    db.upsert_citation(conn, {"uid": "a", "title": "Capital", "year": "1867", "authors": [{"family": "Marx", "given": "K"}], "doi": "10.1/X", "isbn": "978-1-23"})
    assert db.find_duplicate(conn, {"title": "Other", "doi": "10.1/x"})["uid"] == "a"
    assert db.find_duplicate(conn, {"title": "Other", "isbn": "9781 23"})["uid"] == "a"
    assert db.find_duplicate(conn, {"title": "capital", "year": "1867", "authors": [{"family": "marx"}]})["uid"] == "a"
    assert db.find_duplicate(conn, {"title": "Capital", "year": "1868", "authors": [{"family": "Marx"}]}) is None
    assert db.find_duplicate(conn, {"title": "Capital", "year": "1867", "authors": [{"family": "Marx"}]}, exclude_uid="a") is None


def _create(conn, title, **extra):
    form = dict(type="book", year="", container_title="", author_family=[], author_given=[], x_requested_with="fetch", conn=conn)
    form.update(extra)
    return notebook_router.create_citation(title=title, **form)


def test_creating_a_duplicate_is_refused_unless_allowed(conn):
    assert _create(conn, "Capital", doi="10.1/x").status_code == 200
    refused = _create(conn, "Capital again", doi="10.1/x")
    assert refused.status_code == 422
    assert db.page_citations(conn)["total"] == 1
    assert _create(conn, "Capital again", doi="10.1/x", allow_duplicate="1").status_code == 200
    assert db.page_citations(conn)["total"] == 2


def _edition(conn, citation_uid, **fields):
    return db.save_edition(conn, citation_uid, {"label": "Paperback", **fields})


def test_a_book_holds_several_editions_each_with_its_own_pdf(conn):
    uid = db.upsert_citation(conn, {"title": "Capital"})
    first, second = _edition(conn, uid, year="1867"), _edition(conn, uid, label="Penguin", year="1976", publisher="Penguin")
    assert db.set_edition_file(conn, first, b"%PDF-1.4 a", "german.pdf") is None
    assert db.set_edition_file(conn, second, b"%PDF-1.4 b", "english.pdf") is None
    editions = db.list_editions(conn, uid)
    assert [e["year"] for e in editions] == ["1867", "1976"] and {e["file_state"] for e in editions} == {"ok"}
    assert db.edition_file_path(conn, first).read_bytes().endswith(b"a")
    assert db.edition_file_path(conn, second).read_bytes().endswith(b"b")


def test_deleting_the_book_deletes_its_editions_and_their_files(conn):
    uid = db.upsert_citation(conn, {"title": "Paper"})
    ed = _edition(conn, uid)
    db.set_edition_file(conn, ed, b"%PDF-1.4", "paper.pdf")
    path = db.edition_file_path(conn, ed)
    db.delete_citation(conn, uid)
    assert not path.exists() and db.get_edition(conn, ed) is None


def test_a_file_that_is_not_a_pdf_is_refused(conn):
    ed = _edition(conn, db.upsert_citation(conn, {"title": "Paper"}))
    assert db.set_edition_file(conn, ed, b"<html>", "x.pdf")
    assert db.get_edition(conn, ed)["file_state"] == "none"


def test_missing_file_is_reported_not_crashed(conn):
    uid = db.upsert_citation(conn, {"title": "Paper"})
    ed = _edition(conn, uid)
    db.set_edition_file(conn, ed, b"%PDF-1.4", "paper.pdf")
    db.edition_file_path(conn, ed).unlink()
    assert db.get_edition(conn, ed)["file_state"] == "missing"
    assert db.edition_file_path(conn, ed) is None
    assert db.sources_for(conn, [{"uid": uid}])[uid] == {"editions": 1, "files": 1, "missing": 1, "url": False}


def test_search_finds_a_book_by_the_publisher_or_isbn_of_one_edition(conn):
    uid = db.upsert_citation(conn, {"title": "Capital"})
    ed = _edition(conn, uid, publisher="Lawrence", isbn="9781")
    assert [c["uid"] for c in db.page_citations(conn, q="lawrence")["items"]] == [uid]
    db.delete_edition(conn, ed)
    assert db.page_citations(conn, q="lawrence")["total"] == 0


def test_source_filter_separates_files_links_and_metadata_only(conn):
    with_file = db.upsert_citation(conn, {"title": "A"})
    db.set_edition_file(conn, _edition(conn, with_file), b"%PDF-1.4", "a.pdf")
    link = db.upsert_citation(conn, {"title": "B", "url": "https://example.org"})
    bare = db.upsert_citation(conn, {"title": "C"})
    uids = lambda s: sorted(c["uid"] for c in db.page_citations(conn, sources=s)["items"])
    assert uids(["file"]) == [with_file] and uids(["url"]) == [link] and uids(["none"]) == [bare]
    assert uids(["file", "url"]) == sorted([with_file, link])


def test_editions_migration_moves_an_existing_pdf_into_a_first_edition(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        c.execute("ALTER TABLE citations ADD COLUMN file_name TEXT NOT NULL DEFAULT ''")
        c.execute("ALTER TABLE citations ADD COLUMN file_label TEXT NOT NULL DEFAULT ''")
        for (trigger,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'citation%'").fetchall():
            c.execute(f"DROP TRIGGER {trigger}")
        c.execute("DROP TABLE citation_editions")
        c.execute("INSERT INTO citations (uid, title, file_name, file_label) VALUES ('old', 'Old', 'x.pdf', 'x.pdf')")
        c.commit()
        from src.migrations_citations import citation_editions
        citation_editions(c)
        citation_editions(c)
        assert [e["file_name"] for e in db.list_editions(c, "old")] == ["x.pdf"]
        assert "file_name" not in {r[1] for r in c.execute("PRAGMA table_info(citations)")}


def test_picker_options_hold_the_chosen_entry_and_only_a_few_matches(big):
    items = db.picker_items(big, ["c00042"], q="title", limit=30)
    assert items[0]["uid"] == "c00042" and len(items) <= 31
    assert len(db.author_options(big, "family1", limit=10)) <= 10


class _Upload:
    def __init__(self, data: bytes, name="paper.pdf"):
        import io
        self.file, self.filename = io.BytesIO(data), name


def _save(conn, uid="", title="Capital", **form):
    args = dict(type="book", year="1867", container_title="", author_family=["Marx"], author_given=["Karl"], x_requested_with="fetch", conn=conn, title=title)
    args.update(form)
    if uid:
        return notebook_router.update_citation(uid, **args)
    return notebook_router.create_citation(**args)


def test_the_window_saves_the_book_and_a_new_edition_with_a_local_file(conn):
    resp = _save(conn, status="reading", rating="4", keywords="economics, history ,", edition_uid="", ed_source="local", ed_year="1976",
                 ed_publisher="Penguin", ed_isbn="978-0", file=_Upload(b"%PDF-1.4"))
    uid = json.loads(resp.body)["uid"]
    c = db.get_citation(conn, uid)
    assert (c["status"], c["rating"], c["keywords"]) == ("reading", 4, ["economics", "history"])
    [edition] = db.list_editions(conn, uid)
    assert (edition["source"], edition["file_state"], edition["publisher"]) == ("local", "ok", "Penguin")
    assert c["publisher"] == "Penguin" and c["year"] == "1867"


def test_saving_without_edition_details_makes_no_empty_edition(conn):
    uid = json.loads(_save(conn, edition_uid="", ed_source="none").body)["uid"]
    assert db.list_editions(conn, uid) == []


def test_changing_an_edition_to_a_link_or_none_removes_its_stored_file(conn):
    uid = json.loads(_save(conn, edition_uid="", ed_source="local", ed_year="1900", file=_Upload(b"%PDF-1.4")).body)["uid"]
    [edition] = db.list_editions(conn, uid)
    path = db.edition_file_path(conn, edition["uid"])
    _save(conn, uid, edition_uid=edition["uid"], ed_source="link", ed_year="1900", ed_url="https://example.org/book")
    assert not path.exists()
    assert [(e["source"], e["url"]) for e in db.list_editions(conn, uid)] == [("link", "https://example.org/book")]
    _save(conn, uid, edition_uid=edition["uid"], ed_source="none", ed_year="1900", ed_url="https://ignored")
    assert db.list_editions(conn, uid)[0]["source"] == "none"


def test_an_edition_can_be_deleted_from_the_window(conn):
    uid = json.loads(_save(conn, edition_uid="", ed_source="none", ed_year="1900").body)["uid"]
    [edition] = db.list_editions(conn, uid)
    _save(conn, uid, edition_uid=edition["uid"], ed_source="none", delete_edition="1")
    assert db.list_editions(conn, uid) == []


def test_saving_the_book_alone_keeps_stored_keywords_and_details(conn):
    uid = db.upsert_citation(conn, {"title": "Capital", "keywords": ["a"], "status": "read", "rating": 5, "publisher": "Old"})
    db.upsert_citation(conn, {"uid": uid, "title": "Capital again"})
    c = db.get_citation(conn, uid)
    assert (c["keywords"], c["status"], c["rating"], c["publisher"]) == (["a"], "read", 5, "Old")


def test_editions_migration_moves_the_work_level_details_into_a_first_edition(conn):
    conn.execute("INSERT INTO citations (uid, title, year, publisher, isbn, url) VALUES ('old', 'Old', '1950', 'Pub', '123', 'https://x.org')")
    conn.commit()
    migrations.citation_editions(conn)
    migrations.citation_editions(conn)
    [e] = db.list_editions(conn, "old")
    assert (e["publisher"], e["isbn"], e["source"], e["year"]) == ("Pub", "123", "link", "1950")
    assert db.get_citation_raw(conn, "old")["publisher"] == ""


def test_duplicate_found_through_an_edition_doi(conn):
    uid = json.loads(_save(conn, edition_uid="", ed_source="none", ed_doi="10.5/ab").body)["uid"]
    assert db.find_duplicate(conn, {"title": "Other", "doi": "10.5/AB"})["uid"] == uid


def test_the_window_renders_for_a_new_book_a_new_media_and_an_edited_book(conn):
    from tests.test_notebook_citations import _bare_request

    uid = json.loads(_save(conn, edition_uid="", ed_source="local", ed_year="1999", file=_Upload(b"%PDF-1.4")).body)["uid"]
    new = notebook_router.new_citation_modal(_bare_request(), kind="media", conn=conn).body.decode()
    assert "Add media" in new and 'name="ed_source"' in new
    edit = notebook_router.edit_citation_modal(uid, _bare_request(), conn=conn).body.decode()
    assert "Edit book" in edit and 'data-library-editions' in edit and "paper.pdf" in edit
    page = notebook_router.citations_library(_bare_request(), type=[], author=[], year_from="", year_to="", sort="title", conn=conn)
    assert "1 entry" in page.body.decode()
    assert "paper.pdf" in notebook_router.citation_view_modal(uid, _bare_request(), conn=conn).body.decode()


def test_delete_confirmation_names_what_still_uses_the_entry(conn):
    uid = db.upsert_citation(conn, {"title": "Used"})
    db.upsert_notebook_document(conn, {"uid": "d1", "title": "N", "content_json": '{"blocks": []}', "document_type": "full", "note_type": "notes", "created_at": "2026-10-26", "updated_at": "2026-10-26"})
    db.set_notebook_citations(conn, "d1", [uid])
    label = notebook_router._citation_delete_label(conn, db.get_citation(conn, uid))
    assert "1 notes" in label
    db.delete_citation(conn, uid)
    assert db.list_notebook_citations(conn, "d1") == []
