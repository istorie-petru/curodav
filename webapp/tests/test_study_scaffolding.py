"""University module scaffolding: pasted-list parser, versioned JSON format, module tables and the module framework."""

import pytest
from starlette.requests import Request

from src import db, header_views, migrations, modules, study_format, study_lists, university


def _request(path="/"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


# ---- pasted list ----

def test_numbers_dots_and_stars():
    themes = study_lists.parse_themes("1. Cell structure ***\n2) Membranes\n3 Transport *\n")
    assert [(t.number, t.title, t.importance) for t in themes] == [(1, "Cell structure", 3), (2, "Membranes", 0), (3, "Transport", 1)]


def test_lines_without_a_number_continue_the_count():
    themes = study_lists.parse_themes("5. Start\nOsmosis\n\n  Diffusion **  \n")
    assert [(t.number, t.title, t.importance) for t in themes] == [(5, "Start", 0), (6, "Osmosis", 0), (7, "Diffusion", 2)]


def test_a_list_without_numbers_starts_at_one():
    assert [t.number for t in study_lists.parse_themes("A\nB\nC")] == [1, 2, 3]


def test_stars_are_capped_and_empty_lines_dropped():
    themes = study_lists.parse_themes("1. Big *****\n2.\n***\n")
    assert [(t.title, t.importance) for t in themes] == [("Big", 3)]


def test_digits_inside_a_title_are_kept():
    assert study_lists.parse_themes("2. Vitamin B12 and DNA 101")[0].title == "Vitamin B12 and DNA 101"
    assert study_lists.parse_themes("3D printing")[0].title == "3D printing"
    assert study_lists.parse_themes("")  == []


# ---- JSON format ----

DISCIPLINE = {"name": "Biology", "color": "green", "teachers": ["Dr Ionescu"],
              "timetable": [{"weekday": 0, "start": "10:00", "end": "12:00", "room": "A2", "weeks": "odd"}],
              "themes": [{"number": 1, "title": "Cells", "importance": 2}], "exams": [{"title": "Final", "date": "2027-01-20", "weight": 60}],
              "readings": [{"title": "Cell Biology", "author": "Alberts"}]}


def test_a_discipline_round_trips():
    kind, data = study_format.load(study_format.dump("discipline", DISCIPLINE))
    assert kind == "discipline" and data["name"] == "Biology" and data["timetable"][0]["weeks"] == "odd" and data["exams"][0]["weight"] == 60
    assert study_format.load(study_format.dump("discipline", data)) == (kind, data)


def test_a_semester_round_trips():
    kind, data = study_format.load(study_format.dump("semester", {"name": "Autumn", "start_date": "2026-10-01", "disciplines": [DISCIPLINE]}))
    assert kind == "semester" and data["disciplines"][0]["name"] == "Biology"


def test_the_file_carries_its_format_and_version():
    import json

    doc = json.loads(study_format.dump("discipline", DISCIPLINE))
    assert (doc["format"], doc["version"], doc["kind"]) == ("curodav.university", 1, "discipline")


@pytest.mark.parametrize("text, message", [
    ("not json", "valid JSON"),
    ('{"format": "other", "version": 1}', "not a curodav.university"),
    ('{"format": "curodav.university", "version": 2, "kind": "discipline", "data": {}}', "up to version 1"),
    ('{"format": "curodav.university", "version": 1, "kind": "mystery", "data": {}}', "kind must be"),
    ('{"format": "curodav.university", "version": 1, "kind": "discipline", "data": {}}', "name is required"),
    ('{"format": "curodav.university", "version": 1, "kind": "discipline", "data": {"name": "B", "timetable": [{"weekday": 9, "start": "1", "end": "2"}]}}', "weekday"),
    ('{"format": "curodav.university", "version": 1, "kind": "discipline", "data": {"name": "B", "exams": [{"title": "E", "weight": 200}]}}', "percentage"),
    ('{"format": "curodav.university", "version": 1, "kind": "discipline", "data": {"name": "B", "themes": [{"title": "T", "importance": 7}]}}', "0 to 3"),
])
def test_a_bad_file_is_refused_with_a_reason(text, message):
    with pytest.raises(study_format.FormatError, match=message):
        study_format.load(text)


def test_an_older_version_is_upgraded(monkeypatch):
    monkeypatch.setattr(study_format, "VERSION", 2)
    monkeypatch.setitem(study_format.UPGRADES, 1, lambda data: {**data, "name": data["name"] + " (upgraded)"})
    kind, data = study_format.load('{"format": "curodav.university", "version": 1, "kind": "discipline", "data": {"name": "Bio"}}')
    assert data["name"] == "Bio (upgraded)"


# ---- module tables ----

def test_the_university_tables_exist_and_the_migration_is_safe_twice(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as conn:
        migrations._university_tables(conn)
        migrations._university_tables(conn)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'university_%'")}
        assert {"university_semesters", "university_topics", "university_topic_classes"} <= names
    assert 27 in {m.number for m in migrations.MIGRATIONS}


# ---- module framework ----

def test_the_university_module_is_registered_but_off_by_default(monkeypatch):
    monkeypatch.delenv("CC_MODULES", raising=False)
    assert "university" in modules.MODULES and not modules.is_enabled("university")
    assert modules.settings_items() == []
    assert all(label != "University" for _, label in [(u, t) for t, u in header_views.current_settings_groups()[3]["items"]])


def test_turning_the_module_on_adds_its_settings_entry_and_page(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_MODULES", "university")
    assert ("University", "/settings/university") in header_views.current_settings_groups()[3]["items"]
    with db.connect(tmp_path / "c.sqlite") as conn:
        assert "Nothing set up yet" in university.university_settings(_request("/settings/university"), conn=conn).body.decode()


def test_the_settings_page_is_not_found_while_the_module_is_off(monkeypatch, tmp_path):
    from fastapi import HTTPException

    monkeypatch.delenv("CC_MODULES", raising=False)
    with pytest.raises(HTTPException) as exc:
        university._enabled()
    assert exc.value.status_code == 404
    assert any(d.dependency is university._enabled for d in university.router.dependencies)


def test_a_module_page_type_is_offered_only_while_the_module_is_on(monkeypatch):
    monkeypatch.delenv("CC_MODULES", raising=False)
    assert "study" not in db.page_types()
    monkeypatch.setenv("CC_MODULES", "university")
    assert db.page_types()["study"] == "Study page" and "sections" in db.page_types()


def test_a_shelf_with_a_module_page_type_keeps_it_while_the_module_is_on(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_MODULES", "university")
    with db.connect(tmp_path / "c.sqlite") as conn:
        db.upsert_label_config(conn, {"name": "Uni", "page_type": "study"})
        assert db.get_label_config(conn, "Uni")["page_type"] == "study"
    monkeypatch.delenv("CC_MODULES")
    with db.connect(tmp_path / "d.sqlite") as conn:
        db.upsert_label_config(conn, {"name": "Uni", "page_type": "study"})
        assert db.get_label_config(conn, "Uni")["page_type"] == "sections"


# ---- turning a module on in Settings ----

def test_a_module_is_turned_on_and_off_from_settings_and_the_choice_is_stored(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from src.routers import settings as settings_router

    monkeypatch.delenv("CC_MODULES", raising=False)
    monkeypatch.setattr(modules, "_stored", set())
    with db.connect(tmp_path / "c.sqlite") as conn:
        assert not modules.is_enabled("university")
        settings_router.set_module("university", enabled="1", conn=conn)
        assert modules.is_enabled("university") and ("University", "/settings/university") in header_views.current_settings_groups()[3]["items"]
        modules._stored.clear()  # a restart forgets the memory, the database remembers
        modules.load_stored(conn)
        assert modules.is_enabled("university")
        settings_router.set_module("university", enabled="0", conn=conn)
        assert not modules.is_enabled("university")
        with pytest.raises(HTTPException):
            settings_router.set_module("nope", enabled="1", conn=conn)


def test_the_environment_still_forces_a_module_on_and_general_settings_lists_modules(monkeypatch, tmp_path):
    from tests.settings_app import fake_app
    from src.routers import settings as settings_router

    monkeypatch.setattr(modules, "_stored", set())
    monkeypatch.setenv("CC_MODULES", "university")
    assert modules.is_enabled("university") and "university" in modules.forced_keys()
    monkeypatch.delenv("CC_MODULES")
    with db.connect(tmp_path / "c.sqlite") as conn:
        req = _request("/settings/general")
        req.scope["app"] = fake_app()
        html = settings_router.settings_general(req, conn=conn).body.decode()
        assert "University module" in html and "/settings/modules/university" in html


def _legacy_exams(conn):
    """Puts a database back where it was before migrations 33 and 35: an exam table without the evaluation link and notes."""
    conn.execute("DROP TABLE university_milestones")
    conn.execute("CREATE TABLE university_exams (task_uid TEXT PRIMARY KEY, event_uid TEXT NOT NULL, semester_uid TEXT NOT NULL, discipline_tag TEXT NOT NULL, weight REAL)")
    conn.execute("ALTER TABLE university_semesters DROP COLUMN credits_target")
    conn.execute("DELETE FROM schema_migrations WHERE number IN (33, 35)")


def test_a_database_that_ran_the_first_migration_32_gets_the_later_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    with db.connect(path) as conn:
        _legacy_exams(conn)
        conn.commit()
    with db.connect(path) as conn:
        assert "credits_target" in {r[1] for r in conn.execute("PRAGMA table_info(university_semesters)")}
        assert {33, 35} <= {r[0] for r in conn.execute("SELECT number FROM schema_migrations")}


def test_existing_exams_become_milestones_of_a_way_with_their_task_event_and_a_backup(tmp_path):
    import json

    path = tmp_path / "old.sqlite"
    with db.connect(path) as conn:
        _legacy_exams(conn)
        conn.execute("ALTER TABLE university_exams ADD COLUMN component TEXT")
        conn.execute("ALTER TABLE university_exams ADD COLUMN notes TEXT")
        conn.execute("INSERT INTO university_sheet (semester_uid, discipline_tag, key, label, value, position) VALUES ('s', 'Bio', 'eval:w1', 'Written', ?, 200)",
                     (json.dumps({"id": "w1", "weight": "60", "subs": [{"id": "c1", "name": "Theory", "weight": "100"}]}),))
        conn.execute("INSERT INTO university_sheet (semester_uid, discipline_tag, key, label, value, position) VALUES ('s', 'Bio', 'evaluation', 'Form', 'Exam', 1)")
        for n, (component, weight) in enumerate((("c1", 60), (None, 25))):
            task, event = f"t{n}", f"e{n}"
            now = "2026-10-01T00:00:00"
            db.upsert_task(conn, {"uid": task, "title": f"Exam {n}", "description": "", "due_at": "2027-01-20", "status": "active", "created_at": now, "updated_at": now})
            db.upsert_event(conn, {"uid": event, "title": f"Exam {n}", "description": "", "start_at": "2027-01-20T09:00", "end_at": "2027-01-20T11:00", "all_day": 0,
                                   "location": "Aula", "status": "active", "created_at": now, "updated_at": now})
            conn.execute("INSERT INTO university_exams (task_uid, event_uid, semester_uid, discipline_tag, weight, component) VALUES (?, ?, 's', 'Bio', ?, ?)", (task, event, weight, component))
        conn.commit()
    with db.connect(path) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'university_exams'").fetchone()
        rows = {r["task_uid"]: dict(r) for r in conn.execute("SELECT * FROM university_milestones")}
        assert rows["t0"]["way_id"] == "w1" and (rows["t0"]["day"], rows["t0"]["start"], rows["t0"]["end"], rows["t0"]["due"], rows["t0"]["location"]) == ("2027-01-20", "09:00", "11:00", "2027-01-20", "Aula")
        assert rows["t1"]["way_id"] not in ("", "w1") and rows["t1"]["event_uid"] == "e1"
        new_way = conn.execute("SELECT label, value FROM university_sheet WHERE key = ?", (f"eval:{rows['t1']['way_id']}",)).fetchone()
        assert new_way["label"] == "Exam 1" and json.loads(new_way["value"])["weight"] == "25"
        assert not conn.execute("SELECT 1 FROM university_sheet WHERE key = 'evaluation'").fetchone()
    assert any(".before-migration-0035-" in f.name for f in tmp_path.iterdir())
