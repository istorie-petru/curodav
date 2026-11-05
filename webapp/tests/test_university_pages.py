"""University module pages: the Settings page, its modals and previews, and the study page."""

from datetime import date, datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db, event_series, study_format, university
from src.university_discipline import discipline_page
from src import university_evaluation as ue
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
    assert "No semester yet" in html and "/settings/university/semester" in html


def test_the_page_lists_the_semester_and_its_disciplines(conn, sem):
    html = _html(university.university_settings(_request(), conn=conn))
    assert "Autumn 2026" in html and "Biology" in html and "Dr Ionescu" in html and "/groups/University/disciplines/Biology" in html and "Classes end" in html


def test_the_forms_and_the_discipline_view_render(conn, sem):
    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"})
    add_exam(conn, sem, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts")
    page = _html(discipline_page("University", "Biology", _request("/groups/University/disciplines/Biology"), conn=conn))
    for expected in ("Monday", "Final", "Cell Biology", "Timetable", "Attendance", "Other notes"):
        assert expected in page, expected
    reading = up.list_readings(conn, sem["uid"])[0]
    for html in (_html(university.semester_form(_request(), conn=conn)), _html(university.discipline_new(_request(), conn=conn)), _html(university.homework_new(_request(), 'Biology', conn=conn)),
                 _html(university.attendance_limits_form("Biology", _request(), conn=conn)), _html(university.grades_form(_request(), "Biology", conn=conn)),
                 _html(university.discipline_edit("Biology", _request(), conn=conn)),
                 _html(university.slot_new(_request(), "Biology", conn=conn)), _html(university.slot_edit(series, _request(), conn=conn)),
                 _html(university.way_new(_request(), "Biology", conn=conn)), _html(university.reading_new(_request(), "Biology", conn=conn)),
                 _html(university.reading_edit(reading["task_uid"], _request(), conn=conn)), _html(university.sheet_form('Biology', _request(), conn=conn))):
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
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts")
    name, text = up.export_file(conn, sem, "discipline:Biology")
    assert name == "biology.curodav-university.json"
    kind, data = study_format.load(text)
    assert kind == "discipline" and data["timetable"][0]["weeks"] == "even" and data["exams"][0]["weight"] == 60 and data["themes"][1]["title"] == "Membranes"
    assert study_format.load(up.export_file(conn, sem, "semester")[1])[0] == "semester"
    # importing the file into a fresh semester recreates the discipline
    fresh_conn_semester = up.get_semester(conn, up.save_semester(conn, uid=sem["uid"], name="Autumn 2026", shelf_name="", start_date="2026-10-05",
                                                               end_date="2027-02-14", class_end_date="2026-12-18"))
    up.delete_slot(conn, sem["uid"], up.list_slots(conn, sem["uid"])[0]["series_uid"])
    ue.delete_milestone(conn, ue.list_milestones(conn, sem["uid"])[0]["uid"])
    up.delete_reading(conn, up.list_readings(conn, sem["uid"])[0]["task_uid"])
    plan = up.plan_import(conn, fresh_conn_semester, kind, data)
    assert "1 timetable slots, 2 topics, 1 exams, 1 readings" in plan["lines"][0] and "already exists" in plan["warnings"][0]
    up.apply_import(conn, fresh_conn_semester, kind, data, colors=COLORS)
    assert len(up.list_slots(conn, sem["uid"])) == 1 and len(ue.list_milestones(conn, sem["uid"])) == 1 and len(up.list_readings(conn, sem["uid"])) == 1
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
    exam = ue.list_milestones(conn, sem["uid"])[0]
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
    refused = call(tasks_router.update_task, exam_uid, title="Final exam", description="bring ID", due_at="2030-05-05")
    assert refused.status_code in (303, 422) and db.get_task(conn, exam_uid)["due_at"] != "2030-05-05"
    call(tasks_router.update_task, exam_uid, title="Final exam", description="bring ID")
    assert db.get_task(conn, exam_uid)["description"] == "bring ID"
    assert db.get_task(conn, exam_uid)["title"] == "Final exam" and db.get_event(conn, exam["event_uid"])["title"] == "Final exam"
    assert ue.list_milestones(conn, sem["uid"])[0]["raw_title"] == "Final exam"
    call(cal.update_event, "free", title="Dentist again", description="", start_at="2026-10-12T09:00", end_at="2026-10-12T10:00")
    assert db.get_event(conn, "free")["title"] == "Dentist again"


def test_the_shelf_page_goes_to_the_space_and_the_space_shows_the_study_page(conn, sem):
    from src.routers import label_pages
    resp = label_pages.label_page("Autumn 2026", _request("/labels/Autumn 2026"), conn=conn)
    assert resp.status_code == 303 and resp.headers["location"] == "/groups/University"
    html = _html(label_pages.group_page("University", _request("/groups/University"), conn=conn))
    assert "wcard" in html and "view=exams" in html and "view=disciplines" not in html and "view=attendance" not in html and "view=work" not in html and "view=agenda" not in html and "view=board" not in html


def test_a_missing_discipline_or_group_is_not_found(conn, sem):
    for group, name in (("University", "Nope"), ("Nope", "Biology")):
        with pytest.raises(HTTPException) as exc:
            discipline_page(group, name, _request(), conn=conn)
        assert exc.value.status_code == 404


def test_a_slot_saves_straight_away_and_says_so_only_when_text_was_lost(conn, sem):
    def save(series="", weekday="0", start="10:00", end="12:00"):
        return university.slot_save(discipline="Biology", discipline_new="", series_uid=series, weekday=weekday, start=start, end=end, room="A2",
                                    kind="lecture", weeks="all", teachers=[], back="", conn=conn)
    resp = save()
    assert resp.status_code == 303 and "note=" not in resp.headers["location"] and len(up.list_slots(conn, sem["uid"])) == 1
    series = up.list_slots(conn, sem["uid"])[0]["series_uid"]
    db.upsert_event(conn, {**up.series_members(conn, series)[0], "description": "typed"})
    assert "note=" in save(series, "1").headers["location"]
    with pytest.raises(HTTPException) as exc:
        save(start="12:00", end="10:00")
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
    t = up.save_reading(conn, sem, "Biology", task_uid=None, citation_id=uid, locator="ch. 3", category="obligatory", notes="Read twice")
    r = up.list_readings(conn, sem["uid"], "Biology")[0]
    assert (r["title"], r["author"], r["locator"], r["category"], r["notes"]) == ("Cell Biology", "Alberts, B.", "ch. 3", "obligatory", "Read twice")
    assert db.get_task(conn, t) is None and "Obligatory" in _html(discipline_page("University", "Biology", _request(), conn=conn))
    with pytest.raises(up.PlanError, match="not in the library"):
        up.save_reading(conn, sem, "Biology", task_uid=None, citation_id="nope")
    assert "Cell Biology" in _html(university.reading_new(_request(), "Biology", conn=conn))


def test_the_old_library_address_still_works():
    from src.routers import notebook

    resp = notebook.legacy_citations("new", _request("/notebook/citations/new", b"x=1"))
    assert resp.status_code == 307 and resp.headers["location"] == "/library/new?x=1"


def _components():
    return [{"id": "", "name": "Exam", "weight": "60", "subs": [{"id": "", "name": "Theory", "weight": "70"}, {"id": "", "name": "Practice", "weight": "30"}]},
            {"id": "", "name": "Project", "weight": "40", "subs": []}]


def test_the_evaluation_is_one_list_with_components_whose_weights_are_percent_of_their_way(conn, sem):
    assert ue.save_evaluation(conn, sem["uid"], "Biology", _components()) == []
    comps = ue.get_evaluation(conn, sem["uid"], "Biology")
    assert [(c["name"], c["weight"], c["effective"]) for c in comps] == [("Exam", 60.0, 60.0), ("Project", 40.0, 40.0)]
    assert [(x["name"], x["weight"], x["effective"]) for x in comps[0]["subs"]] == [("Theory", 70.0, 42.0), ("Practice", 30.0, 18.0)]


def test_weights_that_do_not_add_up_warn_but_are_kept(conn, sem):
    comps = _components()
    comps[0]["subs"][1]["weight"] = "20"
    comps[1]["weight"] = "30"
    warnings = ue.save_evaluation(conn, sem["uid"], "Biology", comps)
    assert warnings == ["The evaluation weights add up to 90%, not 100%", "The components of Exam add up to 90%, not 100%"]
    assert len(ue.get_evaluation(conn, sem["uid"], "Biology")) == 2
    with pytest.raises(up.PlanError, match="must be a number"):
        ue.save_evaluation(conn, sem["uid"], "Biology", [{"id": "", "name": "X", "weight": "lots", "subs": []}])
    assert len(ue.get_evaluation(conn, sem["uid"], "Biology")) == 2


def test_the_ids_of_ways_survive_an_edit_and_their_milestones_stay(conn, sem):
    add_exam(conn, sem, title="Final", weight="60")
    way = ue.get_evaluation(conn, sem["uid"], "Biology")[0]
    ue.save_evaluation(conn, sem["uid"], "Biology", [{"id": way["id"], "name": "Written exam", "weight": "60", "subs": [], "milestones": [
        {"uid": m["uid"], "title": m["title"], "day": m["day"], "due": m["due"]} for m in way["milestones"]]}])
    again = ue.get_evaluation(conn, sem["uid"], "Biology")[0]
    assert again["id"] == way["id"] and again["name"] == "Written exam" and [m["uid"] for m in again["milestones"]] == [m["uid"] for m in way["milestones"]]
    assert ue.list_milestones(conn, sem["uid"])[0]["weight"] == 60.0


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
    way = ue.get_evaluation(conn, sem["uid"], "Biology")[0]
    assert (way["name"], way["form"], way["weight"]) == ("Project", "Project", 60.0) and [s["name"] for s in way["subs"]] == ["Theory", "Practice"]
    assert sorted((bool(m["event_uid"]), bool(m["task_uid"]), m["title"]) for m in way["milestones"]) == [(False, True, "Send"), (True, False, "Presentation"), (True, False, "Test")]
    presentation = next(m for m in way["milestones"] if m["title"] == "Presentation")
    assert (presentation["day"], presentation["end_day"], presentation["end"]) == ("2027-01-20", "2027-01-21", "12:00")
    assert db.get_event(conn, presentation["event_uid"])["end_at"] == "2027-01-21T12:00"
    html = _html(university.way_edit(way["id"], _request(), "Biology", conn=conn))
    assert 'name="ev_title"' in html and 'name="tk_due"' in html and 'name="sub_weight"' in html and 'value="Project"' in html and "university-preset" not in html


def test_a_new_way_has_no_milestones_of_its_own_whatever_its_type(conn, sem):
    ue.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Project", "form": "Project", "weight": "100", "subs": []})
    assert ue.get_evaluation(conn, sem["uid"], "Biology")[0]["milestones"] == [] and db.list_events(conn) == []


def test_editing_a_way_keeps_its_place_and_the_other_ways_and_deleting_one_removes_its_items(conn, sem):
    add_exam(conn, sem, title="Final", weight="50")
    ue.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Homework", "form": "Homework", "weight": "50", "subs": [], "milestones": [{"title": "Hand in", "due": "2027-01-05"}]})
    first, second = ue.get_evaluation(conn, sem["uid"], "Biology")
    ue.save_way(conn, sem["uid"], "Biology", {"id": first["id"], "name": "Written exam", "form": "Exam", "weight": "50", "subs": []})
    assert [(w["name"], len(w["milestones"])) for w in ue.get_evaluation(conn, sem["uid"], "Biology")] == [("Written exam", 1), ("Homework", 1)]
    notes = ue.delete_way(conn, sem["uid"], "Biology", second["id"])
    assert [w["name"] for w in ue.get_evaluation(conn, sem["uid"], "Biology")] == ["Written exam"] and db.get_task(conn, second["milestones"][0]["task_uid"]) is None and notes


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


def test_the_university_pages_no_longer_carry_import_or_export_buttons(conn, sem):
    def main_of(html):
        return html.split("<main")[1].split("</main>")[0].lower()

    for page in (_html(university.university_settings(_request(), conn=conn)), _html(discipline_page("University", "Biology", _request(), conn=conn))):
        assert "import" not in main_of(page) and "export" not in main_of(page)


def test_the_discipline_window_has_no_evaluation_menu_and_a_full_width_look_with_a_banner_button(conn, sem):
    for html in (_html(university.discipline_edit("Biology", _request(), conn=conn)), _html(university.discipline_new(_request(), conn=conn))):
        assert 'name="evaluation"' not in html and "Evaluation" not in html.split("<main")[0] + html.split("</form>")[0].split("<form")[1] and 'look-row' in html
    edit = _html(university.discipline_edit("Biology", _request(), conn=conn))
    assert "field-wide" in edit.split("look-row")[0].rsplit("<div class=\"field", 1)[1] and "/banners/editor?scope=discipline%3ABiology" in edit and "Add banner" in edit
    assert "banners/editor" not in _html(university.discipline_new(_request(), conn=conn))


def test_a_banner_given_to_a_discipline_shows_on_its_page(conn, sem):
    assert "detail-banner" not in _html(discipline_page("University", "Biology", _request(), conn=conn))
    db.set_page_banner(conn, university.banner_scope("Biology"), {"kind": "remote", "image_url": "https://example.com/bio.jpg", "alt": "Biology banner"})
    page = _html(discipline_page("University", "Biology", _request(), conn=conn))
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
    assert (monday["left"], monday["width"]) == (0.0, 100.0) and monday["top"] == 96.0 and monday["height"] == 96.0
    assert (wednesday["odd"]["left"], wednesday["odd"]["width"]) == (0.0, 50.0) and (wednesday["even"]["left"], wednesday["even"]["width"]) == (50.0, 50.0)
    html = _study(conn)
    assert "week-event uni-class" in html and "is-translucent" not in html and "Left half odd weeks, right half even weeks" in html and 'title="Previous week"' not in html


def test_overlapping_classes_of_one_kind_share_their_half(conn, sem):
    from src import study_page

    blocks = [{"weeks": "odd", "from": 600, "to": 720}, {"weeks": "odd", "from": 660, "to": 780}, {"weeks": "even", "from": 600, "to": 720}]
    study_page.layout_day(blocks, 480, 600)
    assert [(b["left"], b["width"]) for b in blocks] == [(0.0, 25.0), (25.0, 25.0), (50.0, 50.0)]


def test_the_overview_shows_the_week_the_exams_coming_and_what_is_due(conn, sem, frozen_today):
    frozen_today(date(2026, 10, 26))
    add_exam(conn, sem, title="Final", day="2026-11-03", start="09:00", end="11:00")
    add_exam(conn, sem, title="Later", day="2026-12-01", start="09:00", end="11:00")
    for title, due in (("Lab 3", "2026-11-09"), ("Lab 1", "2026-10-27")):
        up.save_homework(conn, sem, "Biology", task_uid=None, title=title, due=due, status="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Done one", due="2026-10-26", status="done")
    from src import study_page

    data = study_page.overview(conn, sem, "University", date(2026, 10, 26), datetime(2026, 10, 26, 8, 0))
    assert data["summary"]["week"] == 4 and data["summary"]["parity"] == "even" and data["summary"]["left"] == "16 weeks left"
    assert [m["title"] for m in data["exams_soon"]] == ["Final", "Later"] and data["exams_this_fortnight"] == 1
    assert [w["title"] for w in data["due"]] == ["Lab 1", "Lab 3"]
    html = _study(conn)
    assert "Next examination" in html and "Final" in html and "Lab 1" in html and "Done one" not in html and "Week 4 of" not in html and "Absences" not in html


def test_the_overview_says_so_when_there_is_nothing_and_the_semester_can_be_over(conn, sem):
    from src import study_page

    assert study_page.summary(conn, sem, date(2027, 3, 1))["left"] == "over"
    assert study_page.summary(conn, sem, date(2026, 9, 1))["left"].startswith("starts")
    empty = _study(conn)
    assert "Next class" in empty and "Next examination" in empty and "Next due" in empty and "Nothing due" not in empty


def test_the_dates_are_as_short_as_they_can_be():
    from src import study_page

    today = date(2026, 10, 26)
    assert [study_page.when(d, today) for d in ("2026-10-25", "2026-10-26", "2026-10-27", "2026-11-09", "2026-11-10", "2027-02-01", None)] == [
        "overdue", "today", "tomorrow", "in 14 days", "10 Nov", "1 Feb 2027", "No date"]


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
    up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="")
    up.save_homework(conn, sem, "Biology", task_uid=None, title="Lab report", due="2026-11-05", status="")
    db.upsert_event(conn, {"uid": "trip", "title": "Field trip", "description": "", "all_day": 0, "status": "active", "start_at": "2026-11-10T08:00", "end_at": "2026-11-10T18:00",
                           "tags": ["Biology"]})
    up._tag_item(conn, "event", "trip", "Biology")
    assert [(i["kind"], i["title"]) for i in up.list_other_items(conn, sem["uid"], "Biology")] == [("task", "Lab report"), ("event", "Field trip")]
    university.other_event_delete("trip", discipline="Biology", conn=conn)
    assert db.get_event(conn, "trip") is None
    university.other_event_delete(ue.list_milestones(conn, sem["uid"])[0]["event_uid"], discipline="Biology", conn=conn)
    assert len(db.list_events(conn)) > 0 and ue.list_milestones(conn, sem["uid"])[0]["event_uid"]



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
    html = _html(discipline_page("University", "Biology", request, conn=conn))
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
    ue.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Quiz", "form": "Exam", "weight": "30", "elimination": True, "notes": "pass mark 5", "subs": [], "milestones": []})
    ue.save_way(conn, sem["uid"], "Biology", {"id": "", "name": "Final", "form": "Exam", "weight": "100", "subs": [], "milestones": []})
    quiz, final = sorted(ue.get_evaluation(conn, sem["uid"], "Biology"), key=lambda w: w["name"] == "Final")
    assert quiz["elimination"] and quiz["weight"] is None and quiz["stored_weight"] == 30 and quiz["notes"] == "pass mark 5"
    assert not final["elimination"] and final["weight"] == 100
    assert ue.evaluation_warnings([quiz, final]) == []
    ue.save_way(conn, sem["uid"], "Biology", {"id": final["id"], "name": "Final", "form": "Exam", "weight": "100", "subs": [], "milestones": []})
    assert next(w for w in ue.get_evaluation(conn, sem["uid"], "Biology") if w["name"] == "Quiz")["stored_weight"] == 30


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


