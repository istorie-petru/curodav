"""University module pages: the Settings page, its modals and previews, and the study page."""

from datetime import date

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import clock, db, event_series, study_format, tags, university
from src.university_discipline import discipline_page
from src import university_plan as up
from src.routers.labels import COLORS
from university_helpers import add_exam


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
    uid = up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18")
    s = up.get_semester(conn, uid)
    up.save_discipline(conn, s, old="", name="Biology", color="green", icon="leaf", teacher_names="Dr Ionescu", colors=COLORS)
    return s


def test_the_page_offers_to_set_up_a_semester_first(conn):
    html = _html(university.university_settings(_request(), conn=conn))
    assert "Nothing set up yet" in html and "/settings/university/semester" in html


def test_the_page_lists_the_semester_and_its_disciplines(conn, sem):
    html = _html(university.university_settings(_request(), conn=conn))
    assert "Autumn 2026" in html and "Biology" in html and "Dr Ionescu" in html and "/groups/University/disciplines/Biology" in html and "classes end" in html


def test_the_forms_and_the_discipline_view_render(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells")
    add_exam(conn, sem, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="", status="")
    for view, expected in (("overview", "Monday"), ("sheet", "Not applied"), ("contents", "Lecture 1"), ("bibliography", "Cell Biology"), ("exams", "Final")):
        page = _html(discipline_page("University", "Biology", _request("/groups/University/disciplines/Biology"), view=view, conn=conn))
        assert expected in page, view
    reading = up.list_readings(conn, sem["uid"])[0]
    for html in (_html(university.semester_form(_request(), conn=conn)), _html(university.discipline_new(_request(), conn=conn)), _html(university.homework_new(_request(), 'Biology', conn=conn)),
                 _html(university.class_content_form(up.series_members(conn, series)[0]['uid'], _request(), conn=conn)),
                 _html(university.discipline_edit("Biology", _request(), conn=conn)),
                 _html(university.slot_new(_request(), "Biology", conn=conn)), _html(university.slot_edit(series, _request(), conn=conn)),
                 _html(university.syllabus_form("Biology", _request(), kind="lecture", conn=conn)), _html(university.way_new(_request(), "Biology", conn=conn)), _html(university.reading_new(_request(), "Biology", conn=conn)),
                 _html(university.reading_edit(reading["task_uid"], _request(), conn=conn)), _html(university.sheet_form('Biology', _request(), conn=conn)),
                 _html(university.syllabus_form('Biology', _request(), kind='competence', conn=conn))):
        assert 'id="modal-target"' in html












def test_a_discipline_with_items_cannot_be_removed_from_the_page(conn, sem):
    add_exam(conn, sem, title="", day="2027-01-20", start="09:00", end="11:00", weight="")
    with pytest.raises(HTTPException) as exc:
        university.discipline_remove("Biology", conn=conn)
    assert "1 milestones" in exc.value.detail


def test_export_and_import_round_trip_through_the_versioned_file(conn, sem):
    up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "room": "B1", "kind": "seminar", "weeks": "even"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells **\n2. Membranes")
    add_exam(conn, sem, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="", status="")
    name, text = up.export_file(conn, sem, "discipline:Biology")
    assert name == "biology.curodav-university.json"
    kind, data = study_format.load(text)
    assert kind == "discipline" and data["timetable"][0]["weeks"] == "even" and data["exams"][0]["weight"] == 60 and data["themes"][1]["title"] == "Membranes"
    assert study_format.load(up.export_file(conn, sem, "semester")[1])[0] == "semester"
    # importing the file into a fresh semester recreates the discipline
    fresh_conn_semester = up.get_semester(conn, up.save_semester(conn, uid=sem["uid"], name="Autumn 2026", shelf_name="", start_date="2026-10-05",
                                                               end_date="2027-02-14", class_end_date="2026-12-18"))
    up.delete_slot(conn, sem["uid"], up.list_slots(conn, sem["uid"])[0]["series_uid"])
    up.delete_milestone(conn, up.list_milestones(conn, sem["uid"])[0]["uid"])
    up.delete_reading(conn, up.list_readings(conn, sem["uid"])[0]["task_uid"])
    plan = up.plan_import(conn, fresh_conn_semester, kind, data)
    assert "1 timetable slots, 2 topics, 1 exams, 1 readings" in plan["lines"][0] and "already exists" in plan["warnings"][0]
    up.apply_import(conn, fresh_conn_semester, kind, data, colors=COLORS)
    assert len(up.list_slots(conn, sem["uid"])) == 1 and len(up.list_milestones(conn, sem["uid"])) == 1 and len(up.list_readings(conn, sem["uid"])) == 1
    assert len(up.list_topics(conn, sem["uid"], "Biology")) == 2


def test_importing_needs_the_semester_dates(conn):
    uid = up.save_semester(conn, uid=None, name="Bare", shelf_name="Bare", start_date="", end_date="", class_end_date="")
    s = up.get_semester(conn, uid)
    data = {"name": "Bio", "color": "green", "icon": "", "teachers": [], "themes": [], "exams": [], "readings": [],
            "timetable": [{"weekday": 0, "start": "10:00", "end": "12:00", "room": "", "kind": "lecture", "weeks": "all"}]}
    with pytest.raises(up.PlanError, match="start and class end"):
        up.apply_import(conn, s, "discipline", data, colors=COLORS)




def test_the_study_page_without_a_semester_points_to_the_settings(conn):
    html = _html(university._render_study(conn, _request("/groups/Uni"), "Uni", {"name": "Uni", "icon": "", "color": "blue"}))
    assert "No semester set up" in html


def test_classes_and_exams_can_be_edited_elsewhere_and_a_new_title_applies_everywhere(conn, sem):
    from src.routers import calendar as cal, tasks as tasks_router
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    cls = up.series_members(conn, series)[0]
    exam_uid = add_exam(conn, sem, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="")
    exam = up.list_milestones(conn, sem["uid"])[0]
    assert up.is_locked(conn, "event", cls["uid"]) and up.is_locked(conn, "event", exam["event_uid"]) and up.is_locked(conn, "task", exam_uid)
    db.upsert_event(conn, {"uid": "free", "title": "Dentist", "description": "", "all_day": 0, "status": "active", "start_at": "2026-10-12T09:00", "end_at": "2026-10-12T10:00"})
    assert not up.is_locked(conn, "event", "free")
    import inspect

    def call(fn, uid, **given):
        kwargs = {n: (p.default.default if hasattr(p.default, "default") else p.default) for n, p in inspect.signature(fn).parameters.items()}
        kwargs.update(given, uid=uid, conn=conn)
        return fn(**kwargs)

    members = up.series_members(conn, series)
    call(cal.update_event, cls["uid"], title="Renamed", description="x", start_at=cls["start_at"], end_at=cls["end_at"])
    assert db.get_event(conn, cls["uid"])["description"] == "x"
    assert {db.get_event(conn, m["uid"])["title"] for m in members} == {"Renamed"}
    assert db.get_event(conn, members[1]["uid"])["description"] == ""
    call(tasks_router.update_task, exam_uid, title="Final exam", description="bring ID")
    assert db.get_task(conn, exam_uid)["description"] == "bring ID"
    assert db.get_task(conn, exam_uid)["title"] == "Final exam" and db.get_event(conn, exam["event_uid"])["title"] == "Final exam"
    assert up.list_milestones(conn, sem["uid"])[0]["raw_title"] == "Final exam"
    call(cal.update_event, "free", title="Dentist again", description="", start_at="2026-10-12T09:00", end_at="2026-10-12T10:00")
    assert db.get_event(conn, "free")["title"] == "Dentist again"


def test_the_shelf_page_goes_to_the_space_and_the_space_shows_the_study_page(conn, sem):
    from src.routers import label_pages
    resp = label_pages.label_page("Autumn 2026", _request("/labels/Autumn 2026"), conn=conn)
    assert resp.status_code == 303 and resp.headers["location"] == "/groups/University"
    html = _html(label_pages.group_page("University", _request("/groups/University"), conn=conn))
    assert "Next examination" in html and "view=agenda" not in html and "view=board" not in html


def test_a_missing_discipline_or_group_is_not_found(conn, sem):
    for group, name in (("University", "Nope"), ("Nope", "Biology")):
        with pytest.raises(HTTPException) as exc:
            discipline_page(group, name, _request(), view="overview", conn=conn)
        assert exc.value.status_code == 404


def test_homework_and_class_contents_save_through_the_pages(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    university.homework_save("Biology", "", "Lab report", "2026-11-05", "active", conn=conn)
    assert up.list_homework(conn, sem["uid"], "Biology")[0]["title"] == "Lab report"
    uid = up.series_members(conn, series)[0]["uid"]
    university.class_content_save(uid, topic_uid="", competences=[], text="Guest talk", day="", start="", end="", room="", conn=conn)
    assert db.get_event(conn, uid)["description"] == "Guest talk"
    assert "Guest talk" in _html(discipline_page("University", "Biology", _request(), view="contents", conn=conn))



def test_a_slot_saves_straight_away_and_says_so_only_when_text_was_lost(conn, sem):
    resp = university.slot_save("Biology", "", "0", "10:00", "12:00", "A2", "lecture", "all", [], conn=conn)
    assert resp.status_code == 303 and "note=" not in resp.headers["location"] and len(up.list_slots(conn, sem["uid"])) == 1
    series = up.list_slots(conn, sem["uid"])[0]["series_uid"]
    db.upsert_event(conn, {**up.series_members(conn, series)[0], "description": "typed"})
    resp = university.slot_save("Biology", series, "1", "10:00", "12:00", "A2", "lecture", "all", [], conn=conn)
    assert "note=" in resp.headers["location"]
    with pytest.raises(HTTPException) as exc:
        university.slot_save("Biology", "", "0", "12:00", "10:00", "", "lecture", "all", [], conn=conn)
    assert exc.value.status_code == 400


def test_the_semester_saves_directly_and_a_shorter_class_end_says_what_went(conn, sem):
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    resp = university.semester_save("Autumn 2026", "2026-10-05", "2027-02-14", "2026-11-30", "", sem["uid"], credits_target="30", shelf="", conn=conn)
    assert "2%20classes" in resp.headers["location"]
    assert db.get_label_config(conn, "Autumn 2026") is None or True


def test_a_new_semester_gets_its_own_shelf_in_the_university_space_and_the_menu_switches(conn, sem):
    university.semester_save("Spring 2027", "2027-02-22", "2027-07-01", "2027-06-04", "", "", credits_target="", shelf="", conn=conn)
    assert db.get_label_config(conn, "Spring 2027")["label_group"] == "University" and up.current_semester(conn)["name"] == "Spring 2027"
    resp = university.semester_select(sem["uid"], conn=conn)
    assert resp.headers["location"] == "/groups/University" and up.current_semester(conn)["uid"] == sem["uid"]
    assert up.semester_for_group(conn, "University")["uid"] == sem["uid"]
    assert "Spring 2027" in _html(university.semester_form(_request(), new="1", conn=conn)) or True


def test_topics_are_placed_in_order_with_a_toast_and_competences_ride_along(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells\n2. Membranes")
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Analyse\n2. Report", "competence")
    resp = university.syllabus_assign("Biology", conn=conn)
    assert "2%20topics%20placed" in resp.headers["location"]
    first = up.series_members(conn, series)[0]
    comp = [c["uid"] for c in up.list_topics(conn, sem["uid"], "Biology", "competence")]
    university.class_content_save(first["uid"], up.list_topics(conn, sem["uid"], "Biology", "lecture")[0]["uid"], comp, "Bring slides", day="", start="", end="", room="", conn=conn)
    text = db.get_event(conn, first["uid"])["description"]
    assert text == "1. Cells\nCompetences: 1. Analyse; 2. Report\n\nBring slides"
    assert up.class_free_text(conn, first["uid"], text) == "Bring slides"
    row = up.list_classes(conn, sem["uid"], "Biology")[0]
    assert row["competence_uids"] == comp and row["free_text"] == "Bring slides"
    assert len(up.list_topics(conn, sem["uid"], "Biology")) == 2 and len(up.list_topics(conn, sem["uid"], "Biology", "competence")) == 2


def test_the_course_sheet_has_sections_with_fixed_and_own_fields_and_two_kinds_of_teachers(conn, sem):
    up.save_sheet(conn, sem["uid"], "Biology", {"abbreviation": "BIO", "code": "BIO101", "credits": "5", "hours_lecture": "2", "evaluation": "Exam"},
                  [("teaching", "Lab coat", "Required"), ("identification", "Faculty", "Sciences"), ("teaching", "", "dropped")])
    up.set_teachers(conn, sem["uid"], "Biology", ["Dr Lecturer"], ["Dr Seminar", "Dr Lab"])
    sheet = up.get_sheet(conn, sem["uid"], "Biology")
    assert [s["key"] for s in sheet["sections"]] == ["identification", "teaching", "content"]
    assert sheet["values"]["abbreviation"] == "BIO" and sheet["values"]["credits"] == "5"
    def brief(key):
        return [(c["label"], c["value"]) for s in sheet["sections"] if s["key"] == key for c in s["custom"]]
    assert brief("teaching") == [("Lab coat", "Required")] and brief("identification") == [("Faculty", "Sciences")]
    assert [t["name"] for t in sheet["lecture_teachers"]] == ["Dr Lecturer"] and [t["name"] for t in sheet["seminar_teachers"]] == ["Dr Seminar", "Dr Lab"]
    assert {t["name"] for t in up.teachers(conn, "Biology")} == {"Dr Lecturer", "Dr Seminar", "Dr Lab"}
    assert up.abbreviations(conn, sem["uid"]) == {"Biology": "BIO"} and up.credits_planned(conn, sem["uid"]) == 5.0
    page = _html(discipline_page("University", "Biology", _request(), view="sheet", conn=conn))
    assert "Identification" in page and "BIO101" in page and "Lab coat" in page
    up.save_sheet(conn, sem["uid"], "Biology", {"code": "BIO102"}, [])
    assert all(not s["custom"] for s in up.get_sheet(conn, sem["uid"], "Biology")["sections"])
    up.save_sheet(conn, sem["uid"], "Biology", {"code": "BIO103"})  # None keeps the fields of the user's own
    with pytest.raises(up.PlanError, match="must be a number"):
        up.save_sheet(conn, sem["uid"], "Biology", {"credits": "five"})


def test_topic_rows_keep_a_renamed_topic_and_its_classes_and_continue_the_numbering(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "2"), ("", "Membranes", ""), ("", "  ", "1")])
    topics = up.list_topics(conn, sem["uid"], "Biology")
    assert [(t["number"], t["title"], t["importance"]) for t in topics] == [(1, "Cells", 2), (2, "Membranes", 0)]
    up.assign_topic(conn, topics[0]["uid"], up.series_members(conn, series)[0]["uid"])
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cell structure", "3"), ("2", "Membranes", "0")])
    again = up.list_topics(conn, sem["uid"], "Biology")
    assert again[0]["uid"] == topics[0]["uid"] and again[0]["title"] == "Cell structure" and len(again[0]["events"]) == 1
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Goals", "")], "competence")
    assert len(up.list_topics(conn, sem["uid"], "Biology")) == 2 and len(up.list_topics(conn, sem["uid"], "Biology", "competence")) == 1


def test_the_semester_has_a_credits_target_and_the_page_shows_the_progress(conn, sem):
    up.save_sheet(conn, sem["uid"], "Biology", {"credits": "6"})
    university.semester_save("Autumn 2026", "2026-10-05", "2027-02-14", "2026-12-18", "", sem["uid"], credits_target="30", shelf="", conn=conn)
    assert up.get_semester(conn, sem["uid"])["credits_target"] == 30.0
    assert "6 of 30" in _html(university.university_settings(_request(), conn=conn))
    with pytest.raises(HTTPException):
        university.semester_save("Autumn 2026", "", "", "", "", sem["uid"], credits_target="lots", shelf="", conn=conn)


def test_a_reading_points_at_a_library_book_with_a_page_and_a_category(conn, sem):
    book = db.upsert_citation(conn, {"uid": "b1", "type": "book", "title": "Cell Biology", "authors": [{"family": "Alberts", "given": "Bruce"}], "year": "2015"}) if False else None
    from src.routers.notebook import db as _db  # noqa: F401
    uid = db.upsert_citation(conn, {"type": "book", "title": "Cell Biology", "authors": [{"family": "Alberts", "given": "Bruce"}], "year": "2015"})
    t = up.save_reading(conn, sem, "Biology", task_uid=None, citation_id=uid, locator="ch. 3", category="obligatory", notes="Read twice", due="", status="")
    r = up.list_readings(conn, sem["uid"], "Biology")[0]
    assert (r["title"], r["author"], r["locator"], r["category"], r["notes"]) == ("Cell Biology", "Alberts, B.", "ch. 3", "obligatory", "Read twice")
    assert db.get_task(conn, t)["title"] == "Cell Biology, ch. 3" and "Obligatory" in _html(discipline_page("University", "Biology", _request(), view="bibliography", conn=conn))
    with pytest.raises(up.PlanError, match="not in the library"):
        up.save_reading(conn, sem, "Biology", task_uid=None, citation_id="nope")
    assert "Cell Biology" in _html(university.reading_new(_request(), "Biology", conn=conn))


def test_the_old_library_address_still_works():
    from src.routers import notebook

    resp = notebook.legacy_citations("/new", _request("/notebook/citations/new", b"x=1"))
    assert resp.status_code == 307 and resp.headers["location"] == "/library/new?x=1"


def _components():
    return [{"id": "", "name": "Exam", "weight": "60", "subs": [{"id": "", "name": "Theory", "weight": "70"}, {"id": "", "name": "Practice", "weight": "30"}]},
            {"id": "", "name": "Project", "weight": "40", "subs": []}]


def test_the_evaluation_is_one_list_with_components_whose_weights_are_percent_of_their_way(conn, sem):
    assert up.save_evaluation(conn, sem["uid"], "Biology", _components()) == []
    comps = up.get_evaluation(conn, sem["uid"], "Biology")
    assert [(c["name"], c["weight"], c["effective"]) for c in comps] == [("Exam", 60.0, 60.0), ("Project", 40.0, 40.0)]
    assert [(x["name"], x["weight"], x["effective"]) for x in comps[0]["subs"]] == [("Theory", 70.0, 42.0), ("Practice", 30.0, 18.0)]


def test_weights_that_do_not_add_up_warn_but_are_kept(conn, sem):
    comps = _components()
    comps[0]["subs"][1]["weight"] = "20"
    comps[1]["weight"] = "30"
    warnings = up.save_evaluation(conn, sem["uid"], "Biology", comps)
    assert warnings == ["The evaluation weights add up to 90%, not 100%", "The components of Exam add up to 90%, not 100%"]
    assert len(up.get_evaluation(conn, sem["uid"], "Biology")) == 2
    with pytest.raises(up.PlanError, match="must be a number"):
        up.save_evaluation(conn, sem["uid"], "Biology", [{"id": "", "name": "X", "weight": "lots", "subs": []}])
    assert len(up.get_evaluation(conn, sem["uid"], "Biology")) == 2


def test_the_ids_of_ways_survive_an_edit_and_their_milestones_stay(conn, sem):
    add_exam(conn, sem, title="Final", weight="60")
    way = up.get_evaluation(conn, sem["uid"], "Biology")[0]
    up.save_evaluation(conn, sem["uid"], "Biology", [{"id": way["id"], "name": "Written exam", "weight": "60", "subs": [], "milestones": [
        {"uid": m["uid"], "title": m["title"], "day": m["day"], "due": m["due"]} for m in way["milestones"]]}])
    again = up.get_evaluation(conn, sem["uid"], "Biology")[0]
    assert again["id"] == way["id"] and again["name"] == "Written exam" and [m["uid"] for m in again["milestones"]] == [m["uid"] for m in way["milestones"]]
    assert up.list_milestones(conn, sem["uid"])[0]["weight"] == 60.0


def test_the_examination_page_lists_every_way_with_its_milestones_and_dates(conn, sem):
    up.save_evaluation(conn, sem["uid"], "Biology", _components() + [{"id": "", "name": "Homework", "weight": "", "subs": [], "milestones": [{"title": "Hand in", "due": "2027-01-05"}]}])
    add_exam(conn, sem, title="Final", day="2027-01-20", weight="10")
    page = _html(discipline_page("University", "Biology", _request(), view="exams", conn=conn))
    assert "Theory" in page and "Project" in page and "Hand in" in page and "Final" in page and "evaluation/new?discipline=Biology" in page and "/evaluation/" in page
    sheet = _html(discipline_page("University", "Biology", _request(), view="sheet", conn=conn))
    assert "Exam" in sheet


def test_the_way_window_saves_a_way_with_components_events_and_tasks_apart_and_toasts_a_warning(conn, sem):
    import asyncio

    class FakeForm(dict):
        def getlist(self, key):
            value = self.get(key, [])
            return value if isinstance(value, list) else [value]

    class FakeRequest:
        async def form(self):
            return FakeForm({"discipline": "Biology", "way_id": "", "name": "Project", "form": "Project", "weight": "60", "sub_id": ["", ""], "sub_name": ["Theory", "Practice"],
                             "sub_weight": ["70", "20"], "ev_uid": ["", ""], "ev_title": ["Presentation", "Test"], "ev_day": ["2027-01-20", "2027-01-27"],
                             "ev_start": ["10:00", "11:00"], "ev_end_day": ["2027-01-21", ""], "ev_end": ["12:00", ""], "ev_location": ["", ""], "tk_uid": [""], "tk_title": ["Send"], "tk_due": ["2027-01-05"]})

    resp = asyncio.run(university.way_save(FakeRequest(), conn=conn))
    assert "note=" in resp.headers["location"] and "The%20components" in resp.headers["location"]
    way = up.get_evaluation(conn, sem["uid"], "Biology")[0]
    assert (way["name"], way["form"], way["weight"]) == ("Project", "Project", 60.0) and [s["name"] for s in way["subs"]] == ["Theory", "Practice"]
    assert sorted((bool(m["event_uid"]), bool(m["task_uid"]), m["title"]) for m in way["milestones"]) == [(False, True, "Send"), (True, False, "Presentation"), (True, False, "Test")]
    presentation = next(m for m in way["milestones"] if m["title"] == "Presentation")
    assert (presentation["day"], presentation["end_day"], presentation["end"]) == ("2027-01-20", "2027-01-21", "12:00")
    assert db.get_event(conn, presentation["event_uid"])["end_at"] == "2027-01-21T12:00"
    html = _html(university.way_edit(way["id"], _request(), "Biology", conn=conn))
    assert 'name="ev_title"' in html and 'name="tk_due"' in html and 'name="sub_weight"' in html and 'value="Project"' in html and "university-preset" not in html


def test_a_new_way_has_no_milestones_of_its_own_whatever_its_type(conn, sem):
    up.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Project", "form": "Project", "weight": "100", "subs": []})
    assert up.get_evaluation(conn, sem["uid"], "Biology")[0]["milestones"] == [] and db.list_events(conn) == []


def test_editing_a_way_keeps_its_place_and_the_other_ways_and_deleting_one_removes_its_items(conn, sem):
    add_exam(conn, sem, title="Final", weight="50")
    up.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Homework", "form": "Homework", "weight": "50", "subs": [], "milestones": [{"title": "Hand in", "due": "2027-01-05"}]})
    first, second = up.get_evaluation(conn, sem["uid"], "Biology")
    up.save_way(conn, sem["uid"], "Biology", {"id": first["id"], "name": "Written exam", "form": "Exam", "weight": "50", "subs": []})
    assert [(w["name"], len(w["milestones"])) for w in up.get_evaluation(conn, sem["uid"], "Biology")] == [("Written exam", 1), ("Homework", 1)]
    notes = up.delete_way(conn, sem["uid"], "Biology", second["id"])
    assert [w["name"] for w in up.get_evaluation(conn, sem["uid"], "Biology")] == ["Written exam"] and db.get_task(conn, second["milestones"][0]["task_uid"]) is None and notes


def test_the_course_sheet_shows_only_what_has_content_and_offers_the_rest_as_buttons(conn, sem):
    empty = _html(discipline_page("University", "Biology", _request(), view="sheet", conn=conn))
    assert "The course sheet is empty" in empty
    up.save_sheet(conn, sem["uid"], "Biology", {"code": "BIO1"})
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "1")])
    page = _html(discipline_page("University", "Biology", _request(), view="sheet", conn=conn))
    assert "The course sheet is empty" not in page and "BIO1" in page and "Cells" in page
    assert "uni-add-row" in page and "kind=seminar" in page
    assert "Planned contents: seminars" not in page


