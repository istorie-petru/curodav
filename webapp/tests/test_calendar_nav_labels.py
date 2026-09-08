"""FullCalendar-parity interactions slice 6 (plans/open.md's "Calendar:
FullCalendar-parity interactions" section, final slice of the arc, see
plans/STATE.md's own entry): live month/week label + AJAX prev/next nav for
4-Week and Week, replacing the old full-page-reload `<a href>` links. Month
is deliberately NOT covered here -- confirmed before building that
`month_view` has no route decorator any more (routers/calendar.py's
`calendar_root_redirect` retired it, "/calendar" always redirects to
"/calendar/fourweek"), so there is no reachable page to wire AJAX nav onto;
`_calendar_month_grid.html`/`_month_view_context` stay untouched.

Open decision (Week's visible label: ISO week number vs. a date range) was
settled via direct AskUserQuestion answer before writing any code: date
range, matching FullCalendar's own default. 4-Week's label follows the same
date-range convention (its own sr-only <h1> used to be a static "4-Week
View" string with no date info at all -- this now gives it a real one).

Covers: `label_text` in both view contexts (and that it's the single value
driving the sr-only <h1>, the visible `#cal-nav-label` span, and the async
region fragment's `data-label-text`, so none of the three can drift), the
grid partials' new `data-prev`/`data-next` attributes, and -- same "no JS
unit-test harness for static/*.js in this repo" gap every prior JS-only
calendar slice's own test file already notes -- `node --check` plus source
greps pinning async_calendar.js's new `bindCalNav` (click interception,
`history.pushState`, the `popstate` listener, and the dataset-driven
label/href update) so a future refactor can't silently drop any of it."""

