"""Tests for routers/dashboard.py: widget filtering (project/tag/list),
each widget renderer's data shape, default-widget seeding, and the
add/edit/reorder/delete wiring. No bridge/Radicale dependency -- all
reads here go through db.py directly."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from src import db
from src.routers import dashboard as dashboard_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, list_path="tasks", due_at=None, tags=None, status="active"):
    db.upsert_task(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": "tasks", "list_path": list_path,
        "title": uid, "description": "", "status": status, "due_at": due_at,
        "tags": tags or [], "created_at": _now(),
    })


def _seed_event(conn, uid, calendar_path="calendar", start_at=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "href": f"/{uid}", "calendar_path": calendar_path, "title": uid,
        "description": "", "status": "active", "all_day": 0, "start_at": start_at,
        "tags": tags or [], "created_at": _now(),
    })


class TestDefaultWidgetSeeding:
    def test_seeds_default_widgets_on_first_visit(self, conn):
        # 2026-08-03 §1 Dashboard rework: first two defaults are now
        # calendar_agenda (third/30%) and today_agenda (two_thirds/70%)
        # side by side, replacing the old mini_month_calendar + today_agenda
        # pairing -- see dashboard_router._DEFAULT_WIDGETS.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        assert [w["type"] for w in widgets] == ["calendar_agenda", "today_agenda", "weekly_overview", "upcoming_events"]

    def test_default_seed_sets_width_on_first_two_widgets(self, conn):
        # calendar_agenda gets third (30%) and today_agenda gets two_thirds
        # (70%) so the side-by-side layout is correct out of the box.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        assert widgets[0]["config"]["width"] == "third"
        assert widgets[1]["config"]["width"] == "two_thirds"

    def test_is_a_noop_once_any_widget_exists(self, conn):
        dashboard_router._ensure_default_widgets(conn)
        db.delete_dashboard_widget(conn, db.list_dashboard_widgets(conn)[0]["uid"])
        dashboard_router._ensure_default_widgets(conn)
        # One fewer than the full default set (one deleted) -- re-seeding
        # must not top it back up, since "any widget exists" already made
        # it a no-op.
        assert len(db.list_dashboard_widgets(conn)) == len(dashboard_router._DEFAULT_WIDGETS) - 1


class TestFiltering:
    def test_tag_filter(self, conn):
        _seed_task(conn, "t1", due_at=date.today().isoformat(), tags=["uni"])
        _seed_task(conn, "t2", due_at=date.today().isoformat(), tags=["personal"])
        result = dashboard_router._filtered_tasks(conn, {"tags": ["uni"]})
        assert {t["uid"] for t in result} == {"t1"}

    def test_project_filter_resolves_through_list(self, conn):
        db.upsert_project(conn, {"uid": "p1", "name": "Uni", "created_at": _now(), "updated_at": _now()})
        db.upsert_task_list(conn, {"uid": "hw", "name": "Homework", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", "p1")
        db.upsert_task_list(conn, {"uid": "other", "name": "Other", "color": "green", "created_at": _now()})
        _seed_task(conn, "t1", list_path="hw")
        _seed_task(conn, "t2", list_path="other")
        result = dashboard_router._filtered_tasks(conn, {"project_uid": "p1"}, open_only=False)
        assert {t["uid"] for t in result} == {"t1"}

    def test_group_filter_resolves_through_projects(self, conn):
        # Step 2a (spaces-home-pipeline, 2026-08-02) -- config["group_uid"]
        # pools every project under that group, same as project_uid pools
        # every list under one project, one level up.
        db.upsert_project_group(conn, {"uid": "g1", "name": "University", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "CS101", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        db.upsert_project(conn, {"uid": "p2", "name": "MATH201", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        db.upsert_project(conn, {"uid": "p3", "name": "Personal", "created_at": _now(), "updated_at": _now()})
        db.upsert_task_list(conn, {"uid": "hw1", "name": "HW1", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw1", "p1")
        db.upsert_task_list(conn, {"uid": "hw2", "name": "HW2", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw2", "p2")
        db.upsert_task_list(conn, {"uid": "other", "name": "Other", "color": "green", "created_at": _now()})
        db.set_task_list_project(conn, "other", "p3")
        _seed_task(conn, "t1", list_path="hw1")
        _seed_task(conn, "t2", list_path="hw2")
        _seed_task(conn, "t3", list_path="other")
        result = dashboard_router._filtered_tasks(conn, {"group_uid": "g1"}, open_only=False)
        assert {t["uid"] for t in result} == {"t1", "t2"}

    def test_group_filter_with_no_matching_projects_returns_nothing(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "Empty group", "created_at": _now()})
        _seed_task(conn, "t1")
        result = dashboard_router._filtered_tasks(conn, {"group_uid": "g1"}, open_only=False)
        assert result == []

    def test_list_uids_filter(self, conn):
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.upsert_task_list(conn, {"uid": "other", "name": "Other", "color": "green", "created_at": _now()})
        _seed_task(conn, "t1", list_path="hw")
        _seed_task(conn, "t2", list_path="other")
        result = dashboard_router._filtered_tasks(conn, {"list_uids": ["hw"]}, open_only=False)
        assert {t["uid"] for t in result} == {"t1"}

    def test_open_only_excludes_done_and_archived(self, conn):
        _seed_task(conn, "t1", status="active")
        _seed_task(conn, "t2", status="done")
        _seed_task(conn, "t3", status="archived")
        result = dashboard_router._filtered_tasks(conn, {})
        assert {t["uid"] for t in result} == {"t1"}

    def test_no_filters_returns_everything_open(self, conn):
        _seed_task(conn, "t1")
        _seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {})
        assert {t["uid"] for t in result} == {"t1", "t2"}


class TestTodayAgendaWidget:
    def test_includes_overdue_and_today_excludes_future(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=2)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "future", due_at=(today + timedelta(days=3)).isoformat())
        data = dashboard_router._render_today_agenda(conn, {})
        assert {t["uid"] for t in data["tasks"]} == {"overdue", "today"}

    def test_events_only_today(self, conn):
        today = date.today()
        _seed_event(conn, "e_today", start_at=f"{today.isoformat()}T09:00:00")
        _seed_event(conn, "e_tomorrow", start_at=f"{(today + timedelta(days=1)).isoformat()}T09:00:00")
        data = dashboard_router._render_today_agenda(conn, {})
        assert {e["uid"] for e in data["events"]} == {"e_today"}


class TestWeeklyOverviewWidget:
    def test_groups_by_day_across_next_seven_days(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=today.isoformat())
        _seed_task(conn, "t2", due_at=(today + timedelta(days=3)).isoformat())
        _seed_task(conn, "t_out_of_range", due_at=(today + timedelta(days=10)).isoformat())
        data = dashboard_router._render_weekly_overview(conn, {})
        assert len(data["days"]) == 7
        assert data["days"][0]["is_today"] is True
        all_task_uids = {t["uid"] for day in data["days"] for t in day["tasks"]}
        assert all_task_uids == {"t1", "t2"}


class TestUpcomingEventsWidget:
    def test_only_future_events_chronological(self, conn):
        now = datetime.now(timezone.utc)
        _seed_event(conn, "past", start_at=(now - timedelta(days=1)).isoformat())
        _seed_event(conn, "soon", start_at=(now + timedelta(days=1)).isoformat())
        _seed_event(conn, "later", start_at=(now + timedelta(days=5)).isoformat())
        data = dashboard_router._render_upcoming_events(conn, {})
        assert [e["uid"] for e in data["events"]] == ["soon", "later"]

    def test_respects_limit(self, conn):
        now = datetime.now(timezone.utc)
        for i in range(5):
            _seed_event(conn, f"e{i}", start_at=(now + timedelta(days=i + 1)).isoformat())
        data = dashboard_router._render_upcoming_events(conn, {"limit": 2})
        assert len(data["events"]) == 2


class TestOverdueTasksWidget:
    def test_only_overdue_open_tasks(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "done_overdue", due_at=(today - timedelta(days=2)).isoformat(), status="done")
        data = dashboard_router._render_overdue_tasks(conn, {})
        assert {t["uid"] for t in data["tasks"]} == {"overdue"}


class TestWidgetCRUD:
    def test_add_widget(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="My Agenda", project_uid="", tags="uni, urgent",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["title"] == "My Agenda"
        assert w["type"] == "today_agenda"
        assert w["config"]["tags"] == ["uni", "urgent"]

    def test_add_widget_with_unknown_source_is_a_noop(self, conn):
        dashboard_router.add_widget(
            source="not_a_real_source", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        assert db.list_dashboard_widgets(conn) == []

    def test_add_widget_resolves_every_source_view_range_combo(self, conn):
        # Every entry in _SELECTION_TO_TYPE should be reachable through
        # the real add_widget entry point, not just the internal resolver
        # -- 2026-08-02's Source/View/Range rework.
        for (view, range_), (expected_type, expected_range_days) in dashboard_router._SELECTION_TO_TYPE.items():
            source = dashboard_router.WIDGET_VIEWS[view]["source"]
            dashboard_router.add_widget(
                source=source, view=view, range=range_ or "", title="", project_uid="", tags="",
                task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
            )
            w = db.list_dashboard_widgets(conn)[-1]
            assert w["type"] == expected_type
            assert w["config"].get("range_days") == expected_range_days

    def test_edit_widget_updates_config(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="upcoming_list", range="all_upcoming", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.edit_widget(w["uid"], source="calendar_tasks", view="upcoming_list", range="all_upcoming", title="Renamed", project_uid="", tags="focus", task_list_uids=[], calendar_uids=[], limit="5", conn=conn)
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["title"] == "Renamed"
        assert updated["config"]["tags"] == ["focus"]
        assert updated["config"]["limit"] == 5

    def test_edit_widget_can_change_source_view_range(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.edit_widget(w["uid"], source="calendar_tasks", view="agenda", range="next_7_days", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn)
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["type"] == "weekly_overview"
        assert updated["config"]["range_days"] == 7

    def test_delete_widget(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.delete_widget(w["uid"], conn=conn)
        assert db.list_dashboard_widgets(conn) == []

    def test_legacy_widget_with_empty_config_reverse_maps_correctly(self, conn):
        # Every dashboard seeded before 2026-08-02's Source/View/Range
        # rework has widgets stored with `config == {}` -- no range_days
        # at all, since that key didn't exist yet. _render_weekly_overview
        # itself defaults an absent range_days to 7, so the reverse
        # mapping used to pre-fill the Filters form has to treat
        # (weekly_overview, None) the same as (weekly_overview, 7), or
        # opening an old Weekly Overview widget's Filters panel would show
        # (and on Save, silently change it to) Today's Agenda instead.
        widget = {"uid": "x", "type": "weekly_overview", "config": {}}
        assert dashboard_router._selection_from_widget(widget) == ("calendar_tasks", "agenda", "next_7_days")

    def test_move_widget_up_and_down(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="agenda", range="today", title="A", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        dashboard_router.add_widget(source="calendar_tasks", view="agenda", range="next_7_days", title="B", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        assert [w["title"] for w in widgets] == ["A", "B"]

        dashboard_router.move_widget(widgets[1]["uid"], direction="up", conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        assert [w["title"] for w in widgets] == ["B", "A"]

        dashboard_router.move_widget(widgets[0]["uid"], direction="up", conn=conn)  # already topmost
        widgets = db.list_dashboard_widgets(conn)
        assert [w["title"] for w in widgets] == ["B", "A"]


class TestWidgetHeight:
    """2026-08-02 -- "a way to resize them vertically and all the widgets
    having a specific values for their width and height, not any
    height." Exact mirror of width's WIDGET_WIDTHS/_widget_width/
    /resize, just the other axis and its own config key -- see
    dashboard.py's WIDGET_HEIGHTS/_widget_height/resize_widget_height."""

    def _add(self, conn, view="agenda", range_="today"):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        return db.list_dashboard_widgets(conn)[-1]

    def test_default_height_comes_from_the_widget_type(self, conn):
        w = self._add(conn)  # today_agenda -> default_height "medium"
        height = dashboard_router._widget_height(w, dashboard_router.WIDGET_TYPES["today_agenda"])
        assert height["key"] == "medium"
        assert height["px"] == dashboard_router.WIDGET_HEIGHTS["medium"]["px"]

    def test_unknown_type_falls_back_to_medium(self, conn):
        height = dashboard_router._widget_height({"config": {}}, None)
        assert height["key"] == "medium"

    def test_resize_sets_config_height(self, conn):
        w = self._add(conn)
        resp = dashboard_router.resize_widget_height(w["uid"], height="tall", conn=conn)
        assert resp.status_code == 200
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["config"]["height"] == "tall"
        assert dashboard_router._widget_height(updated, None)["key"] == "tall"

    def test_resize_rejects_invalid_height(self, conn):
        w = self._add(conn)
        resp = dashboard_router.resize_widget_height(w["uid"], height="huge", conn=conn)
        assert resp.status_code == 400
        assert db.get_dashboard_widget(conn, w["uid"])["config"].get("height") is None

    def test_resize_unknown_widget_404s(self, conn):
        resp = dashboard_router.resize_widget_height("does-not-exist", height="tall", conn=conn)
        assert resp.status_code == 404

    def test_edit_widget_preserves_height_like_it_preserves_width(self, conn):
        w = self._add(conn)
        dashboard_router.resize_widget(w["uid"], width="third", conn=conn)
        dashboard_router.resize_widget_height(w["uid"], height="xl", conn=conn)
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="next_7_days", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["config"]["width"] == "third"
        assert updated["config"]["height"] == "xl"

    def test_stacked_widgets_keep_independent_heights(self, conn):
        # Unlike width, height is NOT shared across a stack's members --
        # each keeps whatever it had before being stacked (dashboard.py's
        # _dissolve_stack docstring explains why: stack members render
        # one above another, so "same height" doesn't mean the same
        # thing "same width, side by side" does).
        a = self._add(conn)
        b = self._add(conn)
        dashboard_router.resize_widget_height(a["uid"], height="short", conn=conn)
        dashboard_router.resize_widget_height(b["uid"], height="xl", conn=conn)
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        assert db.get_dashboard_widget(conn, a["uid"])["config"]["height"] == "short"
        assert db.get_dashboard_widget(conn, b["uid"])["config"]["height"] == "xl"


