"""The course sheet rework: short name, what the course has, absences as a percent, grades and minimums, sorting and the contents revert."""

from datetime import date

import pytest

from src import db, migrations_university, university
from src import university_attendance as ua
from src import university_evaluation as ue
from src import university_plan as up
from src.routers.labels import COLORS
from test_university_pages import _html, _request  # noqa: F401


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_MODULES", "university")
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


@pytest.fixture()
def sem(conn):
    s = up.get_semester(conn, up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18"))
    up.save_discipline(conn, s, old="", name="Istoria Antică", color="green", icon="leaf", teacher_names="", colors=COLORS)
    return s


def test_the_short_name_is_the_first_word_and_a_new_discipline_gets_it_once(conn, sem):
    assert up.short_name(conn, sem["uid"], "Istoria Antică") == "Istoria"
    university.discipline_save(old="", name="Biologie Celulară", color="blue", icon="", abbreviation="", code="", credits="", type="", conn=conn)
    assert up.short_name(conn, sem["uid"], "Biologie Celulară") == "Biologie"
    up.save_sheet(conn, sem["uid"], "Biologie Celulară", {"abbreviation": "BC"})
    assert up.short_name(conn, sem["uid"], "Biologie Celulară") == "BC"


def test_a_course_has_the_kinds_it_is_taught_as_and_a_timetable_kind_is_always_on(conn, sem):
    assert up.course_kinds(conn, sem["uid"], "Istoria Antică") == []
    up.set_course_kinds(conn, sem["uid"], "Istoria Antică", ["lab", "lecture", "nonsense"])
    up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "seminar", "weeks": "all"})
    assert up.course_kinds(conn, sem["uid"], "Istoria Antică") == ["lecture", "seminar", "lab"]


def test_absences_come_from_a_percent_of_the_classes_unless_a_number_replaces_it(conn, sem):
    up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    up.save_slot(conn, sem, "Istoria Antică", {"weekday": 2, "start": "10:00", "end": "12:00", "kind": "seminar", "weeks": "all"})
    up.save_sheet(conn, sem["uid"], "Istoria Antică", {"absences_pct_lecture": "30", "absences_pct_seminar": "30", "absences_seminar": "1"})
    kinds = {k["kind"]: k for k in ua.discipline_attendance(conn, sem["uid"], "Istoria Antică", date(2026, 10, 20))["kinds"]}
    assert kinds["lecture"]["limit"] == int(0.3 * kinds["lecture"]["total"]) and kinds["seminar"]["limit"] == 1


def test_an_elimination_way_is_passed_or_failed_the_others_default_to_the_passing_grade(conn, sem):
    ue.save_evaluation(conn, sem["uid"], "Istoria Antică", [
        {"id": "pass", "name": "Lab", "weight": "", "elimination": True, "subs": []},
        {"id": "small", "name": "Essay", "weight": "30", "subs": []}, {"id": "big", "name": "Exam", "weight": "70", "subs": []}])
    assert [w["id"] for w in ue.get_evaluation(conn, sem["uid"], "Istoria Antică")] == ["big", "small", "pass"]
    ue.set_grades(conn, sem["uid"], "Istoria Antică", {"pass": "0", "big": "8", "small": "4"})
    up.save_sheet(conn, sem["uid"], "Istoria Antică", {"passing": "6"})
    ue.set_minimums(conn, sem["uid"], "Istoria Antică", {"big": "7", "small": ""})
    st = ue.standing(conn, sem["uid"], "Istoria Antică", date(2026, 10, 20))
    ways = {w["id"]: w for w in st["ways"]}
    assert ways["pass"]["passed"] is False and ways["big"]["minimum"] == 7 and ways["small"]["minimum"] == 6 and ways["small"]["passed"] is False
    assert st["final"] == 6.8 and st["passing"] == 6 and st["passed"] is False


def test_an_elimination_way_is_failed_until_it_is_passed(conn, sem):
    ue.save_evaluation(conn, sem["uid"], "Istoria Antică", [{"id": "lab", "name": "Lab", "weight": "", "elimination": True, "subs": []}])
    assert ue.standing(conn, sem["uid"], "Istoria Antică")["ways"][0]["passed"] is False
    ue.set_grades(conn, sem["uid"], "Istoria Antică", {"lab": "1"})
    assert ue.standing(conn, sem["uid"], "Istoria Antică")["ways"][0]["passed"] is True