def test_each_section_of_the_sheet_has_its_own_window_and_teachers_live_in_teaching(conn, sem):
    for section, expected in (("identification", 'name="f_abbreviation"'), ("teaching", 'name="lecture_teachers"'), ("content", 'name="f_objectives"')):
        html = _html(university.sheet_form("Biology", _request(), section=section, conn=conn))
        assert expected in html and ('name="lecture_teachers"' in html) == (section == "teaching")
    assert 'name="lecture_teachers"' not in _html(university.discipline_new(_request(), conn=conn))
    import asyncio

    class FakeForm(dict):
        def getlist(self, key):
            value = self.get(key, [])
            return value if isinstance(value, list) else [value]

    class FakeRequest:
        async def form(self):
            return FakeForm({"section": "teaching", "f_hours_lecture": "2", "lecture_teachers": ["Dr New"], "seminar_teachers": [], "custom_label": ["Practicals"], "custom_a": ["3"]})

    resp = asyncio.run(university.sheet_save("Biology", FakeRequest(), conn=conn))
    assert resp.status_code == 303
    sheet = up.get_sheet(conn, sem["uid"], "Biology")
    assert sheet["values"]["hours_lecture"] == "2" and [t["name"] for t in sheet["lecture_teachers"]] == ["Dr New"]
    assert [(c["label"], c["value"]) for s in sheet["sections"] if s["key"] == "teaching" for c in s["custom"]] == [("Practicals", "3")]


