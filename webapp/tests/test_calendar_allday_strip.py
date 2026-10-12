"""Week/Day all-day strip (2026-08-09) -- all-day events and due tasks were
already computed by week_view/day_view but never rendered (the templates only
showed the hour grid), so they were completely invisible. They now render in a
strip between the day-of-week header and the time-grid-body, both as quiet
text rows (no filled chip background): all-day events carry a small colored
calendar dot (.color-dot cal-*), tasks a square icon, and multi-day all-day
events repeat on every day they span (the same "repeated entry per day"
behavior Month's _month_grid already has)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

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
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _seed_event(conn, uid, start_at, end_at=None, all_day=False, tags=None):
    db.upsert_event(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "start_at": start_at,
            "end_at": end_at,
            "all_day": all_day,
            "status": "active",
            "tags": tags or [],
            "created_at": _now(),
            "updated_at": _now(),
        },
    )


def _seed_task(conn, uid, due_at=None, tags=None):
    db.upsert_task(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "status": "active",
            "due_at": due_at,
            "tags": tags or [],
            "created_at": _now(),
        },
    )


class TestWeekViewStrip:
    def test_all_day_lives_in_the_sidebar_not_the_grid(self, conn):
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert "time-grid-top" in body
        assert "time-grid-allday" not in body
        assert 'data-notebook-sidebar-panel="allday"' in body
        assert "All day" in body

    def test_sidebar_groups_items_by_day(self, conn):
        monday = _this_monday()
        for i in (0, 2):
            _seed_task(conn, f"t{i}", due_at=(monday + timedelta(days=i)).isoformat())
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert len(re.findall(r'class="sidebar-allday-day', body)) == 2

    def test_single_day_event_only_lands_in_its_own_column(self, conn):
        monday = _this_monday()
        target = (monday + timedelta(days=3)).isoformat()  # Thursday
        _seed_event(conn, "thu", start_at=f"{target}T00:00:00", end_at=f"{target}T23:59:00", all_day=True)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        # Exactly one day's cell carries it, and it's the Thursday one.
        hits = [(i, day["iso"]) for i, day in enumerate(resp.context["days"]) if any(e["uid"] == "thu" for e in day["all_day"])]
        assert len(hits) == 1
        assert hits[0][1] == target

    def test_task_only_lands_in_its_due_day_column(self, conn):
        monday = _this_monday()
        due = (monday + timedelta(days=2)).isoformat()  # Wednesday
        _seed_task(conn, "wed_task", due_at=due)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        hits = [(i, day["iso"]) for i, day in enumerate(resp.context["days"]) if any(t["uid"] == "wed_task" for t in day["tasks"])]
        assert len(hits) == 1
        assert hits[0][1] == due


    def test_all_day_event_renders_in_the_sidebar(self, conn):
        monday = _this_monday()
        iso = monday.isoformat()
        _seed_event(conn, "allday1", start_at=f"{iso}T00:00:00", end_at=f"{iso}T23:59:00", all_day=True)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert "sidebar-allday-row" in body
        assert "/events/allday1" in body
        assert {e["uid"] for e in resp.context["days"][0]["all_day"]} == {"allday1"}

    def test_multiday_all_day_event_is_listed_on_every_day_it_spans(self, conn):
        monday = _this_monday()
        d1 = (monday + timedelta(days=1)).isoformat()
        d3 = (monday + timedelta(days=3)).isoformat()
        _seed_event(conn, "trip", start_at=f"{d1}T00:00:00", end_at=f"{d3}T23:59:00", all_day=True)
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert body.count("/events/trip") == 3

    def test_no_bars_means_no_bar_layer_or_spacer(self, conn):
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert 'class="week-allday-bars"' not in body
        assert 'class="week-bars-spacer' not in body

    def test_all_day_event_stays_out_of_timed_grid(self, conn):
        monday = _this_monday()
        iso = monday.isoformat()
        _seed_event(conn, "allday2", start_at=f"{iso}T00:00:00", end_at=f"{iso}T23:59:00", all_day=True)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        timed_uids = {e["uid"] for day in resp.context["days"] for e in day["timed"]}
        assert "allday2" not in timed_uids

    def test_multiday_all_day_event_repeats_every_day_it_spans(self, conn):
        monday = _this_monday()
        d1 = (monday + timedelta(days=1)).isoformat()
        d2 = (monday + timedelta(days=2)).isoformat()
        _seed_event(conn, "trip", start_at=f"{d1}T00:00:00", end_at=f"{d2}T23:59:00", all_day=True)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        per_day = [len([e for e in day["all_day"] if e["uid"] == "trip"]) for day in resp.context["days"]]
        assert per_day.count(1) == 2  # exactly day 1 and day 2

    def test_task_renders_in_strip(self, conn):
        monday = _this_monday()
        iso = monday.isoformat()
        _seed_task(conn, "t1", due_at=iso)
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert "sidebar-allday-row" in body
        assert "t1" in body


class TestDayViewStrip:
    def test_template_has_strip_headers(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        assert "time-grid-top" in body
        assert "time-grid-allday day" in body
        assert 'class="allday-cols day"' in body
        assert ">All day<" in body

    def test_all_day_event_and_task_render(self, conn):
        today_iso = date.today().isoformat()
        _seed_event(conn, "d_allday", start_at=f"{today_iso}T00:00:00", end_at=f"{today_iso}T23:59:00", all_day=True)
        _seed_event(conn, "d_timed", start_at=f"{today_iso}T09:00:00", end_at=f"{today_iso}T10:00:00", all_day=False)
        _seed_task(conn, "d_task", due_at=today_iso)
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        assert {e["uid"] for e in resp.context["all_day"]} == {"d_allday"}
        assert {t["uid"] for t in resp.context["tasks"]} == {"d_task"}
        assert "d_allday" in body
        assert "d_task" in body
        assert "allday-chip" not in body
        assert 'class="color-dot cal-blue"' in body

    def test_multiday_all_day_event_spanning_into_today_still_shows(self, conn):
        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        _seed_event(
            conn, "span", start_at=f"{yesterday}T00:00:00", end_at=f"{today.isoformat()}T23:59:00", all_day=True
        )
        resp = calendar_router.day_view(today.isoformat(), _request(f"/calendar/day/{today.isoformat()}"), conn=conn)
        assert {e["uid"] for e in resp.context["all_day"]} == {"span"}
