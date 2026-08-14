"""1.6 ("Manual recurrence exceptions") -- router-level coverage on top of
test_recurrence_expand.py's pure-logic tests. Covers: db.py's
event_occurrence_overrides accessors, the three /events/{uid}/occurrences/*
routes, event_detail rendering the "This occurrence" card, and calendar
week_view actually reflecting a cancel/move end to end.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/calendar"):
    return Request({
        "type": "http", "method": "GET", "path": path, "query_string": b"",
        "scheme": "http", "server": ("t", 80), "root_path": "", "headers": [],
    })


def _seed_recurring_event(conn, uid="e1"):
    calendar_router.create_event(
        title="Class", description="", start_at="2026-09-01T10:00", end_at="2026-09-01T12:00",
        all_day="", location="", meeting_url="", tags="",
        recurrence="FREQ=WEEKLY;UNTIL=2026-09-22", reminders="",
        holiday_calendar="", exclude_saturday="", exclude_sunday="",
        conn=conn,
    )
    return next(e for e in db.list_events(conn) if e["title"] == "Class")["uid"]


class TestListEventsIncludesFarFutureRecurringOccurrences:
    """Regression test for the db.list_events bug found while building this
    feature (see that function's own comment): a recurring event's own
    literal start_at/end_at only anchor its first occurrence, so the
    date-range query must never exclude a recurring row just because that
    literal anchor predates the queried window -- recurrence_expand.py is
    what actually decides whether it produces any occurrence inside it."""

    def test_recurring_event_is_returned_for_a_window_long_after_its_own_end_at(self, conn):
        db.upsert_event(conn, {
            "uid": "e1", "title": "Weekly", "description": "", "status": "active", "all_day": False,
            "start_at": "2026-01-05T10:00:00", "end_at": "2026-01-05T11:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-12-20",
            "created_at": _now(), "updated_at": _now(),
        })
        # A window many months past the event's own literal end_at.
        events = db.list_events(conn, start="2026-09-07", end="2026-09-13T23:59:59")
        assert any(e["uid"] == "e1" for e in events)

    def test_non_recurring_event_still_respects_the_date_window(self, conn):
        db.upsert_event(conn, {
            "uid": "e1", "title": "One-off", "description": "", "status": "active", "all_day": False,
            "start_at": "2026-01-05T10:00:00", "end_at": "2026-01-05T11:00:00",
            "created_at": _now(), "updated_at": _now(),
        })
        events = db.list_events(conn, start="2026-09-07", end="2026-09-13T23:59:59")
        assert events == []


class TestOverrideAccessors:
    def test_upsert_and_list_by_master(self, conn):
        uid = db.upsert_event_occurrence_override(conn, {
            "master_uid": "e1", "occurrence_date": "2026-09-08T10:00:00", "cancelled": True,
            "created_at": _now(), "updated_at": _now(),
        })
        overrides = db.list_event_occurrence_overrides(conn, "e1")
        assert len(overrides) == 1
        assert overrides[0]["uid"] == uid
        assert overrides[0]["cancelled"] == 1

    def test_upsert_is_idempotent_per_master_and_occurrence(self, conn):
        row = {"master_uid": "e1", "occurrence_date": "2026-09-08T10:00:00", "cancelled": True, "created_at": _now(), "updated_at": _now()}
        db.upsert_event_occurrence_override(conn, row)
        db.upsert_event_occurrence_override(conn, dict(row, cancelled=False, start_at="2026-09-09T14:00:00"))
        overrides = db.list_event_occurrence_overrides(conn, "e1")
        assert len(overrides) == 1
        assert overrides[0]["cancelled"] == 0
        assert overrides[0]["start_at"] == "2026-09-09T14:00:00"

    def test_delete_restores_the_occurrence(self, conn):
        db.upsert_event_occurrence_override(conn, {
            "master_uid": "e1", "occurrence_date": "2026-09-08T10:00:00", "cancelled": True,
            "created_at": _now(), "updated_at": _now(),
        })
        db.delete_event_occurrence_override(conn, "e1", "2026-09-08T10:00:00")
        assert db.list_event_occurrence_overrides(conn, "e1") == []

    def test_deleting_the_master_event_cascades_overrides(self, conn):
        uid = _seed_recurring_event(conn)
        db.upsert_event_occurrence_override(conn, {
            "master_uid": uid, "occurrence_date": "2026-09-08T10:00:00", "cancelled": True,
            "created_at": _now(), "updated_at": _now(),
        })
        db.delete_event(conn, uid)
        assert db.list_event_occurrence_overrides(conn, uid) == []

    def test_list_by_master_groups_correctly(self, conn):
        db.upsert_event_occurrence_override(conn, {"master_uid": "e1", "occurrence_date": "2026-09-08T10:00:00", "cancelled": True, "created_at": _now(), "updated_at": _now()})
        db.upsert_event_occurrence_override(conn, {"master_uid": "e2", "occurrence_date": "2026-09-09T10:00:00", "cancelled": True, "created_at": _now(), "updated_at": _now()})
        by_master = db.list_event_occurrence_overrides_by_master(conn)
        assert set(by_master) == {"e1", "e2"}


class TestOccurrenceRoutes:
    def test_cancel_route_creates_an_override(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.cancel_occurrence(uid, occurrence_date="2026-09-08T10:00:00", conn=conn)
        overrides = db.list_event_occurrence_overrides(conn, uid)
        assert len(overrides) == 1
        assert overrides[0]["cancelled"] == 1

    def test_move_route_creates_an_override_with_new_time(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.move_occurrence(
            uid, occurrence_date="2026-09-08T10:00:00", start_at="2026-09-09T14:00:00",
            end_at="2026-09-09T16:00:00", title="", location="", conn=conn,
        )
        overrides = db.list_event_occurrence_overrides(conn, uid)
        assert overrides[0]["cancelled"] == 0
        assert overrides[0]["start_at"] == "2026-09-09T14:00:00"

    def test_restore_route_removes_the_override(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.cancel_occurrence(uid, occurrence_date="2026-09-08T10:00:00", conn=conn)
        calendar_router.restore_occurrence(uid, occurrence_date="2026-09-08T10:00:00", conn=conn)
        assert db.list_event_occurrence_overrides(conn, uid) == []


class TestEventDetailOccurrenceCard:
    def test_no_occurrence_date_hides_the_card(self, conn):
        uid = _seed_recurring_event(conn)
        resp = calendar_router.event_detail(uid, _request(f"/events/{uid}"), conn=conn)
        assert "This occurrence" not in resp.body.decode()

    def test_occurrence_date_on_a_non_overridden_slot_offers_cancel_and_move(self, conn):
        uid = _seed_recurring_event(conn)
        resp = calendar_router.event_detail(
            uid, _request(f"/events/{uid}"), occurrence_date="2026-09-08T10:00:00", conn=conn,
        )
        body = resp.body.decode()
        assert "This occurrence" in body
        assert "Cancel this occurrence" in body
        assert "Move this occurrence" in body
        assert "Restore to series" not in body

    def test_occurrence_date_on_a_cancelled_slot_offers_restore(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.cancel_occurrence(uid, occurrence_date="2026-09-08T10:00:00", conn=conn)
        resp = calendar_router.event_detail(
            uid, _request(f"/events/{uid}"), occurrence_date="2026-09-08T10:00:00", conn=conn,
        )
        body = resp.body.decode()
        assert "Restore to series" in body
        assert "Cancel this occurrence" not in body


class TestWeekViewReflectsOverrides:
    def test_cancelled_occurrence_does_not_render_in_its_original_week(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.cancel_occurrence(uid, occurrence_date="2026-09-08T10:00:00", conn=conn)
        resp = calendar_router.week_view(_request("/calendar/week"), date_="2026-09-07", conn=conn)
        assert "Class" not in resp.body.decode()

    def test_moved_occurrence_renders_in_its_new_week(self, conn):
        uid = _seed_recurring_event(conn)
        calendar_router.move_occurrence(
            uid, occurrence_date="2026-09-08T10:00:00", start_at="2026-09-30T14:00:00",
            end_at="2026-09-30T16:00:00", title="Moved class", location="", conn=conn,
        )
        # Original week (Sep 7-13): no occurrence anymore.
        resp_old = calendar_router.week_view(_request("/calendar/week"), date_="2026-09-07", conn=conn)
        assert "Moved class" not in resp_old.body.decode()
        # New week (Sep 28-Oct 4), well past the master's own literal
        # start_at/end_at: the moved occurrence still shows up, renamed --
        # regression coverage for the db.list_events date-filter bug this
        # test uncovered (see that function's own comment).
        resp_new = calendar_router.week_view(_request("/calendar/week"), date_="2026-09-28", conn=conn)
        assert "Moved class" in resp_new.body.decode()
