"""The Calendar 4-Week view (2026-08-11) -- Month's day-grid layout
(_four_week_grid) over a rolling, continuous 28-day window instead of
calendar-month boundaries. The current week (the week containing the
anchor date, default today) occupies whichever of the four rows Settings >
General's "4-Week view: current week" preference names
(deps._four_week_position / FOUR_WEEK_POSITION_KEY), so the window starts
`(position - 1) * 7` days before the anchor week.

Covers: the window math (_four_week_window), the grid shape (_four_week_grid
-- always exactly 4 full weeks, every cell in-window, shared day-cell logic
with Month), the position setting's parse/read, the route itself (context
keys, nav, no .not-in-month cells, today highlight on the configured row),
and the Settings > General control + POST route.

Follows the fixture/request-building conventions used for this router in
test_calendar_month_bars.py and test_display_prefs_settings.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db, deps
from src.routers import calendar as calendar_router
from src.routers import settings as settings_router

# 2026-08-10 is a Monday; a Monday-anchored week that starts exactly on the
# 10th and runs to the 6th of September -- convenient fixed dates that put
# no "today" anywhere near the assertions below.
MONDAY = date(2026, 8, 10)
_WEEK_START_MONDAY = date(2026, 8, 10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bare_request(path="/calendar/fourweek"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _request_with_app(path, db_path):
    """Same helper as test_display_prefs_settings.py's own -- a Request
    whose `.app.state.settings.db_path` actually resolves, so deps.py's
    app_meta-backed globals exercise their real (non-fallback) path."""
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="http://localhost:5232")))
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [], "app": fake_app,
        }
    )


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _event(uid: str, start: str, end: str | None = None, all_day: bool = False) -> dict:
    return {"uid": uid, "title": uid, "start_at": start, "end_at": end, "all_day": all_day}


def _task(uid: str, due_at: str) -> dict:
    return {"uid": uid, "title": uid, "due_at": due_at}


def _day(weeks, iso: str) -> dict:
    return next(d for w in weeks for d in w["days"] if d["iso"] == iso)


class TestFourWeekWindow:
    def test_position_1_starts_window_at_anchor_week(self):
        # Anchor week is the Monday week containing the anchor -- position 1
        # puts it on the first row, so the window starts there.
        start, end = calendar_router._four_week_window(MONDAY, "monday", 1)
        assert start == _WEEK_START_MONDAY
        assert end == _WEEK_START_MONDAY + timedelta(days=27)

    def test_position_2_starts_one_week_earlier(self):
        start, _ = calendar_router._four_week_window(MONDAY, "monday", 2)
        assert start == _WEEK_START_MONDAY - timedelta(days=7)

    def test_position_3_starts_two_weeks_earlier(self):
        start, _ = calendar_router._four_week_window(MONDAY, "monday", 3)
        assert start == _WEEK_START_MONDAY - timedelta(days=14)

    def test_position_4_starts_three_weeks_earlier(self):
        start, _ = calendar_router._four_week_window(MONDAY, "monday", 4)
        assert start == _WEEK_START_MONDAY - timedelta(days=21)

    def test_window_is_exactly_28_days(self):
        for position in (1, 2, 3, 4):
            start, end = calendar_router._four_week_window(MONDAY, "monday", position)
            assert end - start == timedelta(days=27)
            assert (end - start).days == 27

    def test_anchor_any_day_of_the_week_resolves_to_its_own_week(self):
        wednesday = MONDAY + timedelta(days=2)
        start, _ = calendar_router._four_week_window(wednesday, "monday", 1)
        assert start == _WEEK_START_MONDAY

    def test_respects_sunday_week_start(self):
        # Same anchor, but "Week starts on" Sunday -> the anchor's week
        # begins Sunday the 9th, and position 1 starts the window there.
        sunday = date(2026, 8, 9)
        start, _ = calendar_router._four_week_window(sunday, "sunday", 1)
        assert start == sunday
        # Position 2 shifts one week earlier, still to a Sunday.
        start, _ = calendar_router._four_week_window(sunday, "sunday", 2)
        assert start == sunday - timedelta(days=7)


class TestFourWeekGrid:
    def test_always_exactly_four_full_weeks_of_28_days(self):
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, [], [])
        assert isinstance(weeks, list)
        assert len(weeks) == 4
        days = [d for w in weeks for d in w["days"]]
        assert len(days) == 28
        assert all(len(w["days"]) == 7 for w in weeks)

    def test_days_are_consecutive_continuous_days(self):
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, [], [])
        days = [d["date"] for w in weeks for d in w["days"]]
        expected = [_WEEK_START_MONDAY + timedelta(days=i) for i in range(28)]
        assert days == expected

    def test_every_cell_is_in_window(self):
        # No adjacent-month/week gray-out: the window is exactly 28 days,
        # so no cell carries not-in-month styling (in_month is always True).
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, [], [])
        assert all(d["in_month"] is True for w in weeks for d in w["days"])

    def test_today_is_marked_on_its_own_cell(self):
        today = date.today()
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, [], [])
        if _WEEK_START_MONDAY <= today < _WEEK_START_MONDAY + timedelta(days=28):
            assert _day(weeks, today.isoformat())["is_today"] is True
        else:
            assert all(not d["is_today"] for w in weeks for d in w["days"])

    def test_all_day_multiday_event_repeats_every_day_it_touches(self):
        # Same repeat-per-day rule as _month_grid -- a 3-day all-day trip
        # fills every day it touches, not just its start day.
        events = [_event("e1", "2026-08-12T00:00:00", "2026-08-14T23:59:00", all_day=True)]
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, events, [])
        touched = {d["iso"] for w in weeks for d in w["days"] if d["rows"]}
        assert touched == {"2026-08-12", "2026-08-13", "2026-08-14"}

    def test_rows_order_and_overflow_shared_with_month(self):
        # The day cells are literally _month_day_cells, so the flat-list
        # ordering (all-day -> timed by time -> task) and the +N more cap
        # carry over unchanged -- spot-check rather than re-testing Month's
        # whole suite here.
        events = [
            _event("late", "2026-08-12T16:00:00", "2026-08-12T17:00:00"),
            _event("trip", "2026-08-12T00:00:00", "2026-08-12T23:59:00", all_day=True),
        ]
        tasks = [_task(f"t{i}", "2026-08-12") for i in range(5)]
        weeks = calendar_router._four_week_grid(_WEEK_START_MONDAY, events, tasks)
        day = _day(weeks, "2026-08-12")
        kinds = [i["kind"] for i in day["rows"]]
        # Same MONTH_MAX_VISIBLE_ITEMS=4 cap: the first four of the seven
        # rows stay visible, the rest fold into "+N more".
        assert kinds == ["all_day", "event", "task", "task"]
        assert day["overflow_count"] == 3


class TestFourWeekPositionParse:
    def test_unset_or_missing_defaults_to_first(self):
        assert deps._four_week_position_from_value(None) == 1
        assert deps._four_week_position_from_value("") == 1
        assert deps._four_week_position_from_value(None) == 1

    def test_valid_values_pass_through(self):
        assert deps._four_week_position_from_value("1") == 1
        assert deps._four_week_position_from_value("2") == 2
        assert deps._four_week_position_from_value("3") == 3
        assert deps._four_week_position_from_value("4") == 4

    def test_out_of_range_and_garbage_clamp_to_first(self):
        assert deps._four_week_position_from_value("0") == 1
        assert deps._four_week_position_from_value("5") == 1
        assert deps._four_week_position_from_value("-1") == 1
        assert deps._four_week_position_from_value("banana") == 1

    def test_defaults_to_first_without_app_scope(self):
        assert deps._four_week_position(_bare_request()) == 1

    def test_defaults_to_first_with_real_app_and_nothing_set(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path):
            pass
        assert deps._four_week_position(_request_with_app("/", db_path)) == 1

    def test_respects_stored_position(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.FOUR_WEEK_POSITION_KEY, "3")
        assert deps._four_week_position(_request_with_app("/", db_path)) == 3


class TestFourWeekViewRoute:
    def test_context_keys_and_default_window(self, conn):
        today = date.today()
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        ctx = resp.context
        assert ctx["calendar_view"] == "fourweek"
        assert len(ctx["weeks"]) == 4
        # Default position 1: window starts at today's week start.
        week_start, _ = calendar_router._week_bounds(today, "monday")
        assert ctx["view_start"] == week_start
        assert ctx["view_end"] == week_start + timedelta(days=27)
        assert ctx["anchor_iso"] == today.isoformat()
        assert ctx["prev_start"] == (week_start - timedelta(days=7)).isoformat()
        assert ctx["next_start"] == (week_start + timedelta(days=7)).isoformat()

    def test_next_link_moves_window_by_exactly_one_week(self, conn):
        # Follow the "next" button: re-render with date_=next_start (the
        # link's own payload) and the window must have slid forward exactly
        # 7 days -- the anchor week moves with it, so the anchor stays on
        # its configured row (today itself leaves the window after the
        # step, which is the point of stepping).
        first = calendar_router.four_week_view(_bare_request(), conn=conn)
        next_anchor = first.context["next_start"]
        second = calendar_router.four_week_view(_bare_request(), date_=next_anchor, conn=conn)
        assert second.context["view_start"] == first.context["view_start"] + timedelta(days=7)
        assert second.context["view_end"] == first.context["view_end"] + timedelta(days=7)
        # prev from the second render lands back exactly where we started.
        third = calendar_router.four_week_view(_bare_request(), date_=second.context["prev_start"], conn=conn)
        assert third.context["view_start"] == first.context["view_start"]

    def test_anchor_param_moves_the_window(self, conn):
        # MONDAY + 35 is another Monday (five full weeks out), so its own
        # week starts exactly there and -- at position 1 -- so does the
        # 28-day window.
        anchor = MONDAY + timedelta(days=35)
        resp = calendar_router.four_week_view(_bare_request(), date_=anchor.isoformat(), conn=conn)
        ctx = resp.context
        assert ctx["anchor_iso"] == anchor.isoformat()
        assert ctx["view_start"] == anchor
        assert ctx["view_end"] == anchor + timedelta(days=27)

    def test_window_shifts_earlier_with_stored_position(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.FOUR_WEEK_POSITION_KEY, "2")
            resp = calendar_router.four_week_view(_request_with_app("/calendar/fourweek", db_path), conn=c)
        assert resp.context["view_start"] == resp.context["view_start"]  # present
        # position 2: starts one week before today's week.
        today = date.today()
        week_start, _ = calendar_router._week_bounds(today, "monday")
        assert resp.context["view_start"] == week_start - timedelta(days=7)

    def test_stored_position_4_puts_current_week_on_last_row(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.FOUR_WEEK_POSITION_KEY, "4")
            resp = calendar_router.four_week_view(_request_with_app("/calendar/fourweek", db_path), conn=c)
        today = date.today()
        week_start, _ = calendar_router._week_bounds(today, "monday")
        assert resp.context["view_start"] == week_start - timedelta(days=21)
        # The row holding today is the LAST (4th) of the four rows.
        today_row = next(
            i for i, w in enumerate(resp.context["weeks"])
            if any(d["is_today"] for d in w["days"])
        )
        assert today_row == 3

    def test_respects_stored_sunday_week_start(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.set_app_meta(c, deps.WEEK_START_KEY, "sunday")
            resp = calendar_router.four_week_view(_request_with_app("/calendar/fourweek", db_path), conn=c)
        today = date.today()
        sunday_start, _ = calendar_router._week_bounds(today, "sunday")
        assert resp.context["view_start"] == sunday_start
        assert resp.context["weekday_names"] == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        assert resp.context["weeks"][0]["days"][0]["date"].strftime("%A") == "Sunday"

    def test_event_and_task_show_on_their_days(self, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        with db.connect(db_path) as c:
            db.upsert_event(c, {
                "uid": "e1", "title": "Trip", "description": "", "status": "active",
                "all_day": 1, "start_at": "2026-08-12T00:00:00", "end_at": "2026-08-12T23:59:00",
                "created_at": _now(),
            })
            db.upsert_task(c, {
                "uid": "t1", "title": "Essay", "description": "", "status": "active",
                "due_at": "2026-08-12", "created_at": _now(),
            })
            resp = calendar_router.four_week_view(_request_with_app("/calendar/fourweek", db_path), date_="2026-08-10", conn=c)
        body = resp.body.decode()
        assert "Trip" in body
        assert "Essay" in body


class TestFourWeekViewTemplate:
    def test_body_has_four_week_grids(self, conn):
        # 2026-08-28 "Calendar split into two pages": 4-Week is a standalone
        # tabbar destination now, no more Month/Week/Day cross-links on this
        # page's own subnav (base.html's tabbar carries the "4-Week" entry
        # instead -- asserted in test_tabbar_has_dedicated_fourweek_and_week_
        # entries below).
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        body = resp.body.decode()
        assert body.count('class="month-week-grid"') == 4

    def test_no_adjacent_month_cells(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        body = resp.body.decode()
        # Every cell is in-window, so no day cell ever carries the
        # .not-in-month class (the template's own comment legitimately
        # mentions the class name; assert on the rendered cell markup).
        assert "month-day-cell not-in-month" not in body

    def test_reuses_month_viewport_shell_and_script(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        body = resp.body.decode()
        assert 'class="card calendar-viewport month-viewport fourweek-viewport"' in body
        assert "calendar_month.js" in body
        assert "month-weekday-row" in body

    @staticmethod
    def _subnav(body: str) -> str:
        # base.html's own tabbar now also contains the literal text
        # "4-Week"/"Week" (their own dedicated tab entries), so a bare
        # substring check on the whole body would false-positive -- isolate
        # just the page's own `.calendar-subnav` segment first.
        start = body.index('class="segmented calendar-subnav"')
        end = body.index("</div>", start)
        return body[start:end]

    def test_month_view_subnav_is_month_day_only(self, conn):
        # 2026-08-28 "Calendar split into two pages": Month's own subnav no
        # longer cross-links to 4-Week/Week -- reaching them is via the
        # tabbar now.
        resp = calendar_router.month_view(_bare_request("/calendar"), year=2026, month=8, conn=conn)
        subnav = self._subnav(resp.body.decode())
        assert '>4-Week<' not in subnav and '>Week<' not in subnav
        assert '>Month<' in subnav and '>Day<' in subnav

    def test_day_view_subnav_is_month_day_only(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _bare_request(f"/calendar/day/{today_iso}"), conn=conn)
        subnav = self._subnav(resp.body.decode())
        assert '>4-Week<' not in subnav and '>Week<' not in subnav
        assert '>Month<' in subnav and '>Day<' in subnav

    def test_fourweek_page_has_no_subnav_cross_links(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        assert 'calendar-subnav' not in resp.body.decode()

    def test_week_page_has_no_subnav_cross_links(self, conn):
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        assert 'calendar-subnav' not in resp.body.decode()

    def test_tabbar_has_dedicated_fourweek_and_week_entries(self, conn):
        # base.html now carries "4-Week"/"Week" as their own fixed tabbar
        # destinations (data-tab="calendar_fourweek"/"calendar_week"),
        # alongside "Calendar" (Month/Day).
        body = calendar_router.four_week_view(_bare_request(), conn=conn).body.decode()
        assert 'data-tab="calendar_fourweek"' in body
        assert 'data-tab="calendar_week"' in body
        assert 'data-tab="calendar" ' in body


class TestFourWeekPositionSetting:
    def test_general_page_renders_control_defaulting_to_first(self, conn):
        resp = settings_router.settings_general(_bare_request("/settings/general"), conn=conn)
        body = resp.body.decode()
        assert 'action="/settings/four-week-position"' in body
        assert "First" in body and "Second" in body and "Third" in body and "Fourth" in body
        assert resp.context["current_four_week_position"] == 1

    def test_general_page_checks_stored_position(self, conn):
        db.set_app_meta(conn, deps.FOUR_WEEK_POSITION_KEY, "3")
        resp = settings_router.settings_general(_bare_request("/settings/general"), conn=conn)
        assert resp.context["current_four_week_position"] == 3
        body = resp.body.decode()
        assert 'value="3" class="seg-radio" checked' in body

    def test_set_route_stores_position(self, conn):
        resp = settings_router.set_four_week_position(position="4", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/general"
        assert db.get_app_meta(conn, deps.FOUR_WEEK_POSITION_KEY) == "4"

    def test_set_route_rejects_unrecognized_values(self, conn):
        settings_router.set_four_week_position(position="9", conn=conn)
        assert db.get_app_meta(conn, deps.FOUR_WEEK_POSITION_KEY) == "1"

    def test_set_route_rejects_garbage(self, conn):
        settings_router.set_four_week_position(position="banana", conn=conn)
        assert db.get_app_meta(conn, deps.FOUR_WEEK_POSITION_KEY) == "1"