def test_a_way_can_link_notes_and_a_saved_way_keeps_what_the_window_does_not_edit(conn, sem):
    ue.save_way(conn, sem["uid"], "Istoria Antică", {"id": "w", "name": "Exam", "weight": "100", "min_grade": "6", "criteria": "Sources", "subs": [], "note_uids": ["n1"]})
    way = ue.get_evaluation(conn, sem["uid"], "Istoria Antică")[0]
    assert way["note_uids"] == ["n1"] and way["min_grade"] == 6 and way["criteria"] == "Sources"


def test_a_reference_typed_by_hand_makes_a_library_entry_once(conn, sem):
    a = up.save_reading(conn, sem, "Istoria Antică", task_uid=None, title="Manual", author="Renfrew")
    b = up.save_reading(conn, sem, "Istoria Antică", task_uid=None, title="Manual", author="Renfrew")
    refs = up.list_readings(conn, sem["uid"])
    assert a != b and len(refs) == 2 and refs[0]["citation_id"] == refs[1]["citation_id"] and db.get_task(conn, a) is None


def test_the_migration_takes_contents_off_the_classes_and_keeps_attendance(conn, sem):
    series = up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": "all"})
    first = up.series_members(conn, series)[0]
    up.save_syllabus(conn, sem["uid"], "Istoria Antică", "1. Origins")
    topic = up.list_topics(conn, sem["uid"], "Istoria Antică")[0]
    up.assign_topic(conn, topic["uid"], first["uid"])
    db.upsert_event(conn, {**db.get_event(conn, first["uid"]), "description": "1. Origins\nbring a pen"})
    ua.set_status(conn, first["uid"], "missed", "sick")
    migrations_university.revert_class_contents(conn)
    assert conn.execute("SELECT COUNT(*) FROM university_topic_classes").fetchone()[0] == 0
    assert db.get_event(conn, first["uid"])["description"] == "bring a pen" and ua.statuses_of(conn, [first["uid"]])[first["uid"]]["status"] == "missed"


def test_the_course_sheet_page_and_its_windows_render(conn, sem):
    from src.university_discipline import discipline_page

    ue.save_way(conn, sem["uid"], "Istoria Antică", {"id": "", "name": "Exam", "form": "Exam", "weight": "100", "subs": []})
    page = _html(discipline_page("University", "Istoria Antică", _request(), conn=conn))
    assert page.index(">Attendance<") < page.index(">Exam<") and "Add a way of evaluating" in page and "Add a class to the timetable" in page and "Add a book" in page
    for html in (_html(university.sheet_form("Istoria Antică", _request(), section="identification", conn=conn)),
                 _html(university.attendance_limits_form("Istoria Antică", _request(), conn=conn)), _html(university.grades_form(_request(), "Istoria Antică", conn=conn))):
        assert 'id="modal-target"' in html


def _lecture(conn, sem, weeks="all"):
    series = up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "12:00", "kind": "lecture", "weeks": weeks})
    return series, up.series_members(conn, series)


def test_a_missed_class_stays_and_a_made_up_class_moves_and_can_be_put_back(conn, sem):
    series, members = _lecture(conn, sem)
    first = members[0]
    ua.set_status(conn, first["uid"], "missed", "sick")
    assert db.get_event(conn, first["uid"])["status"] == "active" and len(up.series_members(conn, series)) == len(members)
    with pytest.raises(up.PlanError):
        ua.set_status(conn, first["uid"], "made_up")
    ua.make_up(conn, first["uid"], "2026-10-09T16:00", "2026-10-09T18:00")
    ua.make_up(conn, first["uid"], "2026-10-10T16:00", "2026-10-10T18:00")
    assert db.get_event(conn, first["uid"])["start_at"] == "2026-10-10T16:00" and ua.statuses_of(conn, [first["uid"]])[first["uid"]]["status"] == "made_up"
    ua.set_status(conn, first["uid"], "missed")
    assert db.get_event(conn, first["uid"])["start_at"] == first["start_at"]


def test_a_timetable_edit_keeps_made_up_times_and_marks_even_when_the_events_are_rebuilt(conn, sem):
    series, members = _lecture(conn, sem)
    ua.set_status(conn, members[0]["uid"], "missed")
    ua.make_up(conn, members[1]["uid"], "2026-10-15T16:00", "2026-10-15T18:00")
    up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "11:50", "kind": "lecture", "weeks": "all"}, series, today=date(2026, 9, 1))
    after = {e["start_at"]: e for e in up.class_events(conn, sem["uid"], "Istoria Antică")}
    marks = ua.statuses_of(conn, [e["uid"] for e in after.values()])
    assert sorted(m["status"] for m in marks.values()) == ["made_up", "missed"] and "2026-10-15T16:00" in after
    # a rebuilt series (another weekday) keeps the marks too
    up.save_slot(conn, sem, "Istoria Antică", {"weekday": 0, "start": "10:00", "end": "11:50", "kind": "lecture", "weeks": "odd"}, up.list_slots(conn, sem["uid"])[0]["series_uid"], today=date(2026, 9, 1))
    marks = ua.statuses_of(conn, [e["uid"] for e in up.class_events(conn, sem["uid"], "Istoria Antică")])
    assert "missed" in {m["status"] for m in marks.values()}


