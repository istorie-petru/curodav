"""Citations (curodav-notes/documentation/plans/STATE.md's "citations are
the priority feature" decision, 2026-10-03) -- core slice coverage: db.py's
citations/notebook_citations CRUD + formatting, routers/notebook.py's
citations_router (the library) and the main router's /{uid}/bibliography
attach endpoints. No DOI/ISBN/URL lookup, no export -- not part of this
pass, see the roadmap checklist."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from starlette.requests import Request

from src import db
from src.routers import export as export_router
from src.routers import notebook as notebook_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _bare_request(path="/notebook/citations", query_string: bytes = b""):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": query_string,
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document(conn, uid="d1", title="My Document", **overrides):
    row = {
        "uid": uid, "title": title, "content_json": '{"blocks": []}',
        "document_type": "full", "note_type": "notes",
        "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_notebook_document(conn, row)
    return db.get_notebook_document(conn, uid)


def _citation(conn, uid="c1", title="A History of Something", **overrides):
    row = {
        "uid": uid, "type": "book", "title": title,
        "authors": [{"family": "Bloch", "given": "Marc"}],
        "year": "1924", "container_title": "", "doi": "", "url": "",
    }
    row.update(overrides)
    db.upsert_citation(conn, row)
    return db.get_citation(conn, uid)


class TestCitationCrud:
    def test_upsert_then_get_round_trips_authors(self, conn):
        _citation(conn)
        c = db.get_citation(conn, "c1")
        assert c["title"] == "A History of Something"
        assert c["authors"] == [{"family": "Bloch", "given": "Marc"}]

    def test_list_citations_sorted_by_title(self, conn):
        _citation(conn, uid="c1", title="Zebra Studies")
        _citation(conn, uid="c2", title="Apple Studies")
        titles = [c["title"] for c in db.list_citations(conn)]
        assert titles == ["Apple Studies", "Zebra Studies"]

    def test_update_preserves_uid(self, conn):
        _citation(conn)
        db.upsert_citation(conn, {"uid": "c1", "title": "Renamed", "authors": []})
        c = db.get_citation(conn, "c1")
        assert c["title"] == "Renamed"
        assert len(db.list_citations(conn)) == 1

    def test_delete_removes_citation_and_its_attachments(self, conn):
        _document(conn, uid="d1")
        _citation(conn)
        db.set_notebook_citations(conn, "d1", ["c1"])
        db.delete_citation(conn, "c1")
        assert db.get_citation(conn, "c1") is None
        assert db.list_notebook_citations(conn, "d1") == []

    def test_format_citation_display(self, conn):
        c = _citation(conn, container_title="Annales d'Histoire")
        display = db.format_citation_display(c)
        assert display == "Bloch, M. (1924) A History of Something. Annales d'Histoire."

    def test_format_citation_display_omits_missing_pieces(self, conn):
        c = _citation(conn, uid="c2", title="Untitled Draft", authors=[], year="", container_title="")
        assert db.format_citation_display(c) == "Untitled Draft."


class TestNotebookCitations:
    def test_set_then_list_round_trips_in_order(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1", title="First")
        _citation(conn, uid="c2", title="Second")
        db.set_notebook_citations(conn, "d1", ["c2", "c1"])
        attached = db.list_notebook_citations(conn, "d1")
        assert [c["uid"] for c in attached] == ["c2", "c1"]

    def test_set_replaces_whole_list(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        _citation(conn, uid="c2", title="Second")
        db.set_notebook_citations(conn, "d1", ["c1"])
        db.set_notebook_citations(conn, "d1", ["c2"])
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d1")] == ["c2"]

    def test_a_citation_can_attach_to_several_documents(self, conn):
        _document(conn, uid="d1")
        _document(conn, uid="d2")
        _citation(conn, uid="c1")
        db.set_notebook_citations(conn, "d1", ["c1"])
        db.set_notebook_citations(conn, "d2", ["c1"])
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d1")] == ["c1"]
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d2")] == ["c1"]


class TestCitationsLibraryRouter:
    def test_library_page_lists_citations(self, conn):
        _citation(conn, title="Thesis Notes")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert "Thesis Notes" in resp.body.decode()

    def test_create_citation_then_appears_in_library(self, conn):
        resp = notebook_router.create_citation(
            type="book", title="New Work", year="2020", container_title="", doi="", url="",
            author_family=["Smith"], author_given=["Jane"],
            x_requested_with=None, conn=conn,
        )
        assert resp.status_code == 303
        citations = db.list_citations(conn)
        assert len(citations) == 1
        assert citations[0]["title"] == "New Work"
        assert citations[0]["authors"] == [{"family": "Smith", "given": "Jane"}]

    def test_create_citation_blank_title_is_a_noop(self, conn):
        notebook_router.create_citation(
            type="book", title="   ", year="", container_title="", doi="", url="",
            author_family=[], author_given=[], x_requested_with=None, conn=conn,
        )
        assert db.list_citations(conn) == []

    def test_update_citation(self, conn):
        _citation(conn)
        notebook_router.update_citation(
            "c1", type="webpage", title="Updated Title", year="2000", container_title="", doi="", url="",
            author_family=[], author_given=[], x_requested_with=None, conn=conn,
        )
        c = db.get_citation(conn, "c1")
        assert c["title"] == "Updated Title"
        assert c["type"] == "webpage"

    def test_delete_citation_route(self, conn):
        _citation(conn)
        notebook_router.delete_citation("c1", x_requested_with=None, conn=conn)
        assert db.get_citation(conn, "c1") is None


class TestBibliographyRoutes:
    def test_attach_modal_lists_existing_and_attached_citations(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1", title="Attachable Work")
        db.set_notebook_citations(conn, "d1", ["c1"])
        req = _bare_request("/notebook/d1/bibliography")
        resp = notebook_router.document_bibliography_modal("d1", req, conn=conn)
        assert resp.context["attached_uids"] == ["c1"]
        assert any(i["uid"] == "c1" for i in resp.context["citation_items"])

    def test_update_bibliography_sets_attached_citations(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        _citation(conn, uid="c2", title="Second")
        resp = notebook_router.update_document_bibliography(
            "d1", citation_uids=["c1", "c2"], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        assert {c["uid"] for c in db.list_notebook_citations(conn, "d1")} == {"c1", "c2"}

    def test_document_page_carries_formatted_citations(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1", title="Rendered Work")
        db.set_notebook_citations(conn, "d1", ["c1"])
        req = _bare_request("/notebook/d1")
        resp = notebook_router.document_page("d1", req, conn=conn)
        assert "Rendered Work" in resp.context["citations"][0]["display"]
        assert "Rendered Work" in resp.body.decode()

    def test_bibliography_route_missing_document_redirects(self, conn):
        resp = notebook_router.update_document_bibliography(
            "missing", citation_uids=["c1"], x_requested_with=None, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/notebook"


class TestBibliographyAutoAddFromFootnotes:
    """Roadmap item J, session 9c -- content_json save scans footnote/
    endnote markers' `data-footnote-data` and auto-attaches any referenced
    citation not already in the bibliography. Append-only: never removes a
    citation the user attached directly, and never reorders an already-
    attached one."""

    def _content_with_marker(self, inner: str) -> dict:
        html = f'<p>See<span class="cdx-footnote-ref" data-footnote-kind="page_citation" {inner}></span></p>'
        return {"blocks": [{"type": "paragraph", "data": {"text": html}}]}

    def test_single_citation_marker_auto_attaches(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        data = '{&quot;citation&quot;:{&quot;uid&quot;:&quot;c1&quot;},&quot;page&quot;:&quot;12&quot;}'
        content = self._content_with_marker(f'data-footnote-data="{data}"')
        assert db.set_notebook_document_content(conn, "d1", content)
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d1")] == ["c1"]

    def test_apud_marker_attaches_both_citations(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        _citation(conn, uid="c2", title="Second")
        data = (
            '{&quot;citations&quot;:{&quot;original&quot;:{&quot;uid&quot;:&quot;c1&quot;},'
            '&quot;secondary&quot;:{&quot;uid&quot;:&quot;c2&quot;}},&quot;page&quot;:&quot;5&quot;}'
        )
        content = self._content_with_marker(f'data-footnote-data="{data}"')
        db.set_notebook_document_content(conn, "d1", content)
        assert {c["uid"] for c in db.list_notebook_citations(conn, "d1")} == {"c1", "c2"}

    def test_already_attached_citation_is_not_duplicated_or_reordered(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        _citation(conn, uid="c2", title="Second")
        db.set_notebook_citations(conn, "d1", ["c2", "c1"])
        data = '{&quot;citation&quot;:{&quot;uid&quot;:&quot;c1&quot;}}'
        content = self._content_with_marker(f'data-footnote-data="{data}"')
        db.set_notebook_document_content(conn, "d1", content)
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d1")] == ["c2", "c1"]

    def test_manually_attached_citation_never_referenced_by_a_footnote_survives(self, conn):
        _document(conn, uid="d1")
        _citation(conn, uid="c1")
        db.set_notebook_citations(conn, "d1", ["c1"])
        content = {"blocks": [{"type": "paragraph", "data": {"text": "no footnotes here"}}]}
        db.set_notebook_document_content(conn, "d1", content)
        assert [c["uid"] for c in db.list_notebook_citations(conn, "d1")] == ["c1"]

    def test_custom_note_marker_with_no_footnote_data_is_a_noop(self, conn):
        _document(conn, uid="d1")
        content = {
            "blocks": [{
                "type": "paragraph",
                "data": {"text": '<p>See<span class="cdx-footnote-ref" data-note-id="n1" data-note="free text"></span></p>'},
            }]
        }
        db.set_notebook_document_content(conn, "d1", content)
        assert db.list_notebook_citations(conn, "d1") == []

    def test_unknown_citation_uid_in_marker_does_not_crash_the_save(self, conn):
        _document(conn, uid="d1")
        data = '{&quot;citation&quot;:{&quot;uid&quot;:&quot;ghost&quot;}}'
        content = self._content_with_marker(f'data-footnote-data="{data}"')
        # No crash; a dangling attach row is harmless and simply never
        # surfaces via list_notebook_citations' INNER JOIN (same convention
        # as the glossary/wikilink auto-detect passes, which also don't
        # validate target existence before inserting the join row).
        assert db.set_notebook_document_content(conn, "d1", content)
        row = conn.execute(
            "SELECT citation_uid FROM notebook_citations WHERE notebook_uid = ?", ("d1",)
        ).fetchone()
        assert row["citation_uid"] == "ghost"
        assert db.list_notebook_citations(conn, "d1") == []


class TestBackupRoundTrip:
    def test_citations_and_attachments_survive_backup_restore(self, conn, tmp_path):
        _document(conn, uid="d1")
        _citation(conn, uid="c1", title="Backed Up Work")
        db.set_notebook_citations(conn, "d1", ["c1"])
        payload = export_router.build_backup_payload(conn)
        assert payload["citations"][0]["title"] == "Backed Up Work"
        assert payload["notebook_citations"] == [
            {"notebook_uid": "d1", "citation_uid": "c1", "position": 0, "created_at": payload["notebook_citations"][0]["created_at"]}
        ]

        with db.connect(tmp_path / "restored.sqlite") as fresh:
            export_router.restore_backup_payload(fresh, payload)
            assert db.get_citation(fresh, "c1")["title"] == "Backed Up Work"
            assert [c["uid"] for c in db.list_notebook_citations(fresh, "d1")] == ["c1"]


class TestDistinctAuthors:
    def test_citation_author_key_prefers_family_and_given(self, conn):
        assert db.citation_author_key({"family": "Bloch", "given": "Marc"}) == "Bloch, Marc"
        assert db.citation_author_key({"family": "Cher", "given": ""}) == "Cher"
        assert db.citation_author_key({"family": "", "given": ""}) == ""

    def test_list_citation_authors_in_use_dedupes_across_citations_and_positions(self, conn):
        _citation(conn, uid="c1", authors=[{"family": "Bloch", "given": "Marc"}, {"family": "Febvre", "given": "Lucien"}])
        _citation(conn, uid="c2", title="Second", authors=[{"family": "Bloch", "given": "Marc"}])
        assert db.list_citation_authors_in_use(conn) == ["Bloch, Marc", "Febvre, Lucien"]


class TestParseCitationYear:
    def test_parses_valid_digits(self, conn):
        assert db.parse_citation_year("1924") == 1924

    def test_blank_and_non_numeric_are_none(self, conn):
        assert db.parse_citation_year("") is None
        assert db.parse_citation_year("c. 1850") is None
        assert db.parse_citation_year(None) is None

    def test_negative_bce_years_parse_correctly(self, conn):
        # 2026-10-03 direct report: a leading "-" (BCE years, a real case
        # for this app's history-coursework use) used to be silently
        # rejected by an `isdigit()` guard -- plain `int()` fixes it.
        assert db.parse_citation_year("-500") == -500
        assert db.parse_citation_year(" -27 ") == -27

    def test_citation_year_sort_key_orders_bce_years_newest_first(self, conn):
        # -100 (100 BCE) is more recent than -500 (500 BCE) -- newest-
        # first still means "closer to year 0 / present day" first.
        keys = [db.citation_year_sort_key(y) for y in ["-500", "-100", "1924", ""]]
        assert sorted(range(len(keys)), key=lambda i: keys[i]) == [2, 1, 0, 3]


class TestCitationsFiltering:
    def test_filter_by_type(self, conn):
        _citation(conn, uid="c1", type="book")
        _citation(conn, uid="c2", title="Second", type="webpage")
        resp = notebook_router.citations_library(
            _bare_request(), type=["webpage"], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2"]

    def test_filter_by_author_matches_any_position_not_just_first(self, conn):
        _citation(conn, uid="c1", authors=[{"family": "Bloch", "given": "Marc"}, {"family": "Febvre", "given": "Lucien"}])
        _citation(conn, uid="c2", title="Second", authors=[{"family": "Other", "given": "Person"}])
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=["Febvre, Lucien"], year_from="", year_to="", sort="title", conn=conn
        )
        # 2026-10-03 direct decision: a secondary-author match is simply
        # included, no special reordering based on which position matched.
        assert [c["uid"] for c in resp.context["citations"]] == ["c1"]

    def test_no_match_still_renders_a_distinct_empty_state(self, conn):
        _citation(conn, uid="c1", type="book")
        resp = notebook_router.citations_library(
            _bare_request(), type=["thesis"], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert resp.context["citations"] == []
        assert "No citations match the current filters" in resp.body.decode()


class TestCitationsYearRangeFiltering:
    """2026-10-03 direct request: Year is a from/to interval, not a
    multi-select of discrete years. Both blank by default -- a blank End
    is only ever defaulted to the present year once Start has a value
    (routers/notebook.py's `_resolve_citation_year_range`)."""

    def test_both_blank_applies_no_year_filter(self, conn):
        _citation(conn, uid="c1", year="1924")
        _citation(conn, uid="c2", title="Second", year="")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert {c["uid"] for c in resp.context["citations"]} == {"c1", "c2"}

    def test_from_and_to_both_set_is_inclusive(self, conn):
        _citation(conn, uid="c1", year="1900")
        _citation(conn, uid="c2", title="Second", year="1950")
        _citation(conn, uid="c3", title="Third", year="2000")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="1900", year_to="1950", sort="title", conn=conn
        )
        assert {c["uid"] for c in resp.context["citations"]} == {"c1", "c2"}

    def test_to_only_filters_everything_up_to_that_year_no_autocomplete_of_from(self, conn):
        _citation(conn, uid="c1", year="1900")
        _citation(conn, uid="c2", title="Second", year="2020")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="1950", sort="title", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c1"]

    def test_from_only_defaults_to_to_the_present_year(self, conn):
        current_year = datetime.now(timezone.utc).year
        _citation(conn, uid="c1", year="1900")
        _citation(conn, uid="c2", title="Second", year=str(current_year))
        _citation(conn, uid="c3", title="Third", year=str(current_year + 5))
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="1900", year_to="", sort="title", conn=conn
        )
        # c3 (in the future) is excluded even though it's >= From -- the
        # autocompleted upper bound is "present day," not "no upper bound".
        assert {c["uid"] for c in resp.context["citations"]} == {"c1", "c2"}

    def test_non_numeric_or_blank_years_never_match_an_active_range(self, conn):
        _citation(conn, uid="c1", year="1924")
        _citation(conn, uid="c2", title="Second", year="")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="1900", year_to="2000", sort="title", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c1"]

    def test_active_filter_count_counts_year_range_as_one(self, conn):
        _citation(conn, uid="c1", type="book", year="1924")
        resp = notebook_router.citations_library(
            _bare_request(), type=["book"], author=[], year_from="1900", year_to="1950", sort="year", conn=conn
        )
        assert resp.context["active_filter_count"] == 3  # 1 type + 1 year-range + sort != title

    def test_negative_bce_years_filter_correctly(self, conn):
        _citation(conn, uid="c1", year="-500")
        _citation(conn, uid="c2", title="Second", year="-100")
        _citation(conn, uid="c3", title="Third", year="1924")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="-500", year_to="-100", sort="title", conn=conn
        )
        assert {c["uid"] for c in resp.context["citations"]} == {"c1", "c2"}