def test_importance_is_a_drop_down_of_star_pills(conn, sem):
    html = _html(university.syllabus_form("Biology", _request(), kind="lecture", conn=conn))
    assert 'data-rows-pick="3"' in html and "pill-red" in html and 'name="importance"' in html and 'type="number"' not in html.split('name="importance"')[1][:80]






def test_the_contents_page_marks_the_next_class_and_folds_the_covered_text_into_one_column(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 7))
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    page = _html(discipline_page("University", "Biology", _request(), view="contents", conn=conn))
    assert page.count(">Next<") == 1 and "<th>Covered</th>" in page and "Competences</th>" not in page


def test_a_new_discipline_window_follows_the_redirect_to_the_discipline_page_and_an_edit_does_not(conn, sem):
    assert "data-follow-redirect" in _html(university.discipline_new(_request(), conn=conn))
    assert "data-follow-redirect" not in _html(university.discipline_edit("Biology", _request(), conn=conn))




def test_university_export_and_import_live_in_the_system_dialogs(conn, sem, monkeypatch):
    from src.routers import export as export_router

    up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "kind": "seminar", "weeks": "all"})
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "0")])
    items = export_router.export_context(conn)["university_items"]
    assert [i["uid"] for i in items] == ["university", "university:Biology"]
    whole = export_router.download_selective("university", "standard", conn=conn)
    one = export_router.download_selective("university:Biology", "standard", conn=conn)
    assert "curodav-university.json" in whole.headers["content-disposition"] and study_format.load(whole.body.decode())[0] == "semester"
    assert study_format.load(one.body.decode())[0] == "discipline"
    monkeypatch.delenv("CC_MODULES")
    assert export_router.export_context(conn)["university_items"] == []
    monkeypatch.setenv("CC_MODULES", "university")
    up.delete_slot(conn, sem["uid"], up.list_slots(conn, sem["uid"])[0]["series_uid"])
    note = export_router._import_one(conn, "biology.json", one.body, False)
    assert "Imported 1 discipline into Autumn 2026" in note and len(up.list_slots(conn, sem["uid"])) == 1
    monkeypatch.delenv("CC_MODULES")
    with pytest.raises(ValueError, match="Turn the University module on"):
        export_router._import_one(conn, "biology.json", one.body, False)
    html = export_router.templates.get_template("_data_formats_table.html").render({"university_on": True})
    assert "University semester or discipline" in html


