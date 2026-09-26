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
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


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


class TestEventColourContrast:
    """C-12: every --cal-bg-*/--cal-fg-* pair clears WCAG AA 4.5:1."""

    def test_all_sixteen_swatches_pass_aa(self):
        pairs = re.findall(r"--cal-bg-(\w+):(#[0-9a-f]{6});\s*--cal-fg-\1:(#[0-9a-f]{6})", CSS)
        assert len(pairs) == 16
        for name, bg, fg in pairs:
            assert _ratio(bg, fg) >= 4.5, (name, bg, fg, round(_ratio(bg, fg), 2))

    def test_event_time_line_is_full_opacity(self):
        rule = re.search(r"\.time-event \.te-time\{([^}]*)\}", CSS).group(1)
        assert "opacity" not in rule


class TestWeekHeader:
    """C-6 / C-23: readable day number, today pill, header links to Day."""

    def test_headers_link_to_day_view_with_unpadded_day_number(self, conn):
        body = calendar_router.week_view(_request("/calendar/week"), date_="2026-10-01", conn=conn).body.decode()
        assert '<a class="thd-link" href="/calendar/day/2026-10-01"' in body
        assert '<span class="thd-dow">Thu</span> <span class="thd-num">1</span>' in body
        assert "Thu 01" not in body

    def test_today_header_is_marked(self, conn):
        body = calendar_router.week_view(_request("/calendar/week"), conn=conn).body.decode()
        assert 'aria-current="date"' in body
        assert ".time-grid-head .thd.is-today .thd-num{background:var(--accent)" in CSS


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

    def test_css_dims_rows_but_not_overdue(self):
        assert ".allday-col.is-past > :not(.is-overdue){opacity:.5;}" in CSS
        assert ".month-day-cell.is-past{opacity" not in CSS
        assert ".month-day-cell.is-past .month-day-bottom > :not(.is-overdue)" in CSS


class TestShortAndCascadedEvents:
    """C-18/C-19 markup hooks."""

    def test_short_event_gets_is_short(self, conn):
        _seed_event(conn, "short", "2026-09-26T09:00:00", "2026-09-26T09:30:00")
        body = calendar_router.day_view("2026-09-26", _request("/calendar/day/2026-09-26"), conn=conn).body.decode()
        assert re.search(r'class="time-event cal-\w+ is-short" data-uid="short"', body)
        assert ".time-event.is-short{display:flex;" in CSS


class TestNowLineAndAutoScroll:
    """C-7: calendar_now.js loaded on Week and Day."""

    def test_script_included(self):
        for name in ("calendar_week.html", "calendar_day.html"):
            assert "static_url('calendar_now.js')" in (TEMPLATES / name).read_text(encoding="utf-8")
        js = (STATIC / "calendar_now.js").read_text(encoding="utf-8")
        assert "now-line" in js and "FALLBACK_HOUR = 7" in js
        assert ".now-line{" in CSS


class TestOverflowPopover:
    """C-10: "+N more" is an anchored popover, not a toast."""

    def test_js_builds_popover_not_toast(self):
        js = (STATIC / "calendar_month_overflow.js").read_text(encoding="utf-8")
        assert "ccToast(" not in js
        for needle in ('role", "dialog"', "Open day", "Escape", "is-sheet", "trigger.focus()"):
            assert needle in js, needle
        assert ".cal-popover{" in CSS and ".cal-popover.is-sheet{" in CSS

    def test_template_carries_date_title_and_rows(self):
        for name in ("_calendar_month_grid.html", "_calendar_fourweek_grid.html"):
            tpl = (TEMPLATES / name).read_text(encoding="utf-8")
            assert 'data-title="{{ day.date.strftime' in tpl
            assert 'data-day-url="/calendar/day/{{ day.iso }}' in tpl
            assert "day.rows + day.overflow" in tpl
            assert 'class="cal-pop-time"' in tpl


class TestPlannerPanel:
    """C-9 / C-20."""

    def test_panel_heights(self):
        assert "#unscheduled-panel-body{height:24px;}" in CSS
        assert "#unscheduled-panel-body{height:auto; max-height:80px;" in CSS


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

    def test_today_and_dots_use_visible_tokens(self):
        assert ".mini-cal-day.is-today .mini-cal-day-num{background:var(--accent);" in CSS
        dot = re.search(r"\.mini-cal-day\.has-activity \.mini-cal-day-num::after\{([^}]*)\}", CSS).group(1)
        assert "var(--fg-tertiary)" in dot
        assert ".month-day-cell.is-today .month-day-num span{background:var(--accent);" in CSS


class TestAgendaWidget:
    """C-16 / H-09."""

    def test_week_overview_columns_and_event_time(self):
        assert ".week-overview-grid{grid-template-columns:repeat(7,minmax(0,1fr));}" in CSS
        tpl = (TEMPLATES / "_widget_agenda.html").read_text(encoding="utf-8")
        assert tpl.index("{% for e in day.events %}") < tpl.index("{% for t in day.tasks %}")
        assert '<span class="wo-time">' in tpl

    def test_habit_rows_match_task_rows(self):
        tpl = (TEMPLATES / "_widget_agenda.html").read_text(encoding="utf-8")
        assert 'aria-label="Log one more: {{ h.title }}' in tpl
        assert ".agenda-habits .agenda-habit-title{font-size:13px;}" in CSS
        assert ".agenda-habit > .form-inline{flex:none; width:36px;" in CSS


class TestEventFormAllDay:
    """C-22."""

    def test_picker_summary_knows_all_day(self):
        js = (STATIC / "datetime_picker.js").read_text(encoding="utf-8")
        assert '" · All day"' in js
        assert 'input[name="all_day"][type="checkbox"]' in js


class TestPhoneAutoScroll:
    """2026-09-25, Peter: "phones need the correct scroll" (C-7 on <=720px):
    the window scrolls to the same target as desktop, once per load, and
    the day-name header pins to the viewport instead of scrolling away."""

    def test_script_scrolls_the_window_once_when_the_grid_is_not_a_scroll_box(self):
        script = (STATIC / "calendar_now.js").read_text()
        assert "if (windowScrolled || window.scrollY > 0) return;" in script
        assert "window.scrollTo(0, Math.max(0, colPageTop - stickyH + targetPx(root) - 12));" in script
        subprocess.run(["node", "--check", str(STATIC / "calendar_now.js")], check=True)

    def test_calendar_containers_stop_clipping_on_phones_so_the_header_sticks(self):
        css = (STATIC / "style.css").read_text()
        assert (
            "@media (max-width:720px){\n  main.main-calendar,\n  main.main-calendar .calendar-viewport,\n"
            "  main.main-calendar .time-grid-wrap{overflow:visible;}\n}"
        ) in css


def test_datetime_picker_follows_week_start_setting():
    # 2026-09-25: the picker's own month grid was hardcoded Monday-first.
    script = (STATIC / "datetime_picker.js").read_text()
    assert 'document.body.dataset.weekStart === "sunday"' in script
    assert "return SUNDAY_FIRST ? dow : (dow + 6) % 7;" in script
    base = (STATIC.parent / "templates" / "base.html").read_text()
    assert 'data-week-start="{{ week_start(request) }}"' in base
    subprocess.run(["node", "--check", str(STATIC / "datetime_picker.js")], check=True)
