"""University module pages: the Settings page, its modals and previews, and the study page."""

from datetime import date

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import clock, db, study_format, tags, university
from src import university_plan as up
from src.routers.labels import COLORS


def _request(path="/", query=b""):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query, "scheme": "http", "server": ("testserver", 80),
                    "root_path": "", "headers": []})


def _html(response) -> str:
    return response.body.decode()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_MODULES", "university")
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


@pytest.fixture()
def sem(conn):
    uid = up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="University", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18")
    s = up.get_semester(conn, uid)
    up.save_discipline(conn, s, old="", name="Biology", color="green", icon="leaf", teacher_names="Dr Ionescu", colors=COLORS)
    return s


def test_the_page_offers_to_set_up_a_semester_first(conn):
    html = _html(university.university_settings(_request(), conn=conn))
    assert "Nothing set up yet" in html and "/settings/university/semester" in html


def test_the_page_lists_the_semester_and_its_disciplines(conn, sem):
    html = _html(university.university_settings(_request(), conn=conn))
    assert "Autumn 2026" in html and "Biology" in html and "Dr Ionescu" in html and "/settings/university/discipline/Biology" in html


def test_the_forms_and_the_discipline_view_render(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells")
    up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="", status="")
    view = _html(university.discipline_view("Biology", _request(), conn=conn))
    assert "Monday 10:00 to 12:00" in view and "1. Cells" in view and "Final" in view and "Cell Biology" in view
    exam = up.list_exams(conn, sem["uid"])[0]
    reading = up.list_readings(conn, sem["uid"])[0]
    for html in (_html(university.semester_form(_request(), conn=conn)), _html(university.discipline_new(_request(), conn=conn)),
                 _html(university.discipline_edit("Biology", _request(), conn=conn)),
                 _html(university.slot_new(_request(), "Biology", teachers=[], conn=conn)), _html(university.slot_edit(series, _request(), teachers=[], conn=conn)),
                 _html(university.syllabus_form("Biology", _request(), conn=conn)), _html(university.exam_new(_request(), "Biology", conn=conn)),
                 _html(university.exam_edit(exam["task_uid"], _request(), conn=conn)), _html(university.reading_new(_request(), "Biology", conn=conn)),
                 _html(university.reading_edit(reading["task_uid"], _request(), conn=conn)), _html(university.import_form(_request(), conn=conn))):
        assert 'id="modal-target"' in html


def test_the_slot_preview_says_what_will_be_created_and_saving_does_it(conn, sem):
    html = _html(university.slot_preview(_request(), "Biology", "", "0", "10:00", "12:00", "A2", "lecture", "odd", [], conn=conn))
    assert "6 lecture classes of Biology" in html and "odd week" in html and "/settings/university/slot" in html
    assert up.list_slots(conn, sem["uid"]) == []
    university.slot_save("Biology", "", "0", "10:00", "12:00", "A2", "lecture", "odd", [], conn=conn)
    assert len(up.list_slots(conn, sem["uid"])) == 1


def test_a_bad_slot_shows_its_problem_in_the_preview_and_refuses_to_save(conn, sem):
    assert "ends before it starts" in _html(university.slot_preview(_request(), "Biology", "", "0", "12:00", "10:00", "", "lecture", "all", [], conn=conn))
    with pytest.raises(HTTPException) as exc:
        university.slot_save("Biology", "", "0", "12:00", "10:00", "", "lecture", "all", [], conn=conn)
    assert exc.value.status_code == 400


def test_the_semester_preview_names_what_a_new_class_end_does(conn, sem):
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    html = _html(university.semester_preview(_request(), "Autumn 2026", "University", "2026-10-05", "2027-02-14", "2026-11-30", "", conn=conn))
    assert "removes 2 classes" in html and "Exams, tasks and one-off events are not touched" in html


def test_the_first_semester_preview_says_whether_the_shelf_is_adopted(conn):
    db.upsert_label_config(conn, {"name": "University", "color": "red"})
    tags.add_default_tag(conn, "University")
    html = _html(university.semester_preview(_request(), "Autumn", "University", "", "", "", "", conn=conn))
    assert "already exists and is adopted" in html and "read only in Organise" in html
    assert "A new shelf Fresh is created" in _html(university.semester_preview(_request(), "Fresh", "", "", "", "", "", conn=conn))


