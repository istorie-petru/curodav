"""Tests for routers/dashboard.py: widget filtering (project/tag/list),
each widget renderer's data shape, default-widget seeding, and the
add/edit/reorder/delete wiring. No bridge/Radicale dependency -- all
reads here go through db.py directly."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from src import db, deps
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
        "tags": tags or [], "created_at": _now(),
    })


def _seed_event(conn, uid, start_at=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": "active", "all_day": 0, "start_at": start_at,
        "tags": tags or [], "created_at": _now(),
    })


def _seed_recurring_event(conn, uid, start_at, end_at=None, recurrence=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": "active", "all_day": 0,
        "start_at": start_at, "end_at": end_at, "recurrence": recurrence,
        "tags": tags or [], "created_at": _now(),
    })


class TestDefaultWidgetSeeding:
    def test_seeds_default_widgets_on_first_visit(self, conn):
        # 2026-08-15 widget consolidation: default seed is Agenda (range=
        # today) + a stack of At a Glance / Agenda (all_upcoming, events
        # only) / Agenda (today, overdue only) -- see
        # dashboard_router._seed_agenda_stack_layout.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        assert [w["type"] for w in top_level] == ["agenda", "stack"]

        stack = top_level[1]
        members = sorted((w for w in widgets if w.get("group_uid") == stack["uid"]), key=lambda w: w["position"])
        assert [w["type"] for w in members] == ["at_a_glance", "agenda", "agenda"]
        assert members[1]["config"]["show"] == ["events"]
        assert members[2]["config"]["show"] == ["overdue"]

    def test_default_seed_sets_width_on_paired_widgets(self, conn):
        # The main Agenda widget and the stack share the width split
        # (half/half) so the side-by-side layout is correct out of the box.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        main_agenda = next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))
        stack = next(w for w in widgets if w["type"] == "stack")
        assert main_agenda["config"]["width"] == "half"
        assert stack["config"]["width"] == "half"

    def test_default_seed_no_longer_includes_removed_types(self, conn):
        # calendar_agenda/weekly_overview/mini_month_calendar are no
        # longer pre-seeded -- still addable manually via "New widget".
        dashboard_router._ensure_default_widgets(conn)
        types = {w["type"] for w in db.list_dashboard_widgets(conn)}
        assert types.isdisjoint({"calendar_agenda", "weekly_overview", "mini_month_calendar"})

    def test_seeds_default_widgets_on_first_visit_only(self, conn):
        # First call seeds the defaults and sets the app_meta flag.
        dashboard_router._ensure_default_widgets(conn)
        assert len(db.list_dashboard_widgets(conn)) == 5  # today_agenda + stack + 3 members
        assert db.get_app_meta(conn, dashboard_router._HOME_SEEDED_KEY) == "1"

    def test_does_not_reseed_after_all_widgets_deleted(self, conn):
        # Seed once, then delete every widget -- the flag is set, so a
        # second call must NOT re-seed. This is the fix for "delete all
        # widgets, reload, defaults reappear" (Scenario 1).
        dashboard_router._ensure_default_widgets(conn)
        for w in db.list_dashboard_widgets(conn):
            db.delete_dashboard_widget(conn, w["uid"])
        dashboard_router._ensure_default_widgets(conn)
        assert db.list_dashboard_widgets(conn) == []

    def test_reseed_is_a_one_time_thing_per_scope(self, conn):
        # Even on a completely fresh DB (no app_meta flag, no widgets),
        # calling _ensure_default_widgets twice must seed exactly once.
        dashboard_router._ensure_default_widgets(conn)
        first_count = len(db.list_dashboard_widgets(conn))
        dashboard_router._ensure_default_widgets(conn)
        second_count = len(db.list_dashboard_widgets(conn))
        assert first_count == 5
        assert second_count == first_count  # no duplicate seeding


class TestFiltering:
    def test_tag_filter(self, conn):
        _seed_task(conn, "t1", due_at=date.today().isoformat(), tags=["uni"])
        _seed_task(conn, "t2", due_at=date.today().isoformat(), tags=["personal"])
        result = dashboard_router._filtered_tasks(conn, {"tags": ["uni"]})
        assert {t["uid"] for t in result} == {"t1"}

    def test_project_filter_is_a_noop_since_task_lists_are_gone(self, conn):
        # Phase 1 (label-space rework, 2026-08-06) dropped `task_lists` --
        # there's no more list->project link to resolve a task's project
        # through (see db.py's Phase 1 comments and dashboard.py's
        # _passes_filters comment), so project_uid no longer narrows
        # anything; only the tags filter still applies.
        db.upsert_label_config(conn, {"name": "Uni", "created_at": _now()})
        _seed_task(conn, "t1")
        _seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {"project_uid": "p1"}, open_only=False)
        assert {t["uid"] for t in result} == {"t1", "t2"}

    def test_list_uids_filter_is_a_noop_since_task_lists_are_gone(self, conn):
        _seed_task(conn, "t1")
        _seed_task(conn, "t2")
        result = dashboard_router._filtered_tasks(conn, {"list_uids": ["hw"]}, open_only=False)
        assert {t["uid"] for t in result} == {"t1", "t2"}

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


class TestAgendaWidgetToday:
    """range="today" reproduces today_agenda's old content: overdue + due-
    today tasks (as separate Overdue/Tasks sections now) and today's
    events."""

    def test_includes_overdue_and_today_excludes_future(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=2)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "future", due_at=(today + timedelta(days=3)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}
        assert {t["uid"] for t in data["tasks"]} == {"today"}

    def test_events_only_today(self, conn):
        today = date.today()
        _seed_event(conn, "e_today", start_at=f"{today.isoformat()}T09:00:00")
        _seed_event(conn, "e_tomorrow", start_at=f"{(today + timedelta(days=1)).isoformat()}T09:00:00")
        data = dashboard_router._render_agenda(conn, {"range": "today"})
        assert {e["uid"] for e in data["events"]} == {"e_today"}

    def test_show_toggles_narrow_the_sections_rendered(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_event(conn, "e_today", start_at=f"{today.isoformat()}T09:00:00")
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["overdue"]})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}
        assert data["tasks"] == []
        assert data["events"] == []


class TestAgendaWidgetDays:
    def test_groups_by_day_across_next_seven_days(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=today.isoformat())
        _seed_task(conn, "t2", due_at=(today + timedelta(days=3)).isoformat())
        _seed_task(conn, "t_out_of_range", due_at=(today + timedelta(days=10)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "next_7_days"})
        assert data["mode"] == "days"
        assert len(data["days"]) == 7
        assert data["days"][0]["is_today"] is True
        all_task_uids = {t["uid"] for day in data["days"] for t in day["tasks"]}
        assert all_task_uids == {"t1", "t2"}

    def test_next_30_days_range(self, conn):
        data = dashboard_router._render_agenda(conn, {"range": "next_30_days"})
        assert len(data["days"]) == 30


class TestAgendaWidgetAllUpcoming:
    def test_only_future_events_chronological(self, conn):
        now = datetime.now(timezone.utc)
        _seed_event(conn, "past", start_at=(now - timedelta(days=1)).isoformat())
        _seed_event(conn, "soon", start_at=(now + timedelta(days=1)).isoformat())
        _seed_event(conn, "later", start_at=(now + timedelta(days=5)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"]})
        assert [e["uid"] for e in data["events"]] == ["soon", "later"]

    def test_respects_limit(self, conn):
        now = datetime.now(timezone.utc)
        for i in range(5):
            _seed_event(conn, f"e{i}", start_at=(now + timedelta(days=i + 1)).isoformat())
        data = dashboard_router._render_agenda(conn, {"range": "all_upcoming", "show": ["events"], "limit": 2})
        assert len(data["events"]) == 2


class TestAgendaWidgetOverdueOnly:
    def test_only_overdue_open_tasks(self, conn):
        today = date.today()
        _seed_task(conn, "overdue", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today", due_at=today.isoformat())
        _seed_task(conn, "done_overdue", due_at=(today - timedelta(days=2)).isoformat(), status="done")
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["overdue"]})
        assert {t["uid"] for t in data["overdue_tasks"]} == {"overdue"}


class TestWidgetCRUD:
    def test_add_widget(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda_view", range="today", title="My Agenda", project_uid="", tags="uni, urgent",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["title"] == "My Agenda"
        assert w["type"] == "agenda"
        assert w["config"]["tags"] == ["uni", "urgent"]

    def test_add_widget_with_unknown_source_is_a_noop(self, conn):
        dashboard_router.add_widget(
            source="not_a_real_source", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        assert db.list_dashboard_widgets(conn) == []

    def test_add_widget_resolves_every_source_view_range_combo(self, conn):
        # Every entry in _SELECTION_TO_TYPE whose view is still offered by
        # the builder should be reachable through the real add_widget entry
        # point, not just the internal resolver -- 2026-08-02's Source/
        # View/Range rework. "cards"/"filled_cards_view" (2026-08-07
        # Projects purge) stay in _SELECTION_TO_TYPE as harmless dead
        # forward-lookup data but are no longer in WIDGET_VIEWS/
        # WIDGET_SOURCES -- add_widget correctly rejects them as an unknown
        # source now (see test_add_widget_rejects_removed_projects_source).
        for (view, range_), (expected_type, expected_extra) in dashboard_router._SELECTION_TO_TYPE.items():
            if view not in dashboard_router.WIDGET_VIEWS:
                continue
            source = dashboard_router.WIDGET_VIEWS[view]["source"]
            dashboard_router.add_widget(
                source=source, view=view, range=range_ or "", title="", project_uid="", tags="",
                task_list_uids=[], calendar_uids=[], limit="", style="", scope="", show_overdue=False,
                show_tasks=False, show_events=False, space_uid="", conn=conn,
            )
            w = db.list_dashboard_widgets(conn)[-1]
            assert w["type"] == expected_type
            for key, value in expected_extra.items():
                assert w["config"].get(key) == value

    def test_edit_widget_updates_config(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="upcoming_list", range="all_upcoming", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.edit_widget(w["uid"], source="calendar_tasks", view="upcoming_list", range="all_upcoming", title="Renamed", project_uid="", tags="focus", task_list_uids=[], calendar_uids=[], limit="5", conn=conn)
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["title"] == "Renamed"
        assert updated["config"]["tags"] == ["focus"]
        assert updated["config"]["limit"] == 5

    def test_edit_widget_can_change_source_view_range(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="agenda_view", range="today", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.edit_widget(w["uid"], source="calendar_tasks", view="agenda_view", range="next_7_days", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn)
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["type"] == "agenda"
        assert updated["config"]["range"] == "next_7_days"

    def test_delete_widget(self, conn):
        dashboard_router.add_widget(source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn)
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.delete_widget(w["uid"], conn=conn)
        assert db.list_dashboard_widgets(conn) == []

    def test_add_widget_plain_limit_post_still_works(self, conn):
        # Limit became a stepper (2026-08-07, modal-input-design Phase A)
        # but the underlying field is still a plain <input type="number">
        # -- a form post of a bare limit=N (no JS, no stepper buttons
        # involved) must keep working exactly as before.
        dashboard_router.add_widget(
            source="calendar_tasks", view="upcoming_list", range="next_7_days", title="",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="7", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["config"]["limit"] == 7

    def test_add_widget_labels_chip_multiselect_combines_with_tags(self, conn):
        # Labels became a chip multiselect (2026-08-07) -- checkboxes named
        # `tags_labels`, one per known label name -- instead of the old
        # `tags` free-text field. _combine_tags folds both into the same
        # config["tags"] list _config_from_form always produced, so a
        # widget created by checking two labels ends up with exactly the
        # same stored shape as the old text-input flow did.
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="Two labels",
            project_uid="", tags="", tags_labels=["Work", "Urgent"],
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["config"]["tags"] == ["Work", "Urgent"]

    def test_add_widget_labels_multiselect_combines_with_legacy_tags_field(self, conn):
        # A stray/legacy `tags` value (e.g. _widget_edit_form.html's hidden
        # carry-forward field for a Project-filter uid) still combines
        # correctly alongside the new checkbox values, in the order tags
        # first then tags_labels.
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="",
            project_uid="", tags="proj-uid-123", tags_labels=["Work"],
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        assert w["config"]["tags"] == ["proj-uid-123", "Work"]

    def test_edit_widget_labels_chip_multiselect(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        w = db.list_dashboard_widgets(conn)[0]
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="today", title="",
            project_uid="", tags="", tags_labels=["Focus", "Reading"],
            task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["config"]["tags"] == ["Focus", "Reading"]

    def test_legacy_widget_with_empty_config_reverse_maps_correctly(self, conn):
        # An old dashboard's widget with no range info in config at all
        # (config == {}) still resolves sensibly -- _agenda_range's own
        # fallback treats an absent `range` (and absent `range_days`) as
        # "today", so the reverse mapping used to pre-fill the Filters
        # form lands on Today's Agenda rather than crashing or picking an
        # arbitrary range.
        widget = {"uid": "x", "type": "agenda", "config": {}}
        assert dashboard_router._selection_from_widget(widget) == ("calendar_tasks", "agenda_view", "today")

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


class TestWidgetHeightRemoved:
    """2026-08-07 -- the manual height editor/drag-resize feature (four
    fixed height presets, a drag handle, its own resize endpoint) was
    fully removed per direct feedback: a widget's height should just be
    "how much content it is", no scrollbar, unless it goes over a max
    height. These are regression guards against any of that quietly
    coming back, not tests of behavior that still exists."""

    def _add(self, conn, view="agenda", range_="today"):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        return db.list_dashboard_widgets(conn)[-1]

    def test_no_height_preset_system_left_on_the_module(self):
        assert not hasattr(dashboard_router, "WIDGET_HEIGHTS")
        assert not hasattr(dashboard_router, "_widget_height")
        assert not hasattr(dashboard_router, "resize_widget_height")

    def test_widget_types_have_no_default_height(self):
        for spec in dashboard_router.WIDGET_TYPES.values():
            assert "default_height" not in spec

    def test_edit_widget_does_not_carry_height_through(self, conn):
        w = self._add(conn)
        row = dict(db.get_dashboard_widget(conn, w["uid"]))
        row["config"] = dict(row.get("config") or {})
        row["config"]["height"] = "xl"  # simulate a stale value from before removal
        db.upsert_dashboard_widget(conn, row)
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="next_7_days", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert "height" not in updated["config"]

    def test_widget_page_context_has_no_widget_heights(self, conn):
        self._add(conn)
        ctx = dashboard_router.widget_page_context(conn)
        assert "widget_heights" not in ctx


class TestWidgetWidthAutomatic:
    """2026-08-07 -- the manual width picker/drag-resize feature (a Width
    <select> in the widget builder form, a drag handle on each card, its
    own /resize endpoint) was fully removed per direct feedback: "auto-fit
    by content" -- each widget type gets a natural width from its own
    default_width, no per-instance override. These are regression guards
    against any of that quietly coming back, not tests of behavior that
    still exists (see TestWidgetStacking above for the width-sharing
    behavior that *does* still exist, for stacks)."""

    def _add(self, conn, view="agenda", range_="today", **extra):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn, **extra,
        )
        return db.list_dashboard_widgets(conn)[-1]

    def test_no_resize_endpoint_left_on_the_module(self):
        assert not hasattr(dashboard_router, "resize_widget")

    def test_add_widget_form_has_no_width_param(self):
        import inspect

        params = inspect.signature(dashboard_router.add_widget).parameters
        assert "width" not in params

    def test_edit_widget_form_has_no_width_param(self):
        import inspect

        params = inspect.signature(dashboard_router.edit_widget).parameters
        assert "width" not in params

    def test_created_widget_always_renders_at_its_types_default_width(self, conn):
        # calendar_tasks/agenda_view resolves to agenda, whose
        # default_width is "half" -- confirm that's what actually renders
        # regardless of anything a stale/forged client might have sent.
        w = self._add(conn)
        assert w["type"] == "agenda"
        wc = dashboard_router._widget_context(conn, w)
        assert wc["width"]["key"] == "half"

    def test_editing_a_widget_does_not_accept_a_width_override(self, conn):
        w = self._add(conn)
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="today", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert "width" not in updated["config"]

    def test_widget_types_default_width_is_the_only_source_of_truth(self, conn):
        # Even if a stale config["width"] is sitting in a widget's config
        # (e.g. from before this removal), it's never read any more --
        # the type's own default_width always wins.
        w = self._add(conn)
        row = dict(db.get_dashboard_widget(conn, w["uid"]))
        row["config"] = dict(row.get("config") or {})
        row["config"]["width"] = "full"  # simulate a stale override
        db.upsert_dashboard_widget(conn, row)
        wc = dashboard_router._widget_context(conn, row)
        assert wc["width"]["key"] == "half"  # today_agenda's own default, not "full"

    def test_widget_page_context_has_no_widget_widths(self, conn):
        self._add(conn)
        ctx = dashboard_router.widget_page_context(conn)
        assert "widget_widths" not in ctx

    def test_builder_fields_partial_has_no_width_field(self, conn):
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert 'name="width"' not in body

    def test_edit_mode_renders_no_width_resize_handle(self, conn):
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert "widget-resize-handle" not in body


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
        # Top-level layout is now Today's Agenda + one stack card (the
        # stack's 3 members render nested inside it, not as their own
        # top-level entries).
        assert len(resp.context["widget_contexts"]) == 2

    def test_renders_in_edit_mode_with_the_add_widget_form(self, conn):
        # Smoke test for the Add-widget form/Filters panel/masonry grid
        # markup moved into _widget_workspace.html (2026-08-02) -- only
        # rendered at all when edit_mode is truthy, so the non-edit render
        # above wouldn't have caught a syntax error in that branch.
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        assert resp.status_code == 200
        assert b"Add widget" in resp.body

    def test_edit_mode_renders_no_height_resize_handle(self, conn):
        # 2026-08-07 -- the manual height editor/drag-resize handle was
        # fully removed; .widget-content now renders identically (no
        # data-height-key, no inline max-height style) for every widget,
        # regardless of type, with the fixed CSS max-height doing the
        # capping instead.
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert "widget-resize-handle-vertical" not in body
        assert "data-height-key" not in body
        # Every widget's .widget-content opens with the exact same bare
        # markup -- no per-widget/per-type variation left at all (today_agenda
        # + the stack's 3 members == 4 occurrences).
        assert body.count('<div class="widget-content">') == 4


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
        assert w["config"]["label_name"] == "space1"
        # Doesn't leak into Home's own (space_uid=None) list.
        assert db.list_dashboard_widgets(conn) == []

    def test_add_widget_redirects_back_to_the_space_page(self, conn):
        resp = dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="space1", conn=conn,
        )
        assert resp.headers["location"] == "/settings/labels/space1"

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
        assert updated["config"]["label_name"] == "space1"  # not clobbered by the edit form
        assert resp.headers["location"] == "/settings/labels/space1"

    def test_delete_widget_redirects_to_its_own_space(self, conn):
        w = self._add(conn, "A", space_uid="space1")
        resp = dashboard_router.delete_widget(w["uid"], conn=conn)
        assert resp.headers["location"] == "/settings/labels/space1"
        assert db.get_dashboard_widget(conn, w["uid"]) is None

    def test_add_widget_redirects_straight_to_spaces_for_a_real_space(self, conn):
        """2026-08-28 fix: when the label actually has generate_space=1,
        the redirect should go straight to /spaces/{name} rather than
        bouncing through /settings/labels/{name}'s own 301."""
        db.upsert_label_config(conn, {"name": "space1", "generate_space": 1, "created_at": "2026-01-01"})
        resp = dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="space1", conn=conn,
        )
        assert resp.headers["location"] == "/spaces/space1"

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