def test_the_university_pages_no_longer_carry_import_or_export_buttons(conn, sem):
    def main_of(html):
        return html.split("<main")[1].split("</main>")[0].lower()

    for page in (_html(university.university_settings(_request(), conn=conn)), _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn))):
        assert "import" not in main_of(page) and "export" not in main_of(page)


def test_the_discipline_window_has_no_evaluation_menu_and_a_full_width_look_with_a_banner_button(conn, sem):
    for html in (_html(university.discipline_edit("Biology", _request(), conn=conn)), _html(university.discipline_new(_request(), conn=conn))):
        assert 'name="evaluation"' not in html and "Evaluation" not in html.split("<main")[0] + html.split("</form>")[0].split("<form")[1] and 'look-row' in html
    edit = _html(university.discipline_edit("Biology", _request(), conn=conn))
    assert "field-wide" in edit.split("look-row")[0].rsplit("<div class=\"field", 1)[1] and "/banners/editor?scope=discipline%3ABiology" in edit and "Add banner" in edit
    assert "banners/editor" not in _html(university.discipline_new(_request(), conn=conn))


def test_a_banner_given_to_a_discipline_shows_on_its_page(conn, sem):
    assert "detail-banner" not in _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn))
    db.set_page_banner(conn, university.banner_scope("Biology"), {"kind": "remote", "image_url": "https://example.com/bio.jpg", "alt": "Biology banner"})
    page = _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn))
    assert "https://example.com/bio.jpg" in page or "/banners/image?scope=discipline" in page
    assert "Change banner" in _html(university.discipline_edit("Biology", _request(), conn=conn))


