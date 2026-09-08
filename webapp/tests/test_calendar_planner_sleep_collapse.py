"""Acceptance tests for Settings > General's "Hide sleep hours in Planner"
(2026-09-09, direct request: "the time tagged as sleep time is just removed
as cells from the planner calendar view"). Off by default; when on, the
Week view's (`routers/calendar.py::week_view`) hour grid collapses whatever
single, uniform Sleep-kind window Settings > Sleep & Leisure Time has
configured -- confirmed via AskUserQuestion:

  - a uniform window across every configured Sleep-kind block is required
    (mixed windows -> no collapse at all, never a guess);
  - the hidden hours are fully removed, not just zero-height-but-reachable;
  - Day view is unaffected regardless of this setting.

Direct-router-call convention, same fixtures/helpers as
test_calendar_week_scheduling.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db, grid_layout
from src.deps import HIDE_SLEEP_HOURS_KEY
from src.routers import calendar as calendar_router
from src.routers import settings as settings_router

_MONDAY = "2026-08-17"  # a real Monday


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/calendar/week"):
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


def _sleep_block(conn, uid, start, end, days=None):
    db.upsert_time_block(
        conn,
        {
            "uid": uid, "kind": "sleep", "label": "Sleep", "start_time": start, "end_time": end,
            "days": ",".join(days or db.TIME_BLOCK_DAYS),
        },
    )


def _leisure_block(conn, uid, start, end, days=None):
    db.upsert_time_block(
        conn,
        {
            "uid": uid, "kind": "leisure", "label": "Leisure", "start_time": start, "end_time": end,
            "days": ",".join(days or db.TIME_BLOCK_DAYS),
        },
    )


def _enable(conn):
    db.set_app_meta(conn, HIDE_SLEEP_HOURS_KEY, "1")


def _event(conn, uid, start_at, end_at):
    db.upsert_event(
        conn,
        {
            "uid": uid, "title": uid, "description": "", "status": "active", "all_day": 0,
            "start_at": start_at, "end_at": end_at, "created_at": _now(),
        },
    )


class TestSettingDefaultsOffAndRoundTrips:
    def test_settings_general_defaults_to_off(self, conn):
        resp = settings_router.settings_general(_request(), conn=conn)
        assert resp.context["current_hide_sleep_hours"] is False

    def test_set_hide_sleep_hours_persists_on_and_off(self, conn):
        settings_router.set_hide_sleep_hours(enabled="1", conn=conn)
        assert db.get_app_meta(conn, HIDE_SLEEP_HOURS_KEY) == "1"
        resp = settings_router.settings_general(_request(), conn=conn)
        assert resp.context["current_hide_sleep_hours"] is True

        settings_router.set_hide_sleep_hours(enabled="", conn=conn)
        assert db.get_app_meta(conn, HIDE_SLEEP_HOURS_KEY) == ""
        resp = settings_router.settings_general(_request(), conn=conn)
        assert resp.context["current_hide_sleep_hours"] is False


class TestPlannerCollapseOffByDefault:
    def test_week_view_shows_every_hour_when_setting_is_off(self, conn):
        _sleep_block(conn, "s1", "00:00", "06:00")
        body = calendar_router.week_view(_request(), date_=_MONDAY, conn=conn).body.decode()
        assert 'class="hr-label"' in body
        # 24 hour labels still present -- nothing collapsed.
        assert body.count('class="hr-label"') == 24
        # Sleep overlay still hatches (not suppressed) since collapsing is off.
        assert "time-block-sleep" in body

    def test_week_view_ignores_sleep_blocks_that_disagree_on_the_window(self, conn):
        _enable(conn)
        _sleep_block(conn, "s1", "00:00", "06:00", days=["Monday"])
        _sleep_block(conn, "s2", "23:00", "23:30", days=["Tuesday"])
        body = calendar_router.week_view(_request(), date_=_MONDAY, conn=conn).body.decode()
        # Mixed windows -> no collapse at all, every hour still renders.
        assert body.count('class="hr-label"') == 24
        assert "time-block-sleep" in body


class TestPlannerCollapseOn:
    def test_uniform_sleep_window_collapses_the_hour_gutter(self, conn):
        _enable(conn)
        # One block per weekday, all sharing the same 00:00-06:00 window --
        # still "uniform" (same start/end), just split across rows.
        _sleep_block(conn, "s1", "00:00", "06:00", days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        _sleep_block(conn, "s2", "00:00", "06:00", days=["Saturday", "Sunday"])
        body = calendar_router.week_view(_request(), date_=_MONDAY, conn=conn).body.decode()
        # Hours 0-5 gone, 6-23 remain -- 18 labels.
        assert body.count('class="hr-label"') == 18
        # No sleep hatch left to render -- those hours don't exist any more.
        assert "time-block-sleep" not in body

    def test_leisure_overlay_still_renders_repositioned(self, conn):
        _enable(conn)
        _sleep_block(conn, "s1", "00:00", "06:00")
        _leisure_block(conn, "l1", "21:00", "22:00")
        ctx = calendar_router._week_view_context(conn, _request(), _MONDAY, None)
        monday_col = ctx["days"][0]
        overlays = {o["kind"]: o for o in monday_col["time_block_overlays"]}
        assert "sleep" not in overlays
        assert "leisure" in overlays
        # 21:00 real, minus the 6h collapsed window -> 15h in.
        assert overlays["leisure"]["top_px"] == 15 * grid_layout.PX_PER_HOUR

    def test_event_after_the_window_is_repositioned_and_grid_shrinks(self, conn):
        _enable(conn)
        _sleep_block(conn, "s1", "00:00", "06:00")
        _event(conn, "e1", f"{_MONDAY}T09:00:00", f"{_MONDAY}T10:00:00")
        ctx = calendar_router._week_view_context(conn, _request(), _MONDAY, None)
        monday_col = ctx["days"][0]
        assert len(monday_col["timed"]) == 1
        # 09:00 real, minus 6h collapsed -> 3h in.
        assert monday_col["timed"][0]["top_px"] == 3 * grid_layout.PX_PER_HOUR
        assert ctx["grid_height_px"] == grid_layout.grid_height_px((0, 360))
        assert ctx["grid_height_px"] < grid_layout.grid_height_px(None)

    def test_sleep_collapse_json_reflects_the_active_window(self, conn):
        _enable(conn)
        _sleep_block(conn, "s1", "00:00", "06:00")
        ctx = calendar_router._week_view_context(conn, _request(), _MONDAY, None)
        import json

        payload = json.loads(ctx["sleep_collapse_json"])
        assert payload == {"active": True, "skip_start": 0, "skip_end": 360}

    def test_sleep_collapse_json_inactive_when_setting_off(self, conn):
        _sleep_block(conn, "s1", "00:00", "06:00")
        ctx = calendar_router._week_view_context(conn, _request(), _MONDAY, None)
        import json

        payload = json.loads(ctx["sleep_collapse_json"])
        assert payload == {"active": False, "skip_start": 0, "skip_end": 0}


class TestDayViewUnaffected:
    def test_day_view_still_renders_all_24_hours_regardless_of_setting(self, conn):
        _enable(conn)
        _sleep_block(conn, "s1", "00:00", "06:00")
        body = calendar_router.day_view(_MONDAY, _request(path=f"/calendar/day/{_MONDAY}"), conn=conn).body.decode()
        assert body.count('class="hr-label"') == 24