def test_placing_topics_in_classes_previews_then_applies(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells\n2. Membranes")
    assert "1. Cells goes to the class of 2026-10-05" in _html(university.syllabus_assign_preview("Biology", _request(), conn=conn))
    university.syllabus_assign("Biology", conn=conn)
    assert db.get_event(conn, up.series_members(conn, series)[1]["uid"])["description"] == "2. Membranes"


def test_a_discipline_with_items_cannot_be_removed_from_the_page(conn, sem):
    up.save_exam(conn, sem, "Biology", task_uid=None, title="", day="2027-01-20", start="09:00", end="11:00", weight="")
    with pytest.raises(HTTPException) as exc:
        university.discipline_remove("Biology", conn=conn)
    assert "1 exams" in exc.value.detail


def test_export_and_import_round_trip_through_the_versioned_file(conn, sem):
    up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "room": "B1", "kind": "seminar", "weeks": "even"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells **\n2. Membranes")
    up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="", status="")
    text = university.export_json(what="discipline", discipline="Biology", conn=conn).body.decode()
    kind, data = study_format.load(text)
    assert kind == "discipline" and data["timetable"][0]["weeks"] == "even" and data["exams"][0]["weight"] == 60 and data["themes"][1]["title"] == "Membranes"
    assert study_format.load(university.export_json(what="semester", conn=conn).body.decode())[0] == "semester"
    # importing the file into a fresh semester recreates the discipline
    fresh_conn_semester = up.get_semester(conn, up.save_semester(conn, uid=sem["uid"], name="Autumn 2026", shelf_name="University", start_date="2026-10-05",
                                                               end_date="2027-02-14", class_end_date="2026-12-18"))
    up.delete_slot(conn, sem["uid"], up.list_slots(conn, sem["uid"])[0]["series_uid"])
    up.delete_exam(conn, up.list_exams(conn, sem["uid"])[0]["task_uid"])
    up.delete_reading(conn, up.list_readings(conn, sem["uid"])[0]["task_uid"])
    plan = up.plan_import(conn, fresh_conn_semester, kind, data)
    assert "1 timetable slots, 2 topics, 1 exams, 1 readings" in plan["lines"][0] and "already exists" in plan["warnings"][0]
    up.apply_import(conn, fresh_conn_semester, kind, data, colors=COLORS)
    assert len(up.list_slots(conn, sem["uid"])) == 1 and len(up.list_exams(conn, sem["uid"])) == 1 and len(up.list_readings(conn, sem["uid"])) == 1
    assert len(up.list_topics(conn, sem["uid"], "Biology")) == 2


def test_importing_needs_the_semester_dates(conn):
    uid = up.save_semester(conn, uid=None, name="Bare", shelf_name="Bare", start_date="", end_date="", class_end_date="")
    s = up.get_semester(conn, uid)
    data = {"name": "Bio", "color": "green", "icon": "", "teachers": [], "themes": [], "exams": [], "readings": [],
            "timetable": [{"weekday": 0, "start": "10:00", "end": "12:00", "room": "", "kind": "lecture", "weeks": "all"}]}
    with pytest.raises(up.PlanError, match="start and class end"):
        up.apply_import(conn, s, "discipline", data, colors=COLORS)


def test_the_study_page_shows_the_week_the_exams_and_the_readings(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 7))
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2026-10-09", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="2026-10-12", status="")
    label = db.effective_label_config(conn, "University")
    html = _html(university._render_study(conn, _request("/labels/University"), "University", label))
    assert "Biology" in html and "10:00 to 12:00" in html and "Final" in html and "2 days" in html and "Cell Biology" in html and "Next class" in html
    assert "10:00 to 12:00" in _html(university._render_study(conn, _request("/labels/University", b"week=2026-10-12"), "University", label))
    assert "10:00 to 12:00" not in _html(university._render_study(conn, _request("/labels/University", b"week=2030-01-01"), "University", label))
    assert clock.today() == date(2026, 10, 7)


def test_the_study_page_without_a_semester_points_to_the_settings(conn):
    db.upsert_label_config(conn, {"name": "Uni", "page_type": "study"})
    html = _html(university._render_study(conn, _request("/labels/Uni"), "Uni", db.effective_label_config(conn, "Uni")))
    assert "No semester set up" in html


def test_classes_and_exams_keep_their_title_and_description_outside_the_module(conn, sem):
    from src.routers import calendar as cal, tasks as tasks_router
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    cls = up.series_members(conn, series)[0]
    exam_uid = up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="")
    exam = up.list_exams(conn, sem["uid"])[0]
    assert up.is_locked(conn, "event", cls["uid"]) and up.is_locked(conn, "event", exam["event_uid"]) and up.is_locked(conn, "task", exam_uid)
    db.upsert_event(conn, {"uid": "free", "title": "Dentist", "description": "", "all_day": 0, "status": "active", "start_at": "2026-10-12T09:00", "end_at": "2026-10-12T10:00"})
    assert not up.is_locked(conn, "event", "free")
    import inspect

    def call(fn, uid, **given):
        kwargs = {n: (p.default.default if hasattr(p.default, "default") else p.default) for n, p in inspect.signature(fn).parameters.items()}
        kwargs.update(given, uid=uid, conn=conn)
        return fn(**kwargs)

    call(cal.update_event, cls["uid"], title="Renamed", description="x", start_at=cls["start_at"], end_at=cls["end_at"])
    assert db.get_event(conn, cls["uid"])["title"] == "Biology Lecture" and db.get_event(conn, cls["uid"])["description"] == ""
    call(tasks_router.update_task, exam_uid, title="Renamed", description="x")
    assert db.get_task(conn, exam_uid)["title"] == "Final"
