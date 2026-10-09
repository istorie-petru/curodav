"""Calendar fixes from the 2026-09-25 UI audit
(documentation/plans/ui-audit-2026-09-25.md, C- ids + H-09). Grid-layout
logic (C-18/C-19) is covered in test_grid_layout.py; this file covers the
rendered markup, the colour tokens and the static assets."""

from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.deps import WEEK_START_KEY
from src.routers import calendar as calendar_router
from src.routers import dashboard as dashboard_router

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "templates"


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
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


def _seed_task(conn, uid, due_at, status="active"):
    db.upsert_task(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": status, "due_at": due_at, "tags": [], "created_at": _now()},
    )


def _seed_event(conn, uid, start_at, end_at):
    db.upsert_event(
        conn,
        {
            "uid": uid, "title": uid, "description": "", "start_at": start_at, "end_at": end_at,
            "all_day": False, "status": "active", "tags": [], "created_at": _now(), "updated_at": _now(),
        },
    )


def _luminance(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)




class TestWeekHeader:
    """C-6 / C-23: readable day number, today pill, header links to Day."""

    def test_headers_link_to_day_view_with_unpadded_day_number(self, conn):
        body = calendar_router.week_view(_request("/calendar/week"), date_="2026-10-01", conn=conn).body.decode()
        assert '<a class="thd-link" href="/calendar/day/2026-10-01"' in body
        assert '<span class="thd-dow">Thu</span> <span class="thd-num">1</span>' in body
        assert "Thu 01" not in body



class TestDayHeader:
    """C-17: no duplicate chevron, readable date, Today button."""

    def test_day_header(self, conn):
        body = calendar_router.day_view("2026-09-26", _request("/calendar/day/2026-09-26"), conn=conn).body.decode()
        assert "Sat, Sep 26, 2026" in body
        back = re.search(r'<a class="icon-btn"[^>]*aria-label="Back to Calendar">(.*?)</a>', body, re.S).group(1)
        assert "chevron-left" not in back
        if date.today().isoformat() != "2026-09-26":
            assert 'class="btn ghost btn-sm cal-today-btn"' in body
        assert '<span class="thd-dow">Saturday</span>' in body


class TestAllDayTitlesAndOverdue:
    """C-3 (title span for ellipsis) and C-24 (overdue open tasks not dimmed)."""

    def test_week_task_title_wrapped_and_overdue_marked(self, conn):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        if today == monday:
            pytest.skip("needs a past day inside the current week")
        past = monday.isoformat()
        _seed_task(conn, "open_past", past)
        _seed_task(conn, "done_past", past, status="done")
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert '<span class="allday-title">open_past</span>' in body
        open_tag = re.search(r'<a class="allday-task([^"]*)"[^>]*title="open_past"', body).group(1)
        done_tag = re.search(r'<a class="allday-task([^"]*)"[^>]*title="done_past"', body).group(1)
        assert "is-overdue" in open_tag
        assert "is-overdue" not in done_tag











class TestMiniCalendar:
    """C-13 / C-14 / C-15."""

    def test_week_start_sunday(self, conn):
        db.set_app_meta(conn, WEEK_START_KEY, "sunday")
        data = dashboard_router._render_mini_month_calendar(conn, {})
        assert data["weekday_initials"][0] == "S"
        assert all(date.fromisoformat(w[0]["date"]).weekday() == 6 for w in data["weeks"])

    def test_week_start_monday_default(self, conn):
        data = dashboard_router._render_mini_month_calendar(conn, {})
        assert data["weekday_initials"] == ["M", "T", "W", "T", "F", "S", "S"]
        assert all(date.fromisoformat(w[0]["date"]).weekday() == 0 for w in data["weeks"])