class TestCitationsSorting:
    def test_sort_by_type(self, conn):
        _citation(conn, uid="c1", title="B Title", type="webpage")
        _citation(conn, uid="c2", title="A Title", type="book")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="type", conn=conn
        )
        # "Book" sorts before "Web page" alphabetically by type label.
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]

    def test_sort_by_year_newest_first_blanks_last(self, conn):
        _citation(conn, uid="c1", year="1924")
        _citation(conn, uid="c2", title="Second", year="2020")
        _citation(conn, uid="c3", title="Third", year="")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="year", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1", "c3"]

    def test_sort_by_author_uses_first_author_only(self, conn):
        _citation(conn, uid="c1", authors=[{"family": "Zorn", "given": "Ada"}])
        _citation(conn, uid="c2", title="Second", authors=[{"family": "Adams", "given": "Bea"}])
        _citation(conn, uid="c3", title="Third", authors=[])
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="author", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1", "c3"]

    def test_default_sort_is_title_alphabetical(self, conn):
        _citation(conn, uid="c1", title="Zebra")
        _citation(conn, uid="c2", title="Apple")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]

    def test_unknown_sort_falls_back_to_title(self, conn):
        _citation(conn, uid="c1", title="Zebra")
        _citation(conn, uid="c2", title="Apple")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="bogus", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]

    def test_unknown_sort2_falls_back_to_title(self, conn):
        _citation(conn, uid="c1", title="Zebra")
        _citation(conn, uid="c2", title="Apple")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="type", sort2="bogus", conn=conn
        )
        # Both citations share a type ("book"), so Primary ties and
        # Secondary falls back to Title.
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]


