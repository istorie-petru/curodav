"""Sleep Time / Leisure Time (1.9 side work, direct feedback: "Add an
option in the settings to set-up Leisure Time and Sleep Time... similar to
the holiday settings, but just adding the hours... and days"). Covers the
Settings > Sleep & Leisure Time page/routes (same shape as
test_settings_holidays.py) plus the Week/Day grid's overlay computation and
client-warning JSON payload (routers/calendar.py's
`_time_block_overlays_for_day`/`_time_blocks_client_payload`)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _request(path="/settings/time-blocks"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [],
        }
    )


class _FakeJsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class TestSettingsTimeBlocksPage:
    def test_renders_with_breadcrumb_and_active_tab(self, conn):
        resp = settings_router.settings_time_blocks(_request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["active_tab"] == "settings_time_blocks"
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]

    def test_empty_state_when_no_blocks(self, conn):
        body = settings_router.settings_time_blocks(_request(), conn=conn).body.decode()
        assert "No sleep time configured yet" in body
        assert "No leisure time configured yet" in body
        assert 'id="sleep-block-table"' not in body
        assert 'id="leisure-block-table"' not in body

    def test_lists_existing_blocks_in_their_own_table(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday,Tuesday"})
        db.upsert_time_block(conn, {"uid": "l1", "kind": "leisure", "label": "Evening", "start_time": "21:00", "end_time": "21:59", "days": "Monday"})
        body = settings_router.settings_time_blocks(_request(), conn=conn).body.decode()
        assert 'id="sleep-block-table"' in body
        assert 'id="leisure-block-table"' in body
        assert "Night" in body
        assert "Evening" in body

    def test_hub_links_to_time_blocks(self, conn):
        body = settings_router.settings_index(_request("/settings"), conn=conn).body.decode()
        assert 'href="/settings/time-blocks"' in body
        assert "Sleep &amp; Leisure Time" in body or "Sleep & Leisure Time" in body


class TestCreateTimeBlock:
    def test_creates_sleep_block(self, conn):
        resp = settings_router.create_time_block(kind="sleep", label="Night", start_time="00:00", end_time="05:59", days=["Monday", "Tuesday"], conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/time-blocks"
        blocks = db.list_time_blocks(conn, "sleep")
        assert len(blocks) == 1
        assert blocks[0]["days"] == "Monday,Tuesday"

    def test_creates_leisure_block(self, conn):
        settings_router.create_time_block(kind="leisure", label="", start_time="21:00", end_time="21:59", days=db.TIME_BLOCK_DAYS, conn=conn)
        blocks = db.list_time_blocks(conn, "leisure")
        assert len(blocks) == 1
        assert blocks[0]["days"] == ",".join(db.TIME_BLOCK_DAYS)

    def test_rejects_end_before_start(self, conn):
        settings_router.create_time_block(kind="sleep", label="Bad", start_time="10:00", end_time="09:00", days=["Monday"], conn=conn)
        assert db.list_time_blocks(conn) == []

    def test_rejects_unknown_kind(self, conn):
        settings_router.create_time_block(kind="nap", label="Nap", start_time="13:00", end_time="14:00", days=["Monday"], conn=conn)
        assert db.list_time_blocks(conn) == []

    def test_drops_invalid_day_names(self, conn):
        settings_router.create_time_block(kind="sleep", label="Night", start_time="00:00", end_time="05:00", days=["Monday", "Someday"], conn=conn)
        assert db.list_time_blocks(conn)[0]["days"] == "Monday"


class TestUpdateTimeBlockField:
    def test_updates_label(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Old", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        req = _FakeJsonRequest({"field": "label", "value": "New"})
        resp = asyncio.run(settings_router.update_time_block_field("s1", req, conn=conn))
        assert resp.status_code == 200
        assert db.get_time_block(conn, "s1")["label"] == "New"

    def test_updates_start_and_end_time(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        req = _FakeJsonRequest({"field": "start_time", "value": "01:00"})
        asyncio.run(settings_router.update_time_block_field("s1", req, conn=conn))
        assert db.get_time_block(conn, "s1")["start_time"] == "01:00"

    def test_rejects_end_time_not_after_start(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        req = _FakeJsonRequest({"field": "end_time", "value": "00:00"})
        resp = asyncio.run(settings_router.update_time_block_field("s1", req, conn=conn))
        assert resp.status_code == 400
        assert db.get_time_block(conn, "s1")["end_time"] == "05:00"

    def test_updates_days(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        req = _FakeJsonRequest({"field": "days", "value": "Monday,Tuesday,Wednesday"})
        asyncio.run(settings_router.update_time_block_field("s1", req, conn=conn))
        assert db.get_time_block(conn, "s1")["days"] == "Monday,Tuesday,Wednesday"

    def test_rejects_a_non_allowlisted_field(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        req = _FakeJsonRequest({"field": "kind", "value": "leisure"})
        resp = asyncio.run(settings_router.update_time_block_field("s1", req, conn=conn))
        assert resp.status_code == 400

    def test_404s_for_unknown_uid(self, conn):
        req = _FakeJsonRequest({"field": "label", "value": "New"})
        resp = asyncio.run(settings_router.update_time_block_field("missing", req, conn=conn))
        assert resp.status_code == 404


class TestDeleteTimeBlock:
    def test_deletes_and_redirects(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        resp = settings_router.delete_time_block("s1", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/time-blocks"
        assert db.list_time_blocks(conn) == []


class TestWeekDayOverlays:
    """The Week/Day grid's soft hatching (routers/calendar.py's
    _time_block_overlays_for_day, rendered by calendar_week.html/
    calendar_day.html as `.time-block-sleep`/`.time-block-leisure`)."""

    def test_sleep_block_appears_on_matching_weekday(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "", "start_time": "00:00", "end_time": "05:59", "days": ",".join(db.TIME_BLOCK_DAYS)})
        overlays = calendar_router._time_block_overlays_for_day(db.list_time_blocks(conn), date(2026, 8, 17))  # a Monday
        assert len(overlays) == 1
        assert overlays[0]["kind"] == "sleep"
        assert overlays[0]["top_px"] == 0
        assert overlays[0]["height_px"] > 0

    def test_block_absent_on_a_day_not_in_its_day_set(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "", "start_time": "00:00", "end_time": "05:59", "days": "Tuesday"})
        overlays = calendar_router._time_block_overlays_for_day(db.list_time_blocks(conn), date(2026, 8, 17))  # a Monday
        assert overlays == []

    def test_week_view_renders_hatching_classes(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": ",".join(db.TIME_BLOCK_DAYS)})
        db.upsert_time_block(conn, {"uid": "l1", "kind": "leisure", "label": "Evening", "start_time": "21:00", "end_time": "21:59", "days": ",".join(db.TIME_BLOCK_DAYS)})
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert "time-block-sleep" in body
        assert "time-block-leisure" in body

    def test_day_view_renders_hatching_classes(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": ",".join(db.TIME_BLOCK_DAYS)})
        body = calendar_router.day_view("2026-08-17", _request("/calendar/day/2026-08-17"), conn=conn).body.decode()
        assert "time-block-sleep" in body

    def test_month_view_has_no_hatching(self, conn):
        """Month (unlike Week/Day) has no time-of-day axis at all --
        Sleep/Leisure Time simply isn't a Month-view concept."""
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": ",".join(db.TIME_BLOCK_DAYS)})
        body = calendar_router.month_view(_request("/calendar"), year=2026, month=8, conn=conn).body.decode()
        assert "time-block-sleep" not in body


class TestClientWarningPayload:
    """The Week/Day grid's client-side scheduling-warning JSON
    (routers/calendar.py's `_time_blocks_client_payload`,
    static/time_blocks.js)."""

    def test_payload_shape(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday,Tuesday"})
        payload = json.loads(calendar_router._time_blocks_client_payload(db.list_time_blocks(conn)))
        assert payload == [{"kind": "sleep", "label": "Night", "days": ["Monday", "Tuesday"], "start_min": 0, "end_min": 359}]

    def test_week_view_embeds_the_payload(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday"})
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert 'id="cc-time-blocks"' in body
        assert '"kind": "sleep"' in body

    def test_day_view_embeds_the_payload(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday"})
        body = calendar_router.day_view("2026-08-17", _request("/calendar/day/2026-08-17"), conn=conn).body.decode()
        assert 'id="cc-time-blocks"' in body
