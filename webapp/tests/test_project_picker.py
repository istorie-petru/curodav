"""Project-picker slice (2026-09-25): tasks and events get a separate,
single-choice Project dropdown (_project_field.html). Projects are still
stored as labels. Also covers the one-project-per-event rule (the task one
is in test_single_project_per_task.py) and its offline-sync counterpart.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import db, offline_sync
from src.routers import calendar as calendar_router
from src.routers import dashboard as dashboard_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        db.upsert_label_config(c, {"name": "Trip", "is_project": 1})
        db.upsert_label_config(c, {"name": "Thesis", "is_project": 1})
        db.upsert_label_config(c, {"name": "Old", "is_project": 1})
        db.archive_project(c, "Old")
        db.upsert_label_config(c, {"name": "urgent"})
        yield c


def _now():
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
    })


def _task(conn, uid, tags):
    db.upsert_task(conn, {"uid": uid, "title": uid, "description": "", "status": "active", "tags": tags, "created_at": _now()})


def _event(conn, uid, tags):
    db.upsert_event(conn, {"uid": uid, "title": uid, "description": "", "status": "active", "all_day": 0,
                           "tags": tags, "start_at": "2026-10-01T10:00:00", "created_at": _now()})


class TestApplyProjectChoice:
    def test_swaps_the_project_and_keeps_other_labels(self, conn):
        assert db.apply_project_choice(conn, ["urgent", "Trip"], "Thesis") == ["urgent", "Thesis"]

    def test_empty_choice_removes_the_project(self, conn):
        assert db.apply_project_choice(conn, ["Trip", "urgent"], "") == ["urgent"]

    def test_a_non_project_choice_is_ignored(self, conn):
        assert db.apply_project_choice(conn, ["urgent"], "urgent") == ["urgent"]

    def test_with_project_only_applies_when_the_form_carried_the_field(self, conn):
        assert dashboard_router._with_project(conn, "urgent,Trip", "Thesis", "") == "urgent,Trip"
        assert dashboard_router._with_project(conn, "urgent,Trip", "Thesis", "1") == "urgent,Thesis"


class TestOneProjectPerEvent:
    def test_new_second_project_is_rejected(self, conn):
        _event(conn, "e1", ["Trip"])
        with pytest.raises(db.MultipleProjectLabelsError) as exc:
            _event(conn, "e1", ["Trip", "Thesis"])
        assert "event" in str(exc.value)
        assert db.get_event(conn, "e1")["tags"] == ["Trip"]

    def test_a_pre_existing_pair_can_still_be_resaved(self, conn):
        # e.g. the week grid re-saving a dragged event that already had two.
        _event(conn, "e1", [])
        db.set_object_labels(conn, "event", "e1", ["Trip", "Thesis"])
        row = dict(db.get_event(conn, "e1"))
        row["start_at"] = "2026-10-02T10:00:00"
        db.upsert_event(conn, row)
        assert db.get_event(conn, "e1")["start_at"].startswith("2026-10-02")

    def test_route_turns_it_into_a_400(self, conn):
        with pytest.raises(HTTPException) as exc:
            calendar_router.create_event(
                title="Trip call", description="", start_at="2026-10-01T09:00", end_at="", all_day="",
                location="", meeting_url="", tags="Trip,Thesis", recurrence="", reminders="",
                holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn,
            )
        assert exc.value.status_code == 400


class TestRoutesApplyTheDropdown:
    def test_create_task(self, conn):
        tasks_router.create_task(title="Pack", description="", due_at="", status="active", tags="",
                                 tags_labels=["urgent"], project="Trip", project_field="1", recurrence="", conn=conn)
        task = next(t for t in db.list_tasks(conn) if t["title"] == "Pack")
        assert sorted(task["tags"]) == ["Trip", "urgent"]

    def test_update_task_moves_it_to_another_project(self, conn):
        _task(conn, "t1", ["Trip", "urgent"])
        # The Labels picker never lists projects, so it only posts "urgent".
        tasks_router.update_task("t1", title="t1", description="", due_at="", start_at="", status="active", tags="",
                                 tags_labels=["urgent"], project="Thesis", project_field="1", recurrence="", conn=conn)
        assert sorted(db.get_task(conn, "t1")["tags"]) == ["Thesis", "urgent"]

    def test_update_task_no_project(self, conn):
        _task(conn, "t1", ["Trip"])
        tasks_router.update_task("t1", title="t1", description="", due_at="", start_at="", status="active", tags="",
                                 tags_labels=[], project="", project_field="1", recurrence="", conn=conn)
        assert db.get_task(conn, "t1")["tags"] == []

    def test_create_and_update_event(self, conn):
        calendar_router.create_event(
            title="Flight", description="", start_at="2026-10-01T09:00", end_at="", all_day="",
            location="", meeting_url="", tags="", tags_labels=["urgent"], project="Trip", project_field="1",
            recurrence="", reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn,
        )
        event = next(e for e in db.list_events(conn) if e["title"] == "Flight")
        assert sorted(event["tags"]) == ["Trip", "urgent"]
        calendar_router.update_event(
            event["uid"], title="Flight", description="", start_at="2026-10-01T09:00", end_at="", all_day="",
            location="", meeting_url="", tags="", tags_labels=["urgent"], project="Thesis", project_field="1",
            recurrence="", reminders="", holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn,
        )
        assert sorted(db.get_event(conn, event["uid"])["tags"]) == ["Thesis", "urgent"]


class TestFormRendering:
    def _options(self, body, name):
        import re
        tags = re.findall(rf'<input type="(?:radio|checkbox)" name="{name}" value="([^"]*)"([^>]*)>', body)
        return [(v, "checked" if re.search(r"\bchecked\b", rest) else "") for v, rest in tags]

    def test_new_task_form_has_a_separate_project_dropdown(self, conn):
        body = tasks_router.new_task_form(_request("/tasks/new"), conn=conn).body.decode()
        assert 'name="project_field" value="1"' in body
        project_values = [v for v, _ in self._options(body, "project")]
        assert project_values == ["", "Thesis", "Trip"]  # No project first, archived left out
        label_values = [v for v, _ in self._options(body, "tags_labels")]
        assert "urgent" in label_values
        assert not {"Trip", "Thesis", "Old"} & set(label_values)

    def test_edit_task_form_preselects_its_project(self, conn):
        _task(conn, "t1", ["Trip", "urgent"])
        body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
        checked = [v for v, c in self._options(body, "project") if c]
        assert checked == ["Trip"]

    def test_archived_current_project_stays_selectable(self, conn):
        _task(conn, "t1", ["Old"])
        body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
        assert [v for v, c in self._options(body, "project") if c] == ["Old"]
        assert "Old (archived)" in body

    def test_edit_event_form_has_it_too(self, conn):
        _event(conn, "e1", ["Thesis"])
        body = calendar_router.edit_event_form("e1", _request("/events/e1/edit"), conn=conn).body.decode()
        assert [v for v, c in self._options(body, "project") if c] == ["Thesis"]

    def test_quick_add_task_from_a_project_page_prefills_it(self, conn):
        body = tasks_router.new_task_form(_request("/tasks/new"), project="Trip", conn=conn).body.decode()
        assert [v for v, c in self._options(body, "project") if c] == ["Trip"]


class TestOfflineSyncOneProjectPerEvent:
    def _op(self, op_id, label, physical, device):
        return {
            "op_id": op_id, "entity_type": "object_label", "entity_uid": "e1", "op_type": "label_add",
            "device_id": device, "hlc": {"physical": physical, "logical": 0, "device_id": device},
            "target": {"object_type": "event", "object_id": "e1", "label_name": label},
        }

    def test_two_devices_giving_an_event_different_projects(self, conn):
        _event(conn, "e1", [])
        results = offline_sync.apply_batch(conn, [self._op("op1", "Trip", 1000, "a"), self._op("op2", "Thesis", 2000, "b")])
        assert db.get_event(conn, "e1")["tags"] == ["Thesis"]
        assert {r["op_id"]: r["status"] for r in results}["op1"] == "rejected_invariant"
        conflict = db.list_sync_conflicts(conn)[0]
        assert (conflict["entity_type"], conflict["losing_value"]) == ("event", "Trip")

    def test_plain_labels_on_events_are_untouched(self, conn):
        _event(conn, "e1", ["Trip"])
        offline_sync.apply_batch(conn, [self._op("op1", "urgent", 1000, "a")])
        assert sorted(db.get_event(conn, "e1")["tags"]) == ["Trip", "urgent"]
