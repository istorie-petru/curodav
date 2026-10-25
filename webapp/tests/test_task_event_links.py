"""The task and event link: a link has a kind, work sessions are one kind, and the migration names the kind of old links."""

from datetime import datetime, timezone

import pytest

from src import db, migrations


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _seed(conn):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    db.upsert_task(conn, {"uid": "t1", "title": "Exam prep", "description": "", "status": "active", "created_at": now})
    for uid, start in (("e1", "2026-11-02T10:00"), ("e2", "2026-11-01T09:00")):
        db.upsert_event(conn, {"uid": uid, "title": f"Event {uid}", "description": "", "start_at": start, "end_at": start, "all_day": 0, "status": "confirmed", "created_at": now})


def test_a_task_links_to_any_number_of_events_with_a_kind(conn):
    _seed(conn)
    db.add_event_task_relation(conn, "e1", "t1", kind="exam")
    db.add_event_task_relation(conn, "e2", "t1")
    links = db.links_for_task(conn, "t1")
    assert [(l["event"]["uid"], l["kind"]) for l in links] == [("e2", "related"), ("e1", "exam")]
    assert [(l["task"]["uid"], l["kind"]) for l in db.links_for_event(conn, "e1")] == [("t1", "exam")]


def test_a_work_session_is_the_work_session_kind(conn):
    _seed(conn)
    uid = db.create_work_allocation(conn, "t1")
    kinds = {l["event"]["uid"]: l["kind"] for l in db.links_for_task(conn, "t1")}
    assert kinds[uid] == "work_session"
    db.add_event_task_relation(conn, "e1", "t1", kind="work_session")
    assert conn.execute("SELECT is_work_allocation FROM event_task_relations WHERE event_uid = 'e1'").fetchone()[0] == 1


def test_a_row_with_only_the_old_flag_still_reads_as_a_work_session(conn):
    _seed(conn)
    conn.execute("INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) VALUES ('e1', 't1', 'x', 1)")
    assert db.links_for_task(conn, "t1")[0]["kind"] == "work_session"


def test_an_unknown_kind_is_refused(conn):
    _seed(conn)
    with pytest.raises(ValueError):
        db.add_event_task_relation(conn, "e1", "t1", kind="mystery")


def test_the_dry_run_counts_and_changes_nothing(conn):
    _seed(conn)
    conn.execute("INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) VALUES ('e1', 't1', 'x', 1)")
    conn.execute("INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) VALUES ('e2', 't1', 'x', 0)")
    before = conn.execute("SELECT event_uid, kind FROM event_task_relations ORDER BY event_uid").fetchall()
    assert db.plan_link_kinds(conn) == {"links": 2, "work_session": 1, "related": 1, "exam": 0, "already_set": 0}
    assert conn.execute("SELECT event_uid, kind FROM event_task_relations ORDER BY event_uid").fetchall() == before


def test_the_migration_names_every_old_link_and_is_safe_twice(conn):
    _seed(conn)
    conn.execute("INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation, hours_estimate, difficulty, own_title) "
                 "VALUES ('e1', 't1', 'x', 1, 2.5, 'hard', 1)")
    conn.execute("INSERT INTO event_task_relations (event_uid, task_uid, created_at, is_work_allocation) VALUES ('e2', 't1', 'x', 0)")
    migrations._links_get_a_kind(conn)
    migrations._links_get_a_kind(conn)
    rows = {r["event_uid"]: dict(r) for r in conn.execute("SELECT * FROM event_task_relations")}
    assert rows["e1"]["kind"] == "work_session" and rows["e2"]["kind"] == "related"
    assert (rows["e1"]["hours_estimate"], rows["e1"]["difficulty"], rows["e1"]["own_title"]) == (2.5, "hard", 1)


def test_the_migration_is_registered_as_destructive_so_it_takes_a_backup():
    assert {m.number: m.destructive for m in migrations.MIGRATIONS}[26] is True


def _request(path="/"):
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


def test_saving_the_links_keeps_work_sessions_and_other_kinds(conn):
    _seed(conn)
    session = db.create_work_allocation(conn, "t1")
    db.add_event_task_relation(conn, "e1", "t1", kind="exam")
    db.sync_task_links(conn, "t1", ["e1", "e2"])
    kinds = {l["event"]["uid"]: l["kind"] for l in db.links_for_task(conn, "t1")}
    assert kinds == {session: "work_session", "e1": "exam", "e2": "related"}
    db.sync_task_links(conn, "t1", ["e2"])
    kinds = {l["event"]["uid"]: l["kind"] for l in db.links_for_task(conn, "t1")}
    assert kinds == {session: "work_session", "e2": "related"}


def test_the_event_side_syncs_the_same_links(conn):
    _seed(conn)
    db.sync_event_links(conn, "e1", ["t1"])
    assert [l["task"]["uid"] for l in db.links_for_event(conn, "e1")] == ["t1"]
    db.sync_event_links(conn, "e1", [])
    assert db.links_for_event(conn, "e1") == []


def test_candidates_share_a_tag_or_are_already_linked(conn):
    _seed(conn)
    conn.execute("INSERT INTO object_tags (object_type, object_id, tag_name) VALUES ('event', 'e1', 'Uni')")
    db.add_event_task_relation(conn, "e2", "t1")
    conn.execute("INSERT INTO object_tags (object_type, object_id, tag_name) VALUES ('task', 't1', 'Uni')")
    task = db.get_task(conn, "t1")
    names = {c["uid"] for c in db.link_candidate_events(conn, task, "2026-01-01")}
    assert names == {"e1", "e2"}


def test_detail_modals_show_the_link_on_both_sides(conn):
    from src.routers import calendar as calendar_router
    from src.routers import tasks as tasks_router

    _seed(conn)
    db.add_event_task_relation(conn, "e1", "t1", kind="exam")
    task_page = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
    assert "Linked events" in task_page and "Event e1" in task_page and "Exam" in task_page
    event_page = calendar_router.event_detail("e1", _request("/events/e1"), conn=conn).body.decode()
    assert "Linked tasks" in event_page and "Exam prep" in event_page
