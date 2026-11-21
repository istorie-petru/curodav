"""The in-app book reader and the annotations kept on it."""

from fastapi.testclient import TestClient

from src import book_annotations, db
from src.deps import get_db
from src.main import app


def test_annotations_are_kept_per_work_and_section(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "Meditations", "type": "book"})
        a = book_annotations.add(c, uid, 2, "  the  quote ", "why")
        assert book_annotations.add(c, uid, 2, "   ") is None
        assert book_annotations.listing(c, uid, 2)[0]["quote"] == "the quote"
        assert book_annotations.listing(c, uid, 1) == []
        book_annotations.remove(c, uid, a)
        assert book_annotations.count(c, uid) == 0


def test_reader_page_explains_a_missing_file(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "No File", "type": "book"})
        app.dependency_overrides[get_db] = lambda: c
        try:
            html = TestClient(app).get(f"/library/{uid}/read").text
        finally:
            app.dependency_overrides.clear()
    assert "has no book file yet" in html
    assert 'aria-label="Back to Library"' in html  # the header arrow returns to the Library, on the view it was last on


def test_adding_books_guesses_title_and_author_from_the_file_name(tmp_path):
    from src.routers.media import _guess

    assert _guess("Marcus Aurelius - Meditations.epub")[0] == "Meditations"
    assert _guess("Dune (Frank Herbert).pdf")[1] == [{"family": "Herbert", "given": "Frank"}]
    assert _guess("plain_name.pdf") == ("plain name", [])


def test_inline_edit_changes_status_and_year(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "T", "type": "film"})
        app.dependency_overrides[get_db] = lambda: c
        try:
            cl = TestClient(app)
            assert cl.post(f"/library/{uid}/update-field", json={"field": "status", "value": "current"}).status_code == 200
            assert cl.post(f"/library/{uid}/update-field", json={"field": "year", "value": "1999"}).status_code == 200
            assert cl.post(f"/library/{uid}/update-field", json={"field": "title", "value": "x"}).status_code == 400
        finally:
            app.dependency_overrides.clear()
        row = db.get_citation_raw(c, uid)
    assert row["status"] == "current" and row["year"] == "1999"


def test_reader_settings_and_the_place_where_a_book_was_left(tmp_path):
    from src import book_reader

    with db.connect(tmp_path / "c.sqlite") as c:
        assert book_reader.settings(c)["layout"] == "auto"
        book_reader.save_settings(c, {"layout": "scrolled", "theme": "bogus", "font_size": "130"})
        got = book_reader.settings(c)
        assert (got["layout"], got["theme"], got["font_size"]) == ("scrolled", "app", "130")
        book_reader.save_position(c, "u1", "epubcfi(/6/4)", 0.4)
        book_reader.save_position(c, "u1", "epubcfi(/6/6)", 0.5)
        assert book_reader.position(c, "u1") == {"cfi": "epubcfi(/6/6)", "fraction": 0.5}


def test_the_reader_page_gets_its_own_content_security_policy():
    from src.security_headers import _READER_PATH

    assert _READER_PATH.match("/library/57b66bb7-8fe4-4a4e-b6c5-cc4f557f3cb9/read")
    assert not _READER_PATH.match("/library/57b66bb7-8fe4-4a4e-b6c5-cc4f557f3cb9")
    assert not _READER_PATH.match("/notebook/57b66bb7-8fe4-4a4e-b6c5-cc4f557f3cb9/read")


def test_lookup_sources_can_be_switched_and_added(tmp_path):
    from src import book_reader

    with db.connect(tmp_path / "c.sqlite") as c:
        on = {x["key"] for x in book_reader.lookups(c) if x["on"]}
        assert on == {"wikipedia", "wiktionary"}
        assert book_reader.save_lookups(c, ["wikipedia", "dexonline"], "Mine", "https://example.com/?q=%s") is None
        got = {x["key"]: x for x in book_reader.lookups(c)}
        assert got["dexonline"]["on"] and not got["wiktionary"]["on"]
        custom = [x for x in got.values() if x["custom"]]
        assert custom[0]["name"] == "Mine" and custom[0]["on"]
        assert book_reader.save_lookups(c, [], "Bad", "https://example.com/") is not None
        book_reader.save_lookups(c, [], remove=custom[0]["key"])
        assert not [x for x in book_reader.lookups(c) if x["custom"]]


