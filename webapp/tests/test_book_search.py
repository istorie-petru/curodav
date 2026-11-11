"""Searching inside books: EPUB, text and PDF files become a passage index searched by words, phrase or regex, read in capped pieces."""

from __future__ import annotations

import shutil
import zipfile

import pytest

from src import book_search, book_text, db, mcp_server
from src.book_text import BookError

CH1 = "<html><body><h1>The Harbour</h1>" + "".join(f"<p>Paragraph {i} about ships and the harbour tide. " + "Filler words go here. " * 8 + "</p>" for i in range(12)) + "<p>The lighthouse keeper wound the brass clock.</p></body></html>"
CH2 = "<html><body><h1>The Orchard</h1><p>Apples grew in the orchard, and the café never closed.</p>" + "<p>" + "Long quiet afternoon. " * 60 + "</p></body></html>"


def make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="ch1.xhtml"/><item id="b" href="ch2.xhtml"/></manifest>'
                                        '<spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
        z.writestr("OEBPS/ch1.xhtml", CH1)
        z.writestr("OEBPS/ch2.xhtml", CH2)


def make_pdf(path, pages):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>"]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


@pytest.fixture()
def epub_book(conn, tmp_path, monkeypatch):
    uid = db.upsert_citation(conn, {"type": "book", "title": "Harbour Tales", "authors": [{"family": "Pop", "given": "Ana"}]})
    path = tmp_path / "book.epub"
    make_epub(path)
    monkeypatch.setattr(book_search, "locate", lambda c, u, e="", f="": ("ed1:epub", path, "epub"))
    return uid, path


def test_words_phrase_and_regex_find_the_same_passage_with_its_chapter(conn, epub_book):
    uid, _ = epub_book
    words = book_search.search(conn, uid, "lighthouse brass", mode="words")
    assert [h["title"] for h in words["hits"]] == ["The Harbour"] and "[lighthouse]" in words["hits"][0]["snippet"]
    assert book_search.search(conn, uid, "brass lighthouse", mode="phrase")["hits"] == []
    assert len(book_search.search(conn, uid, "lighthouse keeper", mode="phrase")["hits"]) == 1
    rx = book_search.search(conn, uid, r"light(house|ship)s? keep", mode="regex")["hits"]
    assert [h["title"] for h in rx] == ["The Harbour"] and "[lighthouse keep]" in rx[0]["snippet"]
    assert book_search.search(conn, uid, "cafe", mode="words")["hits"][0]["title"] == "The Orchard"


def test_contents_lists_chapters_and_read_returns_the_passages_around_a_hit(conn, epub_book):
    uid, _ = epub_book
    toc = book_search.contents(conn, uid)
    assert [i["title"] for i in toc["items"]] == ["The Harbour", "The Orchard"] and toc["kind"] == "chapters"
    hit = book_search.search(conn, uid, "lighthouse")["hits"][0]["hit"]
    got = book_search.read(conn, uid, token="t1", hit=hit, before=1, after=0)
    assert "lighthouse keeper" in got["text"] and got["from"]["title"] == "The Harbour" and got["last_hit"] == hit
    chapter = book_search.read(conn, uid, token="t1", section=1, after=0)
    assert "Apples grew" in chapter["text"] and len(chapter["text"]) <= book_search.READ_CALL_CHARS


def test_reading_is_capped_per_call_and_per_hour_and_never_returns_the_book(conn, epub_book, monkeypatch):
    uid, _ = epub_book
    monkeypatch.setattr(book_search, "READ_CALL_CHARS", 1200)
    monkeypatch.setattr(book_search, "READ_HOUR_CHARS", 2000)
    first = book_search.read(conn, uid, token="t1", section=0)
    assert len(first["text"]) <= 1200 and "next_hit" in first
    total = len(first["text"])
    with pytest.raises(BookError, match="Reading limit"):
        for _ in range(20):
            total += len(book_search.read(conn, uid, token="t1", hit=0, before=0, after=5)["text"])
    assert total <= 2000
    assert book_search.read(conn, uid, token="t2", hit=0, before=0, after=0)["text"]


def test_bad_input_is_a_readable_error(conn, epub_book):
    uid, _ = epub_book
    with pytest.raises(BookError, match="at least one word"):
        book_search.search(conn, uid, "!!!")
    with pytest.raises(BookError, match="valid extended regular"):
        book_search.search(conn, uid, "(unclosed", mode="regex")
    with pytest.raises(BookError, match="mode must"):
        book_search.search(conn, uid, "x", mode="fuzzy")
    with pytest.raises(BookError, match="either hit"):
        book_search.read(conn, uid)
    with pytest.raises(BookError, match="No section"):
        book_search.read(conn, uid, section=9)