class TestContactListWidget:
    """§2 Spaces v2, 2026-08-03 -- contact_list widget filters contacts by
    tags matching the space's group project names (via group_uid) or
    explicit config['tags']."""

    def _seed_contact(self, conn, uid, full_name, tags=None):
        db.upsert_contact(conn, {
            "uid": uid,
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

    def test_label_name_scoping_uses_child_label_names_as_tags(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        self._seed_contact(conn, "c1", "Alice", tags=["CS101"])
        self._seed_contact(conn, "c2", "Bob", tags=["Personal"])
        data = dashboard_router._render_contact_list(conn, {"label_name": "Uni"})
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
    """§2 Spaces v2, 2026-08-03 originally; 2026-08-07 (screenshot-driven
    default-layout rework) replaced the old widget set with the same
    Today's Agenda + At a Glance/Upcoming Events/Overdue Tasks stack Home
    now seeds -- see dashboard_router._seed_agenda_stack_layout."""

    def _make_space(self, conn, name):
        db.upsert_label_config(conn, {"name": name, "generate_space": 1, "created_at": _now()})

    def test_seeds_defaults_for_a_new_space(self, conn):
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        assert [w["type"] for w in top_level] == ["agenda", "stack"]

        stack = top_level[1]
        members = sorted((w for w in widgets if w.get("group_uid") == stack["uid"]), key=lambda w: w["position"])
        assert [w["type"] for w in members] == ["at_a_glance", "agenda", "agenda"]

    def test_default_seed_no_longer_includes_removed_types(self, conn):
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        types = {w["type"] for w in db.list_dashboard_widgets(conn, space_uid="space1")}
        assert types.isdisjoint({"calendar_agenda", "weekly_overview", "mini_month_calendar", "project_preview", "habit_checkin"})

    def test_today_agenda_and_stack_seeded_with_half_width(self, conn):
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        today_agenda = next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))
        stack = next(w for w in widgets if w["type"] == "stack")
        assert today_agenda["config"]["width"] == "half"
        assert stack["config"]["width"] == "half"

    def test_data_rendering_space_widgets_auto_scoped_with_label_name(self, conn):
        # Every widget that actually renders data (today_agenda + the
        # stack's 3 members) carries config["label_name"] so its query is
        # filtered to this space -- the stack container itself has no
        # render of its own and so no config["label_name"] to check.
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        renderable = [w for w in widgets if w["type"] != "stack"]
        assert renderable  # sanity: didn't accidentally filter everything out
        assert all(w["config"].get("label_name") == "space1" for w in renderable)
        assert all(w["label_name"] == "space1" for w in widgets)  # page-scope column, every row including the stack

    def test_does_not_reseed_space_after_all_widgets_deleted(self, conn):
        # Fix for Scenario 2: deleting all Space widgets must not trigger
        # a re-seed on the next call.
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        assert db.get_app_meta(conn, "dashboard_label_space1_seeded_v1") == "1"
        for w in db.list_dashboard_widgets(conn, space_uid="space1"):
            db.delete_dashboard_widget(conn, w["uid"])
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        assert db.list_dashboard_widgets(conn, space_uid="space1") == []

    def test_each_space_tracked_independently(self, conn):
        # space1 and space2 have independent app_meta flags.
        self._make_space(conn, "space1")
        self._make_space(conn, "space2")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space2")
        assert db.get_app_meta(conn, "dashboard_label_space1_seeded_v1") == "1"
        assert db.get_app_meta(conn, "dashboard_label_space2_seeded_v1") == "1"
        # Deleting all of space1's widgets must not affect space2's.
        for w in db.list_dashboard_widgets(conn, space_uid="space1"):
            db.delete_dashboard_widget(conn, w["uid"])
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        assert db.list_dashboard_widgets(conn, space_uid="space1") == []
        assert len(db.list_dashboard_widgets(conn, space_uid="space2")) == 5  # today_agenda + stack + 3 members


class TestSpaceScopedRenderers:
    """_render_project_preview and _render_habit_checkin both need to
    resolve config['group_uid'] the same way _filtered_tasks/_filtered_
    events already do, since a Space's default widgets use group_uid, not
    project_uid, to auto-scope (2026-08-02)."""

    def test_project_preview_label_filter(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Personal", "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "Uni"})
        assert [pv["project"]["uid"] for pv in data["previews"]] == ["CS101"]

    def test_habit_checkin_label_filter(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_habit(conn, {"uid": "h1", "name": "Study", "project_uid": "CS101", "created_at": _now(), "updated_at": _now()})
        db.upsert_habit(conn, {"uid": "h2", "name": "Read", "created_at": _now(), "updated_at": _now()})
        data = dashboard_router._render_habit_checkin(conn, {"label_name": "Uni"})
        assert [r["habit"]["uid"] for r in data["rows"]] == ["h1"]


class TestSpacesProjectsScope:
    """2026-08-15, widget consolidation expanded scope: a Spaces & Projects
    widget placed on a Space/Project page is auto-scoped to that page via
    config['label_name'] -- config['scope']=='everything' opts a single
    widget instance out of that, rendering the same as an unscoped Home
    instance would."""

    def test_default_scope_is_label_scoped(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Personal", "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "Uni"})
        assert [pv["project"]["uid"] for pv in data["previews"]] == ["CS101"]

    def test_scope_everything_ignores_label_name(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Personal", "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "Uni", "scope": "everything"})
        # Same as the unscoped Home case: every plain (non-Space) label,
        # parented or not (list_labels' own "not generate_space" query
        # doesn't filter by parent_name).
        assert {pv["project"]["uid"] for pv in data["previews"]} == {"CS101", "Personal"}

    def test_scope_everything_cards_style_lists_every_space(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Work", "generate_space": 1, "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "Uni", "scope": "everything", "style": "cards"})
        assert {c["uid"] for c in data["cards"]} == {"Uni", "Work"}

    def test_children_include_sub_spaces_not_just_projects(self, conn):
        # db.list_child_labels doesn't distinguish project vs. Space
        # children -- "This Space" scope already includes both, no special
        # casing needed.
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Grad School", "parent_name": "Uni", "generate_space": 1, "created_at": _now()})
        data = dashboard_router._render_spaces_projects(conn, {"label_name": "Uni"})
        assert {pv["project"]["uid"] for pv in data["previews"]} == {"CS101", "Grad School"}

    def test_add_widget_stores_scope(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        dashboard_router.add_widget(
            source="spaces_projects", view="spaces_projects_view", range="", title="", project_uid="",
            tags="", task_list_uids=[], calendar_uids=[], limit="", style="cards", scope="everything",
            show_overdue=False, show_tasks=False, show_events=False, space_uid="Uni", conn=conn,
        )
        w = db.list_dashboard_widgets(conn, space_uid="Uni")[0]
        assert w["type"] == "spaces_projects"
        assert w["config"]["scope"] == "everything"
        assert w["config"]["style"] == "cards"


class TestBareTileWidgets:
    """2026-08-30, direct feedback ("i like the quick links grid but i'd
    like to not have them inside a div card") -- Quick Links and Spaces &
    Projects' own "cards" style both render the same .filled-cards-grid
    tiles, so both opt their widget instance out of the .card wrapper's
    chrome (border/shadow/background/padding -- see .widget-card--bare,
    static/style.css) via _widget_context's own "bare" key. Spaces &
    Projects' "list" style keeps its normal card chrome -- only the tile
    grid was the redundant-double-frame complaint."""

    def _widget(self, conn, wtype, config=None):
        w = {
            "uid": f"w-{wtype}-{(config or {}).get('style', 'x')}", "type": wtype, "title": None,
            "config": config or {}, "position": 1, "created_at": _now(),
        }
        db.upsert_dashboard_widget(conn, w)
        return w

    def test_quick_links_is_bare(self, conn):
        w = self._widget(conn, "quick_links")
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is True

    def test_spaces_projects_cards_style_is_bare(self, conn):
        w = self._widget(conn, "spaces_projects", {"style": "cards"})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is True

    def test_spaces_projects_list_style_keeps_card_chrome(self, conn):
        w = self._widget(conn, "spaces_projects", {"style": "list"})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_spaces_projects_default_style_keeps_card_chrome(self, conn):
        # style absent -- _render_spaces_projects defaults to "list", the
        # bare check has to agree with that same default rather than
        # reading config.get("style") == "cards" in isolation and getting
        # it right only when the key happens to be present.
        w = self._widget(conn, "spaces_projects", {})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_other_widget_types_are_not_bare(self, conn):
        w = self._widget(conn, "streak")
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_bare_class_rendered_on_dashboard(self, conn):
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "0")
        self._widget(conn, "quick_links")
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert "widget-card--bare" in body


