"""A footnote written as [@citation-uid, page] through the API becomes a generated citation, in order, in the user's style."""

from __future__ import annotations

import html
import json
import re

import pytest

from src import api_write, db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def _cite(conn, title, family):
    return db.upsert_citation(conn, {"type": "book", "title": title, "year": "1999", "authors": [{"family": family, "given": "Ana"}]})


def _markers(conn, uid):
    content = db.get_notebook_document_content(conn, uid)
    text = json.dumps(content)
    return [(m.group(1), html.unescape(m.group(2))) for m in re.finditer(r'data-footnote-kind=\\"([a-z_]+)\\" data-note=\\"([^"]*?)\\"', text)] or text


def test_a_cite_note_is_generated_then_repeated_as_ibid_and_op_cit(conn):
    a, b = _cite(conn, "Greek Roads", "Pop"), _cite(conn, "Roman Bridges", "Ionescu")
    md = (f"First[^1] then again[^2] then another source[^3] and back[^4].\n\n[^1]: [@{a}, 12]\n[^2]: [@{a}, 14]\n[^3]: [@{b}, 3]\n[^4]: [@{a}, 20]")
    note = api_write.create_note(conn, title="Essay", markdown=md, source="mcp")
    content = db.get_notebook_document_content(conn, note["uid"])
    sups = re.findall(r"<sup[^>]*></sup>", json.dumps(content["blocks"]).replace('\\"', '"'))
    kinds = [re.search(r'data-footnote-kind="([a-z_]+)"', s).group(1) for s in sups]
    assert kinds == ["page_citation", "ibidem", "page_citation", "opere_citato"]
    assert "Greek Roads" in html.unescape(sups[0]) and "Ibid., 14" in html.unescape(sups[1])
    assert "data-cite" not in json.dumps(content)
    assert {c["uid"] for c in db.list_notebook_citations(conn, note["uid"])} == {a, b}


def test_a_cite_note_continues_after_an_earlier_block_and_forced_kinds_work(conn):
    a, b = _cite(conn, "Greek Roads", "Pop"), _cite(conn, "Roman Bridges", "Ionescu")
    note = api_write.create_note(conn, title="Essay", markdown=f"One[^1].\n\n[^1]: [@{a}, 1]", source="mcp")
    doc = db.get_notebook_document(conn, note["uid"])
    block_id = db.get_notebook_document_content(conn, note["uid"])["blocks"][0]["id"]
    api_write.edit_note(conn, note["uid"], doc["updated_at"], [{"op": "append", "markdown": f"Two[^2] see[^3] quoted[^4].\n\n[^2]: [@{a}, 2]\n[^3]: [cf. @{b}, 9]\n[^4]: [apud @{a} in @{b}, 5]"}], source="mcp")
    text = html.unescape(json.dumps(db.get_notebook_document_content(conn, note["uid"])).replace('\\"', '"'))
    assert re.findall(r'data-footnote-kind="([a-z_]+)"', text) == ["page_citation", "ibidem", "confer", "apud"]
    assert "apud" in text.split("Ibid.")[-1]


def test_an_unknown_citation_or_a_lonely_apud_is_refused_and_nothing_is_saved(conn):
    a = _cite(conn, "Greek Roads", "Pop")
    with pytest.raises(api_write.EditError, match="No citation"):
        api_write.create_note(conn, title="X", markdown="Hi[^1]\n\n[^1]: [@nope, 1]", source="mcp")
    with pytest.raises(api_write.EditError, match="apud needs two"):
        api_write.create_note(conn, title="X", markdown=f"Hi[^1]\n\n[^1]: [apud @{a}, 1]", source="mcp")
    assert conn.execute("SELECT COUNT(*) FROM notebook_documents").fetchone()[0] == 0


def test_a_plain_footnote_still_works_and_the_web_importer_ignores_the_cite_syntax(conn):
    from src.notebook_markdown import markdown_to_blocks

    plain = markdown_to_blocks("A[^1]\n\n[^1]: Just words", cite_notes=True)
    assert "Just words" in json.dumps(plain) and "data-cite" not in json.dumps(plain)
    web = markdown_to_blocks("A[^1]\n\n[^1]: [@abc, 3]")
    assert "data-cite" not in json.dumps(web)