class TestCitationsSecondarySort:
    """2026-10-03 direct request: "primary sort on the left and seundary
    sort on the right" -- Primary groups, Secondary breaks ties within
    each Primary group; Title is still an unconditional final tiebreaker
    after both."""

    def test_secondary_breaks_ties_within_primary_groups(self, conn):
        _citation(conn, uid="c1", title="Z Title", type="book", year="2020")
        _citation(conn, uid="c2", title="A Title", type="book", year="1900")
        _citation(conn, uid="c3", title="M Title", type="webpage", year="1950")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="type", sort2="year", conn=conn
        )
        # Primary: type (book < webpage alphabetically). Within "book",
        # Secondary (year, newest-first) orders c1 (2020) before c2 (1900)
        # -- NOT title order, which would have put c2 first.
        assert [c["uid"] for c in resp.context["citations"]] == ["c1", "c2", "c3"]

    def test_title_is_still_the_final_tiebreaker(self, conn):
        _citation(conn, uid="c1", title="Zebra", type="book")
        _citation(conn, uid="c2", title="Apple", type="book")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="type", sort2="type", conn=conn
        )
        # Primary and Secondary are both "type" (a no-op tie, both equal)
        # -- Title still breaks the tie.
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]

    def test_default_sort2_is_title(self, conn):
        _citation(conn, uid="c1", title="Z Title", type="book")
        _citation(conn, uid="c2", title="A Title", type="book")
        resp = notebook_router.citations_library(
            _bare_request(), type=[], author=[], year_from="", year_to="", sort="type", conn=conn
        )
        assert [c["uid"] for c in resp.context["citations"]] == ["c2", "c1"]