class TestOrganizeTodayWidget:
    """2026-08-15, widget consolidation expanded scope: "what needs
    organizing today" -- decisions to make, not things already scheduled."""

    def test_unallocated_task_due_soon_is_listed(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=(today + timedelta(days=2)).isoformat())
        data = dashboard_router._render_organize_today(conn, {})
        assert [item["task"]["uid"] for item in data["due_soon"]] == ["t1"]

    def test_task_due_soon_but_already_fully_scheduled_is_excluded(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=(today + timedelta(days=2)).isoformat())
        db.create_work_allocation(conn, "t1", start_at=f"{today.isoformat()}T09:00:00", end_at=f"{today.isoformat()}T10:00:00")
        data = dashboard_router._render_organize_today(conn, {})
        assert data["due_soon"] == []

    def test_task_due_soon_with_only_an_undated_session_is_still_listed(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=(today + timedelta(days=1)).isoformat())
        db.create_work_allocation(conn, "t1")  # undated placeholder
        data = dashboard_router._render_organize_today(conn, {})
        assert [item["task"]["uid"] for item in data["due_soon"]] == ["t1"]

    def test_task_due_beyond_the_horizon_is_excluded(self, conn):
        today = date.today()
        _seed_task(conn, "t1", due_at=(today + timedelta(days=10)).isoformat())
        data = dashboard_router._render_organize_today(conn, {})
        assert data["due_soon"] == []

    def test_event_with_no_location_or_url_is_unclear(self, conn):
        today = date.today()
        _seed_event(conn, "e1", start_at=f"{today.isoformat()}T09:00:00")
        data = dashboard_router._render_organize_today(conn, {})
        assert [e["uid"] for e in data["unclear_format"]] == ["e1"]

    def test_event_with_a_location_is_not_unclear(self, conn):
        today = date.today()
        db.upsert_event(conn, {
            "uid": "e1", "title": "e1", "description": "", "status": "active", "all_day": 0,
            "start_at": f"{today.isoformat()}T09:00:00", "location": "Room 101",
            "tags": [], "created_at": _now(),
        })
        data = dashboard_router._render_organize_today(conn, {})
        assert data["unclear_format"] == []

    def test_event_beyond_tomorrow_is_excluded(self, conn):
        today = date.today()
        _seed_event(conn, "e1", start_at=f"{(today + timedelta(days=2)).isoformat()}T09:00:00")
        data = dashboard_router._render_organize_today(conn, {})
        assert data["unclear_format"] == []

    def test_registered_in_widget_types_and_selection_tables(self, conn):
        assert "organize_today" in dashboard_router.WIDGET_TYPES
        assert ("organize_today_view", None) in dashboard_router._SELECTION_TO_TYPE
        assert ("organize_today", None) in dashboard_router._TYPE_TO_SELECTION


