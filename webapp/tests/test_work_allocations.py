"""Tests for 1.4's "Work allocations" (plans/open-priority.md § Work
allocations, § Task & calendar semantics) -- the data-model + task-detail
half of the slice. The project's own Week Calendar view (drag-and-drop
scheduling surface) is a later slice; this covers the underlying mechanism
it will sit on top of:

- A work allocation is a plain calendar Event linked to a task via
  `event_task_relations.is_work_allocation=1` (db.create_work_allocation),
  not a new table/object type.
- The estimated/completed work of a task is calculated from its actual
  calendar allocations (db.task_work_hours).
- Deleting a work allocation removes only that scheduled block, never the
  task (db.delete_work_allocation).
- Changing a task's title keeps its allocation events' titles in sync
  (upsert_task -> db.sync_work_allocation_titles), and editing a
  work-allocation event's title updates the task instead of the event
  (routers/calendar.py's update_event)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import export as export_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _seed_event(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "start_at": "2026-08-17T09:00:00",
        "status": "active",
        "all_day": False,
        "tags": tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_event(conn, row)
    return db.get_event(conn, uid)


def _seed_task(conn, uid, tags=None, **overrides):
    row = {
        "uid": uid,
        "title": uid,
        "description": "",
        "status": "active",
        "tags": tags or [],
        "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


class TestCreateAndList:
    def test_create_work_allocation_makes_a_linked_event(self, conn):
        _seed_task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        event = db.get_event(conn, event_uid)
        assert event is not None
        assert event["title"] == "Research"
        assert event["start_at"] == "2026-08-17T16:00:00"
        assert event["end_at"] == "2026-08-17T18:00:00"

    def test_create_work_allocation_inherits_task_labels(self, conn):
        _seed_task(conn, "t1", tags=["Conference XYZ"])
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        assert db.get_event(conn, event_uid)["tags"] == ["Conference XYZ"]

    def test_multiple_allocations_split_across_days(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.create_work_allocation(conn, "t1", "2026-08-20T14:00:00", "2026-08-20T16:00:00")
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert [a["start_at"] for a in allocations] == ["2026-08-17T16:00:00", "2026-08-20T14:00:00"]

    def test_create_work_allocation_without_dates_makes_undated_session(self, conn):
        """The task modal's "+" button creates a work session with NO date --
        an unscheduled placeholder event (start/end NULL), still a real
        work-allocation session of the task."""
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1")
        event = db.get_event(conn, event_uid)
        assert event["start_at"] is None
        assert event["end_at"] is None
        assert db.work_allocation_task_uid(conn, event_uid) == "t1"

    def test_first_undated_work_allocation_returns_oldest_undated(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        undated_uid = db.create_work_allocation(conn, "t1")
        assert db.first_undated_work_allocation_for_task(conn, "t1")["uid"] == undated_uid

    def test_first_undated_work_allocation_none_when_all_dated(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        assert db.first_undated_work_allocation_for_task(conn, "t1") is None

    def test_set_work_allocation_times_places_undated_session(self, conn):
        _seed_task(conn, "t1")
        undated_uid = db.create_work_allocation(conn, "t1")
        assert db.set_work_allocation_times(conn, undated_uid, "2026-08-17T16:00:00", "2026-08-17T18:00:00") is True
        event = db.get_event(conn, undated_uid)
        assert event["start_at"] == "2026-08-17T16:00:00"
        assert event["end_at"] == "2026-08-17T18:00:00"

    def test_set_work_allocation_times_rejects_non_allocation(self, conn):
        _seed_event(conn, "e1")
        assert db.set_work_allocation_times(conn, "e1", "2026-08-17T16:00:00", "2026-08-17T18:00:00") is False
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-17T09:00:00"  # untouched

    def test_list_work_allocations_excludes_ordinary_relations(self, conn):
        """An ordinary Relations-card link (is_work_allocation=0) must never
        show up as a work allocation -- the flag is the only thing that
        distinguishes the two uses of the same table."""
        _seed_task(conn, "t1", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"])
        db.add_event_task_relation(conn, "e1", "t1")
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_work_allocation_task_uid_roundtrip(self, conn):
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        assert db.work_allocation_task_uid(conn, event_uid) == "t1"

    def test_work_allocation_task_uid_none_for_ordinary_event(self, conn):
        _seed_event(conn, "e1")
        assert db.work_allocation_task_uid(conn, "e1") is None


class TestHours:
    def test_scheduled_hours_sum_across_blocks(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")  # 2h
        db.create_work_allocation(conn, "t1", "2026-08-20T14:00:00", "2026-08-20T16:30:00")  # 2.5h
        hours = db.task_work_hours(conn, "t1")
        assert hours["scheduled"] == pytest.approx(4.5)

    def test_completed_hours_only_counts_past_blocks(self, conn):
        _seed_task(conn, "t1")
        # Safely in the past relative to any real clock.
        db.create_work_allocation(conn, "t1", "2020-01-01T09:00:00", "2020-01-01T11:00:00")  # 2h, past
        # Safely in the future.
        db.create_work_allocation(conn, "t1", "2099-01-01T09:00:00", "2099-01-01T12:00:00")  # 3h, future
        hours = db.task_work_hours(conn, "t1")
        assert hours["scheduled"] == pytest.approx(5.0)
        assert hours["completed"] == pytest.approx(2.0)
        assert hours["remaining"] == pytest.approx(3.0)

    def test_no_allocations_is_all_zero(self, conn):
        _seed_task(conn, "t1")
        assert db.task_work_hours(conn, "t1") == {"scheduled": 0.0, "completed": 0.0, "remaining": 0.0}


class TestDeleteSemantics:
    def test_delete_work_allocation_removes_only_the_block(self, conn):
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.delete_work_allocation(conn, event_uid)
        assert db.get_event(conn, event_uid) is None
        assert db.get_task(conn, "t1") is not None
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_deleting_the_task_does_not_delete_past_allocation_history_implicitly(self, conn):
        """delete_task's existing cascade only removes event_task_relations
        rows, never the events themselves -- unaffected by is_work_allocation,
        same as it already worked for ordinary relations."""
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.delete_task(conn, "t1")
        assert db.get_event(conn, event_uid) is not None
        assert db.list_event_task_relations(conn) == []


class TestTitleSync:
    def test_editing_task_title_updates_allocation_event_titles(self, conn):
        _seed_task(conn, "t1", title="Research")
        e1 = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        e2 = db.create_work_allocation(conn, "t1", "2026-08-20T14:00:00", "2026-08-20T16:00:00")
        task = db.get_task(conn, "t1")
        task_row = dict(task)
        task_row["title"] = "Research (renamed)"
        db.upsert_task(conn, task_row)
        assert db.get_event(conn, e1)["title"] == "Research (renamed)"
        assert db.get_event(conn, e2)["title"] == "Research (renamed)"

    def test_title_sync_does_not_touch_ordinary_related_events(self, conn):
        _seed_task(conn, "t1", title="Research", tags=["Work"])
        _seed_event(conn, "e1", tags=["Work"], title="Unrelated event")
        db.add_event_task_relation(conn, "e1", "t1")
        task_row = dict(db.get_task(conn, "t1"))
        task_row["title"] = "Research (renamed)"
        db.upsert_task(conn, task_row)
        assert db.get_event(conn, "e1")["title"] == "Unrelated event"

    def test_editing_allocation_event_title_updates_the_task_not_the_event(self, conn):
        _seed_task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        calendar_router.update_event(
            event_uid,
            title="Deep research",
            description="",
            start_at="2026-08-17T16:00:00",
            end_at="2026-08-17T18:00:00",
            all_day="", location="", meeting_url="", tags="", recurrence="", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="",
            conn=conn,
        )
        assert db.get_task(conn, "t1")["title"] == "Deep research"
        # The event itself ends up with the same title (kept in sync from
        # the task, not independently renamed to something conflicting).
        assert db.get_event(conn, event_uid)["title"] == "Deep research"

    def test_editing_ordinary_event_title_is_unaffected(self, conn):
        _seed_event(conn, "e1", title="Plain event")
        calendar_router.update_event(
            "e1", title="Renamed plain event", description="", start_at="2026-08-17T09:00:00", end_at="",
            all_day="", location="", meeting_url="", tags="", recurrence="", reminders="",
            holiday_calendar="", exclude_saturday="", exclude_sunday="", conn=conn
        )
        assert db.get_event(conn, "e1")["title"] == "Renamed plain event"


class TestTaskDetailRouter:
    def test_add_work_allocation_route_creates_a_block(self, conn):
        _seed_task(conn, "t1")
        resp = tasks_router.add_work_allocation(
            "t1", start_at="2026-08-17T16:00:00", end_at="2026-08-17T18:00:00", conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/tasks/t1")
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_add_work_allocation_rejects_end_before_start(self, conn):
        _seed_task(conn, "t1")
        tasks_router.add_work_allocation(
            "t1", start_at="2026-08-17T18:00:00", end_at="2026-08-17T16:00:00", conn=conn
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_add_work_allocation_without_date_creates_unscheduled_session(self, conn):
        """The Work sessions card's "+" button posts NO date at all -- the
        route must create an unscheduled session placeholder (start/end NULL)
        rather than reject the empty form."""
        _seed_task(conn, "t1")
        resp = tasks_router.add_work_allocation("t1", start_at="", end_at="", conn=conn)
        assert resp.status_code == 303
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["start_at"] is None
        assert allocations[0]["end_at"] is None
        assert db.first_undated_work_allocation_for_task(conn, "t1")["uid"] == allocations[0]["uid"]

    def test_remove_work_allocation_route_keeps_task(self, conn):
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        resp = tasks_router.remove_work_allocation("t1", event_uid=event_uid, conn=conn)
        assert resp.status_code == 303
        assert db.get_task(conn, "t1") is not None
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_set_times_route_dates_an_undated_session(self, conn):
        """The Work sessions card's per-session picker (2026-08-17) posts
        start_at/end_at to set-times; an undated placeholder becomes a
        scheduled block."""
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1")  # undated placeholder
        resp = tasks_router.set_work_allocation_times(
            "t1", event_uid, start_at="2026-08-17T16:00", end_at="2026-08-17T18:00", conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/tasks/t1")
        session = db.get_event(conn, event_uid)
        assert session["start_at"] == "2026-08-17T16:00"
        assert session["end_at"] == "2026-08-17T18:00"

    def test_set_times_route_rejects_end_before_start(self, conn):
        _seed_task(conn, "t1")
        event_uid = db.create_work_allocation(conn, "t1")
        tasks_router.set_work_allocation_times(
            "t1", event_uid, start_at="2026-08-17T18:00", end_at="2026-08-17T16:00", conn=conn
        )
        session = db.get_event(conn, event_uid)
        assert session["start_at"] is None

    def test_set_times_route_rejects_non_allocation_event(self, conn):
        """db.set_work_allocation_times only moves a session that actually
        belongs to this task; an ordinary event (or another task's session)
        is a no-op, never an error."""
        _seed_task(conn, "t1")
        _seed_event(conn, "e1")  # plain calendar event, not a work session
        resp = tasks_router.set_work_allocation_times(
            "t1", "e1", start_at="2026-08-17T16:00", end_at="2026-08-17T18:00", conn=conn
        )
        assert resp.status_code == 303
        assert db.get_event(conn, "e1")["start_at"] == "2026-08-17T09:00:00"  # untouched

    def test_task_detail_renders_work_sessions_card(self, conn):
        _seed_task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert "Work sessions" in body
        assert "/tasks/t1/work-allocations" in body
        assert "/tasks/t1/work-allocations/remove" in body
        # New card shape: sessions are a numbered list ("Session n") with the
        # when-area now the shared datetime picker (client-rendered trigger
        # label) posting to the session's own set-times endpoint; the hidden
        # start/end inputs carry the current values.
        assert "Session 1" in body
        assert f"/tasks/t1/work-allocations/{event_uid}/set-times" in body
        assert 'value="2026-08-17T16:00:00"' in body
        assert 'value="2026-08-17T18:00:00"' in body
        assert "datetime-local" not in body

    def test_work_sessions_card_numbers_sessions_in_creation_order(self, conn):
        _seed_task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.create_work_allocation(conn, "t1")  # undated placeholder, added second
        body = tasks_router.task_detail("t1", _request("/tasks/t1"), conn=conn).body.decode()
        assert "Session 1" in body
        assert "Session 2" in body

    def test_task_form_renders_work_sessions_card_on_edit(self, conn):
        _seed_task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        body = tasks_router.edit_task_form("t1", _request("/tasks/t1/edit"), conn=conn).body.decode()
        assert "/tasks/t1/work-allocations" in body


class TestPanelInfoAndSessionStepper:
    """1.9 "Unscheduled work" panel rework -- the db summary the planning
    grids' panel items render (work_allocation_panel_info), the panel's −
    button (remove_latest_work_allocation + its route), and the same-origin
    `next` redirect the +/− forms post so the reload returns to the grid."""

    def test_panel_info_no_sessions(self, conn):
        _seed_task(conn, "t1")
        info = db.work_allocation_panel_info(conn, "t1")
        assert info == {"count": 0, "scheduled_hours": 0.0, "total_hours": 0.0, "undated_count": 0}

    def test_panel_info_dated_sessions_sum_scheduled(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.create_work_allocation(conn, "t1", "2026-08-18T09:00:00", "2026-08-18T10:30:00")
        info = db.work_allocation_panel_info(conn, "t1")
        assert info["count"] == 2
        assert info["scheduled_hours"] == 3.5
        assert info["total_hours"] == 3.5
        assert info["undated_count"] == 0

    def test_panel_info_undated_session_counts_one_hour_toward_total(self, conn):
        """An undated session has no duration yet -- its planned contribution
        counts as the default 1-hour block it becomes when placed, so the
        x/y reads "on the calendar out of planned"."""
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        db.create_work_allocation(conn, "t1")  # undated
        info = db.work_allocation_panel_info(conn, "t1")
        assert info["count"] == 2
        assert info["scheduled_hours"] == 2.0
        assert info["total_hours"] == 3.0
        assert info["undated_count"] == 1

    def test_panel_info_unknown_task_is_zero_filled(self, conn):
        assert db.work_allocation_panel_info(conn, "ghost") == {
            "count": 0, "scheduled_hours": 0.0, "total_hours": 0.0, "undated_count": 0,
        }

    def test_remove_latest_removes_most_recent_session(self, conn):
        _seed_task(conn, "t1")
        first = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        second = db.create_work_allocation(conn, "t1")
        removed = db.remove_latest_work_allocation(conn, "t1")
        assert removed == second
        remaining = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        assert remaining == [first]

    def test_remove_latest_with_no_sessions_returns_none(self, conn):
        _seed_task(conn, "t1")
        assert db.remove_latest_work_allocation(conn, "t1") is None
        assert db.remove_latest_work_allocation(conn, "ghost") is None

    def test_remove_latest_never_touches_a_dated_session(self, conn):
        """Direct feedback (2026-08-14): the panel's number is "sessions
        still needing placement" (undated_count), so its "−" must only ever
        remove undated sessions -- even one created AFTER an already-
        scheduled block (i.e. more recent in creation order) must be picked
        over it. With no undated sessions left, "−" is a no-op even though
        the task still has dated ones."""
        _seed_task(conn, "t1")
        dated = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        undated = db.create_work_allocation(conn, "t1")  # created after `dated`
        removed = db.remove_latest_work_allocation(conn, "t1")
        assert removed == undated
        remaining = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        assert remaining == [dated]
        # Nothing left to remove -- the dated session is never touched.
        assert db.remove_latest_work_allocation(conn, "t1") is None
        assert [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")] == [dated]

    def test_add_work_allocation_route_returns_to_next_path(self, conn):
        _seed_task(conn, "t1")
        resp = tasks_router.add_work_allocation(
            "t1", start_at="", end_at="", next="/week?date_=2026-08-17", conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/week?date_=2026-08-17"
        assert db.first_undated_work_allocation_for_task(conn, "t1") is not None

    def test_add_work_allocation_route_rejects_open_redirect_next(self, conn):
        """A client-submitted `next` is only honored when it's a same-origin
        path -- a scheme or //-host payload falls back to the task."""
        _seed_task(conn, "t1")
        for bad in ("https://evil.example", "//evil.example", "\\\\evil"):
            resp = tasks_router.add_work_allocation("t1", start_at="", end_at="", next=bad, conn=conn)
            assert resp.headers["location"] == "/tasks/t1"

    def test_remove_latest_route_removes_one_session_and_returns_to_next(self, conn):
        _seed_task(conn, "t1")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        resp = tasks_router.remove_latest_work_allocation(
            "t1", next="/calendar/week?date_=2026-08-17", conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/calendar/week?date_=2026-08-17"
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1


class TestBackupRoundTrip:
    def test_work_allocation_flag_survives_export_and_restore(self, conn):
        """The is_work_allocation marker rides along in the JSON backup
        (routers/export.py) same as the rest of event_task_relations --
        restoring must not silently downgrade a work allocation into an
        ordinary Relations-card link."""
        _seed_task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", "2026-08-17T16:00:00", "2026-08-17T18:00:00")
        data = json.loads(export_router.export_data_json(conn=conn).body)
        relation = next(r for r in data["event_task_relations"] if r["event_uid"] == event_uid)
        assert relation["is_work_allocation"] == 1

        payload = {
            "events": data["events"], "tasks": data["tasks"], "contacts": [],
            "labels": [], "object_labels": [], "schedule_classes": [],
            "schedule_holidays": [], "schedule_settings": {},
            "task_completions": [], "event_task_relations": data["event_task_relations"],
        }
        upload = UploadFile(file=BytesIO(json.dumps(payload).encode("utf-8")))
        export_router.import_json(upload, conn=conn)
        assert [a["uid"] for a in db.list_work_allocations_for_task(conn, "t1")] == [event_uid]
