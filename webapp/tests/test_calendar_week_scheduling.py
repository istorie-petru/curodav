"""Acceptance tests for the merged Week view's scheduling affordances
(`routers/calendar.py::week_view`, `GET /calendar/week`): the former
standalone "Timetable" sub-view (1.7/1.9) folded directly into Week (1.9 side
work, direct feedback: "merge the calendar's week view with the timetable
view"). One grid, both capabilities at once -- ordinary events stay fully
interactive (drag-to-move/resize, drag-to-create on empty space, both via
static/calendar.js) AND every work-allocation event renders prominently with
its own move/resize/delete (block only) via static/project_calendar.js, plus
the "Unscheduled work" sidebar (now collapsible) that drags a task onto the
grid to schedule it. The create/move/delete allocation endpoints live at
/calendar/week/allocations... and redirect back to /calendar/week. Same
direct-router-call convention as test_week_planning.py. Formerly
test_calendar_timetable.py, testing the since-removed timetable_view/
calendar_timetable.html."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router

_MONDAY = "2026-08-17"  # a real Monday
_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/calendar/week",
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _task(conn, uid, tags=None, status="active", **overrides):
    row = {
        "uid": uid, "title": uid, "description": "", "status": status,
        "tags": tags or [], "created_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return db.get_task(conn, uid)


def _project(conn, name):
    db.upsert_label_config(
        conn, {"name": name, "is_project": 1, "start_date": "2026-08-01", "end_date": "2026-09-01", "created_at": _now()}
    )


class TestWeekViewRoute:
    def test_renders_grid_and_unscheduled_panel(self, conn):
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert "Unscheduled work" in body
        assert "project-calendar-col" in body
        # Merged view keeps the ordinary Week grid's own create-on-drag
        # affordance alongside the scheduling one (the old Timetable
        # sub-view deliberately excluded this).
        assert "calendar-create-col" in body

    def test_open_task_with_no_allocation_is_not_unscheduled(self, conn):
        # audit-fixes-2.1.md (2026-09-10, direct bug report): a task with
        # zero work sessions at all used to still show up on this panel
        # (with a bare "0" pill) -- there's nothing to place yet, so it
        # shouldn't appear until the task actually has an undated session
        # (see test_task_with_undated_session_stays_on_unscheduled_panel
        # below for that case).
        _task(conn, "t1", title="Research")
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert 'data-task-uid="t1"' not in body

    def test_task_with_allocation_drops_off_unscheduled_list(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-task-item" not in body

    def test_task_with_undated_session_stays_on_unscheduled_panel(self, conn):
        """A session added from the task modal's Work sessions "+" button has
        no date yet -- the task is still unscheduled work and must remain in
        the drag-source panel until the session is placed onto a slot."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-task-item" in body
        assert "Research" in body

    def test_completed_task_never_appears_unscheduled(self, conn):
        _task(conn, "t1", title="Done thing", status="done")
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert "Done thing" not in body

    def test_unscheduled_task_shows_its_project_pill(self, conn):
        """1.9 one-line card: the project renders as a pill (icon + name)
        before the task title, not a `Project > Task` prefix."""
        _project(conn, "Conference XYZ")
        _task(conn, "t1", tags=["Conference XYZ"], title="Research")
        db.create_work_allocation(conn, "t1")  # an undated session -- a
        # 0-session task no longer appears on this panel at all (see
        # test_open_task_with_no_allocation_is_not_unscheduled above).
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert 'class="unscheduled-project-pill"' in body
        assert "Conference XYZ" in body
        assert "&gt; Research" not in body

    def test_work_allocation_renders_prominent_and_owned_by_project_calendar_js(self, conn):
        """A scheduled block is a .work-allocation (project_calendar.js's
        form-POST move/resize/delete) that shares .time-event styling -- but
        calendar.js must not double-own it (it uses
        `.time-event:not(.work-allocation)`)."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "work-allocation" in body
        assert "/calendar/week/allocations" in body

    def test_scheduled_block_links_to_its_task_view(self, conn):
        """A scheduled work block is one target for the task it belongs to,
        opened via JS (project_calendar.js interaction 4, taskUrlBase
        config) for ANY non-drag click on the block, title text included --
        the title is a plain span, not a nested <a> (direct feedback: "why
        can't the whole div be a link and moved at the same time" -- the
        whole block can't itself be a real <a> since it also contains a
        delete <form>/<button>, invalid inside <a>, so instead the title
        drops link semantics and the whole block, title included, is one
        uniform drag target). The delete form still targets the allocation
        endpoint."""
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-uid="t1"' in body
        assert '<span class="te-name">Research</span>' in body
        assert 'href="/tasks/t1"' not in body
        assert 'href="/tasks/t1/edit"' not in body
        assert 'taskUrlBase: "/tasks/"' in body
        assert "/calendar/week/allocations/" in body

    def test_ordinary_event_renders_fully_interactive_not_subdued(self, conn):
        """The merged Week view is the ordinary Calendar grid FIRST -- an
        ordinary event stays a plain, fully interactive `.time-event`
        (draggable/clickable via calendar.js), unlike the old Timetable
        sub-view where it was a read-only `.context-event`."""
        db.upsert_event(
            conn,
            {
                "uid": "e-plain", "title": "Ordinary meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": [],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "context-event" not in body
        assert "Ordinary meeting" in body
        assert 'href="/events/e-plain"' in body

    def test_label_filter_applies_to_events(self, conn):
        db.upsert_event(
            conn,
            {
                "uid": "e-a", "title": "Blue meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": ["work"],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        db.upsert_event(
            conn,
            {
                "uid": "e-b", "title": "Personal thing", "description": "",
                "start_at": f"{_MONDAY}T14:00:00", "end_at": f"{_MONDAY}T15:00:00",
                "all_day": False, "status": "active", "tags": ["personal"],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}&label=work".encode()), date_=_MONDAY, label="work", conn=conn
        ).body.decode()
        assert "Blue meeting" in body
        assert "Personal thing" not in body

    def test_unscheduled_panel_has_collapse_toggle_button(self, conn):
        """Direct feedback: "make the Unscheduled work block collapsible via
        a sidebar button." -- static/unscheduled_panel_toggle.js drives it,
        state is per-device (localStorage), no server involvement."""
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert 'id="unscheduled-panel-toggle"' in body
        assert 'id="unscheduled-panel-body"' in body
        assert "unscheduled_panel_toggle.js" in body

    def test_no_separate_timetable_link_in_subnav(self, conn):
        body = calendar_router.week_view(_request(), conn=conn).body.decode()
        assert ">Timetable<" not in body
        assert "/calendar/timetable" not in body


class TestTimetableRedirect:
    def test_old_timetable_link_redirects_to_week(self, conn):
        resp = calendar_router.timetable_view_redirect()
        assert resp.status_code == 303
        assert resp.headers["location"] == "/calendar/week"

    def test_redirect_preserves_date_and_label(self, conn):
        resp = calendar_router.timetable_view_redirect(date_=_MONDAY, label="work")
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/week?date_={_MONDAY}&label=work"


class TestCreateWeekAllocation:
    def test_dragging_any_open_task_creates_an_allocation(self, conn):
        _task(conn, "t1", title="Research")
        resp = calendar_router.create_week_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/week?date_={_MONDAY}"
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_no_project_membership_check(self, conn):
        _project(conn, "Some Project")
        _task(conn, "t1", title="Unaffiliated task")
        calendar_router.create_week_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_completed_task_is_rejected(self, conn):
        _task(conn, "t1", title="Done", status="done")
        calendar_router.create_week_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        assert db.list_work_allocations_for_task(conn, "t1") == []

    def test_dragging_task_with_undated_session_places_that_session(self, conn):
        """Dragging a task that has an undated session placeholder places
        THAT session onto the dropped slot instead of creating yet another
        block -- so repeated "+" sessions each get placed by a drag, not
        multiplied."""
        _task(conn, "t1", title="Research")
        undated_uid = db.create_work_allocation(conn, "t1")
        calendar_router.create_week_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T18:00:00", date_=_MONDAY, conn=conn
        )
        allocations = db.list_work_allocations_for_task(conn, "t1")
        assert len(allocations) == 1
        assert allocations[0]["uid"] == undated_uid
        assert allocations[0]["start_at"] == f"{_MONDAY}T16:00:00"
        assert allocations[0]["end_at"] == f"{_MONDAY}T18:00:00"


class TestMoveWeekAllocation:
    def test_move_changes_start_and_end(self, conn):
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        tuesday = (datetime.fromisoformat(_MONDAY) + timedelta(days=1)).date().isoformat()
        resp = calendar_router.move_week_allocation(
            event_uid, start_at=f"{tuesday}T09:00:00", end_at=f"{tuesday}T11:30:00", date_=_MONDAY, conn=conn
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/week?date_={_MONDAY}"
        event = db.get_event(conn, event_uid)
        assert event["start_at"] == f"{tuesday}T09:00:00"
        assert event["end_at"] == f"{tuesday}T11:30:00"

    def test_moving_a_non_allocation_event_is_rejected(self, conn):
        db.upsert_event(
            conn,
            {
                "uid": "e-plain", "title": "Ordinary meeting", "description": "",
                "start_at": f"{_MONDAY}T12:00:00", "end_at": f"{_MONDAY}T13:00:00",
                "all_day": False, "status": "active", "tags": [],
                "created_at": _now(), "updated_at": _now(),
            },
        )
        calendar_router.move_week_allocation(
            "e-plain", start_at=f"{_MONDAY}T14:00:00", end_at=f"{_MONDAY}T15:00:00", date_=_MONDAY, conn=conn
        )
        event = db.get_event(conn, "e-plain")
        assert event["start_at"] == f"{_MONDAY}T12:00:00"


class TestDeleteWeekAllocation:
    def test_delete_unschedules_the_block_not_the_task(self, conn):
        """"Delete" on a block doesn't delete the session -- it clears its
        start/end back to undated, so the task's session count never drops
        just from unscheduling; the task itself is never deleted either."""
        _task(conn, "t1", title="Research")
        event_uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = calendar_router.delete_week_allocation(event_uid, date_=_MONDAY, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/calendar/week?date_={_MONDAY}"
        assert db.get_task(conn, "t1") is not None
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == [event_uid]
        assert remaining[0]["start_at"] is None
        assert remaining[0]["end_at"] is None

    def test_delete_leaves_the_tasks_other_sessions_untouched(self, conn):
        _task(conn, "t1", title="Research")
        for day in ("2026-08-17", "2026-08-18", "2026-08-19"):
            db.create_work_allocation(conn, "t1", f"{day}T16:00:00", f"{day}T18:00:00")
        event_uids = [wa["uid"] for wa in db.list_work_allocations_for_task(conn, "t1")]
        calendar_router.delete_week_allocation(event_uids[0], date_=_MONDAY, conn=conn)
        remaining = db.list_work_allocations_for_task(conn, "t1")
        assert [wa["uid"] for wa in remaining] == event_uids
        by_uid = {wa["uid"]: wa for wa in remaining}
        assert by_uid[event_uids[0]]["start_at"] is None
        assert by_uid[event_uids[1]]["start_at"] is not None
        assert by_uid[event_uids[2]]["start_at"] is not None


class TestUnscheduledPanelStepper:
    """"Unscheduled work" panel: per-item pill shows sessions still needing
    placement (`undated_count`), not the task's total session count.
    2026-09-10 (audit-fixes-2.1.md, direct request): the item's own +/-
    stepper buttons are gone -- a plain click on the item itself now opens
    the task view modal (project_calendar.js's pointer-drag `end()`, a
    release with no drag; see TestClickOpensTaskModal below), and there is
    no in-panel way to add or remove a session anymore -- both now live on
    the task modal's own Work sessions card."""

    def test_item_has_no_plus_or_minus_buttons(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")  # one undated session
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'data-task-uid="t1"' in body
        assert "unscheduled-count" in body
        assert "unscheduled-stepper" not in body
        assert "unscheduled-step-btn" not in body
        assert "/tasks/t1/work-allocations/remove-latest" not in body
        # No <form> at all -- adding a session is a plain JS click now, not
        # a submitted form (see project_calendar.js's end()).
        assert "<form" not in body.split('id="unscheduled-panel"')[1].split("</aside>")[0]

    def test_count_reflects_sessions_still_needing_placement(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert '<span class="unscheduled-count" title="Sessions still needing placement">2</span>' in body

        calendar_router.create_week_allocation(
            task_uid="t1", start_at=f"{_MONDAY}T16:00:00", end_at=f"{_MONDAY}T17:00:00", date_=_MONDAY, conn=conn
        )
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert '<span class="unscheduled-count" title="Sessions still needing placement">1</span>' in body

    def test_count_still_shown_with_more_than_one_undated_session(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "/tasks/t1/work-allocations/remove-latest" not in body
        assert '<span class="unscheduled-count" title="Sessions still needing placement">2</span>' in body

    def test_card_is_one_line_without_hours(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert "unscheduled-count" in body
        assert "unscheduled-hours" not in body
        assert "unscheduled-grip" not in body
        assert "unscheduled-task-body" not in body

    def test_item_has_no_native_draggable_attribute(self, conn):
        _task(conn, "t1", title="Research")
        db.create_work_allocation(conn, "t1")
        body = calendar_router.week_view(
            _request(query_string=f"date_={_MONDAY}".encode()), date_=_MONDAY, conn=conn
        ).body.decode()
        assert 'draggable="true"' not in body


class TestClickOpensTaskModal:
    """audit-fixes-2.1.md (2026-09-10, direct request, second pass same
    day): "for any pill inside it, the user could click it and open the
    task view modal window." Supersedes the same-session click-to-add-
    session behavior (a plain click on the same gesture can't do both --
    see TestUnscheduledPanelStepper's docstring). No browser harness in
    this suite (same convention as TestGridDragConflictFix above) --
    structural source checks against project_calendar.js confirm the
    no-drag click branch opens the task modal via the same
    taskUrlBase/CCModal convention interaction 4 already uses for a placed
    `.work-allocation` block, and that the old click-to-add POST is gone."""

    def test_no_drag_release_opens_the_task_modal(self):
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        assert "if (!wasDrag) {" in script
        click_branch = script.split("if (!wasDrag) {")[1].split("if (!col) return")[0]
        assert "cfg.taskUrlBase" in click_branch
        assert "item.dataset.taskUid" in click_branch
        assert "window.CCModal" in click_branch
        assert "CCModal.open(url, item)" in click_branch

    def test_click_to_add_session_post_is_gone(self):
        # The earlier same-session click-to-add-session POST is gone from
        # the no-drag click branch -- adding a session now happens from the
        # task modal's own Work sessions card instead.
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        click_branch = script.split("if (!wasDrag) {")[1].split("if (!col) return")[0]
        assert '"/work-allocations"' not in click_branch
        assert "postAction(" not in click_branch

    def test_stepper_pointerdown_carveout_is_gone(self):
        # The old code let a pointerdown on `.unscheduled-stepper` click
        # through without starting a drag, so the now-removed +/- buttons
        # would still work -- dead now that the stepper markup is gone.
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        assert "unscheduled-stepper" not in script

    def test_falls_back_to_navigation_without_ccmodal(self):
        # Same fallback interaction 4 already documents for a placed block:
        # no window.CCModal -> plain navigation to the task URL instead of
        # silently doing nothing.
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        click_branch = script.split("if (!wasDrag) {")[1].split("if (!col) return")[0]
        assert "window.location.href = url" in click_branch


class TestUnscheduledPanelFixedHeight:
    """Direct bug report (2026-09-08), same session as the class above:
    "dragging and dropping from unscheduled work to the planner, and vice
    versa, should not move the scrollbar page." Root cause: #unscheduled-
    panel-body's outer height used to be purely a function of its item
    count (`.project-calendar-unscheduled` is `flex:none`) -- scheduling or
    unscheduling one task changes that count by exactly one, reflowing the
    grid card below it in the same flex column even though the grid's own
    `.time-grid-wrap` scrollTop (already preserved, async_calendar.js
    `refreshWeek`) never moved. A plain block move/resize never touches this
    panel's item count, which is why the report was scoped to exactly the
    two unscheduled<->planner drag directions. Fix: a fixed (not max-)
    height + its own overflow-y:auto on style.css's `#unscheduled-panel-body`
    so the aside's own footprint can no longer change with item count. A
    first pass fixed it at ~3 rows (84px) -- a direct follow-up report
    ("the Unscheduled work div got bigger") caught that this read as a
    size regression for the common one-or-two-item case, so it's now
    sized to exactly one row (26px) instead, still fixed either way. A
    second follow-up ("it shouldn't have a sidebar") caught that a one-row
    box hits its own scrollbar far more often than the 3-row one did, so
    the track is now hidden (scrollbar-width:none + the -webkit- override,
    same pattern .tabbar already uses) -- still scrollable, just no
    visible track. A third follow-up ("I would like to have it have the min
    height a bit bigger") caught that 26px (the exact content height of one
    row, no slack) read as cramped -- bumped to 36px, still a fixed height
    either way."""

    def test_panel_body_has_a_fixed_height_with_its_own_scroll(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert "#unscheduled-panel-body{height:36px; overflow-y:auto; scrollbar-width:none;}" in css
        assert "#unscheduled-panel-body::-webkit-scrollbar{display:none;}" in css
        # A max-height (not a fixed height) would still shrink/grow with
        # content and reintroduce the exact reflow this fix removes.
        assert "#unscheduled-panel-body{max-height:" not in css


class TestUnscheduledPanelToggleStaysOnTheRight:
    """Direct follow-up report (2026-09-08), same session as the two classes
    above: collapsing the "Unscheduled work" panel moved its toggle button
    from the right edge of the header to the left. Root cause:
    `.unscheduled-panel-head` is `justify-content:space-between` with two
    children (the h2 title + the toggle button) -- collapsing hides the h2
    (`display:none`), leaving the toggle as the row's ONLY flex item, and
    `space-between` puts a lone flex item at flex-start (left), not
    flex-end. Fix: `#unscheduled-panel-toggle{margin-left:auto;}` pins it to
    the row's own right edge regardless of whether its sibling is present in
    layout."""

    def test_toggle_has_margin_left_auto(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert "#unscheduled-panel-toggle{margin-left:auto;}" in css


class TestGridDragConflictFix:
    """Direct feedback, confirmed live (2026-08-14): dragging a task from the
    Unscheduled work panel onto the merged Week grid showed a 30-minute-tall
    hover ghost mid-drag (calendar.js's own click-to-create preview, now also
    running on this page since the grid columns carry `.calendar-create-col`
    too) even though the drop always creates a 60-minute (DEFAULT_BLOCK_
    MINUTES) work allocation -- the preview and the outcome disagreed.
    Structural source checks only (no browser in this test environment,
    same convention as test_pwa_shell.py's own JS structural checks) --
    `window.__ccGridDragActive` is set by every project_calendar.js drag
    (task-panel drag, block move/resize) and checked by calendar.js's own
    hover-preview before it shows/updates its ghost, and project_calendar.js
    now renders its OWN properly-sized (DEFAULT_BLOCK_MINUTES-tall) slot
    preview inside the hovered column instead."""

    def test_calendar_js_checks_the_suppression_flag(self):
        script = (_STATIC_DIR / "calendar.js").read_text()
        assert "window.__ccGridDragActive" in script

    def test_project_calendar_js_sets_the_flag_on_every_drag_start(self):
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        assert script.count("window.__ccGridDragActive = true") >= 2  # task-panel drag + block move/resize
        assert "window.__ccGridDragActive = false" in script

    def test_project_calendar_js_renders_a_real_sized_slot_preview(self):
        script = (_STATIC_DIR / "project_calendar.js").read_text()
        assert "slotGhost" in script
        assert "DEFAULT_BLOCK_MINUTES" in script
        assert 'slotGhost.className = "schedule-ghost"' in script


class TestWeekGridAsyncCrud:
    """async-CRUD (features/async-crud.md) for the merged Week grid: the
    work-allocation create/move/delete endpoints stay dual-mode -- plain 303
    redirect to /calendar/week without the fetch header (no-JS forms keep
    working), JSON when `X-Requested-With: fetch` (project_calendar.js now
    POSTs through ccApi instead of submitting a hidden form), so a drag no
    longer reloads the page. And `GET /calendar/regions?region=week` renders
    the #week-grid fragment async_calendar.js swaps in after such a change."""

    def test_create_allocation_is_dual_mode(self, conn):
        _task(conn, "t1", title="Research")
        resp = calendar_router.create_week_allocation(
            task_uid="t1",
            start_at=f"{_MONDAY}T16:00:00",
            end_at=f"{_MONDAY}T18:00:00",
            date_=_MONDAY,
            x_requested_with="fetch",
            conn=conn,
        )
        assert resp.status_code == 200
        assert resp.body.decode() == '{"ok":true}'
        assert len(db.list_work_allocations_for_task(conn, "t1")) == 1

    def test_move_allocation_is_dual_mode(self, conn):
        _task(conn, "t1", title="Research")
        uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = calendar_router.move_week_allocation(
            event_uid=uid,
            start_at=f"{_MONDAY}T09:00:00",
            end_at=f"{_MONDAY}T10:00:00",
            date_=_MONDAY,
            x_requested_with="fetch",
            conn=conn,
        )
        assert resp.status_code == 200
        assert db.get_event(conn, uid)["start_at"] == f"{_MONDAY}T09:00:00"

    def test_delete_allocation_is_dual_mode(self, conn):
        _task(conn, "t1", title="Research")
        uid = db.create_work_allocation(conn, "t1", f"{_MONDAY}T16:00:00", f"{_MONDAY}T18:00:00")
        resp = calendar_router.delete_week_allocation(event_uid=uid, date_=_MONDAY, x_requested_with="fetch", conn=conn)
        assert resp.status_code == 200
        assert db.get_event(conn, uid)["start_at"] is None  # unscheduled, not deleted

    def test_week_region_renders_the_week_grid_fragment(self, conn):
        _task(conn, "t1", title="Research")
        resp = calendar_router.calendar_regions(_request(query_string=b"region=week&date_=" + _MONDAY.encode()), region="week", date_=_MONDAY, conn=conn)
        body = resp.body.decode()
        assert 'id="week-grid"' in body
        assert 'id="unscheduled-panel"' in body
        assert 'time-col calendar-create-col project-calendar-col' in body
