"""Default widget seeding for Home and for a Space, and that it happens only once."""

from __future__ import annotations

from datetime import timedelta

from dashboard_seed import now_iso, seed_event, seed_task

from src import db
from src.routers import dashboard as dashboard_router


class TestDefaultWidgetSeeding:
    def test_seeds_default_widgets_on_first_visit(self, conn):
        # 2026-08-15 widget consolidation: default seed is Agenda (range=
        # today) + a stack of At a Glance / Agenda (all_upcoming) -- see
        # dashboard_router._seed_agenda_stack_layout.
        # 2026-09-13: dropped the stack's former third member (another
        # today-range Agenda, overdue+tasks+events) -- it duplicated the
        # standalone widget's own content almost exactly, a side effect of
        # a 2026-09-03 fix that widened its Show list to match. Seeded
        # widgets also get explicit titles now ("Today"/"At a
        # glance"/"Upcoming") instead of falling back to the generic
        # "Agenda" spec label three separate times.
        # 2026-09-14 (Spaces -- labels-as-membership rework slice 5): the
        # Upcoming member's Show list grew from events-only to
        # events+tasks -- config-only, see _DEFAULT_STACK_MEMBER_TYPES's
        # own comment.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        # Item 15 (2026-09-24): + a trailing Habit Check-in (25/50/25).
        assert [w["type"] for w in top_level] == ["agenda", "stack", "habit_checkin"]
        assert top_level[0]["title"] == "Today"
        assert top_level[2]["title"] == "Habits"

        stack = top_level[1]
        members = sorted((w for w in widgets if w.get("group_uid") == stack["uid"]), key=lambda w: w["position"])
        assert [w["type"] for w in members] == ["at_a_glance", "agenda"]
        assert [w["title"] for w in members] == ["At a glance", "Upcoming"]
        assert members[1]["config"]["show"] == ["events", "tasks"]

    def test_seeded_upcoming_widget_actually_renders_both_tasks_and_events(self, conn, today):
        # 2026-09-14 (Spaces -- labels-as-membership rework slice 5):
        # end-to-end check, not just the config-seeding assertion above --
        # the seeded Upcoming member's config, run through the real
        # renderer, must surface a task alongside an event, not just
        # events (its pre-slice-5 default).
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        stack = next(w for w in widgets if w["type"] == "stack")
        upcoming = next(w for w in widgets if w.get("group_uid") == stack["uid"] and w["title"] == "Upcoming")
        seed_task(conn, "t1", due_at=(today + timedelta(days=2)).isoformat())
        seed_event(conn, "e1", start_at=f"{(today + timedelta(days=3)).isoformat()}T09:00:00")
        data = dashboard_router._render_agenda(conn, upcoming["config"])
        assert {t["uid"] for t in data["tasks"]} == {"t1"}
        assert {e["uid"] for e in data["events"]} == {"e1"}

    def test_default_seed_sets_width_on_paired_widgets(self, conn):
        # Item 15 (2026-09-24): Home is a 25/50/25 row -- Today, the stack,
        # Habit Check-in -- filling the 12-column grid exactly.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        main_agenda = next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))
        stack = next(w for w in widgets if w["type"] == "stack")
        habits = next(w for w in widgets if w["type"] == "habit_checkin")
        assert (main_agenda["config"]["width"], stack["config"]["width"], habits["config"]["width"]) == ("quarter", "half", "quarter")
        spans = [dashboard_router.WIDGET_WIDTHS[w["config"]["width"]]["span"] for w in (main_agenda, stack, habits)]
        assert sum(spans) == 12

    def test_label_page_seed_keeps_half_half_pair(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "created_at": "2026-09-24"})
        dashboard_router._ensure_default_label_widgets(conn, "CS101")
        widgets = db.list_dashboard_widgets(conn, label_name="CS101")
        assert "habit_checkin" not in {w["type"] for w in widgets}
        main_agenda = next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))
        assert main_agenda["config"]["width"] == "half"

    def test_default_seed_no_longer_includes_removed_types(self, conn):
        # calendar_agenda/weekly_overview/mini_month_calendar are no
        # longer pre-seeded -- still addable manually via "New widget".
        dashboard_router._ensure_default_widgets(conn)
        types = {w["type"] for w in db.list_dashboard_widgets(conn)}
        assert types.isdisjoint({"calendar_agenda", "weekly_overview", "mini_month_calendar"})

    def test_seeds_default_widgets_on_first_visit_only(self, conn):
        # First call seeds the defaults and sets the app_meta flag; a second call adds nothing.
        dashboard_router._ensure_default_widgets(conn)
        assert len(db.list_dashboard_widgets(conn)) == 5  # today_agenda + stack + 2 members + habit_checkin
        assert db.get_app_meta(conn, dashboard_router._HOME_SEEDED_KEY) == "1"
        dashboard_router._ensure_default_widgets(conn)
        assert len(db.list_dashboard_widgets(conn)) == 5

    def test_does_not_reseed_after_all_widgets_deleted(self, conn):
        # Seed once, then delete every widget -- the flag is set, so a
        # second call must NOT re-seed. This is the fix for "delete all
        # widgets, reload, defaults reappear" (Scenario 1).
        dashboard_router._ensure_default_widgets(conn)
        for w in db.list_dashboard_widgets(conn):
            db.delete_dashboard_widget(conn, w["uid"])
        dashboard_router._ensure_default_widgets(conn)
        assert db.list_dashboard_widgets(conn) == []



class TestDefaultSpaceWidgets:
    """§2 Spaces v2, 2026-08-03 originally; 2026-08-07 (screenshot-driven
    default-layout rework) replaced the old widget set with the same
    Today's Agenda + At a Glance/Upcoming Events stack Home now seeds --
    see dashboard_router._seed_agenda_stack_layout. 2026-09-13: stack
    trimmed from 3 members to 2 (dropped a duplicate today-range Agenda),
    same change as Home's."""

    def _make_space(self, conn, name):
        db.upsert_label_config(conn, {"name": name, "generate_space": 1, "created_at": now_iso()})

    def test_seeds_defaults_for_a_new_space(self, conn):
        self._make_space(conn, "space1")
        dashboard_router._ensure_default_label_widgets(conn, "space1")
        widgets = db.list_dashboard_widgets(conn, space_uid="space1")
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        assert [w["type"] for w in top_level] == ["agenda", "stack"]

        stack = top_level[1]
        members = sorted((w for w in widgets if w.get("group_uid") == stack["uid"]), key=lambda w: w["position"])
        assert [w["type"] for w in members] == ["at_a_glance", "agenda"]

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
        # stack's 2 members) carries config["label_name"] so its query is
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
        assert len(db.list_dashboard_widgets(conn, space_uid="space2")) == 4  # today_agenda + stack + 2 members