from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "templates"


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _bare_request(path="/calendar/fourweek"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


class TestFourWeekLabelText:
    def test_context_has_label_text_as_a_date_range(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        ctx = resp.context
        expected = f"{ctx['view_start'].strftime('%b %d')} – {ctx['view_end'].strftime('%b %d, %Y')}"
        assert ctx["label_text"] == expected

    def test_label_text_moves_with_the_window(self, conn):
        first = calendar_router.four_week_view(_bare_request(), conn=conn)
        next_anchor = first.context["next_start"]
        second = calendar_router.four_week_view(_bare_request(), date_=next_anchor, conn=conn)
        assert second.context["label_text"] != first.context["label_text"]
        expected = f"{second.context['view_start'].strftime('%b %d')} – {second.context['view_end'].strftime('%b %d, %Y')}"
        assert second.context["label_text"] == expected

    def test_sr_only_h1_and_visible_label_share_the_same_text(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        body = resp.body.decode()
        label_text = resp.context["label_text"]
        assert f'<h1 class="sr-only">{label_text}</h1>' in body
        assert f'<span class="cal-nav-label" id="cal-nav-label" aria-live="polite">{label_text}</span>' in body

    def test_nav_links_carry_cal_nav_classes(self, conn):
        resp = calendar_router.four_week_view(_bare_request(), conn=conn)
        body = resp.body.decode()
        assert 'class="icon-btn cal-nav-prev"' in body
        assert 'class="icon-btn cal-nav-next"' in body

    def test_region_fragment_carries_label_text_and_prev_next(self, conn):
        resp = calendar_router.calendar_regions(_bare_request("/calendar/regions"), region="fourweek", conn=conn)
        body = resp.body.decode()
        ctx = resp.context
        assert f'data-label-text="{ctx["label_text"]}"' in body
        assert f'data-prev="{ctx["prev_start"]}"' in body
        assert f'data-next="{ctx["next_start"]}"' in body


class TestWeekLabelText:
    def test_context_has_label_text_as_a_date_range(self, conn):
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        ctx = resp.context
        expected = f"{ctx['monday'].strftime('%b %d')} – {ctx['sunday'].strftime('%b %d, %Y')}"
        assert ctx["label_text"] == expected

    def test_label_text_matches_the_old_sr_only_h1_format(self, conn):
        # 2026-09-09 (slice 4/5 entries, STATE.md): the sr-only <h1> used to
        # build this inline as `{{ monday.strftime('%b %d') }} &ndash;
        # {{ sunday.strftime('%b %d, %Y') }}` -- label_text now supplies the
        # exact same text from one place instead.
        monday = date(2026, 8, 10)
        resp = calendar_router.week_view(_bare_request("/calendar/week"), date_=monday.isoformat(), conn=conn)
        sunday = resp.context["sunday"]
        assert resp.context["label_text"] == f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"

    def test_sr_only_h1_and_visible_label_share_the_same_text(self, conn):
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        label_text = resp.context["label_text"]
        assert f'<h1 class="sr-only">{label_text}</h1>' in body
        assert f'<span class="cal-nav-label" id="cal-nav-label" aria-live="polite">{label_text}</span>' in body

    def test_nav_links_carry_cal_nav_classes(self, conn):
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        body = resp.body.decode()
        assert 'class="icon-btn cal-nav-prev"' in body
        assert 'class="icon-btn cal-nav-next"' in body

    def test_region_fragment_carries_label_text_and_prev_next(self, conn):
        resp = calendar_router.calendar_regions(_bare_request("/calendar/regions"), region="week", conn=conn)
        body = resp.body.decode()
        ctx = resp.context
        assert f'data-label-text="{ctx["label_text"]}"' in body
        assert f'data-prev="{ctx["prev_week"]}"' in body
        assert f'data-next="{ctx["next_week"]}"' in body


class TestMonthUntouched:
    """Confirms the deliberate scoping decision above -- Month's own
    context/template gained no label_text/data-prev/data-next, since it has
    no reachable page to use them on."""

    def test_month_context_has_no_label_text(self, conn):
        resp = calendar_router.month_view(_bare_request("/calendar"), conn=conn)
        assert "label_text" not in resp.context

    def test_month_grid_partial_has_no_prev_next_data_attrs(self):
        html = (_TEMPLATES_DIR / "_calendar_month_grid.html").read_text()
        assert "data-prev=" not in html
        assert "data-next=" not in html
        assert "data-label-text=" not in html


class TestCalNavScriptStructural:
    """No JS unit-test harness for static/*.js in this repo (same recurring
    gap every prior JS-only calendar slice's own test file notes) --
    verified via `node --check` (syntax) plus source greps pinning the
    specific behaviors bindCalNav must have."""

    def test_async_calendar_js_syntax_is_valid(self):
        subprocess.run(["node", "--check", str(_STATIC_DIR / "async_calendar.js")], check=True)

    def test_bind_cal_nav_is_wired_for_fourweek_and_week_only(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert 'bindCalNav("fourweek-grid", "/calendar/fourweek", refreshFourweek);' in script
        assert 'bindCalNav("week-grid", "/calendar/week", refreshWeek);' in script
        # Month deliberately excluded -- no bindCalNav call anywhere inside
        # its own #month-grid block specifically (bindCalNav's own
        # definition legitimately appears earlier in the file, shared by
        # the two blocks that do call it).
        month_block = script.split('var regionEl = document.getElementById("month-grid");')[1].split(
            'var fourweekEl = document.getElementById("fourweek-grid");'
        )[0]
        assert "bindCalNav(" not in month_block

    def test_nav_click_is_intercepted_not_a_real_navigation(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert 'document.querySelector(".cal-nav-prev")' in script
        assert 'document.querySelector(".cal-nav-next")' in script
        assert "e.preventDefault();" in script

    def test_url_is_pushed_after_a_successful_nav_swap(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert "window.history.pushState(" in script

    def test_back_forward_are_wired_via_popstate(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert 'window.addEventListener("popstate"' in script

    def test_failed_nav_falls_back_to_a_real_navigation(self):
        # Same "converge to server truth" fallback every other refresh
        # failure in this file already takes.
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert "window.location.href = pageBase" in script

    def test_dataset_driven_label_and_href_update_after_swap(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert "gridEl.dataset.prev" in script
        assert "gridEl.dataset.next" in script
        assert "gridEl.dataset.labelText" in script
        assert "labelEl.textContent = gridEl.dataset.labelText;" in script

    def test_refresh_fourweek_and_week_accept_a_date_override(self):
        # Both refresh functions must support a caller-supplied date (the
        # nav path) while still defaulting to the region's own current
        # data-date (the pre-existing mutation-refresh call site).
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert "function refreshFourweek(dateVal) {" in script
        assert "function refreshWeek(dateVal) {" in script
        assert 'var d = dateVal != null ? dateVal : fourweekEl.dataset.date || "";' in script
        assert 'var d = dateVal != null ? dateVal : weekEl.dataset.date || "";' in script