class TestWidgetStacking:
    """2026-08-02: stacking pins two+ widgets together into one grid slot,
    same shared width, immune to the rest of the dashboard reflowing
    around them -- see stack_widget/unstack_widget/_dissolve_stack in
    routers/dashboard.py."""

    def _add(self, conn, title, view="agenda", range_="today"):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title=title, project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        return db.list_dashboard_widgets(conn)[-1]

    def test_stack_onto_plain_widget_creates_a_stack(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        resp = dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        assert resp.status_code == 200

        widgets = db.list_dashboard_widgets(conn)
        stacks = [w for w in widgets if w["type"] == "stack"]
        assert len(stacks) == 1
        stack_uid = stacks[0]["uid"]

        members = sorted((w for w in widgets if w.get("group_uid") == stack_uid), key=lambda w: w["position"])
        assert [w["title"] for w in members] == ["A", "B"]
        # Neither member should still look like a top-level widget.
        assert all(w.get("group_uid") == stack_uid for w in members)

    def test_stack_onto_existing_stack_appends_at_the_end(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")

        dashboard_router.stack_widget(c["uid"], target_uid=stack_uid, conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        members = sorted((w for w in widgets if w.get("group_uid") == stack_uid), key=lambda w: w["position"])
        assert [w["title"] for w in members] == ["A", "B", "C"]

    def test_stacked_widgets_share_the_stack_width_not_their_own(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        dashboard_router.edit_widget(
            a["uid"], source="calendar_tasks", view="agenda", range="today", title="A", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        stack = next(w for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        # New stack inherits the target's own effective width (its
        # config.width, or the type's default_width if unset).
        assert stack["config"]["width"] in dashboard_router.WIDGET_WIDTHS

    def test_a_stack_cannot_be_stacked_onto_something_else(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        resp = dashboard_router.stack_widget(stack_uid, target_uid=c["uid"], conn=conn)
        assert resp.status_code == 400

    def test_unstack_pops_widget_back_to_top_level(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        dashboard_router.stack_widget(c["uid"], target_uid=a["uid"], conn=conn)

        dashboard_router.unstack_widget(c["uid"], conn=conn)
        updated_c = db.get_dashboard_widget(conn, c["uid"])
        assert updated_c["group_uid"] is None
        # Stack still has 2 members (A, B) -- shouldn't have dissolved.
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        remaining = [w for w in db.list_dashboard_widgets(conn) if w.get("group_uid") == stack_uid]
        assert len(remaining) == 2

    def test_unstacking_down_to_one_member_dissolves_the_stack(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)

        dashboard_router.unstack_widget(b["uid"], conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        # The stack itself should be gone, and A should be a plain
        # top-level widget again.
        assert not any(w["type"] == "stack" for w in widgets)
        updated_a = db.get_dashboard_widget(conn, a["uid"])
        assert updated_a["group_uid"] is None

    def test_deleting_a_stack_dissolves_it_instead_of_destroying_members(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")

        dashboard_router.delete_widget(stack_uid, conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        assert not any(w["type"] == "stack" for w in widgets)
        # Both A and B must still exist, just ungrouped.
        titles = sorted(w["title"] for w in widgets)
        assert titles == ["A", "B"]
        assert all(w.get("group_uid") is None for w in widgets)

    def test_deleting_one_member_leaves_a_two_member_stack_intact(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        dashboard_router.stack_widget(c["uid"], target_uid=a["uid"], conn=conn)

        # Delete a plain top-level widget unrelated to the stack -- should
        # never touch the stack at all.
        d = self._add(conn, "D")
        dashboard_router.delete_widget(d["uid"], conn=conn)
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        assert len([w for w in db.list_dashboard_widgets(conn) if w.get("group_uid") == stack_uid]) == 3

    def test_deleting_a_member_down_to_one_dissolves_the_stack(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)

        dashboard_router.delete_widget(b["uid"], conn=conn)
        widgets = db.list_dashboard_widgets(conn)
        assert not any(w["type"] == "stack" for w in widgets)
        updated_a = db.get_dashboard_widget(conn, a["uid"])
        assert updated_a is not None
        assert updated_a["group_uid"] is None

    def test_reorder_ignores_stack_members_position_scale(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        # Reordering C should only ever consider other top-level widgets
        # (the stack itself, not A/B individually) -- must not 400/error
        # out or silently corrupt anything by comparing against a stack
        # member's own intra-group position.
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        resp = dashboard_router.reorder_widget(c["uid"], after_uid=stack_uid, conn=conn)
        assert resp.status_code == 200
        top_level = [w for w in db.list_dashboard_widgets(conn) if not w.get("group_uid")]
        assert [w["uid"] for w in top_level] == [stack_uid, c["uid"]]

    def test_reorder_within_a_stack(self, conn):
        # 2026-08-02: reorder_widget scopes itself by the moved widget's
        # own group_uid now, so the same endpoint that reorders top-level
        # widgets also reorders a stack's members -- static/app.js's
        # dedicated intra-stack drag handler posts here too.
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        stack_uid = next(w["uid"] for w in db.list_dashboard_widgets(conn) if w["type"] == "stack")
        dashboard_router.stack_widget(c["uid"], target_uid=stack_uid, conn=conn)  # appends at the end
        members = sorted((w for w in db.list_dashboard_widgets(conn) if w.get("group_uid") == stack_uid), key=lambda w: w["position"])
        assert [w["title"] for w in members] == ["A", "B", "C"]

        # Move A (currently first) to land after C (currently last).
        resp = dashboard_router.reorder_widget(a["uid"], after_uid=c["uid"], conn=conn)
        assert resp.status_code == 200
        members = sorted((w for w in db.list_dashboard_widgets(conn) if w.get("group_uid") == stack_uid), key=lambda w: w["position"])
        assert [w["title"] for w in members] == ["B", "C", "A"]

        # Top-level order must be completely untouched by an intra-stack
        # reorder -- still just [stack].
        top_level = [w for w in db.list_dashboard_widgets(conn) if not w.get("group_uid")]
        assert [w["uid"] for w in top_level] == [stack_uid]

    def test_reorder_rejects_after_uid_from_a_different_collection(self, conn):
        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        # C is top-level; B is inside the stack -- can't reorder C to land
        # after a widget that belongs to a different collection.
        resp = dashboard_router.reorder_widget(c["uid"], after_uid=b["uid"], conn=conn)
        assert resp.status_code == 400

    def test_dashboard_view_nests_stack_children_and_excludes_them_from_top_level(self, conn):
        from starlette.requests import Request

        a = self._add(conn, "A")
        b = self._add(conn, "B")
        c = self._add(conn, "C")
        dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        # Not what this test is about -- skip the one-time mini-calendar
        # backfill migration (dashboard_view always runs it) so it
        # doesn't add an unrelated fourth top-level widget here.
        db.set_app_meta(conn, dashboard_router._MINI_CALENDAR_BACKFILL_KEY, "1")

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        contexts = resp.context["widget_contexts"]

        # Top level: the stack (containing A, B) + C. A and B must not
        # also appear as their own top-level entries.
        assert len(contexts) == 2
        stack_ctx = next(ctx for ctx in contexts if ctx["is_stack"])
        assert [child["widget"]["title"] for child in stack_ctx["children"]] == ["A", "B"]
        assert not any(ctx["widget"]["uid"] in (a["uid"], b["uid"]) for ctx in contexts if not ctx["is_stack"])


class TestDashboardRoute:
    def test_renders_with_seeded_defaults(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        assert resp.status_code == 200
        assert len(resp.context["widget_contexts"]) == len(dashboard_router._DEFAULT_WIDGETS)

    def test_renders_in_edit_mode_with_the_add_widget_form(self, conn):
        # Smoke test for the Add-widget form/Filters panel/masonry grid
        # markup moved into _widget_workspace.html (2026-08-02) -- only
        # rendered at all when edit_mode is truthy, so the non-edit render
        # above wouldn't have caught a syntax error in that branch.
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, edit=True, conn=conn)
        assert resp.status_code == 200
        assert b"Add widget" in resp.body

    def test_edit_mode_renders_the_vertical_resize_handle_per_widget(self, conn):
        # 2026-08-02 -- confirms widget_inner's .widget-content wrapper +
        # .widget-resize-handle-vertical actually reach the page for every
        # seeded default widget, not just that the route doesn't 500.
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, edit=True, conn=conn)
        body = resp.body.decode()
        assert body.count("widget-resize-handle-vertical") == len(dashboard_router._DEFAULT_WIDGETS)
        assert 'class="widget-content"' in body


class TestSpaceWidgets:
    """Per-space widget grid (2026-08-02 follow-up to spaces-home-pipeline)
    -- a Space page gets the exact same add/edit/resize/stack/reorder
    machinery as Home, scoped via space_uid, and every widget added from a
    Space auto-scopes to it via config['group_uid']."""

    def _add(self, conn, title, space_uid="", view="agenda", range_="today"):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title=title, project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid=space_uid, conn=conn,
        )
        return db.list_dashboard_widgets(conn, space_uid=space_uid or None)[-1]

    def test_add_widget_is_scoped_to_the_space_and_auto_group_filtered(self, conn):
        w = self._add(conn, "Space Widget", space_uid="space1")
        assert w["space_uid"] == "space1"
        assert w["config"]["group_uid"] == "space1"
        # Doesn't leak into Home's own (space_uid=None) list.
        assert db.list_dashboard_widgets(conn) == []

    def test_add_widget_redirects_back_to_the_space_page(self, conn):
        resp = dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="space1", conn=conn,
        )
        assert resp.headers["location"] == "/projects/groups/space1"

    def test_add_widget_with_no_space_uid_redirects_home(self, conn):
        resp = dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        assert resp.headers["location"] == "/"

    def test_home_and_two_spaces_have_independent_widget_lists(self, conn):
        self._add(conn, "Home widget")
        self._add(conn, "Space1 widget", space_uid="space1")
        self._add(conn, "Space2 widget", space_uid="space2")
        assert [w["title"] for w in db.list_dashboard_widgets(conn)] == ["Home widget"]
        assert [w["title"] for w in db.list_dashboard_widgets(conn, space_uid="space1")] == ["Space1 widget"]
        assert [w["title"] for w in db.list_dashboard_widgets(conn, space_uid="space2")] == ["Space2 widget"]

    def test_edit_widget_preserves_space_scope(self, conn):
        w = self._add(conn, "Original", space_uid="space1")
        resp = dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="today", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["title"] == "Renamed"
        assert updated["config"]["group_uid"] == "space1"  # not clobbered by the edit form
        assert resp.headers["location"] == "/projects/groups/space1"

    def test_delete_widget_redirects_to_its_own_space(self, conn):
        w = self._add(conn, "A", space_uid="space1")
        resp = dashboard_router.delete_widget(w["uid"], conn=conn)
        assert resp.headers["location"] == "/projects/groups/space1"
        assert db.get_dashboard_widget(conn, w["uid"]) is None

    def test_reorder_does_not_mix_widgets_from_different_pages(self, conn):
        home_a = self._add(conn, "Home A")
        home_b = self._add(conn, "Home B")
        space_a = self._add(conn, "Space A", space_uid="space1")
        # Reorder home_b to land after space_a's uid -- should be rejected
        # since space_a isn't in home_b's own collection (space_uid=None).
        resp = dashboard_router.reorder_widget(home_b["uid"], after_uid=space_a["uid"], conn=conn)
        assert resp.status_code == 400

    def test_stack_onto_rejects_widgets_from_different_pages(self, conn):
        home_a = self._add(conn, "Home A")
        space_a = self._add(conn, "Space A", space_uid="space1")
        resp = dashboard_router.stack_widget(home_a["uid"], target_uid=space_a["uid"], conn=conn)
        assert resp.status_code == 400

    def test_stack_onto_within_the_same_space_works(self, conn):
        a = self._add(conn, "A", space_uid="space1")
        b = self._add(conn, "B", space_uid="space1")
        resp = dashboard_router.stack_widget(b["uid"], target_uid=a["uid"], conn=conn)
        assert resp.status_code == 200
        stack_uid = json.loads(resp.body)["stack_uid"]
        stack = db.get_dashboard_widget(conn, stack_uid)
        assert stack["space_uid"] == "space1"


class TestCalendarAgendaWidget:
    """§1 Dashboard rework, 2026-08-03 -- calendar_agenda combines
    _render_mini_month_calendar + _render_weekly_overview into one dict
    so the template can render the month grid above and the agenda below."""

    def test_returns_calendar_and_agenda_keys(self, conn):
        data = dashboard_router._render_calendar_agenda(conn, {})
        assert "calendar" in data
        assert "agenda" in data

    def test_calendar_sub_dict_has_weeks_and_month_label(self, conn):
        data = dashboard_router._render_calendar_agenda(conn, {})
        assert "weeks" in data["calendar"]
        assert "month_label" in data["calendar"]

    def test_agenda_sub_dict_has_7_days(self, conn):
        data = dashboard_router._render_calendar_agenda(conn, {})
        assert len(data["agenda"]["days"]) == 7

    def test_group_uid_scoping_filters_tasks_in_both_sub_renders(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "Uni", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "CS101", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        db.upsert_task_list(conn, {"uid": "hw", "name": "HW", "color": "blue", "created_at": _now()})
        db.set_task_list_project(conn, "hw", "p1")
        today = date.today()
        _seed_task(conn, "t_in", list_path="hw", due_at=today.isoformat())
        _seed_task(conn, "t_out", due_at=today.isoformat())
        data = dashboard_router._render_calendar_agenda(conn, {"group_uid": "g1"})
        all_agenda_task_uids = {t["uid"] for day in data["agenda"]["days"] for t in day["tasks"]}
        assert "t_in" in all_agenda_task_uids
        assert "t_out" not in all_agenda_task_uids

    def test_registered_in_widget_types(self, conn):
        assert "calendar_agenda" in dashboard_router.WIDGET_TYPES
        spec = dashboard_router.WIDGET_TYPES["calendar_agenda"]
        assert spec["default_width"] == "third"
        assert spec["default_height"] == "xl"

    def test_registered_in_selection_tables(self, conn):
        assert ("calendar_agenda_view", None) in dashboard_router._SELECTION_TO_TYPE
        assert ("calendar_agenda", None) in dashboard_router._TYPE_TO_SELECTION


class TestContactListWidget:
    """§2 Spaces v2, 2026-08-03 -- contact_list widget filters contacts by
    tags matching the space's group project names (via group_uid) or
    explicit config['tags']."""

    def _seed_contact(self, conn, uid, full_name, tags=None):
        db.upsert_contact(conn, {
            "uid": uid, "href": f"/{uid}", "addressbook_path": "contacts",
            "full_name": full_name, "tags": tags or [], "created_at": _now(),
        })

    def test_returns_contacts_key(self, conn):
        data = dashboard_router._render_contact_list(conn, {})
        assert "contacts" in data

    def test_no_filter_returns_all_contacts(self, conn):
        self._seed_contact(conn, "c1", "Alice")
        self._seed_contact(conn, "c2", "Bob")
        data = dashboard_router._render_contact_list(conn, {})
        assert {c["uid"] for c in data["contacts"]} == {"c1", "c2"}

    def test_explicit_tags_filter(self, conn):
        self._seed_contact(conn, "c1", "Alice", tags=["professor"])
        self._seed_contact(conn, "c2", "Bob", tags=["student"])
        data = dashboard_router._render_contact_list(conn, {"tags": ["professor"]})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}

    def test_group_uid_scoping_uses_project_names_as_tags(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "Uni", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "CS101", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        self._seed_contact(conn, "c1", "Alice", tags=["CS101"])
        self._seed_contact(conn, "c2", "Bob", tags=["Personal"])
        data = dashboard_router._render_contact_list(conn, {"group_uid": "g1"})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}

    def test_limit_caps_results(self, conn):
        for i in range(5):
            self._seed_contact(conn, f"c{i}", f"Contact {i}", tags=["tagged"])
        data = dashboard_router._render_contact_list(conn, {"tags": ["tagged"], "limit": 3})
        assert len(data["contacts"]) == 3

    def test_registered_in_widget_types(self, conn):
        assert "contact_list" in dashboard_router.WIDGET_TYPES
        spec = dashboard_router.WIDGET_TYPES["contact_list"]
        assert spec["default_width"] == "third"

    def test_registered_in_selection_tables(self, conn):
        assert ("contact_list_view", None) in dashboard_router._SELECTION_TO_TYPE
        assert ("contact_list", None) in dashboard_router._TYPE_TO_SELECTION


class TestDefaultSpaceWidgets:
    """§2 Spaces v2, 2026-08-03 -- _DEFAULT_SPACE_WIDGETS now seeds
    calendar_agenda + weekly_overview (30/70) + project_preview + habit_checkin."""

    def test_seeds_four_defaults_for_a_new_space(self, conn):
        dashboard_router._ensure_default_space_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        types = [w["type"] for w in widgets]
        assert "calendar_agenda" in types
        assert "weekly_overview" in types
        assert "project_preview" in types
        assert "habit_checkin" in types

    def test_calendar_agenda_seeded_with_third_width(self, conn):
        dashboard_router._ensure_default_space_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        cal_widget = next(w for w in widgets if w["type"] == "calendar_agenda")
        assert cal_widget["config"]["width"] == "third"

    def test_weekly_overview_seeded_with_range_days_7(self, conn):
        dashboard_router._ensure_default_space_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        wo_widget = next(w for w in widgets if w["type"] == "weekly_overview")
        assert wo_widget["config"]["range_days"] == 7

    def test_all_space_widgets_auto_scoped_with_group_uid(self, conn):
        dashboard_router._ensure_default_space_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        assert all(w["config"].get("group_uid") == "space1" for w in widgets)


class TestSpaceScopedRenderers:
    """_render_project_preview and _render_habit_checkin both need to
    resolve config['group_uid'] the same way _filtered_tasks/_filtered_
    events already do, since a Space's default widgets use group_uid, not
    project_uid, to auto-scope (2026-08-02)."""

    def test_project_preview_group_filter(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "Uni", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "CS101", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        db.upsert_project(conn, {"uid": "p2", "name": "Personal", "created_at": _now(), "updated_at": _now()})
        data = dashboard_router._render_project_preview(conn, {"group_uid": "g1"})
        assert [pv["project"]["uid"] for pv in data["previews"]] == ["p1"]

    def test_habit_checkin_group_filter(self, conn):
        db.upsert_project_group(conn, {"uid": "g1", "name": "Uni", "created_at": _now()})
        db.upsert_project(conn, {"uid": "p1", "name": "CS101", "group_uid": "g1", "created_at": _now(), "updated_at": _now()})
        db.upsert_habit(conn, {"uid": "h1", "name": "Study", "project_uid": "p1", "created_at": _now(), "updated_at": _now()})
        db.upsert_habit(conn, {"uid": "h2", "name": "Read", "created_at": _now(), "updated_at": _now()})
        data = dashboard_router._render_habit_checkin(conn, {"group_uid": "g1"})
        assert [r["habit"]["uid"] for r in data["rows"]] == ["h1"]
