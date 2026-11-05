"""University attendance, entry conditions and grades, the module's defaults, and a discipline made from the timetable."""

from datetime import date

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import app_defaults, db, university
from src import university_attendance as ua
from src import university_evaluation as ue
from src import university_plan as up
from src.routers.labels import COLORS
from src.university_discipline import discipline_page


def _request(path="/", query=b""):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query, "scheme": "http", "server": ("testserver", 80),
                    "root_path": "", "headers": []})


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_MODULES", "university")
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


@pytest.fixture()
def sem(conn):
    uid = up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18")
    s = up.get_semester(conn, uid)
    up.save_discipline(conn, s, old="", name="Biology", color="green", icon="leaf", teacher_names="", colors=COLORS)
    up.save_slot(conn, s, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_slot(conn, s, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "kind": "seminar", "weeks": "all"})
    return s


def _classes(conn, sem, kind):
    return [c for c in up.list_classes(conn, sem["uid"], "Biology", date(2026, 10, 26)) if c["kind"] == kind]


def test_a_past_class_counts_as_attended_until_it_is_marked(conn, sem):
    data = ua.discipline_attendance(conn, sem["uid"], "Biology", date(2026, 10, 26))
    seminar = next(k for k in data["kinds"] if k["kind"] == "seminar")
    assert seminar["held"] == 3 and seminar["missed"] == 0 and seminar["limit"] is None
    assert {c["status"] for c in data["classes"] if c["past"]} == {"attended"} and {c["status"] for c in data["classes"] if not c["past"]} == {""}


def test_missed_classes_count_against_the_limit_and_excused_ones_do_not(conn, sem):
    up.save_sheet(conn, sem["uid"], "Biology", {"absences_seminar": "1"})
    first, second, third = _classes(conn, sem, "seminar")[:3]
    ua.set_status(conn, first["uid"], "missed", "Ana lent the notes")
    ua.set_status(conn, second["uid"], "excused")
    seminar = next(k for k in ua.discipline_attendance(conn, sem["uid"], "Biology", date(2026, 10, 26))["kinds"] if k["kind"] == "seminar")
    assert (seminar["missed"], seminar["limit"], seminar["left"], seminar["at_risk"], seminar["over"]) == (1, 1, 0, True, False)
    ua.set_status(conn, third["uid"], "missed")
    data = ua.discipline_attendance(conn, sem["uid"], "Biology", date(2026, 10, 26))
    assert data["over"] and [c["note"] for c in data["missed"]] == ["Ana lent the notes", ""]


def test_a_cancelled_class_keeps_its_event_archived_and_comes_back_when_marked_again(conn, sem):
    lecture = _classes(conn, sem, "lecture")[0]
    ua.set_status(conn, lecture["uid"], "cancelled")
    assert db.get_event(conn, lecture["uid"])["status"] == "archived"
    held = next(k for k in ua.discipline_attendance(conn, sem["uid"], "Biology", date(2026, 10, 26))["kinds"] if k["kind"] == "lecture")["held"]
    assert held == 2
    ua.set_status(conn, lecture["uid"], "attended")
    assert db.get_event(conn, lecture["uid"])["status"] == "active" and ua.statuses_of(conn, [lecture["uid"]]) == {}


def test_marking_from_a_menu_keeps_the_note_and_rejects_what_is_not_a_class(conn, sem):
    lecture = _classes(conn, sem, "lecture")[0]
    ua.set_status(conn, lecture["uid"], "missed", "sick")
    resp = university.attendance_save(lecture["uid"], status="excused", note="", back="", keep_note="1", conn=conn)
    assert resp.status_code == 303 and resp.headers["location"] == "/groups/University/disciplines/Biology"
    assert ua.statuses_of(conn, [lecture["uid"]])[lecture["uid"]] == {"status": "excused", "note": "sick"}
    with pytest.raises(up.PlanError):
        ua.set_status(conn, lecture["uid"], "late")


def _ways(conn, sem):
    ue.save_evaluation(conn, sem["uid"], "Biology", [
        {"id": "exam", "name": "Exam", "weight": "60", "min_grade": "5", "criteria": "Sources and dates", "subs": [], "milestones": None,
         "conditions": [{"kind": "attendance", "target": "seminar", "value": ""}, {"kind": "other", "target": "", "value": "Essay handed in"},
                        {"kind": "grade", "target": "sem", "value": "5"}]},
        {"id": "sem", "name": "Seminar", "weight": "40", "subs": [{"id": "act", "name": "Activity", "weight": "50"}, {"id": "ess", "name": "Essay", "weight": "50"}],
         "milestones": None}])


def test_the_final_grade_waits_for_every_weighted_way_and_a_way_takes_its_components_mean(conn, sem):
    _ways(conn, sem)
    ue.set_grades(conn, sem["uid"], "Biology", {"act": "8", "ess": "9"})
    st = ue.standing(conn, sem["uid"], "Biology", date(2026, 10, 26))
    assert st["final"] is None and st["so_far"] == 8.5 and st["graded"] == 1
    ue.set_grades(conn, sem["uid"], "Biology", {"exam": "4"})
    st = ue.standing(conn, sem["uid"], "Biology", date(2026, 10, 26))
    assert st["final"] == 5.8 and st["passed"] is False
    ue.set_grades(conn, sem["uid"], "Biology", {"exam": "7", "act": ""})
    assert ue.standing(conn, sem["uid"], "Biology", date(2026, 10, 26))["final"] is None
    with pytest.raises(up.PlanError):
        ue.set_grades(conn, sem["uid"], "Biology", {"exam": "seven"})