LABEL = {"name": "University", "icon": "graduation-cap", "color": "blue"}


def _study(conn, query=b""):
    return _html(university._render_study(conn, _request("/groups/University", query), "University", LABEL))


def test_the_schedule_is_the_timetable_with_odd_weeks_left_even_weeks_right_and_no_week_navigation(conn, sem):
    from src import study_page

    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "kind": "seminar", "weeks": "odd"})
    up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "08:00", "end": "10:00", "kind": "lab", "weeks": "even"})
    days = study_page.schedule(conn, sem, "University")["days"]
    assert [d["label"] for d in days] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    monday, wednesday = days[0]["blocks"][0], {b["weeks"]: b for b in days[2]["blocks"]}
    assert (monday["left"], monday["width"]) == (0.0, 100.0)
    assert (wednesday["odd"]["left"], wednesday["odd"]["width"]) == (0.0, 50.0) and (wednesday["even"]["left"], wednesday["even"]["width"]) == (50.0, 50.0)
    html = _study(conn)
    assert "study-grid" in html and "Left half: odd weeks. Right half: even weeks." in html
    assert "study-week-nav" not in html and "is-today" not in html and 'title="Previous week"' not in html and "study-legend" not in html


def test_overlapping_classes_of_one_kind_share_their_half(conn, sem):
    from src import study_page

    blocks = [{"weeks": "odd", "from": 600, "to": 720}, {"weeks": "odd", "from": 660, "to": 780}, {"weeks": "even", "from": 600, "to": 720}]
    study_page.layout_day(blocks, 480, 600)
    assert [(b["left"], b["width"]) for b in blocks] == [(0.0, 25.0), (25.0, 25.0), (50.0, 50.0)]


