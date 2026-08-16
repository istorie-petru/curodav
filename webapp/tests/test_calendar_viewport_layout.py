"""Calendar "fit the page" layout + Day/Agenda merge (2026-08-08), direct
feedback: "make the calendar month view fit the page, with a slight
resize... week view to fit the page and be scrollable... merge the day
and agenda view in a side by side manner, both independently scrollable"
then "make day-agenda-split calendar-viewport scrollable like the
calendar week view. Remove the agenda at the bottom of the calendar day
view".

Covers: the CSS hooks (.calendar-viewport/.month-viewport) actually land
in each template's markup, the segmented nav drops the Agenda tab
everywhere (Month/Week/Day), the day view is a single-pane scrollable
grid carrying NO agenda data anymore, and GET /calendar/agenda redirects
instead of rendering its own page."""

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
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


class TestAgendaRedirect:
    def test_redirects_to_today_on_day(self, conn):
        resp = calendar_router.agenda_view()
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/day/{date.today().isoformat()}"

    def test_preserves_label_filter(self, conn):
        resp = calendar_router.agenda_view(label="Work")
        assert resp.headers["location"] == f"/calendar/day/{date.today().isoformat()}?label=Work"

    def test_takes_no_request_or_conn(self):
        # It never renders a template or touches the database anymore --
        # a pure redirect shouldn't need either.
        import inspect

        params = inspect.signature(calendar_router.agenda_view).parameters
        assert "request" not in params
        assert "conn" not in params


class TestDayViewNoLongerCarriesAgendaData:
    def test_context_has_no_agenda_days_or_window(self, conn):
        # 2026-08-08: the agenda pane was removed from Day (feedback:
        # "remove the agenda at the bottom of the calendar day view") --
        # _build_agenda_days is gone, so neither context key may exist.
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        assert "agenda_days" not in resp.context
        assert "agenda_window_end" not in resp.context

    def test_body_has_no_agenda_pane(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        assert "agenda-pane" not in body
        assert "day-agenda-split" not in body


class TestViewportCssHooks:
    def test_month_view_has_viewport_classes(self, conn):
        resp = calendar_router.month_view(_request("/calendar"), year=2026, month=8, conn=conn)
        body = resp.body.decode()
        assert 'class="card calendar-viewport month-viewport"' in body

    def test_week_view_has_viewport_class(self, conn):
        # 1.9 side work: Week merged with the former Timetable sub-view, so
        # the grid card now also carries `.project-calendar-grid` (the
        # scheduling-surface class) alongside `.calendar-viewport`.
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert 'class="card calendar-viewport project-calendar-grid"' in body

    def test_day_view_has_single_viewport_class(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        # Day is now the same single-pane scrollable calendar-viewport as
        # Week -- no day-pane/agenda-pane split anymore.
        assert 'class="card calendar-viewport"' in body
        assert 'day-agenda-split' not in body


class TestAgendaTabRemovedFromSegmentedNav:
    def test_month_view_nav_has_no_agenda_tab(self, conn):
        resp = calendar_router.month_view(_request("/calendar"), year=2026, month=8, conn=conn)
        body = resp.body.decode()
        assert ">Month<" in body and ">Week<" in body and ">Day<" in body
        assert ">Agenda<" not in body
        assert "/calendar/agenda" not in body

    def test_week_view_nav_has_no_agenda_tab(self, conn):
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert ">Agenda<" not in body
        assert "/calendar/agenda" not in body

    def test_day_view_nav_has_no_agenda_tab(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        assert ">Agenda<" not in body
        assert "/calendar/agenda" not in body


class TestCalendarAgendaTemplateRemoved:
    def test_calendar_agenda_html_no_longer_exists(self):
        from pathlib import Path

        templates_dir = Path(__file__).resolve().parent.parent / "src" / "templates"
        assert not (templates_dir / "calendar_agenda.html").exists()
