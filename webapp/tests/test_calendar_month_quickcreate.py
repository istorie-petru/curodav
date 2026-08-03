"""Tests for Phase 10 of the projects/tags rework: month-view
click-and-hold drag-to-create. The drag interaction itself is client-side
JS (static/calendar_month.js, untested here -- this codebase has no JS
test infra for calendar.js/schedule_grid.js/tasks_table.js either, same
convention); what's tested is the server side it depends on: the
new /events/new?date=X&end_date=Y prefill path (all-day, spanning
midnight-to-midnight) and that it doesn't regress the existing
Week/Day drag-to-create path (date+start_time+end_time, no end_date)."""

from __future__ import annotations

import pytest

from src import db
from src.routers import calendar as calendar_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


class TestNewEventFormDateRangePrefill:
    def test_date_and_end_date_prefills_all_day_range(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        resp = calendar_router.new_event_form(req, date="2026-08-10", end_date="2026-08-12", conn=conn)
        assert resp.status_code == 200
        assert resp.context["prefill_start"] == "2026-08-10T00:00"
        assert resp.context["prefill_end"] == "2026-08-12T23:59"
        assert resp.context["prefill_all_day"] is True

    def test_single_day_range_same_start_and_end(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        resp = calendar_router.new_event_form(req, date="2026-08-10", end_date="2026-08-10", conn=conn)
        assert resp.context["prefill_start"] == "2026-08-10T00:00"
        assert resp.context["prefill_end"] == "2026-08-10T23:59"
        assert resp.context["prefill_all_day"] is True

    def test_week_day_drag_create_path_unaffected(self, conn):
        """The pre-existing Week/Day drag-to-create path (start_time/
        end_time, no end_date) must still take priority and not be
        reinterpreted as an all-day range."""
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        resp = calendar_router.new_event_form(req, date="2026-08-10", start_time="14:00", end_time="15:30", conn=conn)
        assert resp.context["prefill_start"] == "2026-08-10T14:00"
        assert resp.context["prefill_end"] == "2026-08-10T15:30"
        assert resp.context["prefill_all_day"] is False

    def test_plain_date_only_unaffected(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        resp = calendar_router.new_event_form(req, date="2026-08-10", conn=conn)
        assert resp.context["prefill_start"] == "2026-08-10T09:00"
        assert resp.context["prefill_end"] is None
        assert resp.context["prefill_all_day"] is False

    def test_no_params_at_all(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/events/new", "headers": []})
        resp = calendar_router.new_event_form(req, conn=conn)
        assert resp.context["prefill_start"] is None
        assert resp.context["prefill_all_day"] is False