def test_a_changed_file_is_read_again(conn, epub_book, tmp_path):
    uid, path = epub_book
    assert book_search.search(conn, uid, "zeppelin")["hits"] == []
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("OEBPS/ch3.xhtml", "<html><body><h1>Sky</h1><p>A zeppelin drifted over the harbour town this morning.</p></body></html>")
    with zipfile.ZipFile(tmp_path / "new.epub", "w") as z:
        for info in zipfile.ZipFile(path).infolist():
            data = zipfile.ZipFile(path).read(info.filename)
            if info.filename.endswith("content.opf"):
                data = data.replace(b'<item id="b" href="ch2.xhtml"/>', b'<item id="b" href="ch2.xhtml"/><item id="c" href="ch3.xhtml"/>').replace(b'<itemref idref="b"/>', b'<itemref idref="b"/><itemref idref="c"/>')
            z.writestr(info.filename, data)
    shutil.copy(tmp_path / "new.epub", path)
    assert [h["title"] for h in book_search.search(conn, uid, "zeppelin")["hits"]] == ["Sky"]


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="pdftotext is not installed")
def test_a_pdf_is_searched_by_page_through_the_real_edition_file(conn, tmp_path):
    uid = db.upsert_citation(conn, {"type": "book", "title": "Paper Book", "authors": []})
    edition = db.save_edition(conn, uid, {"year": "1999"})
    from src.db.citation_library import files_dir

    folder = files_dir(conn)
    folder.mkdir(parents=True, exist_ok=True)
    make_pdf(folder / "p.pdf", ["First page about harbours and the long quiet sea " * 3, "Second page mentions the lighthouse keeper alone " * 3])
    conn.execute("UPDATE citation_editions SET file_name = 'p.pdf' WHERE uid = ?", (edition,))
    conn.commit()
    hit = book_search.search(conn, uid, "lighthouse keeper", mode="phrase")["hits"][0]
    assert hit["page"] == 2 and "[lighthouse keeper]" in hit["snippet"]
    assert book_search.contents(conn, uid)["kind"] == "pages"


def test_a_scanned_pdf_and_a_missing_file_say_so(conn, tmp_path):
    uid = db.upsert_citation(conn, {"type": "book", "title": "Nothing", "authors": []})
    with pytest.raises(BookError, match="no book file"):
        book_search.search(conn, uid, "x")
    with pytest.raises(BookError, match="No library entry"):
        book_search.search(conn, "nope", "x")
    assert all(len(p) <= book_text.PASSAGE_MAX for p in book_text.passages("a\n\n" + "word. " * 700))


def test_the_mcp_tools_work_and_book_errors_are_tool_errors(conn, epub_book):
    uid, _ = epub_book
    token = {"uid": "tok", "scopes": "read:notes"}
    ok = mcp_server.call_tool(conn, "search_book", {"uid": uid, "query": "lighthouse"}, token)
    assert not ok.get("isError") and ok["structuredContent"]["hits"]
    got = mcp_server.call_tool(conn, "read_book", {"uid": uid, "hit": ok["structuredContent"]["hits"][0]["hit"]}, token)
    assert "lighthouse" in got["structuredContent"]["text"]
    bad = mcp_server.call_tool(conn, "search_book", {"uid": uid, "query": "(x", "mode": "regex"}, token)
    assert bad["isError"] and "regular expression" in bad["content"][0]["text"]
    names = {t.name for t in mcp_server.visible_tools({"scopes": "read:notes"})}
    assert {"search_book", "book_contents", "read_book"} <= names


def test_the_rest_routes_serve_the_same_search_and_reads(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from src import access_tokens, api_auth, main

    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("CC_AUTH_USERNAME", "alice")
    monkeypatch.setenv("CC_AUTH_PASSWORD", "s3cret-pass")
    monkeypatch.delenv("CC_SKIP_AUTH", raising=False)
    api_auth.reset_rate_limits()
    book = tmp_path / "book.epub"
    make_epub(book)
    monkeypatch.setattr(book_search, "locate", lambda c, u, e="", f="": ("ed1:epub", book, "epub"))
    with TestClient(main.create_app(), base_url="http://testserver", follow_redirects=False) as client:
        with db.connect(client.app.state.settings.db_path, reuse_schema=True) as c:
            uid = db.upsert_citation(c, {"type": "book", "title": "Harbour Tales", "authors": []})
            _, secret = access_tokens.create_personal_token(c, "Script", "read")
        auth = {"Authorization": f"Bearer {secret}"}
        found = client.get(f"/api/v1/citations/{uid}/book/search", params={"q": "lighthouse"}, headers=auth)
        assert found.status_code == 200, found.text
        assert found.json()["hits"][0]["title"] == "The Harbour"
        text = client.get(f"/api/v1/citations/{uid}/book/read", params={"hit": found.json()["hits"][0]["hit"]}, headers=auth)
        assert text.status_code == 200 and "lighthouse" in text.json()["text"]
        assert client.get(f"/api/v1/citations/{uid}/book/contents", headers=auth).json()["kind"] == "chapters"
        bad = client.get(f"/api/v1/citations/{uid}/book/search", params={"q": "(x", "mode": "regex"}, headers=auth)
        assert bad.status_code == 422 and "regular expression" in bad.json()["detail"]["message"]
        assert client.get(f"/api/v1/citations/{uid}/book/search", params={"q": "x"}).status_code == 401
    api_auth.reset_rate_limits()
