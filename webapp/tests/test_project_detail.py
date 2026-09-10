"""GET /projects/{name} -- the real project page rebuilt 2026-08-30 (see
routers/projects.py's module docstring): a Kanban board of every task
carrying the project's label (columns = status), with an upcoming-events
card above it. Replaces the 2026-08-15..2026-08-30 redirect stub;
plans/STATE.md backlog item 9 ("Projects page -- view-like, not
dashboard-like").

Direct-call pattern (bare `Request({...})`, no ASGI app) follows
test_phase2_labels.py's own TestGeneratedSpacePage -- TemplateResponse
exposes its render context via `.context`, so assertions read the same
data the template would."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import projects as projects_router

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/projects/Trip"):
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


def _promote(conn, name="Trip", start="2026-01-01", end="2026-12-31"):
    db.upsert_label_config(
        conn, {"name": name, "is_project": 1, "start_date": start, "end_date": end, "created_at": _now()}
    )


def _task(conn, uid, tags, status="active", due_at=None):
    db.upsert_task(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": status, "tags": tags, "created_at": _now(), "due_at": due_at},
    )


def _event(conn, uid, tags, start_at):
    db.upsert_event(
        conn,
        {"uid": uid, "title": uid, "description": "", "status": "active", "all_day": 0, "tags": tags,
         "start_at": start_at, "created_at": _now()},
    )


class TestNotAProjectRedirects:
    def test_plain_label_redirects_to_its_label_page(self, conn):
        db.upsert_label_config(conn, {"name": "Plain", "created_at": _now()})
        resp = projects_router.project_detail("Plain", _request("/projects/Plain"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Plain"

    def test_unknown_label_redirects_too(self, conn):
        resp = projects_router.project_detail("Ghost", _request("/projects/Ghost"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Ghost"

    def test_demoted_project_redirects(self, conn):
        _promote(conn, "Trip")
        projects_router.demote("Trip", conn=conn)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/labels/Trip"


class TestKanbanBoard:
    def test_renders_a_project_with_no_tasks(self, conn):
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.status_code == 200
        assert resp.context["project"]["name"] == "Trip"
        assert resp.context["board_statuses"] == ["active", "in_progress", "waiting", "done"]
        assert all(resp.context["columns"][s] == [] for s in resp.context["board_statuses"])

    def test_tasks_bucket_by_status(self, conn):
        _promote(conn, "Trip")
        _task(conn, "t1", ["Trip"], status="active")
        _task(conn, "t2", ["Trip"], status="in_progress")
        _task(conn, "t3", ["Trip"], status="done")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        columns = resp.context["columns"]
        assert [t["uid"] for t in columns["active"]] == ["t1"]
        assert [t["uid"] for t in columns["in_progress"]] == ["t2"]
        assert [t["uid"] for t in columns["done"]] == ["t3"]

    def test_archived_tasks_are_excluded_from_the_board(self, conn):
        _promote(conn, "Trip")
        _task(conn, "t1", ["Trip"], status="archived")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert "archived" not in resp.context["board_statuses"]
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert "t1" not in all_uids

    def test_tasks_from_other_projects_are_excluded(self, conn):
        _promote(conn, "Trip")
        _promote(conn, "Other", start="2026-01-01", end="2026-12-31")
        _task(conn, "t1", ["Trip"], status="active")
        _task(conn, "t2", ["Other"], status="active")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert all_uids == {"t1"}

    def test_habit_tagged_tasks_are_excluded(self, conn):
        # list_tasks_sharing_labels excludes the configured habit label,
        # same exclusion the "link an existing task" pool already applies
        # -- a habit is never a Kanban card.
        _promote(conn, "Trip")
        habit_label = db.get_task_habit_settings(conn)["habit_label"]
        _task(conn, "h1", ["Trip", habit_label], status="active")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        all_uids = {t["uid"] for col in resp.context["columns"].values() for t in col}
        assert "h1" not in all_uids


class TestKanbanDragAndDrop:
    """audit-fixes-2.1.md (2026-09-10, direct bug report): "The kanban
    board for tasks doesn't allow for tasks to be drag and dropped."
    static/tasks_board.js already implemented Pointer-Events drag-and-drop
    against exactly this board's markup (`#kanban-board`, `.kanban-column
    [data-status]`, `.kanban-cards[data-status]`, `.kanban-card[data-uid]`)
    and posts to the same /tasks/{uid}/update-field endpoint the old
    per-card status dropdown used -- it was simply never <script>-included
    on this page after the 2026-08-28 rework that deleted the standalone
    Kanban page it was originally written for. No browser harness in this
    suite -- structural checks that the script is now wired up and its
    selectors genuinely match this page's rendered markup, same convention
    test_calendar_week_scheduling.py's TestGridDragConflictFix uses for
    JS-only changes."""

    def test_tasks_board_js_is_included(self, conn):
        _promote(conn, "Trip")
        body = projects_router.project_detail("Trip", _request(), conn=conn).body.decode()
        assert 'src="/static/tasks_board.js' in body

    def test_board_markup_matches_the_scripts_own_selectors(self, conn):
        _promote(conn, "Trip")
        _task(conn, "t1", ["Trip"], status="active")
        body = projects_router.project_detail("Trip", _request(), conn=conn).body.decode()
        script = (_STATIC_DIR / "tasks_board.js").read_text(encoding="utf-8")
        # Every selector tasks_board.js queries against must actually
        # appear in the rendered board -- confirms the re-wiring is
        # against real, matching markup, not just an included-but-inert
        # script.
        assert 'getElementById("kanban-board")' in script
        assert 'id="kanban-board"' in body
        assert '.closest(".kanban-cards")' in script
        assert 'class="kanban-cards" data-status="active"' in body
        assert 'querySelectorAll(".kanban-card")' in script
        assert 'class="kanban-card" data-uid="t1" data-status="active"' in body

    def test_drag_persists_through_the_update_field_endpoint(self):
        script = (_STATIC_DIR / "tasks_board.js").read_text(encoding="utf-8")
        assert "/tasks/${uid}/update-field" in script
        assert 'JSON.stringify({ field: "status", value: newStatus })' in script


class TestAgendaCard:
    # end=None throughout this class (unlike _promote's own 2026-12-31
    # default) -- these tests assert exact list contents, and a default
    # end_date would itself surface as a synthetic deadline row
    # (TestProjectDeadlineAsEvent below), throwing off every count/order
    # assertion here. Deadline behavior gets its own class/fixtures.
    # Renamed from TestUpcomingEventsCard, context key from "events" to
    # "agenda_items" (2026-09-10, audit-fixes-2.1.md) when the card
    # started merging in due-dated tasks -- see TestAgendaCardIncludesTasks
    # below for that half.
    def test_no_events_renders_empty(self, conn):
        _promote(conn, "Trip", end=None)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_only_future_events_tagged_with_the_project_show(self, conn):
        _promote(conn, "Trip", end=None)
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        _event(conn, "e_future", ["Trip"], future)
        _event(conn, "e_past", ["Trip"], past)
        _event(conn, "e_other_project", ["Other"], future)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [e["uid"] for e in resp.context["agenda_items"]] == ["e_future"]

    def test_todays_earlier_event_still_shows(self, conn):
        # 2026-09-10 fix, same pass as the tasks merge below: this filter
        # used to compare the FULL now_iso timestamp (wall-clock precision)
        # against start_at -- the exact bug routers/dashboard.py's own
        # Agenda widget fixed 2026-09-03 for the same reason. An event
        # earlier today than "right now" must still show; only a date-level
        # comparison gets that right.
        _promote(conn, "Trip", end=None)
        earlier_today = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        _event(conn, "e_earlier", ["Trip"], earlier_today)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [e["uid"] for e in resp.context["agenda_items"]] == ["e_earlier"]

    def test_events_are_sorted_soonest_first(self, conn):
        _promote(conn, "Trip", end=None)
        soon = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        _event(conn, "e_later", ["Trip"], later)
        _event(conn, "e_soon", ["Trip"], soon)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [e["uid"] for e in resp.context["agenda_items"]] == ["e_soon", "e_later"]

    def test_capped_at_eight(self, conn):
        _promote(conn, "Trip", end=None)
        for i in range(10):
            when = (datetime.now(timezone.utc) + timedelta(days=i + 1)).isoformat()
            _event(conn, f"e{i}", ["Trip"], when)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert len(resp.context["agenda_items"]) == 8


class TestAgendaCardIncludesTasks:
    """audit-fixes-2.1.md (2026-09-10, direct request): "I would like the
    agenda card to also include tasks due date in that list, like other
    widgets in the normal dashboard." Due-dated open tasks tagged with this
    project merge into the SAME chronologically-sorted list events/the
    deadline already render through (not a separate section) -- each
    becomes an `{"kind": "task", ...}` dict alongside the plain event/
    deadline shapes."""

    def test_task_with_due_date_appears_in_the_agenda(self, conn):
        _promote(conn, "Trip", end=None)
        future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        _task(conn, "t1", ["Trip"], due_at=future)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        items = resp.context["agenda_items"]
        assert len(items) == 1
        assert items[0]["kind"] == "task"
        assert items[0]["uid"] == "t1"
        assert items[0]["start_at"] == future

    def test_task_with_no_due_date_is_excluded(self, conn):
        _promote(conn, "Trip", end=None)
        _task(conn, "t1", ["Trip"])
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_past_due_task_is_excluded(self, conn):
        _promote(conn, "Trip", end=None)
        past = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        _task(conn, "t1", ["Trip"], due_at=past)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_due_today_task_still_counts_as_upcoming(self, conn):
        _promote(conn, "Trip", end=None)
        today = datetime.now(timezone.utc).date().isoformat()
        _task(conn, "t1", ["Trip"], due_at=today)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert [i["uid"] for i in resp.context["agenda_items"]] == ["t1"]

    def test_done_task_is_excluded(self, conn):
        _promote(conn, "Trip", end=None)
        future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        _task(conn, "t1", ["Trip"], status="done", due_at=future)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_task_from_another_project_is_excluded(self, conn):
        _promote(conn, "Trip", end=None)
        _promote(conn, "Other", start="2026-01-01", end="2026-12-31")
        future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        _task(conn, "t1", ["Other"], due_at=future)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_tasks_and_events_sort_together_by_date(self, conn):
        _promote(conn, "Trip", end=None)
        soon_task = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        mid_event = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        later_task = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
        _task(conn, "t_later", ["Trip"], due_at=later_task)
        _event(conn, "e_mid", ["Trip"], mid_event)
        _task(conn, "t_soon", ["Trip"], due_at=soon_task)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        ordering = [i["uid"] for i in resp.context["agenda_items"]]
        assert ordering == ["t_soon", "e_mid", "t_later"]

    def test_tasks_and_events_share_the_same_eight_item_cap(self, conn):
        _promote(conn, "Trip", end=None)
        for i in range(5):
            when = (datetime.now(timezone.utc) + timedelta(days=i + 1)).isoformat()
            _event(conn, f"e{i}", ["Trip"], when)
        for i in range(5):
            when = (datetime.now(timezone.utc) + timedelta(days=i + 20)).date().isoformat()
            _task(conn, f"t{i}", ["Trip"], due_at=when)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert len(resp.context["agenda_items"]) == 8

    def test_task_row_renders_as_a_task_link_with_relative_due_date(self, conn):
        _promote(conn, "Trip", end=None)
        future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        _task(conn, "t1", ["Trip"], due_at=future)
        body = projects_router.project_detail("Trip", _request(), conn=conn).body.decode()
        assert 'href="/tasks/t1"' in body


class TestProjectDeadlineAsEvent:
    """Direct follow-up request: the project's own deadline (label_config's
    end_date) shows up in the Agenda card too, as a synthetic,
    non-clickable entry (`is_deadline`) sorted in among the real events/
    tasks."""

    def test_future_end_date_appears_as_a_deadline_entry(self, conn):
        future_end = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
        _promote(conn, "Trip", end=future_end)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        items = resp.context["agenda_items"]
        assert len(items) == 1
        assert items[0]["is_deadline"] is True
        assert items[0]["title"] == "Project deadline"
        assert items[0]["start_at"] == f"{future_end}T00:00:00"

    def test_deadline_dated_today_still_counts_as_upcoming(self, conn):
        today = datetime.now(timezone.utc).date().isoformat()
        _promote(conn, "Trip", end=today)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert len(resp.context["agenda_items"]) == 1
        assert resp.context["agenda_items"][0]["is_deadline"] is True

    def test_past_end_date_does_not_appear(self, conn):
        past_end = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        _promote(conn, "Trip", end=past_end)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_no_end_date_means_no_deadline_entry(self, conn):
        _promote(conn, "Trip", end=None)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["agenda_items"] == []

    def test_deadline_sorts_alongside_real_events_by_date(self, conn):
        future_end = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
        _promote(conn, "Trip", end=future_end)
        sooner = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        later = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        _event(conn, "e_sooner", ["Trip"], sooner)
        _event(conn, "e_later", ["Trip"], later)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        ordering = [e.get("uid") or e.get("title") for e in resp.context["agenda_items"]]
        assert ordering == ["e_sooner", "Project deadline", "e_later"]

    def test_deadline_renders_with_a_deadline_pill_and_no_link(self, conn):
        future_end = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
        _promote(conn, "Trip", end=future_end)
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        body = resp.body.decode()
        assert "Project deadline" in body
        assert "pill-red" in body
        assert "Deadline" in body


class TestHeaderBannerAndAvatar:
    """Direct request ("the banner header, the profile picture") -- this
    page is a "dashboard type" page for the shared page-header convention
    (_page_banner.html's own docstring already named this route as a
    future caller) even though it deliberately has no widget grid. Covers
    the same context _page_banner.html needs, plus the edit-mode-gated
    Add/Change banner control -- not the image rendering itself, which
    test_banners.py already covers generically."""

    def test_no_banner_set_falls_back_to_default_and_renders_plain_title(self, conn):
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        body = resp.body.decode()
        assert "page-banner-wrap" in body
        assert "page-banner-title-plain" in body
        assert resp.context["has_own_banner"] is False

    def test_own_banner_renders_cover_and_avatar_overlap(self, conn):
        _promote(conn, "Trip")
        db.set_page_banner(conn, "Trip", {"kind": "remote", "image_url": "https://example.com/a.jpg", "alt": "x"})
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        body = resp.body.decode()
        assert "page-banner-avatar-wrap" in body
        assert "https://example.com/a.jpg" in body
        assert resp.context["has_own_banner"] is True
        assert 'class="page-banner-title"' in body

    def test_add_banner_button_only_shows_in_edit_mode(self, conn):
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert "Add banner" not in resp.body.decode()
        db.set_app_meta(conn, "edit_mode_enabled", "1")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        body = resp.body.decode()
        assert "Add banner" in body
        assert "/banners/editor?scope=Trip&amp;page_url=/projects/Trip" in body

    def test_change_banner_label_once_a_banner_is_set(self, conn):
        _promote(conn, "Trip")
        db.set_page_banner(conn, "Trip", {"kind": "remote", "image_url": "https://example.com/a.jpg", "alt": "x"})
        db.set_app_meta(conn, "edit_mode_enabled", "1")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        body = resp.body.decode()
        assert "Change banner" in body
        assert "Add banner" not in body

    def test_page_url_points_at_the_projects_route_not_settings_labels(self, conn):
        # Regression guard: dashboard_router._return_url would resolve a
        # project label to /settings/labels/{name} (it predates this page)
        # -- the banner editor must redirect back to /projects/{name}
        # instead, or saving a banner here bounces the user to the wrong
        # page.
        _promote(conn, "Trip")
        resp = projects_router.project_detail("Trip", _request(), conn=conn)
        assert resp.context["page_url"] == "/projects/Trip"
