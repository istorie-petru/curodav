"""A work session carries its own title, hours estimate and difficulty."""

from datetime import datetime, timezone

import pytest

from src import db, work_sessions
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _task_with_session(conn):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    db.upsert_task(conn, {"uid": "t1", "title": "Thesis", "description": "", "status": "active", "created_at": now})
    return db.create_work_allocation(conn, "t1")


def test_details_are_saved_on_the_session(conn):
    uid = _task_with_session(conn)
    assert db.update_work_session(conn, "t1", uid, title="Chapter 2", hours_estimate="3.5", difficulty="hard")
    session = db.list_work_allocations_for_task(conn, "t1")[0]
    assert (session["title"], session["hours_estimate"], session["difficulty"]) == ("Chapter 2", 3.5, "hard")


def test_own_title_survives_a_task_rename_but_default_title_follows_it(conn):
    own = _task_with_session(conn)
    plain = db.create_work_allocation(conn, "t1")
    db.update_work_session(conn, "t1", own, title="Chapter 2", hours_estimate="", difficulty="easy")
    task = db.get_task(conn, "t1")
    db.upsert_task(conn, {**task, "title": "Dissertation"})
    assert db.get_event(conn, own)["title"] == "Chapter 2"
    assert db.get_event(conn, plain)["title"] == "Dissertation"


def test_blank_title_gives_the_title_back_to_the_task(conn):
    uid = _task_with_session(conn)
    db.update_work_session(conn, "t1", uid, title="Chapter 2", hours_estimate="", difficulty="easy")
    db.update_work_session(conn, "t1", uid, title="", hours_estimate="", difficulty="easy")
    assert db.get_event(conn, uid)["title"] == "Thesis"


def test_another_tasks_event_is_refused(conn):
    uid = _task_with_session(conn)
    assert not db.update_work_session(conn, "other", uid, title="x", hours_estimate="", difficulty="easy")


@pytest.mark.parametrize("difficulties, expected", [
    ([], None),
    (["easy"], "easy"),
    (["easy", "hard"], "moderate"),
    (["hard", "hard", "moderate"], "hard"),
    ([None, "moderate"], "moderate"),
])
def test_average_difficulty(difficulties, expected):
    assert work_sessions.average_difficulty(difficulties) == expected


@pytest.mark.parametrize("raw, parsed", [("2.5", 2.5), ("", None), ("-1", None), ("abc", None), ("0", 0.0)])
def test_parse_hours(raw, parsed):
    assert work_sessions.parse_hours(raw) == parsed
