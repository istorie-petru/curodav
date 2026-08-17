"""Sleep Time / Leisure Time (1.9 side work, direct feedback: "Add an
option in the settings to set-up Leisure Time and Sleep Time... similar to
the holiday settings, but just adding the hours... and days"). Covers the
Settings > Sleep & Leisure Time page/routes (same shape as
test_settings_holidays.py) plus the Week/Day grid's overlay computation and
client-warning JSON payload (routers/calendar.py's
`_time_block_overlays_for_day`/`_time_blocks_client_payload`). The page was
a Tasks-table-style grid with inline editing; the 2026-08-17 settings HTML
uniformity pass (SETTINGS_UI_GUIDE.md pattern B) rebuilt it onto the
grouped-list + modal pattern -- a read-only row per block, one Edit button
opening time_block_edit_modal.html (delete lives in that modal's footer),
and a per-section "+ Add" toolbar button opening the same modal empty. The
old per-field inline edit (update_time_block_field +
static/settings_time_blocks.js) is gone, replaced by one whole-form
update_time_block endpoint."""

from __future__ import annotations

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


def _request(path="/settings/time-blocks", query_string=b""):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": query_string,
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [],
        }
    )


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
        assert 'id="sleep-block-list"' not in body
        assert 'id="leisure-block-list"' not in body
        assert 'href="/settings/time-blocks/new?kind=sleep"' in body
        assert 'href="/settings/time-blocks/new?kind=leisure"' in body

    def test_lists_existing_blocks_in_their_own_list(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday,Tuesday"})
        db.upsert_time_block(conn, {"uid": "l1", "kind": "leisure", "label": "Evening", "start_time": "21:00", "end_time": "21:59", "days": "Monday"})
        body = settings_router.settings_time_blocks(_request(), conn=conn).body.decode()
        assert 'id="sleep-block-list"' in body
        assert 'id="leisure-block-list"' in body
        assert "Night" in body
        assert "Evening" in body
        assert "00:00&ndash;05:59 &middot; Monday Tuesday" in body
        assert 'href="/settings/time-blocks/s1/edit"' in body
        assert 'href="/settings/time-blocks/l1/edit"' in body
        assert 'class="inline-text"' not in body
        assert 'id="sleep-block-table"' not in body

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


class TestTimeBlockEditModal:
    def test_new_modal_renders_empty_add_form(self, conn):
        resp = settings_router.new_time_block_modal(_request("/settings/time-blocks/new"), kind="sleep", conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Add sleep time block" in body
        assert 'action="/settings/time-blocks"' in body
        assert 'id="time-block-form"' in body
        assert 'value="sleep"' in body
        assert 'name="days"' in body
        assert 'value="00:00"' not in body

    def test_new_modal_kind_flows_into_the_form(self, conn):
        resp = settings_router.new_time_block_modal(_request("/settings/time-blocks/new"), kind="leisure", conn=conn)
        body = resp.body.decode()
        assert "Add leisure time block" in body
        assert 'value="leisure"' in body

    def test_edit_modal_prefills_values_and_posts_to_update(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday,Tuesday"})
        resp = settings_router.edit_time_block_modal("s1", _request("/settings/time-blocks/s1/edit"), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Edit time block" in body
        assert 'action="/settings/time-blocks/s1/update"' in body
        assert 'value="Night"' in body
        assert 'value="00:00"' in body
        assert 'value="05:59"' in body
        assert 'action="/settings/time-blocks/s1/delete"' in body

    def test_edit_modal_404s_for_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.edit_time_block_modal("missing", _request("/settings/time-blocks/missing/edit"), conn=conn)
        assert exc.value.status_code == 404


class TestUpdateTimeBlock:
    def test_updates_label(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Old", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        resp = settings_router.update_time_block("s1", label="New", start_time="00:00", end_time="05:00", days=["Monday"], conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/time-blocks"
        assert db.get_time_block(conn, "s1")["label"] == "New"

    def test_updates_start_and_end_time(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        settings_router.update_time_block("s1", label="Night", start_time="01:00", end_time="05:00", days=["Monday"], conn=conn)
        assert db.get_time_block(conn, "s1")["start_time"] == "01:00"

    def test_drops_end_time_not_after_start(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        settings_router.update_time_block("s1", label="Night", start_time="00:00", end_time="00:00", days=["Monday"], conn=conn)
        assert db.get_time_block(conn, "s1")["end_time"] == "05:00"

    def test_updates_days(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        settings_router.update_time_block("s1", label="Night", start_time="00:00", end_time="05:00", days=["Monday", "Tuesday", "Wednesday"], conn=conn)
        assert db.get_time_block(conn, "s1")["days"] == "Monday,Tuesday,Wednesday"

    def test_drops_invalid_day_names(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        settings_router.update_time_block("s1", label="Night", start_time="00:00", end_time="05:00", days=["Monday", "Someday"], conn=conn)
        assert db.get_time_block(conn, "s1")["days"] == "Monday"

    def test_kind_is_fixed_by_the_row_not_the_form(self, conn):
        db.upsert_time_block(conn, {"uid": "s1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:00", "days": "Monday"})
        settings_router.update_time_block("s1", label="Night", start_time="00:00", end_time="05:00", days=["Monday"], conn=conn)
        assert db.get_time_block(conn, "s1")["kind"] == "sleep"

    def test_404s_for_unknown_uid(self, conn):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            settings_router.update_time_block("missing", label="New", start_time="00:00", end_time="05:00", days=["Monday"], conn=conn)
        assert exc.value.status_code == 404


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