def test_reattach_is_safe_to_repeat(conn, sem):
    _, members = _lecture(conn, sem)
    ua.set_status(conn, members[0]["uid"], "excused")
    assert ua.reattach(conn, sem["uid"], "Istoria Antică") == 0 and ua.reattach(conn, sem["uid"], "Istoria Antică") == 0


def test_the_migration_fills_in_the_origin_of_older_marks_and_leaves_old_extra_classes_alone(conn, sem):
    _, members = _lecture(conn, sem)
    conn.execute("INSERT INTO university_attendance (event_uid, semester_uid, discipline_tag, status, note, updated_at) VALUES (?, ?, 'Istoria Antică', 'missed', '', 'x')",
                 (members[0]["uid"], sem["uid"]))
    extra = up.add_class(conn, sem, "Istoria Antică", "lecture", "2026-10-20", "10:00", "12:00")
    conn.execute("INSERT INTO university_attendance (event_uid, semester_uid, discipline_tag, status, note, updated_at) VALUES (?, ?, 'Istoria Antică', 'made_up', '', 'x')", (extra, sem["uid"]))
    migrations_university.attendance_origin(conn)
    migrations_university.attendance_origin(conn)
    rows = {r["event_uid"]: r for r in conn.execute("SELECT * FROM university_attendance")}
    assert rows[members[0]["uid"]]["original_start"] == members[0]["start_at"] and rows[members[0]["uid"]]["kind"] == "lecture" and rows[extra]["original_start"] == ""


def test_a_class_is_never_deleted_from_the_calendar_and_missed_ones_are_drawn_faded(conn, sem):
    from src.routers import calendar as cal

    _, members = _lecture(conn, sem)
    for route in (cal.delete_event, cal.delete_following, cal.delete_series):
        resp = route(members[0]["uid"], x_requested_with="fetch", conn=conn)
        assert resp.status_code == 409
    assert db.get_event(conn, members[0]["uid"]) is not None
    ua.set_status(conn, members[0]["uid"], "missed")
    events = [db.get_event(conn, m["uid"]) for m in members[:2]]
    cal._annotate_skipped_classes(conn, events)
    assert events[0].get("skipped") is True and not events[1].get("skipped")


def test_one_item_of_a_way_can_be_added_and_changed_on_its_own_and_an_existing_item_can_be_attached(conn, sem):
    ue.save_way(conn, sem["uid"], "Istoria Antică", {"id": "w1", "name": "Project", "form": "Project", "weight": "100", "subs": []})
    ue.save_item(conn, sem["uid"], "Istoria Antică", "w1", {"uid": "", "title": "Draft", "due": "2026-12-01", "description": "First chapter"})
    m = ue.list_milestones(conn, sem["uid"])[0]
    assert db.get_task(conn, m["task_uid"])["description"] == "First chapter"
    ue.save_item(conn, sem["uid"], "Istoria Antică", "w1", {"uid": m["uid"], "title": "Draft", "due": "2026-12-02", "description": "Second chapter"})
    assert len(ue.list_milestones(conn, sem["uid"])) == 1 and db.get_task(conn, m["task_uid"])["due_at"] == "2026-12-02"
    db.upsert_task(conn, {"uid": "hw", "title": "Reading log", "description": "", "status": "active", "due_at": "2026-12-10", "created_at": "x", "updated_at": "x"})
    ue.attach_item(conn, sem["uid"], "Istoria Antică", "w1", "task", "hw")
    assert {x["task_uid"] for x in ue.list_milestones(conn, sem["uid"])} >= {"hw"} and up.is_locked(conn, "task", "hw")
    with pytest.raises(up.PlanError):
        ue.attach_item(conn, sem["uid"], "Istoria Antică", "w1", "task", "hw")
    with pytest.raises(up.PlanError):
        ue.save_item(conn, sem["uid"], "Istoria Antică", "w1", {"uid": "", "title": ""})
    page = _html(university.attach_form(_request(), "task", "hw", conn=conn))
    assert 'id="modal-target"' in page
    for html in (_html(university.milestone_new(_request(), "Istoria Antică", "w1", conn=conn)), _html(university.milestone_edit(m["uid"], _request(), conn=conn))):
        assert 'id="modal-target"' in html and 'name="description"' in html
