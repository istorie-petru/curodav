"""Citation formats: Chicago, and the Academia Română style from the supplied two-page guide."""

from src import citation_formats as f

BOOK = {"type": "book", "title": "Din viața familiei Ion C. Brătianu", "authors": [{"given": "Sabina", "family": "Cantacuzino"}],
        "volume": "I", "place": "București", "publisher": "Editura Albatros", "year": "1993"}
ARTICLE = {"type": "article-journal", "title": "Începuturile transporturilor feroviare în Balcani", "container_title": "Revista istorică",
           "authors": [{"given": "Robert", "family": "Păiușan"}], "volume": "8", "year": "1995", "issue": "9-10", "pages": "671-677"}


def test_romanian_note_for_a_book_follows_the_guide_order():
    assert f.footnote(BOOK, "romanian", "13") == "Sabina Cantacuzino, <i>Din viața familiei Ion C. Brătianu</i>, vol. I, București, Albatros, 1993, p. 13."


def test_romanian_note_uses_f_a_when_the_book_has_no_year():
    book = {**BOOK, "year": ""}
    assert "București, Albatros, f. a., p. 101." in f.footnote(book, "romanian", "101")


def test_romanian_note_for_a_journal_article_has_roman_year_number_and_page_range():
    assert f.footnote(ARTICLE, "romanian") == (
        "Robert Păiușan, <i>Începuturile transporturilor feroviare în Balcani</i>, în <i>Revista istorică</i>, VIII, 1995, nr. 9-10, p. 671-677.")


def test_romanian_note_for_a_web_source_gives_the_address_and_the_access_date():
    web = {"type": "webpage", "title": "War Museum", "url": "www.warmuseum.ca", "accessed": "2004-11-03"}
    assert f.footnote(web, "romanian") == "www.warmuseum.ca, 3 nov. 2004."


def test_romanian_repeated_references_use_ibidem_idem_apud_cf_and_passim():
    assert f.repeated("ibidem", None, "romanian") == "Ibidem."
    assert f.repeated("ibidem", None, "romanian", "221") == "Ibidem, p. 221."
    assert f.repeated("idem", BOOK, "romanian", "101").startswith("Idem, <i>Din viața")
    assert f.repeated("confer", BOOK, "romanian", "35").startswith("Cf. Sabina Cantacuzino")
    assert f.repeated("passim", BOOK, "romanian").endswith(", passim.")
    assert f.repeated("opere_citato", BOOK, "romanian", "7") == "Sabina Cantacuzino, <i>op. cit.</i>, p. 7."
    assert ", apud Sabina Cantacuzino" in f.repeated("apud", ARTICLE, "romanian", "333", secondary=BOOK)


def test_romanian_bibliography_starts_with_the_family_name_and_may_drop_the_publisher_word():
    assert f.bibliography(BOOK, "romanian").startswith("Cantacuzino, Sabina, <i>Din viața")
    assert "București, Albatros, 1993." in f.bibliography(BOOK, "romanian")


def test_chicago_note_for_a_book_has_italic_title_and_publication_in_parentheses():
    book = {"type": "book", "title": "The Making of the English Working Class", "authors": [{"given": "E. P.", "family": "Thompson"}],
            "place": "New York", "publisher": "Pantheon", "year": "1964"}
    assert f.footnote(book, "chicago", "12") == "E. P. Thompson, <i>The Making of the English Working Class</i> (New York: Pantheon, 1964), 12."


def test_chicago_note_for_an_article_quotes_the_title_and_italicises_the_journal():
    art = {"type": "article-journal", "title": "On Time", "container_title": "Past & Present", "authors": [{"given": "E. P.", "family": "Thompson"}],
           "volume": "38", "issue": "1", "year": "1967", "pages": "56-97"}
    assert f.footnote(art, "chicago") == "E. P. Thompson, “On Time,” <i>Past &amp; Present</i> 38, no. 1 (1967): 56-97."


def test_chicago_bibliography_inverts_the_first_author_and_ends_with_publication():
    book = {"type": "book", "title": "Imagined Communities", "authors": [{"given": "Benedict", "family": "Anderson"}],
            "place": "London", "publisher": "Verso", "year": "1983", "edition": "2nd"}
    assert f.bibliography(book, "chicago") == "Anderson, Benedict. <i>Imagined Communities</i>. 2nd ed. London: Verso, 1983."