class TestLimitFieldExposedForMoreViews:
    """2026-08-15, widget consolidation expanded scope ("widgets should be
    more customizable"): contact_list's own render function already reads
    config['limit'] -- the builder just never offered a way to set it.
    Verified via _resolve_selection + the stored config, not the JS (no
    browser in this test environment)."""

    def test_contact_list_view_has_limit_flag(self):
        assert dashboard_router.WIDGET_VIEWS["contact_list_view"]["has_limit"] is True


class TestIsLongLivedRecurrence:
    """2026-08-15, new Weekly Schedule widget -- filters a short recurring
    reminder out while keeping a real standing weekly pattern, purely from
    the event's own recurrence rule (no DB, no "as of" date needed)."""

    def test_open_ended_weekly_qualifies(self):
        event = {"uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00", "recurrence": "FREQ=WEEKLY"}
        assert dashboard_router._is_long_lived_recurrence(event) is True

    def test_semester_long_until_qualifies(self):
        event = {
            "uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00",
            "recurrence": "FREQ=WEEKLY;UNTIL=2026-12-15",
        }
        assert dashboard_router._is_long_lived_recurrence(event) is True

    def test_short_count_reminder_does_not_qualify(self):
        event = {
            "uid": "e1", "start_at": "2026-09-01T08:00:00", "end_at": "2026-09-01T08:05:00",
            "recurrence": "FREQ=DAILY;COUNT=3",
        }
        assert dashboard_router._is_long_lived_recurrence(event) is False

    def test_non_recurring_does_not_qualify(self):
        event = {"uid": "e1", "start_at": "2026-09-01T10:00:00", "end_at": "2026-09-01T11:00:00"}
        assert dashboard_router._is_long_lived_recurrence(event) is False

    def test_no_start_at_does_not_qualify(self):
        assert dashboard_router._is_long_lived_recurrence({"uid": "e1", "recurrence": "FREQ=WEEKLY"}) is False


