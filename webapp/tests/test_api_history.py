"""Every change made through MCP or the API can be undone, exactly, and an undo refuses to overwrite later changes unless forced."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src import api_history, api_service, db, mcp_server, university, university_plan as up
from src.api_write import EditError

assert university

TOKEN = {"uid": "t1", "scopes": "read write:notes write:library write:university"}


@pytest.fixture()
def conn(tmp_path, monkeypatch, frozen_today):
    monkeypatch.setenv("CC_MODULES", "university")
    frozen_today(date(2026, 9, 20))
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def _call(conn, tool, **arguments):
    reply = mcp_server.handle(conn, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, TOKEN)
    result = reply.get("error") or reply["result"]
    assert not result.get("isError"), result
    return result["structuredContent"]


def _latest(conn):
    return api_history.list_changes(conn)[0]


def _snapshot_of_everything(conn):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND (name LIKE 'university%' OR name IN "
                                         "('events', 'tasks', 'event_series', 'object_tags', 'object_labels', 'citations', 'notebook_documents'))")]
    out = {}
    for t in tables:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
        for r in rows:
            r.pop("updated_at", None)
            r.pop("completed_at", None)
        out[t] = sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
    return out


def _semester_with_biology(conn):
    _call(conn, "university_save_semester", name="Autumn 2026", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18")
    _call(conn, "university_save_discipline", name="Biology")


def test_a_note_edit_is_undone_and_the_undo_can_be_undone(conn):
    created = _call(conn, "create_note", title="Kant", markdown="First line")
    note = api_service.get_note(conn, created["uid"])
    _call(conn, "rename_note", uid=created["uid"], revision=note["revision"], title="Kant on duty")
    api_history.undo(conn, _latest(conn)["uid"])
    assert api_service.get_note(conn, created["uid"])["title"] == "Kant"
    api_history.undo(conn, _latest(conn)["uid"])
    assert api_service.get_note(conn, created["uid"])["title"] == "Kant on duty"


def test_undoing_a_new_note_removes_it(conn):
    created = _call(conn, "create_note", title="Scratch")
    api_history.undo(conn, _latest(conn)["uid"])
    assert db.get_notebook_document(conn, created["uid"]) is None


def test_a_library_change_is_undone_with_its_ratings(conn):
    uid = _call(conn, "library_save_entry", entry={"type": "film", "title": "Stalker"})["uid"]
    _call(conn, "library_set_tracking", uid=uid, status="finished", rating=5)
    api_history.undo(conn, _latest(conn)["uid"])
    assert api_service.get_citation(conn, uid)["media"]["status"] is None


def test_replacing_exams_is_undone_with_their_events_and_tasks(conn):
    _semester_with_biology(conn)
    _call(conn, "university_save_class_slot", discipline="Biology", weekday="Monday", start="10:00", end="12:00")
    _call(conn, "university_save_evaluation", discipline="Biology",
          way={"name": "Exam", "weight": "100", "exams": [{"title": "Written", "day": "2027-01-20", "start": "09:00", "end": "11:00"}]})
    before = _snapshot_of_everything(conn)
    way = api_service.get_discipline(conn, "Biology")["evaluation"][0]
    _call(conn, "university_save_evaluation", discipline="Biology", way={"id": way["id"], "name": "Exam", "weight": "100", "exams": []})
    assert api_service.get_discipline(conn, "Biology")["exams"] == []
    api_history.undo(conn, _latest(conn)["uid"])
    assert _snapshot_of_everything(conn) == before


def test_a_rebuilt_timetable_is_undone_exactly(conn):
    _semester_with_biology(conn)
    series = _call(conn, "university_save_class_slot", discipline="Biology", weekday="Monday", start="10:00", end="12:00")["series_uid"]
    before = _snapshot_of_everything(conn)
    _call(conn, "university_save_class_slot", discipline="Biology", weekday="Tuesday", start="14:00", end="16:00", series_uid=series)
    api_history.undo(conn, _latest(conn)["uid"])
    assert _snapshot_of_everything(conn) == before


def test_undo_refuses_to_overwrite_a_later_change_unless_forced(conn):
    _semester_with_biology(conn)
    _call(conn, "university_set_course_sheet", discipline="Biology", fields={"credits": "5"})
    change = _latest(conn)["uid"]
    sem = up.current_semester(conn)
    up.save_sheet(conn, sem["uid"], "Biology", {"credits": "6"})
    with pytest.raises(EditError) as err:
        api_history.undo(conn, change)
    assert err.value.code == "conflict"
    api_history.undo(conn, change, force=True)
    assert up.get_sheet(conn, sem["uid"], "Biology")["values"]["credits"] == ""


def test_a_renamed_discipline_is_renamed_back(conn):
    _semester_with_biology(conn)
    _call(conn, "university_save_discipline", name="Botany", old_name="Biology")
    api_history.undo(conn, _latest(conn)["uid"])
    names = [d["name"] for d in up.disciplines(conn, up.current_semester(conn))]
    assert "Biology" in names and "Botany" not in names


def test_a_new_discipline_with_details_asks_to_undo_the_details_first(conn):
    _semester_with_biology(conn)
    added = api_history.list_changes(conn)[0]["uid"]
    _call(conn, "university_save_class_slot", discipline="Biology", weekday="Monday", start="10:00", end="12:00")
    with pytest.raises(EditError) as err:
        api_history.undo(conn, added, force=True)
    assert "first" in str(err.value)


def test_changes_older_than_a_week_are_dropped(conn, frozen_today):
    _call(conn, "create_note", title="Old")
    frozen_today(date(2026, 9, 30))
    _call(conn, "create_note", title="New")
    assert [c["summary"] for c in api_history.list_changes(conn)] == ["Created note New"]