def test_entry_conditions_are_worked_out_and_other_ones_are_ticked_by_hand(conn, sem):
    _ways(conn, sem)
    exam = ue.standing(conn, sem["uid"], "Biology", date(2026, 10, 26))["ways"][0]
    assert [r["is_met"] for r in exam["condition_rows"]] == [None, False, None] and exam["eligible"] is False
    up.save_sheet(conn, sem["uid"], "Biology", {"absences_seminar": "2"})
    ue.set_grades(conn, sem["uid"], "Biology", {"sem": "6"})
    other = exam["condition_rows"][1]["id"]
    ue.tick_condition(conn, sem["uid"], "Biology", "exam", other, True)
    exam = ue.standing(conn, sem["uid"], "Biology", date(2026, 10, 26))["ways"][0]
    assert [r["is_met"] for r in exam["condition_rows"]] == [True, True, True] and exam["eligible"] is True and exam["criteria"] == "Sources and dates"
    page = discipline_page("University", "Biology", _request(), conn=conn).body.decode()
    assert "Exam" in page and "Grade" in page


def test_a_condition_needs_a_number_for_a_minimum_grade(conn, sem):
    with pytest.raises(up.PlanError):
        ue.save_evaluation(conn, sem["uid"], "Biology", [{"id": "", "name": "Exam", "weight": "100", "subs": [], "milestones": None,
                                                          "conditions": [{"kind": "grade", "target": "x", "value": "high"}]}])


def test_a_changed_class_reminder_reaches_the_coming_classes_only(conn, sem):
    changed = up.save_defaults(conn, sem, class_reminder="15", exam_reminder="", class_length="90", passing_grade="6", today=date(2026, 10, 26))
    members = [m for s in up.list_slots(conn, sem["uid"]) for m in up.series_members(conn, s["series_uid"])]
    assert changed == len([m for m in members if m["start_at"] >= "2026-10-26"])
    assert all(m["reminders"] == ([15] if m["start_at"] >= "2026-10-26" else []) for m in members)
    assert app_defaults.get(conn, "class_reminder") == "15" and up.defaults(conn)["class_length"] == "90" and ue.passing_grade(conn) == 6.0
    with pytest.raises(up.PlanError):
        up.save_defaults(conn, sem, class_reminder="", exam_reminder="", class_length="5", passing_grade="5")


def test_a_discipline_typed_on_the_timetable_is_made_with_a_free_colour_and_an_abbreviation(conn, sem):
    resp = university.slot_save(discipline="Istoria Antică a Greciei", discipline_new="", series_uid="", weekday="1", start="10:00", end="11:50", room="A1",
                                kind="lecture", weeks="all", teachers=["Popescu Ion"], back="settings", conn=conn)
    assert resp.headers["location"] == "/settings/university"
    made = next(d for d in up.disciplines(conn, sem) if d["name"] == "Istoria Antică a Greciei")
    assert made["color"] not in ("green", "gray") and up.abbreviations(conn, sem["uid"])["Istoria Antică a Greciei"] == "Istoria"
    assert [t["name"] for t in made["teachers"]] == ["Popescu Ion"] and up.auto_abbreviation("Biology") == "Biology"


def test_the_timetable_is_no_longer_edited_on_the_settings_page_and_a_new_slot_can_start_at_an_hour(conn, sem):
    html = university.university_settings(_request(), conn=conn).body.decode()
    assert "uni-hour" not in html
    form = university.slot_new(_request(), discipline="", weekday="1", start="10:00", conn=conn).body.decode()
    assert "Tuesday" in form and "11:50" in form and "Discipline" in form
    with pytest.raises(HTTPException):
        university.slot_save(discipline="", discipline_new="", series_uid="", weekday="1", start="10:00", end="11:50", room="", kind="lecture", weeks="all",
                             teachers=[], back="settings", conn=conn)


def test_the_semester_lists_render_across_disciplines(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 26))
    _ways(conn, sem)
    ue.save_way(conn, sem["uid"], "Biology", {"id": "exam", "name": "Exam", "weight": "60", "subs": [], "milestones": [{"title": "Final", "day": "2026-11-03", "start": "09:00"}],
                                              "conditions": [], "min_grade": "5", "criteria": ""})
    ua.set_status(conn, _classes(conn, sem, "lecture")[0]["uid"], "missed")
    from src import study_page
    for view, expected in ((b"view=exams", "nbtl-item"), (b"view=exams", "Final")):
        html = university._render_study(conn, _request("/groups/University", view), "University", {"name": "University", "icon": "", "color": ""}).body.decode()
        assert expected in html, view
    assert study_page.exams(conn, sem, date(2026, 10, 26))["groups"][0]["rows"][0]["title"] == "Final"