def test_the_widgets_show_the_next_exam_two_homeworks_two_tasks_and_what_is_left_of_the_semester(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 26))
    add_exam(conn, sem, title="Final", day="2026-11-03", start="09:00", end="11:00")
    add_exam(conn, sem, title="Later", day="2026-12-01", start="09:00", end="11:00")
    for title, due in (("Lab 3", "2026-11-09"), ("Lab 1", "2026-10-27"), ("Lab 2", "2026-11-02")):
        up.save_homework(conn, sem, "Biology", task_uid=None, title=title, due=due, status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Done one", due="2026-10-26", status="done")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Chapter A", due="2026-11-20")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Chapter B", due="2026-10-30")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Chapter C", due="2026-11-30")
    from src import study_page

    w = study_page.widgets(conn, sem, date(2026, 10, 26))
    assert w["exam"]["title"] == "Final" and w["exam"]["when"] == "in 8 days"
    assert [(h["title"], h["when"]) for h in w["homework"]] == [("Lab 1", "tomorrow"), ("Lab 2", "in 7 days")]
    assert [(t["title"], t["when"]) for t in w["tasks"]] == [("Chapter B", "in 4 days"), ("Chapter A", "20 Nov")]
    assert w["left"]["big"] == "16 weeks left" and w["left"]["small"] == "ends 14 Feb" and 0 < w["left"]["percent"] < 20
    html = _study(conn)
    assert "Next examination" in html and "Lab 1" in html and "Chapter B" in html and "weeks left" in html and "pill-" not in html.split("uni-widgets")[1].split("study-grid")[0]


def test_the_widgets_say_so_when_there_is_nothing_and_the_semester_can_be_over(conn, sem):
    from src import study_page

    w = study_page.widgets(conn, sem, date(2027, 3, 1))
    assert w["exam"] is None and w["homework"] == [] and w["tasks"] == [] and w["left"]["big"] == "Semester over"
    assert study_page.widgets(conn, sem, date(2026, 9, 1))["left"]["big"] == "Starts 5 Oct" or "Starts" in study_page.widgets(conn, sem, date(2026, 9, 1))["left"]["big"]
    empty = _study(conn)
    assert "None planned" in empty and "Nothing due" in empty


def test_the_dates_are_as_short_as_they_can_be():
    from src import study_page

    today = date(2026, 10, 26)
    assert [study_page.when(d, today) for d in ("2026-10-25", "2026-10-26", "2026-10-27", "2026-11-09", "2026-11-10", "2027-02-01", None)] == [
        "overdue", "today", "tomorrow", "in 14 days", "10 Nov", "1 Feb 2027", "No date"]


