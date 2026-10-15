"""The journal: one note per ISO week (2026-42), filed by year, started from the journal template, with a strip of weeks."""

import json
from datetime import date

import pytest
from starlette.requests import Request

from src import db, migrations
from src.routers import notebook as router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path="/notebook"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def _template(conn, uid="tpl"):
    db.upsert_notebook_document(conn, {"uid": uid, "title": "Weekly", "document_type": "full", "note_type": "journal", "is_template": True,
                                       "content_json": json.dumps({"blocks": [{"type": "header", "data": {"text": "Goals", "level": 2}}]}),
                                       "created_at": "2026-10-01", "updated_at": "2026-10-01", "properties": [{"key": "mood", "value": ""}]})
    return uid


def test_the_week_key_is_the_iso_year_and_two_digit_week():
    assert db.week_key(date(2026, 10, 15)) == "2026-42"
    assert db.week_key(date(2026, 1, 1)) == "2026-01"
    assert db.week_key(date(2027, 1, 1)) == "2026-53"


def test_a_year_has_52_or_53_weeks():
    assert db.weeks_in_year(2026) == 53 and db.weeks_in_year(2027) == 52


def test_a_weeks_note_is_made_once_and_reopened_after(conn):
    first = db.create_journal_entry(conn, "2026-42")
    assert db.create_journal_entry(conn, "2026-42") == first
    assert db.get_notebook_document(conn, first)["title"] == "2026-42"


def test_a_new_entry_starts_from_the_journal_template(conn):
    uid = db.create_journal_entry(conn, "2026-42", _template(conn))
    doc = db.get_notebook_document(conn, uid)
    assert doc["note_type"] == "journal" and "Goals" in doc["content_json"] and doc["is_template"] == 0
    assert [p["key"] for p in doc["properties"]] == ["mood"]


def test_only_a_real_template_counts_as_the_journal_template(conn):
    db.upsert_notebook_document(conn, {"uid": "n", "title": "Plain", "document_type": "full", "note_type": "", "content_json": "{}",
                                       "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    db.set_journal_template(conn, "n")
    assert db.get_journal_template(conn) == ""
    db.set_journal_template(conn, _template(conn))
    assert db.get_journal_template(conn) == "tpl"


def test_entries_sit_in_year_folders_and_not_in_label_folders(conn):
    for week in ("2026-42", "2026-43", "2025-52"):
        db.create_journal_entry(conn, week)
    assert db.list_journal_years(conn) == [{"name": "2026", "count": 2}, {"name": "2025", "count": 1}]
    folders = db.list_notebook_folders(conn)
    assert folders["projects"] == [] and folders["labels"] == []


def test_a_year_folder_lists_its_weeks_newest_first_with_a_strip_of_every_week(conn):
    db.create_journal_entry(conn, "2026-42")
    db.create_journal_entry(conn, "2026-43")
    resp = router.folder_view(_request("/notebook/folder"), kind="journal", name="2026", conn=conn)
    assert [d["title"] for d in resp.context["documents"]] == ["2026-43", "2026-42"]
    weeks = resp.context["journal_weeks"]
    assert len(weeks) == 53 and [w["nr"] for w in weeks if w["uid"]] == [42, 43]


def test_the_strip_is_also_on_each_journal_note_so_weeks_are_one_click_away(conn):
    uid = db.create_journal_entry(conn, "2026-42")
    body = router.document_page(uid, _request(f"/notebook/{uid}"), conn=conn).body.decode()
    assert 'class="journal-strip is-sticky"' in body and "is-active" in body


def test_an_ordinary_note_has_no_strip(conn):
    db.upsert_notebook_document(conn, {"uid": "n", "title": "Plain", "document_type": "full", "note_type": "", "content_json": "{}",
                                       "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    assert 'class="journal-strip' not in router.document_page("n", _request("/notebook/n"), conn=conn).body.decode()


def test_opening_a_week_redirects_to_its_note_and_a_bad_week_goes_back(conn):
    resp = router.open_journal_week(week="2026-42", conn=conn)
    assert resp.headers["location"] == f"/notebook/{db.journal_entry_for(conn, '2026-42')}"
    for bad in ("2026-54", "2026-00", "2027-53", "week 42", "2026-4"):
        assert router.open_journal_week(week=bad, conn=conn).headers["location"] == "/notebook/journal"


def test_the_home_counts_journal_weeks(conn):
    db.create_journal_entry(conn, "2026-42")
    body = router.list_documents(_request(), conn=conn).body.decode()
    assert "Journal" in body and "1 week" in body


def test_the_journal_page_lists_years(conn):
    db.create_journal_entry(conn, "2026-42")
    assert ">2026<" in router.journal_home(_request("/notebook/journal"), conn=conn).body.decode()


def test_a_note_exports_as_markdown_with_its_frontmatter(conn):
    uid = db.create_journal_entry(conn, "2026-42", _template(conn))
    resp = router.export_document_markdown(uid, conn=conn)
    text = resp.body.decode()
    assert text.startswith("---\n") and 'title: "2026-42"' in text and 'week: "2026-42"' in text and "## Goals" in text


def test_saving_a_note_does_not_erase_its_week(conn):
    uid = db.create_journal_entry(conn, "2026-42")
    doc = db.get_notebook_document(conn, uid)
    db.upsert_notebook_document(conn, {k: doc[k] for k in ("uid", "title", "content_json", "document_type", "note_type", "created_at", "updated_at")})
    assert db.get_notebook_document(conn, uid)["journal_week"] == "2026-42"


def test_the_migration_turns_daily_entries_into_weekly_ones_keeping_the_first_of_each_week():
    import sqlite3

    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE notebook_documents (uid TEXT PRIMARY KEY, title TEXT, journal_date TEXT NOT NULL DEFAULT '')")
    old.executemany("INSERT INTO notebook_documents VALUES (?, ?, ?)", [
        ("a", "2026-10-12", "2026-10-12"), ("b", "2026-10-14", "2026-10-14"), ("c", "2026-10-19", "2026-10-19"), ("d", "Plain", "")])
    migrations._journal_notes_become_weekly(old)
    rows = dict(old.execute("SELECT uid, journal_week FROM notebook_documents").fetchall())
    assert rows == {"a": "2026-42", "b": "", "c": "2026-43", "d": ""}
    assert old.execute("SELECT title FROM notebook_documents WHERE uid = 'a'").fetchone()[0] == "2026-42"