class TestCitationsFiltersModal:
    def test_renders_options_and_current_selection(self, conn):
        _citation(conn, uid="c1", type="book", year="1924", authors=[{"family": "Bloch", "given": "Marc"}])
        req = _bare_request("/notebook/citations/filters", query_string=b"type=book&year_from=1900&year_to=1950")
        resp = notebook_router.citations_filters_modal(
            req, type=["book"], author=[], year_from="1900", year_to="1950", sort="title", conn=conn
        )
        assert resp.context["selected_types"] == ["book"]
        assert resp.context["selected_year_from"] == "1900"
        assert resp.context["selected_year_to"] == "1950"
        assert any(i["uid"] == "Bloch, Marc" for i in resp.context["author_items"])
        assert resp.context["apply_href"] == "/notebook/citations?type=book&year_from=1900&year_to=1950"

    def test_apply_href_is_bare_path_with_no_active_filters(self, conn):
        req = _bare_request("/notebook/citations/filters")
        resp = notebook_router.citations_filters_modal(
            req, type=[], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert resp.context["apply_href"] == "/notebook/citations"

    def test_both_year_fields_blank_by_default_no_autocomplete(self, conn):
        req = _bare_request("/notebook/citations/filters")
        resp = notebook_router.citations_filters_modal(
            req, type=[], author=[], year_from="", year_to="", sort="title", conn=conn
        )
        assert resp.context["selected_year_from"] == ""
        assert resp.context["selected_year_to"] == ""

    def test_primary_and_secondary_sort_both_carried_through(self, conn):
        req = _bare_request("/notebook/citations/filters", query_string=b"sort=year&sort2=author")
        resp = notebook_router.citations_filters_modal(
            req, type=[], author=[], year_from="", year_to="", sort="year", sort2="author", conn=conn
        )
        assert resp.context["selected_sort"] == "year"
        assert resp.context["selected_sort2"] == "author"
        assert resp.context["apply_href"] == "/notebook/citations?sort=year&sort2=author"

    def test_from_set_with_blank_to_displays_present_year(self, conn):
        current_year = datetime.now(timezone.utc).year
        req = _bare_request("/notebook/citations/filters", query_string=b"year_from=1900")
        resp = notebook_router.citations_filters_modal(
            req, type=[], author=[], year_from="1900", year_to="", sort="title", conn=conn
        )
        assert resp.context["selected_year_to"] == str(current_year)


class TestCitationsSearch:
    def test_q_filters_by_title_and_author(self, tmp_path):
        from fastapi.testclient import TestClient
        from src import db
        from src.main import app
        from src.deps import get_db
        with db.connect(tmp_path / "c.sqlite") as c:
            db.upsert_citation(c, {"title": "Alpha Book", "authors": [{"family": "Smith", "given": "A"}]})
            db.upsert_citation(c, {"title": "Beta Paper", "authors": [{"family": "Jones", "given": "B"}]})
            app.dependency_overrides[get_db] = lambda: c
            try:
                cl = TestClient(app)
                by_title = cl.get("/notebook/citations?q=alpha").text
                by_author = cl.get("/notebook/citations?q=jones").text
            finally:
                app.dependency_overrides.clear()
        assert "Alpha Book" in by_title and "Beta Paper" not in by_title
        assert "Beta Paper" in by_author and "Alpha Book" not in by_author