class TestWeeklyScheduleWidget:
    """2026-08-15, new type -- a compact, static weekly-pattern view of a
    label's long-lived recurring events; no revival of the removed
    Schedule module, purely a presentation over ordinary recurring
    Calendar events."""

    def test_short_lived_recurrence_is_excluded(self, conn):
        _seed_recurring_event(conn, "e1", "2026-09-01T10:00:00", "2026-09-01T10:30:00", recurrence="FREQ=DAILY;COUNT=3")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []
        assert data["agenda_rows"] == []

    def test_non_recurring_event_is_excluded(self, conn):
        _seed_event(conn, "e1", start_at="2026-09-01T10:00:00")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []

    def test_semester_long_weekly_event_produces_one_day_column(self, conn):
        # 2026-09-01 is a Tuesday.
        _seed_recurring_event(conn, "lecture", "2026-09-01T10:00:00", "2026-09-01T11:30:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert len(data["days"]) == 1
        assert data["days"][0]["weekday"] == 1  # Tuesday, Monday=0
        assert data["days"][0]["label"] == "Tue"
        assert len(data["days"][0]["blocks"]) == 1
        assert data["days"][0]["blocks"][0]["event"]["uid"] == "lecture"
        assert data["agenda_rows"][0]["event"]["uid"] == "lecture"

    def test_grid_is_only_as_tall_as_the_events_own_time_span(self, conn):
        # Two lectures 10:00-11:00 and 14:00-15:00 -- the grid should be
        # tightened to roughly 9:30-15:30, not the full 24h day, so a
        # 10:00 block doesn't start near the very top of a mostly-empty
        # column.
        _seed_recurring_event(conn, "morning", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        _seed_recurring_event(conn, "afternoon", "2026-09-03T14:00:00", "2026-09-03T15:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15")
        data = dashboard_router._render_weekly_schedule(conn, {})
        blocks = {b["event"]["uid"]: b for day in data["days"] for b in day["blocks"]}
        assert blocks["morning"]["top_pct"] < blocks["afternoon"]["top_pct"]
        # Neither block should be flush against the very top of its column
        # (a 30-minute pad was added before the earliest start).
        assert blocks["morning"]["top_pct"] > 0

    def test_biweekly_event_is_flagged(self, conn):
        _seed_recurring_event(conn, "lecture", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;INTERVAL=2")
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"][0]["blocks"][0]["biweekly"] is True
        assert data["agenda_rows"][0]["biweekly"] is True

    def test_label_scoping(self, conn):
        _seed_recurring_event(conn, "cs101", "2026-09-01T10:00:00", "2026-09-01T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15", tags=["CS101"])
        _seed_recurring_event(conn, "other", "2026-09-02T10:00:00", "2026-09-02T11:00:00", recurrence="FREQ=WEEKLY;UNTIL=2026-12-15", tags=["Other"])
        data = dashboard_router._render_weekly_schedule(conn, {"tags": ["CS101"]})
        agenda_uids = {row["event"]["uid"] for row in data["agenda_rows"]}
        assert agenda_uids == {"cs101"}

    def test_registered_in_widget_types_and_selection_tables(self, conn):
        assert "weekly_schedule" in dashboard_router.WIDGET_TYPES
        assert ("weekly_schedule_view", None) in dashboard_router._SELECTION_TO_TYPE
        assert ("weekly_schedule", None) in dashboard_router._TYPE_TO_SELECTION

    def test_all_day_recurring_event_is_excluded_not_crashed(self, conn):
        # 2026-08-30 bug fix: db.sync_contact_birthday_event writes an
        # all_day=True, FREQ=YEARLY event with a bare "1900-MM-DD"
        # start_at (no "THH:MM" time portion) for every contact with a
        # birthday -- automatic, not something a user has to construct by
        # hand. Before the fix, this crashed _minutes_of_day's fixed-
        # offset slice (ValueError: invalid literal for int() with base
        # 10: '') for any dashboard with a Weekly Schedule widget whose
        # label matched a birthday'd contact, taking down GET / entirely.
        # An all-day event has no time-of-day to place on this grid
        # anyway (same exclusion grid_layout.layout_day already applies),
        # so it should just be skipped, not crash the widget.
        db.upsert_event(conn, {
            "uid": "birthday-1", "title": "Jordan's Birthday",
            "description": "", "status": "active", "all_day": 1,
            "start_at": "1900-06-15", "end_at": None, "recurrence": "FREQ=YEARLY",
            "tags": [], "created_at": _now(),
        })
        data = dashboard_router._render_weekly_schedule(conn, {})
        assert data["days"] == []
        assert data["agenda_rows"] == []