def test_a_highlight_has_a_colour_and_a_note_that_can_change(tmp_path):
    from src import book_annotations

    with db.connect(tmp_path / "c.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "T", "type": "book"})
        a = book_annotations.add(c, uid, 0, "words", color="green")
        assert book_annotations.listing(c, uid)[0]["color"] == "green"
        book_annotations.update(c, uid, a, note="think", color="pink")
        got = book_annotations.listing(c, uid)[0]
        assert (got["note"], got["color"]) == ("think", "pink")
        book_annotations.update(c, uid, a, color="bogus")
        assert book_annotations.listing(c, uid)[0]["color"] == "pink"


def test_a_word_file_is_converted_to_an_epub_once(tmp_path):
    import shutil

    import pytest

    from src import book_convert

    if not (shutil.which("ebook-convert") and shutil.which("pandoc")):
        pytest.skip("needs Calibre's ebook-convert and pandoc")
    import subprocess

    (tmp_path / "a.md").write_text("# Title\n\nSome words here.\n")
    subprocess.run(["pandoc", str(tmp_path / "a.md"), "-o", str(tmp_path / "a.docx")], check=True)
    with db.connect(tmp_path / "c.sqlite") as c:
        first = book_convert.to_epub(c, tmp_path / "a.docx")
        stamp = first.stat().st_mtime_ns
        assert first.suffix == ".epub" and first.parent == tmp_path / "book_conversions"
        assert book_convert.to_epub(c, tmp_path / "a.docx").stat().st_mtime_ns == stamp


def test_bookmarks_are_kept_in_reading_order(tmp_path):
    from src import book_bookmarks

    with db.connect(tmp_path / "c.sqlite") as c:
        uid = db.upsert_citation(c, {"title": "T", "type": "book"})
        late = book_bookmarks.add(c, uid, 3, "epubcfi(/6/8)", "  Chapter   3 ", 0.6)
        book_bookmarks.add(c, uid, 1, "", "Page 2", 0.2)
        got = book_bookmarks.listing(c, uid)
        assert [b["label"] for b in got] == ["Page 2", "Chapter 3"]
        book_bookmarks.remove(c, uid, late)
        assert len(book_bookmarks.listing(c, uid)) == 1


def test_define_prefers_a_dictionary_then_wikipedia(monkeypatch):
    from src import book_define

    calls = []

    def fake(url):
        calls.append(url)
        if "dictionaryapi.dev" in url and "serene" in url:
            return [{"meanings": [{"partOfSpeech": "adjective", "definitions": [{"definition": "calm and peaceful"}]}]}]
        if "wikipedia.org" in url:
            return {"title": "Stoicism", "extract": "A school of philosophy.", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Stoicism"}}}
        return None

    monkeypatch.setattr(book_define, "_get", fake)
    word = book_define.define("Serene", "en")
    assert word["source"] == "Dictionary" and word["entries"][0]["defs"] == ["calm and peaceful"]
    phrase = book_define.define("the Stoic school", "en")
    assert phrase["source"] == "Wikipedia" and phrase["summary"].startswith("A school")
    assert book_define.define("", "en")["source"] == ""


def test_comic_archives_are_converted_to_cbz_and_a_scan_gets_an_ocr_copy(tmp_path):
    from pathlib import Path

    from src import book_convert

    assert book_convert.converted_name(Path("x.cbr")) == "cbz" and book_convert.converted_name(Path("x.docx")) == "epub"
    (tmp_path / "scan.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    with db.connect(tmp_path / "c.sqlite") as c:
        assert book_convert.ocr_path(c, tmp_path / "scan.pdf") is None  # nothing made yet
    assert isinstance(book_convert.ocr_available(), bool)


def test_metadata_inside_a_book_names_an_upload(tmp_path):
    import shutil
    import subprocess

    import pytest

    from src import book_convert

    if not (shutil.which("ebook-meta") and shutil.which("ebook-convert")):
        pytest.skip("needs Calibre")
    (tmp_path / "a.txt").write_text("Words.\n")
    subprocess.run(["ebook-convert", str(tmp_path / "a.txt"), str(tmp_path / "a.epub"), "--title", "Real Title", "--authors", "Jane Doe"], capture_output=True, check=True)
    got = book_convert.read_metadata((tmp_path / "a.epub").read_bytes(), "whatever.epub")
    assert got["title"] == "Real Title" and got["authors"] == "Jane Doe"
    assert book_convert.read_metadata(b"plain", "x.txt") == {}


def test_reading_statistics(tmp_path):
    from datetime import date

    from src import book_stats

    with db.connect(tmp_path / "c.sqlite") as c:
        a = db.upsert_citation(c, {"title": "A", "type": "book"})
        b = db.upsert_citation(c, {"title": "B", "type": "book"})
        assert book_stats.add_time(c, a, "2026-11-19", 5000) == 120  # one beat is capped
        book_stats.add_time(c, a, "2026-11-20", 60)
        book_stats.add_time(c, b, "2026-11-21", 30)
        book_stats.add_time(c, b, "2026-11-21", 30)
        db.set_tracking(c, b, {"status": "finished", "finished_on": "2026-11-21", "started_on": "2026-11-21"})
        today = date(2026, 11, 21)
        got = book_stats.stats(c, *book_stats.period("month", today), today)
        assert got["seconds"] == 240 and got["days_read"] == 3 and got["books_read"] == 2
        assert got["finished"] == {"total": 1, "by_kind": {"book": 1}} and got["started"] == 1
        assert got["streak"] == {"current": 3, "longest": 3} and got["top_books"][0]["title"] == "A"
        assert book_stats.period("week", today)[0] == date(2026, 11, 16)
        assert book_stats.stats(c, date(2026, 1, 1), date(2026, 1, 31), today)["seconds"] == 0


def test_highlights_can_be_searched_across_books_and_picked_for_a_quote(tmp_path):
    from src import book_annotations

    with db.connect(tmp_path / "c.sqlite") as c:
        a = db.upsert_citation(c, {"title": "Meditations", "type": "book", "authors": [{"family": "Aurelius", "given": "Marcus"}]})
        b = db.upsert_citation(c, {"title": "Letters", "type": "book"})
        book_annotations.add(c, a, 0, "You have power over your mind", "keep this", color="green")
        book_annotations.add(c, b, 0, "Time is the thing we lose", color="blue")
        assert book_annotations.search(c, "power")["total"] == 1
        assert book_annotations.search(c, "mind keep")["items"][0]["title"] == "Meditations"  # the quote and the note both count
        assert book_annotations.search(c, "", books=[b])["items"][0]["quote"].startswith("Time")
        assert book_annotations.search(c, "", colors=["green"])["total"] == 1 and book_annotations.search(c, "", only_notes=True)["total"] == 1
        assert [x["n"] for x in book_annotations.books_with_highlights(c)] == [1, 1]
        app.dependency_overrides[get_db] = lambda: c
        try:
            html = TestClient(app).get("/notebook/highlights?q=power").text
            listing = TestClient(app).get("/notebook/highlights/list?color=blue").text
        finally:
            app.dependency_overrides.clear()
    assert "You have power over your mind" in html and "Aurelius" in html and "Time is the thing" not in html
    assert "Time is the thing we lose" in listing and "power over" not in listing


def test_define_never_lets_the_language_choose_another_host(monkeypatch):
    from src import book_define

    seen = []
    monkeypatch.setattr(book_define, "_get", lambda url: seen.append(url) or None)
    book_define.define("two words", "x/")
    book_define.define("two words", "@evil.example")
    assert seen and all(u.startswith("https://en.wikipedia.org/") for u in seen)


def test_the_server_voice_reads_a_sentence_or_says_it_cannot(monkeypatch):
    from src import book_speech

    monkeypatch.setattr(book_speech.shutil, "which", lambda name: None)
    assert book_speech.speak("Hello.", "en") is None and not book_speech.available()


def test_the_server_voice_prefers_piper_in_the_book_language(monkeypatch):
    from src import book_speech

    class Resp:
        def __init__(self, status, content=b"", data=None):
            self.status_code, self.content, self._data = status, content, data

        def json(self):
            return self._data

    asked = []
    monkeypatch.setenv("CC_PIPER_URL", "http://127.0.0.1:5150")
    monkeypatch.setattr(book_speech, "_voices", {"at": 0.0, "list": {}})
    monkeypatch.setattr(book_speech.httpx, "get", lambda url, timeout: Resp(200, data={
        "en_US-lessac-medium": {"language": {"code": "en_US"}}, "ro_RO-mihai-medium": {"language": {"code": "ro_RO"}}}))
    monkeypatch.setattr(book_speech.httpx, "post", lambda url, json, timeout: asked.append(json["voice"]) or Resp(200, b"RIFF...."))
    assert book_speech.voice_for("ro") == "ro_RO-mihai-medium" and book_speech.voice_for("ro-RO") == "ro_RO-mihai-medium"
    assert book_speech.voice_for("de") == "en_US-lessac-medium"
    assert book_speech.speak("Bună ziua.", "ro") == b"RIFF...." and asked == ["ro_RO-mihai-medium"]
