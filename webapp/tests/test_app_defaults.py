"""App defaults: the default class reminder and the default tag of a new note."""

import pytest

from src import app_defaults, db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def test_class_reminder_is_empty_until_set(conn):
    assert app_defaults.class_reminders(conn) == []
    app_defaults.put(conn, "class_reminder", "15")
    assert app_defaults.class_reminders(conn) == [15]


def test_note_tag_round_trips(conn):
    app_defaults.put(conn, "note_tag", " Inbox ")
    assert app_defaults.get(conn, "note_tag") == "Inbox"


def test_event_end_adds_the_default_length_on_the_same_day(conn):
    assert app_defaults.event_end(conn, "2026-10-29T09:00") is None
    app_defaults.put(conn, "event_length", "60")
    assert app_defaults.event_end(conn, "2026-10-29T09:00") == "2026-10-29T10:00"
    assert app_defaults.event_end(conn, "2026-10-29T23:30") is None


def test_the_defaults_page_saves_only_listed_choices(conn):
    from src.routers import defaults

    defaults.save_default(key="event_reminder", value="15", conn=conn)
    defaults.save_default(key="event_reminder", value="7", conn=conn)
    defaults.save_default(key="nonsense", value="1", conn=conn)
    assert app_defaults.get(conn, "event_reminder") == "15"
    assert app_defaults.event_reminders(conn) == [15]


def test_quiet_hours_wrap_past_midnight(conn):
    from datetime import datetime

    assert not app_defaults.in_quiet_hours(conn, datetime(2026, 10, 30, 23, 0))
    app_defaults.put(conn, "quiet_start", "22:00")
    app_defaults.put(conn, "quiet_end", "07:00")
    assert app_defaults.in_quiet_hours(conn, datetime(2026, 10, 30, 23, 0))
    assert app_defaults.in_quiet_hours(conn, datetime(2026, 10, 30, 6, 59))
    assert not app_defaults.in_quiet_hours(conn, datetime(2026, 10, 30, 7, 0))


def test_the_calendar_opens_on_the_chosen_view(conn):
    from src.routers import calendar as calendar_router

    assert calendar_router.calendar_root_redirect(conn=conn).headers["location"] == "/calendar/fourweek"
    app_defaults.put(conn, "calendar_view", "week")
    assert calendar_router.calendar_root_redirect(conn=conn).headers["location"] == "/calendar/week"


def test_a_folder_template_is_used_for_new_notes_in_that_folder(conn):
    from src.routers import defaults, notebook

    template = db.upsert_notebook_document(conn, {"uid": "t1", "title": "Meeting", "is_template": 1, "document_type": "full", "note_type": "", "content_json": "{}",
                                                  "created_at": "2026-10-30T09:00:00", "updated_at": "2026-10-30T09:00:00"})
    defaults.save_default(key="folder_template:Work", value="t1", conn=conn)
    assert app_defaults.folder_template(conn, "Work") == "t1"
    defaults.save_default(key="folder_template:Work", value="missing", conn=conn)
    assert app_defaults.folder_template(conn, "Work") == "t1"
    assert notebook.new_note_context(None, conn, label="Work")["template_uid"] == "t1"
    assert notebook.new_note_context(None, conn, label="Home")["template_uid"] == ""


def test_global_search_reaches_notes_and_notebook_folders(conn):
    from src.routers import search

    db.upsert_notebook_document(conn, {"uid": "n1", "title": "Thesis outline", "is_template": 0, "document_type": "full", "note_type": "",
                                       "content_json": "{}", "created_at": "2026-10-30T09:00:00", "updated_at": "2026-10-30T09:00:00"})
    found = search._notebook_pages(conn, "thesis")
    assert [(p["title"], p["url"]) for p in found] == [("Thesis outline", "/notebook/n1")]
    assert search._notebook_pages(conn, "") == []


def test_a_note_opened_directly_goes_back_to_its_folder(conn):
    from starlette.requests import Request

    from src.routers import notebook

    db.upsert_notebook_document(conn, {"uid": "n2", "title": "Plan", "is_template": 0, "document_type": "full", "note_type": "", "content_json": "{}",
                                       "created_at": "2026-10-30T09:00:00", "updated_at": "2026-10-30T09:00:00"})
    assert db.notebook_folder_of(conn, "n2") == ("unfiled", "")
    assert db.notebook_folder_of(conn, "missing") == ("", "")


def test_a_note_in_a_shelf_goes_back_to_that_folder(conn):
    from src.routers import notebook

    uid = db.upsert_notebook_document(conn, {"uid": "n3", "title": "Budget", "is_template": 0, "document_type": "full", "note_type": "",
                                             "content_json": "{}", "tags": ["Work"], "created_at": "2026-10-30T09:00:00", "updated_at": "2026-10-30T09:00:00"})
    assert db.notebook_folder_of(conn, "n3") == ("label", "Work")


def test_a_new_habit_form_starts_with_the_default_reminder(conn):
    from starlette.requests import Request

    from src.routers import tasks

    app_defaults.put(conn, "habit_reminder", "08:00")
    request = Request({"type": "http", "method": "GET", "path": "/tasks/new", "headers": [], "query_string": b"", "app": None, "server": ("t", 80), "scheme": "http"})
    assert tasks.new_task_form(request, habit=True, conn=conn).context["default_reminder_time"] == "08:00"


def test_the_tasks_tab_opens_the_chosen_view(conn):
    from src.routers import tasks

    assert tasks.open_tasks(conn=conn).headers["location"] == "/tasks"
    app_defaults.put(conn, "tasks_view", "board")
    assert tasks.open_tasks(conn=conn).headers["location"] == "/tasks/board"
