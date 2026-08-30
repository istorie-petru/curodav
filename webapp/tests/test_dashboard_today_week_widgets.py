"""Tests for the 1.9 side-work "port /today and /week into the Dashboard"
slice (plans/STATE.md): the scheduled_work_today widget type
(routers/dashboard.py; important_urgent was a second such type, removed
outright along with the rest of the Importance/Urgency feature -- see
src/derived_state.py's module docstring; quick_links was a third, retired
2026-08-30 and merged into spaces_projects' own cards style -- see
test_dashboard_router.py::TestSpacesProjectsCardsIncludesProjects), the
/today and /week redirects, and the widget-partial double-line date+time
audit fix."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src import db
from src.routers import calendar as calendar_router
from src.routers import dashboard as dashboard_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, due_at=None, tags=None, status="active"):
    db.upsert_task(conn, {
        "uid": uid,
        "title": uid, "description": "", "status": status, "due_at": due_at,
        "tags": list(tags or []), "created_at": _now(),
    })


def _seed_event(conn, uid, start_at=None, end_at=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": "active", "all_day": 0,
        "start_at": start_at, "end_at": end_at,
        "tags": tags or [], "created_at": _now(),
    })


class TestScheduledWorkTodayWidget:
    def test_sums_todays_work_allocation_hours(self, conn):
        today_iso = date.today().isoformat()
        _seed_task(conn, "t1")
        start = f"{today_iso}T09:00:00"
        end = f"{today_iso}T10:30:00"
        _seed_event(conn, "ev1", start_at=start, end_at=end)
        db.create_work_allocation(conn, "t1", start, end)
        data = dashboard_router._render_scheduled_work_today(conn, {})
        assert data["total_hours"] == 1.5
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["task"]["uid"] == "t1"

    def test_ignores_ordinary_events_and_other_days(self, conn):
        today_iso = date.today().isoformat()
        tomorrow_iso = (date.today() + timedelta(days=1)).isoformat()
        _seed_event(conn, "plain_today", start_at=f"{today_iso}T09:00:00", end_at=f"{today_iso}T10:00:00")
        _seed_task(conn, "t1")
        start = f"{tomorrow_iso}T09:00:00"
        end = f"{tomorrow_iso}T10:00:00"
        _seed_event(conn, "ev_tomorrow", start_at=start, end_at=end)
        db.create_work_allocation(conn, "t1", start, end)
        data = dashboard_router._render_scheduled_work_today(conn, {})
        assert data["sessions"] == []
        assert data["total_hours"] == 0.0

    def test_respects_tag_filter(self, conn):
        today_iso = date.today().isoformat()
        _seed_task(conn, "t1")
        start, end = f"{today_iso}T09:00:00", f"{today_iso}T10:00:00"
        _seed_event(conn, "ev1", start_at=start, end_at=end, tags=["Uni"])
        db.create_work_allocation(conn, "t1", start, end)
        db.set_object_labels(conn, "event", "ev1", ["Uni"])
        data = dashboard_router._render_scheduled_work_today(conn, {"tags": ["Other"]})
        assert data["sessions"] == []

    def test_registered_in_widget_types(self):
        spec = dashboard_router.WIDGET_TYPES["scheduled_work_today"]
        assert spec["template"] == "_widget_scheduled_work_today.html"
        assert spec["render"] is dashboard_router._render_scheduled_work_today


class TestNewWidgetsAddableThroughBuilder:
    def test_scheduled_work_addable_via_source_view(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="scheduled_work_view", range="", title="",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["type"] == "scheduled_work_today"

    def test_selection_round_trips_for_each_new_type(self):
        for wtype in ("scheduled_work_today",):
            source, view, range_ = dashboard_router._selection_from_widget({"type": wtype, "config": {}})
            resolved_type, resolved_range = dashboard_router._resolve_selection(source, view, range_)
            assert resolved_type == wtype


class TestTodayAndWeekRetiredAsRedirects:
    def test_today_redirects_to_dashboard(self):
        resp = dashboard_router.today_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"

    def test_week_redirects_to_calendar_week(self):
        resp = calendar_router.week_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/calendar/week"

    def test_week_redirect_preserves_date(self):
        resp = calendar_router.week_redirect(date_="2026-08-17")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/calendar/week?date_=2026-08-17"

    def test_today_and_week_no_longer_have_a_tabbar_entry(self):
        import pathlib
        base = pathlib.Path(__file__).resolve().parents[1] / "src" / "templates" / "base.html"
        source = base.read_text()
        assert 'data-tab="today"' not in source
        assert 'data-tab="week"' not in source
        # The redirects themselves must still exist somewhere real, just
        # not as a tabbar destination any more.
        assert 'href="/today"' not in source
        assert 'href="/week"' not in source

    def test_today_and_week_routers_are_gone(self):
        import pathlib
        routers_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "routers"
        assert not (routers_dir / "today.py").exists()
        assert not (routers_dir / "week.py").exists()


class TestUpcomingEventsDoubleLineFix:
    def test_date_time_column_is_wide_enough_and_nowraps(self):
        # Structural check (no browser to measure real wrapping) -- same
        # ceiling this app's other CSS-shape tests already accept.
        # 2026-08-17 widget uniformity pass: the nowrap fix moved out of an
        # inline `width:150px` td into the shared `.widget-row-time` class
        # (style.css) the widget_link_row macro attaches, so the event-time
        # column can no longer wrap to two lines -- assert the class exists
        # in the CSS and the agenda template actually uses it.
        import pathlib
        templates = pathlib.Path(__file__).resolve().parents[1] / "src" / "templates"
        css = (templates.parent / "static" / "style.css").read_text()
        assert ".widget-row-time{white-space:nowrap;}" in css
        partial = (templates / "_widget_agenda.html").read_text()
        assert "leading_class='widget-row-time'" in partial
        assert "width:110px" not in partial
        # no widget should hand-roll a fixed-width cell any more (the
        # spaces_projects progress fill's `style="width:{{ ... }}%"` is a
        # dynamic value, not a fixed column, so only flag fixed pixels)
        import re
        for name in templates.glob("_widget_*.html"):
            text = name.read_text()
            assert not re.search(r'style="width:\s*\d', text), f"{name.name} still hand-rolls a width"
            assert "width:150px" not in text, f"{name.name} still has the old fixed-width cell"
