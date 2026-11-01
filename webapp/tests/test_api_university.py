"""Filling University details through MCP: the same checks as the windows, and the result reads back as typed in the app."""

from __future__ import annotations

from datetime import date

import pytest

from src import api_service, db, mcp_server, university, university_plan as up

assert university  # registers the module

WRITER = {"uid": "t1", "scopes": "read:university write:university"}


@pytest.fixture()
def conn(tmp_path, monkeypatch, frozen_today):
    monkeypatch.setenv("CC_MODULES", "university")
    frozen_today(date(2026, 9, 20))
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def _call(conn, tool, token=WRITER, **arguments):
    reply = mcp_server.handle(conn, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}, token)
    return reply.get("error") or reply["result"]


def _semester(conn):
    result = _call(conn, "university_save_semester", name="Autumn 2026", start_date="2026-10-05", end_date="2027-02-14",
                   class_end_date="2026-12-18")
    return result["structuredContent"]["semester_uid"]


def test_a_course_sheet_document_can_be_filled_in_full(conn):
    _semester(conn)
    assert _call(conn, "university_save_discipline", name="Istoria Arheologiei")["structuredContent"]["discipline"] == "Istoria Arheologiei"
    _call(conn, "university_set_course_sheet", discipline="istoria arheologiei",
          fields={"code": "IA101", "credits": "5", "absences_seminar": "2", "objectives": "Know the field"},
          extra=[{"section": "content", "label": "Bibliography notes", "value": "See the library"}])
    _call(conn, "university_set_teachers", discipline="Istoria Arheologiei", lecture=["Dr Popescu"], seminar=["Ana Ionescu"])
    _call(conn, "university_save_class_slot", discipline="Istoria Arheologiei", weekday="Monday", start="10:00", end="12:00",
          kind="lecture", room="A2")
    _call(conn, "university_save_evaluation", discipline="Istoria Arheologiei",
          way={"name": "Final exam", "weight": "70", "exams": [{"title": "Written exam", "day": "2027-01-20", "start": "09:00", "end": "11:00"}]})
    _call(conn, "university_set_topics", discipline="Istoria Arheologiei", topics=["Introduction", "Methods"])
    _call(conn, "university_save_reading", discipline="Istoria Arheologiei", title="Manual", author="Renfrew", locator="pp. 1-40",
          category="obligatory")
    _call(conn, "university_save_homework", discipline="Istoria Arheologiei", title="Essay", due="2026-11-10")

    d = api_service.get_discipline(conn, "Istoria Arheologiei")
    assert d["course_sheet"]["code"] == "IA101" and d["course_sheet"]["credits"] == "5"
    assert d["course_sheet"]["abbreviation"] == "IA"
    assert d["teachers"] and set(d["teachers"]) == {"Dr Popescu", "Ana Ionescu"}
    assert d["timetable"][0]["weekday"] == "Monday" and d["timetable"][0]["room"] == "A2"
    assert d["evaluation"][0]["name"] == "Final exam" and d["exams"][0]["date"] == "2027-01-20"
    assert d["topics"]["lecture"] == ["Introduction", "Methods"]
    assert d["readings"][0]["title"].startswith("Manual")
    sem = up.current_semester(conn)
    assert up.get_sheet(conn, sem["uid"], "Istoria Arheologiei")["sections"][2]["custom"][0]["label"] == "Bibliography notes"


def test_the_windows_rules_refuse_bad_input(conn):
    _semester(conn)
    _call(conn, "university_save_discipline", name="Biology")
    bad = [
        _call(conn, "university_set_course_sheet", discipline="Biology", fields={"credits": "five"}),
        _call(conn, "university_set_course_sheet", discipline="Biology", fields={"grade_of_teacher": "10"}),
        _call(conn, "university_save_class_slot", discipline="Biology", weekday="Funday", start="10:00", end="12:00"),
        _call(conn, "university_save_class_slot", discipline="Biology", weekday="Monday", start="12:00", end="10:00"),
        _call(conn, "university_set_topics", discipline="Chemistry", topics=["x"]),
    ]
    assert all(r["isError"] for r in bad)


def test_an_evaluation_way_keeps_its_place_when_changed(conn):
    _semester(conn)
    _call(conn, "university_save_discipline", name="Biology")
    _call(conn, "university_save_evaluation", discipline="Biology", way={"name": "Lab work", "weight": "30"})
    _call(conn, "university_save_evaluation", discipline="Biology", way={"name": "Exam", "weight": "70"})
    lab = api_service.get_discipline(conn, "Biology")["evaluation"][0]
    _call(conn, "university_save_evaluation", discipline="Biology", way={"id": lab["id"], "name": "Lab reports", "weight": "40"})
    assert [(w["name"], w["weight"]) for w in api_service.get_discipline(conn, "Biology")["evaluation"]] == [("Lab reports", 40.0), ("Exam", 70.0)]


def test_university_edits_need_their_own_permission(conn):
    _semester(conn)
    reader = {"uid": "t2", "scopes": "read:notes read:university write:notes"}
    names = {t.name for t in mcp_server.visible_tools(reader)}
    assert "get_discipline" in names and "university_save_discipline" not in names
    assert "error" in mcp_server.handle(conn, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "university_save_discipline", "arguments": {"name": "Biology"}}}, reader)