def test_chicago_names_collapse_to_et_al_from_four_authors():
    four = [{"given": g, "family": "X"} for g in "ABCD"]
    assert f.footnote({"type": "book", "title": "T", "authors": four, "year": "2000"}, "chicago").startswith("A X et al., <i>T</i>")


def test_chicago_ibidem_and_the_idem_note_drop_the_author():
    assert f.repeated("ibidem", None, "chicago", "9") == "Ibid., 9."
    assert f.repeated("idem", BOOK, "chicago", "4").startswith("Idem, <i>Din")


def test_user_text_is_escaped():
    assert "&lt;b&gt;" in f.footnote({"type": "book", "title": "<b>x</b>", "year": "2000"}, "chicago")


# ---- Routes and storage ------------------------------------------------------------------------------

import asyncio
import json

import pytest
from starlette.requests import Request

from src import db
from src.routers import notebook as router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _json_request(payload):
    request = Request({"type": "http", "method": "POST", "path": "/", "query_string": b"", "scheme": "http",
                       "server": ("testserver", 80), "root_path": "", "headers": []})

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}

    request._receive = receive
    return request


def _book(conn):
    return db.upsert_citation(conn, {"type": "book", "title": "Capitalul", "authors": [{"given": "Karl", "family": "Marx"}],
                                     "year": "1867", "place": "Hamburg", "publisher": "Meissner", "edition": "1st"})


def test_academic_fields_are_stored_and_kept_when_a_save_leaves_them_out(conn):
    uid = _book(conn)
    db.upsert_citation(conn, {"uid": uid, "type": "book", "title": "Capitalul", "year": "1867"})
    saved = db.get_citation(conn, uid)
    assert (saved["place"], saved["publisher"], saved["edition"]) == ("Hamburg", "Meissner", "1st")


def test_the_citation_format_defaults_to_chicago_and_can_be_changed(conn):
    assert db.get_citation_format(conn) == "chicago"
    db.set_citation_format(conn, "romanian")
    assert db.get_citation_format(conn) == "romanian"
    db.set_citation_format(conn, "nonsense")
    assert db.get_citation_format(conn) == "romanian"


def test_a_generated_endnote_follows_the_chosen_format(conn):
    uid = _book(conn)
    chicago = json.loads(asyncio.run(router.citation_footnote(_json_request({"kind": "page_citation", "citation": uid, "page": "5"}), conn=conn)).body)["text"]
    db.set_citation_format(conn, "romanian")
    romanian = json.loads(asyncio.run(router.citation_footnote(_json_request({"kind": "page_citation", "citation": uid, "page": "5"}), conn=conn)).body)["text"]
    assert chicago == "Karl Marx, <i>Capitalul</i>, 1st ed. (Hamburg: Meissner, 1867), 5."
    assert romanian == "Karl Marx, <i>Capitalul</i>, Hamburg, Meissner, 1867, p. 5."


def test_ibidem_needs_no_citation_and_an_unknown_citation_is_refused(conn):
    assert json.loads(asyncio.run(router.citation_footnote(_json_request({"kind": "ibidem"}), conn=conn)).body)["text"] == "Ibid."
    assert asyncio.run(router.citation_footnote(_json_request({"kind": "idem", "citation": "missing"}), conn=conn)).status_code == 404


def test_the_form_saves_the_new_fields(conn):
    router.create_citation(type="chapter", title="On Value", year="1990", container_title="Essays", doi="", url="", author_family=["Smith"],
                           author_given=["Ada"], subtitle="", edition="", volume="", issue="", pages="10-20", publisher="Verso", place="London",
                           isbn="", issn="", accessed="", institution="", degree="", editors="Ben Lee", note="", x_requested_with=None, conn=conn)
    saved = db.list_citations(conn)[0]
    assert (saved["pages"], saved["publisher"], saved["editors"]) == ("10-20", "Verso", "Ben Lee")


def test_the_bibliography_on_a_document_page_uses_the_chosen_format(conn):
    uid = _book(conn)
    db.upsert_notebook_document(conn, {"uid": "d1", "title": "D", "document_type": "full", "note_type": "", "content_json": "{}",
                                       "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    db.attach_notebook_citation(conn, "d1", uid)
    request = Request({"type": "http", "method": "GET", "path": "/notebook/d1", "query_string": b"", "scheme": "http",
                       "server": ("testserver", 80), "root_path": "", "headers": []})
    assert "Marx, Karl. <i>Capitalul</i>." in router.document_page("d1", request, conn=conn).body.decode()