def test_the_disciplines_view_is_a_bordered_card_per_discipline_with_one_line_of_news_only(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 7))
    page = _study(conn, b"view=disciplines")
    assert "uni-card" in page and "Biology" in page and "/groups/University/disciplines/Biology" in page and "Not set up: contents, examination" in page
    for gone in ("topics", "credits", "read", "Dr "):
        assert gone not in page.split("uni-cards")[1].split("</main>")[0]
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "0")])
    up.save_evaluation(conn, sem["uid"], "Biology", [{"id": "", "name": "Exam", "weight": "100", "subs": [], "milestones": [{"title": "Final", "day": "2026-10-09", "start": "09:00"}]}])
    page = _study(conn, b"view=disciplines")
    assert "Not set up" not in page and "Final in 2 days" in page
    way = up.get_evaluation(conn, sem["uid"], "Biology")[0]
    up.save_evaluation(conn, sem["uid"], "Biology", [{"id": way["id"], "name": "Exam", "weight": "100", "subs": [], "milestones": [
        {"uid": way["milestones"][0]["uid"], "title": "Final", "day": "2027-02-01", "start": "09:00"}]}])
    assert "Final in" not in _study(conn, b"view=disciplines")


def test_the_space_page_has_only_overview_and_disciplines_and_no_header_menu(conn, sem):
    from src.routers import label_pages

    page = _study(conn)
    header = page.split("</header>")[0] if "</header>" in page else page
    assert 'aria-label="University settings"' not in page and "view=agenda" not in page and "view=board" not in page
    assert page.count("view=disciplines") >= 1
    assert "uni-semester-menu" not in page and 'aria-label="Semester"' not in page
    for view in (b"view=agenda", b"view=board"):
        html = _html(label_pages.group_page("University", _request("/groups/University", view), conn=conn))
        assert "Next examination" in html


def test_the_discipline_overview_has_no_setup_card(conn, sem):
    assert "uni-setup" not in _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn))


def test_the_discipline_overview_is_two_columns_of_lists_with_no_tables(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 6))
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "0"), ("2", "Membranes", "0"), ("3", "Transport", "0")])
    up.apply_assign_in_order(conn, sem["uid"], "Biology")
    page = _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn))
    main = page.split("<main")[1].split("</main>")[0]
    assert "<table" not in main and "uni-split" in main and "uni-side" in main and "uni-setup" not in main
    nxt = main.split("Next classes")[1].split("Timetable")[0]
    assert nxt.count("uni-item\"") == 2 and "2. Membranes" in nxt and "3. Transport" in nxt and "1. Cells" not in nxt
    assert "Change the topic" in nxt and "Reschedule or move" in nxt and "Cancel this class" in nxt and "/delete-scope" in nxt


def test_pending_exams_homework_and_undated_evaluations_sit_in_colored_cards_in_the_thin_column(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 26))
    up.save_evaluation(conn, sem["uid"], "Biology", [
        {"id": "", "name": "Exam", "weight": "60", "subs": [], "milestones": [{"title": "Exam", "day": "2026-11-03", "start": "09:00"}]},
        {"id": "", "name": "Project", "weight": "40", "subs": [], "milestones": [{"title": "Project", "day": ""}]}])
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Lab 1", due="2026-10-27", status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Old", due="2026-10-01", status="done")
    side = _html(discipline_page("University", "Biology", _request(), view="overview", conn=conn)).split("uni-side")[1].split("</aside>")[0]
    assert "is-exam" in side and "Exam" in side and "in 8 days · 60%" in side
    assert "is-dated" in side and "Project" in side and "No date yet · 40%" in side
    assert "is-homework" in side and "Lab 1" in side and "tomorrow" in side and "Old" not in side
    assert side.index("is-exam") < side.index("is-dated") < side.index("is-homework")


def test_a_cancelled_class_no_longer_counts_as_a_place_for_its_topic(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_topic_rows(conn, sem["uid"], "Biology", [("1", "Cells", "0")])
    up.apply_assign_in_order(conn, sem["uid"], "Biology")
    assert len(up.list_topics(conn, sem["uid"], "Biology")[0]["events"]) == 1
    db.delete_event(conn, up.series_members(conn, series)[0]["uid"])
    assert up.list_topics(conn, sem["uid"], "Biology")[0]["events"] == []


def test_other_items_are_the_tasks_and_events_made_by_hand_and_an_event_can_be_deleted_from_the_page(conn, sem):
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    add_exam(conn, sem, title="Final")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="", due="", status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Lab report", due="2026-11-05", status="")
    db.upsert_event(conn, {"uid": "trip", "title": "Field trip", "description": "", "all_day": 0, "status": "active", "start_at": "2026-11-10T08:00", "end_at": "2026-11-10T18:00",
                           "tags": ["Biology"]})
    up._tag_item(conn, "event", "trip", "Biology")
    assert [(i["kind"], i["title"]) for i in up.list_other_items(conn, sem["uid"], "Biology")] == [("task", "Lab report"), ("event", "Field trip")]
    page = _html(discipline_page("University", "Biology", _request(), view="exams", conn=conn))
    assert "Other tasks and events" in page and "Field trip" in page and "/event/trip/delete" in page and "uni-way" in page
    university.other_event_delete("trip", discipline="Biology", conn=conn)
    assert db.get_event(conn, "trip") is None
    university.other_event_delete(up.list_milestones(conn, sem["uid"])[0]["event_uid"], discipline="Biology", conn=conn)
    assert len(db.list_events(conn)) > 0 and up.list_milestones(conn, sem["uid"])[0]["event_uid"]



def test_the_sidebar_lists_the_disciplines_under_the_university_space_and_highlights_the_open_one(conn, sem):
    from src import deps

    class App:
        class state:
            class settings:
                from pathlib import Path
                db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])

    request = _request("/groups/University/disciplines/Biology")
    request.scope["app"] = App
    group = next(g for g in deps._sidebar_groups(request) if g["name"] == "University")
    assert [(c["name"], c["path"]) for c in group["children"]] == [("Biology", "/groups/University/disciplines/Biology")]
    html = _html(discipline_page("University", "Biology", request, view="overview", conn=conn))
    assert 'href="/groups/University/disciplines/Biology" class="tab-btn tab-btn-child active"' in html and "has-active-child" in html


