"""The Library search box: key:value terms, and the list that only shows when something is searched."""

from fastapi.testclient import TestClient

from src import db, library_query
from src.deps import get_db
from src.main import app

NAMES = {"book": "Book", "film": "Film"}


def test_terms_become_filters_and_the_rest_stays_text():
    out = library_query.parse('dune type:film status:reading year:2000-2010 author:"le guin" tag:x bogus:1', NAMES)
    assert out["types"] == ["film"] and out["statuses"] == ["current"] and out["tags"] == ["x"]
    assert (out["year_lo"], out["year_hi"]) == (2000, 2010)
    assert out["text"] == "dune le guin bogus:1"


def test_year_comparisons():
    assert library_query.parse("year:>1990", NAMES)["year_lo"] == 1991
    assert library_query.parse("year:<1990", NAMES)["year_hi"] == 1989


def test_the_page_lists_only_when_searching(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        db.upsert_citation(c, {"title": "Alpha Book", "type": "book", "year": "1999"})
        db.upsert_citation(c, {"title": "Beta Film", "type": "film", "year": "2005"})
        app.dependency_overrides[get_db] = lambda: c
        try:
            cl = TestClient(app)
            bare = cl.get("/library").text
            by_type = cl.get("/library?q=type:film").text
            by_year = cl.get("/library?q=year:1990-2000").text
        finally:
            app.dependency_overrides.clear()
    assert "library-table" not in bare and "Alpha Book" not in bare
    assert "Beta Film" in by_type and "Alpha Book" not in by_type
    assert "Alpha Book" in by_year and "Beta Film" not in by_year