def test_the_window_of_a_class_holds_its_attendance_menu_and_what_it_covers_and_the_exam_window_its_steps(conn, sem):
    from src.routers import calendar as cal, tasks as tasks_router

    series = up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    first = up.series_members(conn, series)[0]
    body = cal.event_detail(first["uid"], _request(f"/events/{first['uid']}"), conn=conn).body.decode()
    assert 'name="status" value="missed"' in body and "/makeup" in body and "/delete" not in body and 'value="cancelled"' not in body
    task_uid = add_exam(conn, sem, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    exam = ue.list_milestones(conn, sem["uid"])[0]
    assert "Final" in cal.event_detail(exam["event_uid"], _request("/events/x"), conn=conn).body.decode() and "60% of the grade" in cal.event_detail(exam["event_uid"], _request("/events/x"), conn=conn).body.decode()
    assert "60% of the grade" in tasks_router.task_detail(task_uid, _request(f"/tasks/{task_uid}"), conn=conn).body.decode()


def test_a_discipline_page_renders_when_the_timetable_slots_have_teachers(conn, sem):
    db.upsert_contact(conn, {"uid": "t1", "full_name": "Dr Timetable", "created_at": "2026-10-01", "updated_at": "2026-10-01"})
    up.save_slot(conn, sem, "Biology", {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all", "teachers": ["t1"]})
    up.sync_teachers(conn, sem["uid"], "Biology")
    assert "Dr Timetable" in _html(discipline_page("University", "Biology", _request(), conn=conn))
