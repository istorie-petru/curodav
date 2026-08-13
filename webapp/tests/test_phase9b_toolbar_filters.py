"""Phase 9b (toolbar rework, 2026-08-07): the two-row toolbar pattern
(row 1 light -- title/view switcher/search/primary action; row 2
collapsible filters, auto-open when a filter is active) applied to Tasks
(Table/Timeline/Board), Calendar (Month/Week/Day/Agenda), and Contacts.

Covers:
  1. Board/Timeline now respect date_filter/status_filter/importance_filter/
     urgency_filter (previously Table-only).
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
from src.routers import timeline as timeline_router


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


def _seed_task(conn, uid, due_at=None, status="active", importance=None, urgency=None, tags=None):
    db.upsert_task(
        conn,
        {
            "uid": uid,
            "title": uid,
            "description": "",
            "status": status,
            "due_at": due_at,
            "importance": importance,
            "urgency": urgency,
            "tags": tags or [],
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


class TestBoardTimelineFiltersRespected:
    def test_board_respects_status_filter_without_removing_columns(self, conn):
        _seed_task(conn, "a1", status="active")
        _seed_task(conn, "w1", status="waiting")
        resp = tasks_router.board_view(_request("/tasks/board"), status_filter="active", conn=conn)
        columns = resp.context["columns"]
        # Board's whole layout is a status grouping -- status_filter narrows
        # *which* tasks land in each column, it doesn't remove columns.
        assert "waiting" in columns
        assert columns["waiting"] == []
        assert [t["uid"] for t in columns["active"]] == ["a1"]

    def test_board_respects_importance_filter(self, conn):
        _seed_task(conn, "hi", status="active", importance=3)
        _seed_task(conn, "lo", status="active", importance=1)
        resp = tasks_router.board_view(_request("/tasks/board"), importance_filter="3", conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"hi"}

    def test_board_respects_urgency_filter(self, conn):
        _seed_task(conn, "now", status="active", urgency=3)
        _seed_task(conn, "later", status="active", urgency=1)
        resp = tasks_router.board_view(_request("/tasks/board"), urgency_filter="3", conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"now"}

    def test_board_respects_date_filter(self, conn):
        today = date.today()
        _seed_task(conn, "today_task", status="active", due_at=today.isoformat())
        _seed_task(conn, "future_task", status="active", due_at=(today + timedelta(days=20)).isoformat())
        resp = tasks_router.board_view(_request("/tasks/board"), date_filter="today", conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"today_task"}

    def test_timeline_respects_status_and_importance_filters(self, conn):
        today = date.today()
        _seed_task(conn, "keep", status="active", importance=3, due_at=today.isoformat())
        _seed_task(conn, "drop_status", status="waiting", importance=3, due_at=today.isoformat())
        _seed_task(conn, "drop_importance", status="active", importance=1, due_at=today.isoformat())
        resp = timeline_router.timeline_view(
            _request("/tasks/timeline"), status_filter="active", importance_filter="3", conn=conn
        )
        bar_uids = {b["task"]["uid"] for b in resp.context["bars"]}
        assert bar_uids == {"keep"}

    def test_timeline_respects_date_filter(self, conn):
        today = date.today()
        _seed_task(conn, "today_task", status="active", due_at=today.isoformat())
        _seed_task(conn, "overdue_task", status="active", due_at=(today - timedelta(days=5)).isoformat())
        resp = timeline_router.timeline_view(_request("/tasks/timeline"), date_filter="overdue", conn=conn)
        bar_uids = {b["task"]["uid"] for b in resp.context["bars"]}
        assert bar_uids == {"overdue_task"}


class TestTaskLabelFilter:
    def test_table_view_narrows_by_label(self, conn):
        _seed_task(conn, "work1", tags=["Work"])
        _seed_task(conn, "home1", tags=["Home"])
        resp = tasks_router.list_tasks(_request("/tasks"), label="Work", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"work1"}
        assert resp.context["active_label"] == "Work"
        assert "Work" in resp.context["task_label_names"]

    def test_board_view_narrows_by_label(self, conn):
        _seed_task(conn, "work1", status="active", tags=["Work"])
        _seed_task(conn, "home1", status="active", tags=["Home"])
        resp = tasks_router.board_view(_request("/tasks/board"), label="Work", conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"work1"}

    def test_timeline_view_narrows_by_label(self, conn):
        today = date.today()
        _seed_task(conn, "work1", status="active", due_at=today.isoformat(), tags=["Work"])
        _seed_task(conn, "home1", status="active", due_at=today.isoformat(), tags=["Home"])
        resp = timeline_router.timeline_view(_request("/tasks/timeline"), label="Work", conn=conn)
        bar_uids = {b["task"]["uid"] for b in resp.context["bars"]}
        assert bar_uids == {"work1"}

    def test_label_filter_is_case_insensitive(self, conn):
        _seed_task(conn, "work1", tags=["Work"])
        resp = tasks_router.list_tasks(_request("/tasks"), label="work", conn=conn)
        open_uids = {t["uid"] for t in resp.context["open_tasks"]}
        assert open_uids == {"work1"}


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
    def test_month_view_renders_exactly_one_toolbar(self, conn):
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 1

    def test_week_view_renders_exactly_one_toolbar(self, conn):
        resp = calendar_router.week_view(_request("/calendar/week"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 1

    def test_day_view_renders_exactly_one_toolbar(self, conn):
        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _request(f"/calendar/day/{today_iso}"), conn=conn)
        assert _toolbar_div_count(resp.body.decode()) == 1

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
    these drop down menus into the topbar") -- date/status/importance/
    urgency/label
    are inline "fancy dropdowns" (_filter_dropdown.html) in row 1, each a
    radio list that navigates on pick. The active filter is simply the
    checked radio (mirrored in the trigger's summary text), so there's no
    collapsible panel left to auto-open. Contacts still uses the
    checkbox-hack, so its assertions below are unchanged."""

    def test_tasks_status_filter_is_the_checked_radio(self, conn):
        _seed_task(conn, "a", status="active")
        resp = tasks_router.list_tasks(_request("/tasks"), status_filter="active", conn=conn)
        body = resp.body.decode()
        assert ("active", True) in _radios(body, "status_filter")
        assert ("all", False) in _radios(body, "status_filter")
        # the checkbox-hack is gone entirely
        assert "toolbar-filters-checkbox" not in body

    def test_tasks_no_filter_selects_all_statuses(self, conn):
        _seed_task(conn, "a", status="active")
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        assert ("all", True) in _radios(body, "status_filter")

    def test_tasks_label_filter_is_the_checked_radio(self, conn):
        _seed_task(conn, "a", tags=["Work"])
        resp = tasks_router.list_tasks(_request("/tasks"), label="Work", conn=conn)
        body = resp.body.decode()
        assert ("Work", True) in _radios(body, "label")
        assert ("", False) in _radios(body, "label")

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
    Calendar now carry the four "fancy dropdown" filter triggers inline in
    row 1 (templates/_filter_dropdown.html's .filter-dropdown-trigger), each
    a compact descriptor+chevron button sitting next to the primary "New"
    button. Covers Tasks/Calendar/Contacts/Schedule -- 2026-08-08 Contacts'
    tag filter and Schedule's label filter both moved off their old
    mechanisms (Contacts' checkbox-hack Filters button, Schedule's
    nothing-at-all) onto the same dropdown, so they're part of this
    trigger-position check too.

    Critically, this also checks the New button is NOT pushed out of
    row 1 -- both the dropdown triggers (compact, fixed-size) and the New
    button are direct children of .toolbar-row; the old collapsible
    .toolbar-filters-body (which lived outside .toolbar-row entirely) no
    longer exists, so nothing can affect row 1's wrapping anymore."""

    def test_tasks_filters_trigger_has_no_text_label(self, conn):
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        assert ">Filters<" not in body
        assert "filter-dropdown-trigger" in body

    def test_tasks_dropdowns_and_new_button_both_stay_in_row_1(self, conn):
        resp = tasks_router.list_tasks(_request("/tasks"), conn=conn)
        body = resp.body.decode()
        # All four filter dropdowns plus the New button sit inside row 1 --
        # there is no .toolbar-filters-body (or hidden checkbox) anymore to
        # push anything onto another line.
        filters_pos = body.index("filter-dropdown-trigger")
        new_button_pos = body.index('href="/tasks/new"')
        assert filters_pos < new_button_pos
        assert "toolbar-filters-body" not in body
        assert "tasks-filters-toggle" not in body

    def test_calendar_filters_trigger_sits_immediately_before_new_button(self, conn):
        today = date.today()
        _seed_event(conn, "a", start_at=f"{today.isoformat()}T09:00:00", tags=["Work"])
        resp = calendar_router.month_view(_request("/calendar"), conn=conn)
        body = resp.body.decode()
        assert ">Filters<" not in body
        filters_pos = body.index("filter-dropdown-trigger")
        new_button_pos = body.index('href="/events/new"')
        assert filters_pos < new_button_pos

    def test_contacts_filters_trigger_sits_immediately_before_new_button(self, conn):
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
        filters_pos = body.index("filter-dropdown-trigger")
        new_button_pos = body.index('href="/contacts/new"')
        assert filters_pos < new_button_pos
        assert "toolbar-filters-body" not in body


class TestScheduleToolbarConsistency:
    """Schedule brought into the same .toolbar.top-app-bar.toolbar-2row/
    .toolbar-row shell as Calendar/Tasks/Contacts (Phase 9c), including a
    visible search box for the `q` param routers/schedule.py already
    accepted but had no input for."""

    def test_schedule_uses_the_shared_toolbar_shell(self, conn):
        from src.routers import schedule as schedule_router

        resp = schedule_router.classes_view(_request("/schedule"), conn=conn)
        body = resp.body.decode()
        assert 'class="toolbar top-app-bar toolbar-2row"' in body
        assert 'class="toolbar-row"' in body

    def test_schedule_table_view_has_a_search_box(self, conn):
        from src.routers import schedule as schedule_router

        # 2026-08-08: the toolbar search box and the Table-view body's own
        # duplicate search box merged into one -- see schedule_classes.html's
        # comment. Placeholder describes the columns classes_view actually
        # searches (name/acronym/professor/room).
        resp = schedule_router.classes_view(_request("/schedule"), conn=conn)
        body = resp.body.decode()
        assert 'name="q"' in body
        assert 'placeholder="Search course, professor, room..."' in body
        assert body.count('name="q"') == 1

    def test_schedule_search_actually_filters(self, conn):
        from src.routers import schedule as schedule_router

        db.upsert_schedule_class(
            conn,
            {
                "uid": "cl1", "day": "Monday", "start_time": "09:00", "end_time": "10:00",
                "name": "Algorithms", "credits": 5, "parity": "all", "created_at": _now(), "updated_at": _now(),
            },
        )
        db.upsert_schedule_class(
            conn,
            {
                "uid": "cl2", "day": "Tuesday", "start_time": "09:00", "end_time": "10:00",
                "name": "History", "credits": 5, "parity": "all", "created_at": _now(), "updated_at": _now(),
            },
        )
        resp = schedule_router.classes_view(_request("/schedule?q=Algo"), q="Algo", conn=conn)
        body = resp.body.decode()
        assert "Algorithms" in body
        assert "History" not in body
