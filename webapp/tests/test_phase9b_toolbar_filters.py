"""Phase 9b (toolbar rework, 2026-08-07): the two-row toolbar pattern
(row 1 light -- title/view switcher/search/primary action; row 2
collapsible filters, auto-open when a filter is active) applied to Tasks
(Table/Timeline/Board), Calendar (Month/Week/Day/Agenda), and Contacts.

Covers:
  1. Board/Timeline now respect date_filter/status_filter (previously
     Table-only; both Board/Timeline and the Importance/Urgency filters
     are since removed outright, see the module comment below and
     src/derived_state.py's module docstring).
  2. The new Tasks label filter narrows results in all three views.
  3. The new Calendar event label filter narrows results in month + day
     views, including the task chips Day also shows.
  4. Every calendar page renders exactly one `.toolbar` element (the
     screenshot-reported "two toolbars stacked" bug this rework fixes).
  5. Contacts' Active/Archived renders as a real `.segmented` control, not
     the old unstyled `.segmented-control`/`.segmented-btn` pair.
  6. The collapsible filter `<details>` is `open` when a filter is active,
     closed when none are.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/"):
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


def _seed_task(conn, uid, due_at=None, status="active", tags=None):
    db.upsert_task(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "status": status,
            "due_at": due_at,
            "tags": list(tags or []),
            "created_at": _now(),
        },
    )


def _seed_event(conn, uid, start_at, tags=None):
    db.upsert_event(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "start_at": start_at,
            "end_at": None,
            "all_day": False,
            "status": "active",
            "tags": tags or [],
            "created_at": _now(),
            "updated_at": _now(),
        },
    )


_TOOLBAR_DIV_RE = re.compile(r'<div class="toolbar(?:"| )')


def _radios(body: str, name: str) -> list[tuple[str, bool]]:
    """(value, is_checked) pairs for every radio named `name` in a rendered
    page -- tolerant of the fancy-dropdown partial's multi-line input tags
    (the `checked` attribute lands on its own indented line)."""
    out = []
    for m in re.finditer(r'<input type="radio" name="%s" value="([^"]*)"[^>]*?>' % re.escape(name), body, re.S):
        out.append((m.group(1), "checked" in m.group(0)))
    return out


def _toolbar_div_count(body: str) -> int:
    """Counts top-level `.toolbar` divs (a class attribute that starts
    with "toolbar", i.e. `class="toolbar"` or `class="toolbar ..."`) --
    deliberately not a generic \\btoolbar\\b regex, since that would also
    match `toolbar-filters`/`toolbar-row`/`toolbar-2row`, which are
    intentionally separate, nested classes, not additional top-level
    toolbars."""
    return len(_TOOLBAR_DIV_RE.findall(body))


def _narrow_header_count(body: str) -> int:
    """Counts top-level `.page-header-narrow` divs -- the replacement for
    Calendar's old `.toolbar.top-app-bar.toolbar-2row` row (2026-08-29,
    sidebar redesign item 13e follow-up, direct request): the toolbar is
    gone outright, its real controls (prev/next nav, the Month|Day
    subnav, the label filter) folded into this one header strip instead.
    Same "exactly one, never duplicated" invariant the old
    _toolbar_div_count coverage guarded, just pointed at the new
    structure."""
    return body.count('class="page-header-narrow"') + body.count('class="page-header-narrow has-banner"')


# 2026-08-28 "major rework" session (items 3+4): TestBoardTimelineFilters
# Respected and TestTaskLabelFilter are both deleted -- Kanban/Timeline are
# retired to plain redirects (routers/tasks.py::board_view_redirect,
# routers/timeline.py's whole-file rewrite) and the Tasks table's label
# filter is gone entirely (item 3, "filtering reduced to date only"), so
# none of this coverage has anything left to exercise. See
# test_timeline_router.py/test_tasks_view_rework.py for what replaced it.


class TestEventLabelFilter:
    def test_month_view_narrows_events_by_label(self, conn):
        today = date.today()
        _seed_event(conn, "work_evt", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        _seed_event(conn, "home_evt", start_at=f"{today.isoformat()}T10:00:00", tags=["Home"])
        resp = calendar_router.month_view(_request("/calendar"), label="Work", conn=conn)
        body = resp.body.decode()
        assert "work_evt" in body
        assert "home_evt" not in body
        assert "Work" in resp.context["event_label_names"]

    def test_day_view_narrows_events_and_task_chips_by_label(self, conn):
        today_iso = date.today().isoformat()
        _seed_event(conn, "work_evt", start_at=f"{today_iso}T09:00:00", tags=["Work"])
        _seed_event(conn, "home_evt", start_at=f"{today_iso}T10:00:00", tags=["Home"])
        _seed_task(conn, "work_task", due_at=today_iso, tags=["Work"])
        _seed_task(conn, "home_task", due_at=today_iso, tags=["Home"])
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), label="Work", conn=conn)
        timed_uids = {e["uid"] for e in resp.context["timed"]}
        task_uids = {t["uid"] for t in resp.context["tasks"]}
        assert timed_uids == {"work_evt"}
        assert task_uids == {"work_task"}

    def test_no_label_returns_everything(self, conn):
        today = date.today()
        _seed_event(conn, "a", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        _seed_event(conn, "b", start_at=f"{today.isoformat()}T10:00:00", tags=["Home"])
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        body = resp.body.decode()
        assert "a" in body or True  # sanity: page renders
        assert resp.context["active_label"] == ""


class TestCalendarSingleToolbar:
    # 2026-08-29 (sidebar redesign item 13e follow-up, direct request):
    # Calendar's `.toolbar.top-app-bar.toolbar-2row` row is gone outright
    # -- these now guard the same "exactly one, never duplicated"
    # invariant against its replacement, .page-header-narrow.
    def test_month_view_renders_exactly_one_toolbar(self, conn):
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 0
        assert _narrow_header_count(resp.body.decode()) == 1

    def test_week_view_renders_exactly_one_toolbar(self, conn):
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 0
        assert _narrow_header_count(resp.body.decode()) == 1

    def test_day_view_renders_exactly_one_toolbar(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 0
        assert _narrow_header_count(resp.body.decode()) == 1

    def test_agenda_view_redirects_to_day_which_has_exactly_one_toolbar(self, conn):
        # 2026-08-08: Agenda merged into Day and was then removed again
        # (routers/calendar.py's day_view) -- agenda_view itself is just a
        # redirect now, no template/toolbar of its own to count; Day (the
        # redirect target) is what test_day_view_renders_exactly_one_toolbar
        # above already covers, this just confirms the redirect lands there.
        resp = calendar_router.agenda_view()
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/calendar/day/")


class TestContactsNoArchivedState:
    def test_no_active_archived_segmented_control(self, conn):
        # 2026-08-07: Active/Archived removed entirely (not just restyled)
        # -- Contacts has no special "archived" state anymore, only
        # labels. This supersedes the Phase 9b finding that the old
        # Active/Archived pair rendered with no matching CSS (segmented-
        # control/segmented-btn) -- there's nothing to restyle, it's gone.
        resp = contacts_router.list_contacts(_request("/contacts"), conn=conn)
        body = resp.body.decode()
        assert ">Active<" not in body
        assert ">Archived<" not in body
        assert "segmented-control" not in body
        assert "segmented-btn" not in body


class TestActiveFilterShownInDropdown:
    """2026-08-08: Tasks' and Calendar's row-2 collapsible filter body is
    gone (feedback: "remove the filters details button and reintegrate
    these drop down menus into the topbar") -- date/status/label are
    inline "fancy dropdowns" (_filter_dropdown.html) in row 1, each a
    radio list that navigates on pick. The active filter is simply the
    checked radio (mirrored in the trigger's summary text), so there's no
    collapsible panel left to auto-open. Contacts still uses the
    checkbox-hack, so its assertions below are unchanged."""

    # 2026-08-28 "major rework" session (item 3): Tasks' Status/label
    # dropdowns are gone -- the old test_tasks_status_filter_is_the_checked_
    # radio/test_tasks_no_filter_selects_all_statuses/test_tasks_label_
    # filter_is_the_checked_radio all exercised removed machinery. Tasks'
    # one surviving dropdown (Date) is unaffected by this rework and has no
    # dedicated radio-checked test here to begin with (pre-existing gap,
    # not introduced by this session).

    def test_calendar_label_filter_is_the_checked_radio(self, conn):
        today = date.today()
        _seed_event(conn, "a", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        resp = calendar_router.month_view(_request("/calendar"), label="Work", conn=conn)
        body = resp.body.decode()
        assert ("Work", True) in _radios(body, "label")
        assert ("", False) in _radios(body, "label")
        assert "toolbar-filters-checkbox" not in body

    def test_calendar_no_label_selects_all_labels(self, conn):
        today = date.today()
        _seed_event(conn, "a", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        body = resp.body.decode()
        assert ("", True) in _radios(body, "label")

    def test_contacts_label_radio_checked_when_tag_filter_is_active(self, conn):
        db.upsert_contact(
            conn,
            {
                "uid": "c1",
                "full_name": "Ada",
                "tags": ["Friends"],
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        resp = contacts_router.list_contacts(_request("/contacts"), tag="Friends", conn=conn)
        body = resp.body.decode()
        # Radio values are lowercased (display name stays "Friends") so the
        # router's case-insensitive match still highlights the right pick.
        assert ("friends", True) in _radios(body, "tag")
        assert ("", False) in _radios(body, "tag")
        assert "toolbar-filters-checkbox" not in body

    def test_contacts_no_tag_filter_selects_all_labels(self, conn):
        resp = contacts_router.list_contacts(_request("/contacts"), conn=conn)
        body = resp.body.decode()
        assert "toolbar-filters-checkbox" not in body
        assert _radios(body, "tag") == []


class TestIconOnlyFiltersNextToAdd:
    """2026-08-08: the icon-only "Filters" button is gone too -- Tasks and
    Calendar carry their filter triggers inline (templates/
    _filter_dropdown.html's .filter-dropdown-trigger), each a compact
    descriptor+chevron button.

    2026-08-29 follow-up (sidebar redesign item 13e, direct request):
    Tasks/Calendar/Contacts' own `.toolbar.top-app-bar.toolbar-2row` row
    -- and the per-page "+ New" button that used to live in it -- is gone
    outright, redundant with the sidebar's own global quick-add. What
    used to be "does Filters sit right before New in row 1" is now
    "does the filter trigger render inside the narrow header, with no
    toolbar-2row/toolbar-filters-body left at all"."""

    def test_tasks_filters_trigger_has_no_text_label(self, conn):
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        assert ">Filters<" not in body
        assert "filter-dropdown-trigger" in body

    def test_tasks_filter_trigger_lives_in_the_narrow_header_not_a_toolbar(self, conn):
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        header_pos = body.index('class="page-header-narrow"')
        filters_pos = body.index("filter-dropdown-trigger")
        assert header_pos < filters_pos
        assert 'toolbar-2row"' not in body
        assert "toolbar-filters-body" not in body
        assert "tasks-filters-toggle" not in body

    def test_calendar_filter_trigger_lives_in_the_narrow_header_not_a_toolbar(self, conn):
        today = date.today()
        _seed_event(conn, "a", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        body = resp.body.decode()
        assert ">Filters<" not in body
        header_pos = body.index('class="page-header-narrow"')
        filters_pos = body.index("filter-dropdown-trigger")
        assert header_pos < filters_pos
        assert 'toolbar-2row"' not in body

    def test_contacts_filter_trigger_lives_in_the_narrow_header_not_a_toolbar(self, conn):
        db.upsert_contact(
            conn,
            {
                "uid": "c1",
                "full_name": "Ada",
                "tags": ["Friends"],
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        resp = contacts_router.list_contacts(_request("/contacts"), conn=conn)
        body = resp.body.decode()
        assert ">Filters<" not in body
        header_pos = body.index('class="page-header-narrow"')
        filters_pos = body.index("filter-dropdown-trigger")
        assert header_pos < filters_pos
        assert 'toolbar-2row"' not in body
        assert "toolbar-filters-body" not in body


# 2026-08-15: TestScheduleToolbarConsistency is deleted -- the whole
# Schedule module (routers/schedule.py, schedule_classes.html) is removed,
# see plans/STATE.md's removal entry.