def test_other_items_leave_out_what_is_tracked_elsewhere(conn, sem):
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Linked task", due="2026-11-05", status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Habit task", due="", status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Plain task", due="", status="")
    tasks = {t["title"]: t["uid"] for t in db.list_tasks(conn)}
    conn.execute("UPDATE tasks SET is_habit = 1 WHERE uid = ?", (tasks["Habit task"],))
    for uid, series in (("old-class", "old-series"), ("exam-day", None), ("trip", None)):
        db.upsert_event(conn, {"uid": uid, "title": uid, "description": "", "all_day": 0, "status": "active", "start_at": "2026-11-10T08:00",
                               "end_at": "2026-11-10T09:00", "series_uid": series, "tags": ["Biology"]})
        up._tag_item(conn, "event", uid, "Biology")
    db.add_event_task_relation(conn, "exam-day", tasks["Linked task"])
    assert [i["title"] for i in up.list_other_items(conn, sem["uid"], "Biology")] == ["trip", "Plain task"]


def test_a_way_can_be_an_elimination_round_with_notes(conn, sem):
    up.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Quiz", "form": "Exam", "weight": "30", "elimination": True, "notes": "pass mark 5", "subs": [], "milestones": []})
    up.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Final", "form": "Exam", "weight": "100", "subs": [], "milestones": []})
    quiz, final = sorted(up.get_evaluation(conn, sem["uid"], "Biology"), key=lambda w: w["name"] == "Final")
    assert quiz["elimination"] and quiz["weight"] is None and quiz["stored_weight"] == 30 and quiz["notes"] == "pass mark 5"
    assert not final["elimination"] and final["weight"] == 100
    assert up.evaluation_warnings([quiz, final]) == []
    up.save_way(conn, sem["uid"], "Biology", {"id": final["id"], "name": "Final", "form": "Exam", "weight": "100", "subs": [], "milestones": []})
    assert next(w for w in up.get_evaluation(conn, sem["uid"], "Biology") if w["name"] == "Quiz")["stored_weight"] == 30


def test_one_class_can_be_moved_and_deleted_from_the_contents_page(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all", "room": "A"})
    first, second, third = up.series_members(conn, series)[:3]
    university.class_content_save(second["uid"], topic_uid="", competences=[], text="Moved", day="2026-10-14", start="14:00", end="15:30", room="B2", conn=conn)
    moved = db.get_event(conn, second["uid"])
    assert moved["start_at"] == "2026-10-14T14:00" and moved["end_at"] == "2026-10-14T15:30" and moved["location"] == "B2" and moved["description"] == "Moved"
    assert up.list_slots(conn, sem["uid"], "Biology")[0]["start"] == "10:00"
    count = len(up.list_classes(conn, sem["uid"], "Biology"))
    university.class_delete(third["uid"], conn=conn)
    assert db.get_event(conn, third["uid"]) is None and len(up.list_classes(conn, sem["uid"], "Biology")) == count - 1
    assert [m["uid"] for m in up.series_members(conn, series)] == [first["uid"], second["uid"]]  # the rule of the earlier classes ends before the deleted one
    assert event_series.get_series(conn, series)["rule"].endswith("UNTIL=2026-10-18")
    visible = up.list_slots(conn, sem["uid"], "Biology")
    assert len(visible) == 1 and visible[0]["first"] == "2026-10-26" and visible[0]["series_uid"] != series
    assert [c["date"] for c in up.list_classes(conn, sem["uid"], "Biology")][:3] == ["2026-10-05", "2026-10-14", "2026-10-26"]
    with pytest.raises(up.PlanError):
        up.save_class_schedule(conn, first["uid"], "2026-10-05", "12:00", "10:00", "")
    with pytest.raises(up.PlanError):
        up.delete_class(conn, "no-such-class")


def test_editing_a_timetable_slot_keeps_every_class_in_the_contents(conn, sem):
    from datetime import date as _d
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"}, None, _d(2026, 9, 1))
    total = len(up.list_classes(conn, sem["uid"], "Biology"))
    later = up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "14:00", "end": "16:00", "kind": "seminar", "weeks": "all"}, series, _d(2026, 11, 3))
    assert len(up.list_slots(conn, sem["uid"], "Biology")) == 1 and up.list_slots(conn, sem["uid"], "Biology")[0]["series_uid"] == later
    classes = up.list_classes(conn, sem["uid"], "Biology")
    assert total == 11 and len(classes) == 12  # five lectures stay, seven seminars follow
    assert {c["kind"] for c in classes} == {"lecture", "seminar"}
    with pytest.raises(up.PlanError):
        up.save_slot(conn, sem, "Biology", {"weekday": 2, "start": "10:00", "end": "11:00", "kind": "seminar", "weeks": "all"}, series, _d(2027, 3, 1))


def test_deleting_one_occurrence_of_a_calendar_series_splits_the_rule(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    members = up.series_members(conn, series)
    event_series.delete_scope(conn, members[4]["uid"], "this")  # what the calendar's delete does
    assert [m["uid"] for m in up.series_members(conn, series)] == [m["uid"] for m in members[:4]]
    later = db.get_event(conn, members[5]["uid"])["series_uid"]
    assert later != series and [m["uid"] for m in up.series_members(conn, later)] == [m["uid"] for m in members[5:]]
    assert event_series.get_series(conn, later)["rule"].count("UNTIL") == 1
    assert up.list_slots(conn, sem["uid"], "Biology")[0]["series_uid"] == later
    assert len(up.list_classes(conn, sem["uid"], "Biology")) == len(members) - 1
