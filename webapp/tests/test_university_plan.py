"""University module domain layer: semester and disciplines, timetable and class end, syllabus, exams and readings."""

from datetime import date

import pytest

from src import db, tags, university, university_plan as up
from src.routers.labels import COLORS

assert university  # registers the module and its page type


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_MODULES", "university")
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


@pytest.fixture()
def sem(conn):
    uid = up.save_semester(conn, uid=None, name="Autumn 2026", shelf_name="University", start_date="2026-10-05", end_date="2027-02-14",
                           class_end_date="2026-12-18")
    return up.get_semester(conn, uid)


def _bio(conn, sem, teachers="Dr Ionescu"):
    return up.save_discipline(conn, sem, old="", name="Biology", color="green", icon="leaf", teacher_names=teachers, colors=COLORS)


LECTURE = {"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "kind": "lecture", "weeks": "all"}


# ---- semester ----

def test_a_semester_creates_a_managed_shelf_with_the_study_page(conn, sem):
    cfg = db.get_label_config(conn, "University")
    assert cfg["managed_by"] == "university" and cfg["page_type"] == "study"
    with pytest.raises(tags.ManagedLabelError):
        db.upsert_label_config(conn, {"name": "University", "color": "red"})


def test_a_new_semester_shelf_is_pinned_to_the_sidebar_and_an_adopted_one_is_left_alone(conn, sem):
    assert db.get_label_config(conn, "University")["sidebar_pin"] == 1
    db.upsert_label_config(conn, {"name": "Old", "color": "red"})
    up.save_semester(conn, uid=None, name="Spring", shelf_name="Old", start_date="", end_date="", class_end_date="")
    assert db.get_label_config(conn, "Old")["sidebar_pin"] == 0


def test_an_existing_shelf_is_adopted_by_name(conn):
    db.upsert_label_config(conn, {"name": "University", "color": "red"})
    tags.add_default_tag(conn, "University")
    assert up.plan_semester(conn, "University") == {"shelf": "University", "adopts": True, "tags": ["University"]}
    uid = up.save_semester(conn, uid=None, name="Autumn", shelf_name="University", start_date="2026-10-05", end_date="", class_end_date="")
    assert db.get_label_config(conn, "University")["color"] == "red" and up.get_semester(conn, uid)["shelf_name"] == "University"


def test_semester_dates_are_checked(conn):
    with pytest.raises(up.PlanError, match="before the start"):
        up.save_semester(conn, uid=None, name="X", shelf_name="X", start_date="2026-10-05", end_date="2026-09-01", class_end_date="")
    with pytest.raises(up.PlanError, match="needs a name"):
        up.save_semester(conn, uid=None, name=" ", shelf_name="", start_date="", end_date="", class_end_date="")


def test_one_shelf_holds_one_semester(conn, sem):
    with pytest.raises(up.PlanError, match="already holds"):
        up.save_semester(conn, uid=None, name="Spring", shelf_name="University", start_date="", end_date="", class_end_date="")


# ---- disciplines ----

def test_a_discipline_is_a_tag_and_its_teachers_are_contacts(conn, sem):
    _bio(conn, sem, "Dr Ionescu, Dr Popa")
    d = up.disciplines(conn, sem)[0]
    assert (d["name"], d["color"]) == ("Biology", "green") and sorted(t["name"] for t in d["teachers"]) == ["Dr Ionescu", "Dr Popa"]
    up.save_discipline(conn, sem, old="Biology", name="Biology", color="green", icon="leaf", teacher_names="Dr Popa", colors=COLORS)
    assert [t["name"] for t in up.disciplines(conn, sem)[0]["teachers"]] == ["Dr Popa"]


def test_renaming_a_discipline_renames_its_classes(conn, sem):
    _bio(conn, sem)
    up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_discipline(conn, sem, old="Biology", name="Botany", color="green", icon="", teacher_names="", colors=COLORS)
    slot = up.list_slots(conn, sem["uid"])[0]
    assert slot["discipline"] == "Botany" and up.series_members(conn, slot["series_uid"])[0]["title"] == "Botany Lecture"


def test_a_discipline_with_items_cannot_be_removed(conn, sem):
    _bio(conn, sem)
    up.save_slot(conn, sem, "Biology", LECTURE)
    with pytest.raises(up.PlanError, match="1 timetable slots"):
        up.remove_discipline(conn, sem, "Biology")


# ---- timetable ----

def test_a_weekly_slot_makes_one_event_per_week_until_class_end(conn, sem):
    _bio(conn, sem, "Dr Ionescu")
    plan = up.plan_slot(conn, sem, "Biology", LECTURE)
    assert (plan["classes"], plan["first"], plan["last"]) == (11, "2026-10-05", "2026-12-14")
    series = up.save_slot(conn, sem, "Biology", LECTURE, None)
    members = up.series_members(conn, series)
    assert len(members) == 11 and members[0]["title"] == "Biology Lecture" and members[0]["location"] == "A2"
    assert members[0]["start_at"].startswith("2026-10-05T10:00") and members[-1]["start_at"].startswith("2026-12-14")
    assert tags.tags_for_object(conn, "event", members[3]["uid"]) == ["Biology"]
    assert [c["full_name"] for c in db.list_object_contacts(conn, "event", members[0]["uid"])] == []


def test_the_teacher_of_a_slot_is_a_contact_on_each_class(conn, sem):
    _bio(conn, sem)
    teacher = up.disciplines(conn, sem)[0]["teachers"][0]["uid"]
    series = up.save_slot(conn, sem, "Biology", dict(LECTURE, teachers=[teacher]))
    for m in up.series_members(conn, series):
        assert [c["uid"] for c in db.list_object_contacts(conn, "event", m["uid"])] == [teacher]


def test_odd_and_even_weeks_keep_their_parity(conn, sem):
    _bio(conn, sem)
    odd = up.save_slot(conn, sem, "Biology", dict(LECTURE, weeks="odd"))
    even = up.save_slot(conn, sem, "Biology", dict(LECTURE, weekday=2, weeks="even"))
    assert [m["start_at"][:10] for m in up.series_members(conn, odd)][:3] == ["2026-10-05", "2026-10-19", "2026-11-02"]
    assert [m["start_at"][:10] for m in up.series_members(conn, even)][:3] == ["2026-10-14", "2026-10-28", "2026-11-11"]


def test_a_day_before_the_semester_start_falls_in_the_next_matching_week(conn):
    uid = up.save_semester(conn, uid=None, name="S", shelf_name="S", start_date="2026-10-07", end_date="2027-01-31", class_end_date="2026-12-18")
    s = up.get_semester(conn, uid)
    assert up.first_class_date(date(2026, 10, 7), 0, "odd") == date(2026, 10, 19)
    assert up.first_class_date(date(2026, 10, 7), 0, "even") == date(2026, 10, 12)
    assert s["start_date"] == "2026-10-07"


def test_a_holiday_calendar_skips_its_days_without_shifting_the_parity(conn):
    db.upsert_holiday(conn, {"uid": "h1", "calendar_name": "Uni", "label": "Winter break", "date_from": "2026-11-16", "date_to": "2026-11-20", "year_agnostic": 0})
    uid = up.save_semester(conn, uid=None, name="S", shelf_name="S", start_date="2026-10-05", end_date="2027-02-01", class_end_date="2026-12-18", holiday_calendar="Uni")
    s = up.get_semester(conn, uid)
    up.save_discipline(conn, s, old="", name="Bio", color="green", icon="", teacher_names="", colors=COLORS)
    series = up.save_slot(conn, s, "Bio", LECTURE)
    days = [m["start_at"][:10] for m in up.series_members(conn, series)]
    assert "2026-11-16" not in days and "2026-11-09" in days and "2026-11-23" in days


def test_changing_only_the_room_updates_the_classes_in_place(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    before = {m["uid"] for m in up.series_members(conn, series)}
    assert up.plan_slot(conn, sem, "Biology", dict(LECTURE, room="B1"), series)["rebuilds"] is False
    assert up.save_slot(conn, sem, "Biology", dict(LECTURE, room="B1", start="11:00", end="13:00"), series) == series
    members = up.series_members(conn, series)
    assert {m["uid"] for m in members} == before and members[2]["location"] == "B1" and members[2]["start_at"].endswith("11:00")


def test_changing_the_weekday_rebuilds_and_names_the_text_it_would_lose(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    first = up.series_members(conn, series)[0]
    db.upsert_event(conn, {**first, "description": "Cells and membranes"})
    plan = up.plan_slot(conn, sem, "Biology", dict(LECTURE, weekday=1), series)
    assert plan["rebuilds"] and plan["lost"] == ["2026-10-05"]
    new = up.save_slot(conn, sem, "Biology", dict(LECTURE, weekday=1), series)
    assert new != series and up.series_members(conn, new)[0]["start_at"].startswith("2026-10-06")
    assert up.list_slots(conn, sem["uid"])[0]["weekday"] == 1 and len(up.list_slots(conn, sem["uid"])) == 1


def test_a_slot_needs_sensible_times_and_dates(conn, sem):
    with pytest.raises(up.PlanError, match="ends before"):
        up.plan_slot(conn, sem, "Biology", dict(LECTURE, end="09:00"))
    with pytest.raises(up.PlanError, match="weekday"):
        up.plan_slot(conn, sem, "Biology", dict(LECTURE, weekday=9))
    no_end = up.get_semester(conn, up.save_semester(conn, uid=None, name="N", shelf_name="N", start_date="2026-10-05", end_date="", class_end_date=""))
    with pytest.raises(up.PlanError, match="class end date"):
        up.plan_slot(conn, no_end, "Biology", LECTURE)


def test_the_slots_are_read_back_from_the_series(conn, sem):
    _bio(conn, sem)
    up.save_slot(conn, sem, "Biology", dict(LECTURE, weeks="odd"))
    slot = up.list_slots(conn, sem["uid"], "Biology")[0]
    assert (slot["weekday"], slot["start"], slot["end"], slot["room"], slot["weeks"], slot["kind"]) == (0, "10:00", "12:00", "A2", "odd", "lecture")


def test_deleting_a_slot_removes_its_classes(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    assert up.delete_slot(conn, sem["uid"], series) == 11
    assert up.list_slots(conn, sem["uid"]) == [] and db.list_events(conn) == []


# ---- class end ----

def test_moving_the_class_end_shortens_and_extends_every_series_but_not_exams(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    exam = up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="60")
    plan = up.plan_class_end(conn, sem["uid"], date(2026, 11, 30))
    assert plan["removed"] == 2 and plan["added"] == 0
    up.set_class_end(conn, sem["uid"], date(2026, 11, 30))
    assert up.series_members(conn, series)[-1]["start_at"].startswith("2026-11-30") and len(up.series_members(conn, series)) == 9
    assert up.plan_class_end(conn, sem["uid"], date(2027, 1, 11))["added"] == 6
    up.set_class_end(conn, sem["uid"], date(2027, 1, 11))
    members = up.series_members(conn, series)
    assert members[-1]["start_at"].startswith("2027-01-11") and len(members) == 15 and all(not (m.get("description") or "") for m in members)
    assert up.list_exams(conn, sem["uid"])[0]["task_uid"] == exam
    assert up.get_semester(conn, sem["uid"])["class_end_date"] == "2027-01-11"


def test_saving_the_semester_with_a_new_class_end_moves_the_series(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_semester(conn, uid=sem["uid"], name="Autumn 2026", shelf_name="University", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-11-09")
    assert len(up.series_members(conn, series)) == 6


# ---- syllabus ----

def test_a_pasted_syllabus_is_stored_and_kept_across_edits(conn, sem):
    _bio(conn, sem)
    assert up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells **\n2. Membranes\n3. Transport *") == 3
    first = up.list_topics(conn, sem["uid"], "Biology")[0]
    assert (first["number"], first["title"], first["importance"]) == (1, "Cells", 2)
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells **\n2. Membranes")
    assert up.list_topics(conn, sem["uid"], "Biology")[0]["uid"] == first["uid"] and len(up.list_topics(conn, sem["uid"], "Biology")) == 2
    assert up.syllabus_text(conn, sem["uid"], "Biology") == "1. Cells **\n2. Membranes"


def test_assigning_a_topic_writes_the_description_but_never_over_typed_text(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells\n2. Membranes")
    t1, t2 = up.list_topics(conn, sem["uid"], "Biology")
    c1, c2 = up.series_members(conn, series)[:2]
    assert up.assign_topic(conn, t1["uid"], c1["uid"]) == "written" and db.get_event(conn, c1["uid"])["description"] == "1. Cells"
    assert up.assign_topic(conn, t2["uid"], c1["uid"]) == "written"  # its own earlier text may be replaced
    db.upsert_event(conn, {**db.get_event(conn, c2["uid"]), "description": "Bring a pen"})
    assert up.assign_topic(conn, t1["uid"], c2["uid"]) == "conflict" and db.get_event(conn, c2["uid"])["description"] == "Bring a pen"
    assert up.assign_topic(conn, t1["uid"], c2["uid"], force=True) == "written"
    up.unassign_topic(conn, c2["uid"])
    assert db.get_event(conn, c2["uid"])["description"] == ""


def test_assigning_in_order_skips_classes_with_typed_text_and_names_them(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_syllabus(conn, sem["uid"], "Biology", "1. A\n2. B\n3. C")
    members = up.series_members(conn, series)
    db.upsert_event(conn, {**members[0], "description": "Exam briefing"})
    plan = up.plan_assign_in_order(conn, sem["uid"], "Biology")
    assert plan["blocked"] == ["2026-10-05"] and [p[2] for p in plan["pairs"]] == [1, 2, 3] and plan["pairs"][0][4] == "2026-10-12"
    assert up.apply_assign_in_order(conn, sem["uid"], "Biology") == 3
    assert db.get_event(conn, members[1]["uid"])["description"] == "1. A" and db.get_event(conn, members[0]["uid"])["description"] == "Exam briefing"
    assert up.plan_assign_in_order(conn, sem["uid"], "Biology")["pairs"] == []


# ---- exams and readings ----

def test_an_exam_is_a_task_and_an_event_joined_by_an_exam_link(conn, sem):
    _bio(conn, sem)
    uid = up.save_exam(conn, sem, "Biology", task_uid=None, title="", day="2027-01-20", start="09:00", end="11:30", weight="60", location="Aula")
    exam = up.list_exams(conn, sem["uid"], today=date(2027, 1, 10))[0]
    assert (exam["title"], exam["date"], exam["start"], exam["end"], exam["weight"], exam["days_left"]) == ("Biology exam", "2027-01-20", "09:00", "11:30", 60.0, 10)
    link = db.links_for_task(conn, uid)[0]
    assert link["kind"] == "exam" and link["event"]["uid"] == exam["event_uid"]
    assert db.get_task(conn, uid)["due_at"].startswith("2027-01-20") and tags.tags_for_object(conn, "task", uid) == ["Biology"]
    assert tags.tags_for_object(conn, "event", exam["event_uid"]) == ["Biology"]


def test_editing_an_exam_moves_the_task_and_the_event_together(conn, sem):
    _bio(conn, sem)
    uid = up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="")
    again = up.save_exam(conn, sem, "Biology", task_uid=uid, title="Final exam", day="2027-01-22", start="10:00", end="12:00", weight="40")
    assert again == uid
    exam = up.list_exams(conn, sem["uid"])[0]
    assert (exam["title"], exam["date"], exam["start"], exam["weight"]) == ("Final exam", "2027-01-22", "10:00", 40.0)
    assert db.get_task(conn, uid)["due_at"].startswith("2027-01-22") and len(db.list_events(conn)) == 1


def test_exam_input_is_checked(conn, sem):
    with pytest.raises(up.PlanError, match="percentage"):
        up.save_exam(conn, sem, "Biology", task_uid=None, title="", day="2027-01-20", start="09:00", end="11:00", weight="140")
    with pytest.raises(up.PlanError, match="ends before"):
        up.save_exam(conn, sem, "Biology", task_uid=None, title="", day="2027-01-20", start="11:00", end="09:00", weight="")


def test_deleting_an_exam_removes_both_halves(conn, sem):
    _bio(conn, sem)
    uid = up.save_exam(conn, sem, "Biology", task_uid=None, title="", day="2027-01-20", start="09:00", end="11:00", weight="")
    up.delete_exam(conn, uid)
    assert up.list_exams(conn, sem["uid"]) == [] and db.list_events(conn) == [] and db.get_task(conn, uid) is None


def test_a_reading_is_a_task_with_the_usual_statuses(conn, sem):
    _bio(conn, sem)
    uid = up.save_reading(conn, sem, "Biology", task_uid=None, title="Cell Biology", author="Alberts", due="2026-11-02", status="")
    r = up.list_readings(conn, sem["uid"])[0]
    assert (r["title"], r["author"], r["due"], r["status"]) == ("Cell Biology", "Alberts", "2026-11-02", "active")
    up.save_reading(conn, sem, "Biology", task_uid=uid, title="Cell Biology", author="Alberts", due="2026-11-02", status="done")
    assert up.list_readings(conn, sem["uid"])[0]["status"] == "done" and db.get_task(conn, uid)["status"] == "done"
    up.delete_reading(conn, uid)
    assert up.list_readings(conn, sem["uid"]) == []


# ---- lecture notes ----

def test_a_class_note_starts_from_the_lecture_template_and_is_filed_under_the_discipline(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_syllabus(conn, sem["uid"], "Biology", "1. Cells\n2. Membranes")
    first, second = up.series_members(conn, series)[:2]
    up.assign_topic(conn, up.list_topics(conn, sem["uid"], "Biology")[1]["uid"], second["uid"])
    assert up.class_note(conn, second["uid"]) is None
    uid = up.open_class_note(conn, second["uid"])
    note = db.get_notebook_document(conn, uid)
    props = {p["key"]: p["value"] for p in note["properties"]}
    assert note["title"] == "Biology lecture 2, 2026-10-12" and props["discipline"] == "Biology" and props["date"] == "2026-10-12"
    assert props["topic"] == "2. Membranes" and props["lecture number"] == "2" and props["class"] == second["uid"]
    assert tags.tags_for_object(conn, "note", uid) == ["Biology"]
    assert up.open_class_note(conn, second["uid"]) == uid and up.class_notes_by_event(conn, [first["uid"], second["uid"]]) == {second["uid"]: uid}
    assert conn.execute("SELECT COUNT(*) FROM notebook_documents WHERE is_template = 1").fetchone()[0] == 1


def test_the_exam_lists_the_lecture_notes_of_its_discipline(conn, sem):
    _bio(conn, sem)
    series = up.save_slot(conn, sem, "Biology", LECTURE)
    up.save_exam(conn, sem, "Biology", task_uid=None, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="")
    uid = up.open_class_note(conn, up.series_members(conn, series)[0]["uid"])
    assert [n["uid"] for n in up.list_exams(conn, sem["uid"])[0]["notes"]] == [uid]


def test_a_note_cannot_be_made_for_an_event_that_is_not_a_class(conn, sem):
    db.upsert_event(conn, {"uid": "e1", "title": "Dentist", "description": "", "all_day": 0, "status": "active", "start_at": "2026-10-12T09:00", "end_at": "2026-10-12T10:00"})
    with pytest.raises(up.PlanError, match="not a class"):
        up.open_class_note(conn, "e1")
