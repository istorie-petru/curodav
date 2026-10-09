"""Adding, editing, reordering and deleting widgets through the router functions."""

from __future__ import annotations

from src import db
from src.routers import dashboard as dashboard_router


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
        #
        # "group_members_view" (item 20, 2026-09-26) is the first entry
        # EXCLUDED from Home's own scope (its render function has nothing
        # to resolve without a group page's label_name) -- tested on a real
        # group's page_uid instead of Home, same as every other combo,
        # just with project_uid set; see
        # TestGroupMembersWidgetScope::test_excluded_from_home below for
        # the Home-rejection half of this behavior.
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1})
        db.set_group_members(conn, "Uni", ["Uni"])
        group_key = db.group_page_key("Uni")
        for (view, range_), (expected_type, expected_extra) in dashboard_router._SELECTION_TO_TYPE.items():
            if view not in dashboard_router.WIDGET_VIEWS:
                continue
            source = dashboard_router.WIDGET_VIEWS[view]["source"]
            project_uid = group_key if view == "group_members_view" else ""
            dashboard_router.add_widget(
                source=source, view=view, range=range_ or "", title="", project_uid=project_uid, tags="",
                task_list_uids=[], calendar_uids=[], limit="", style="", scope="", show=[],
                space_uid="", conn=conn,
            )
            w = db.list_dashboard_widgets(conn, label_name=project_uid or None)[-1]
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


class TestGroupMembersWidgetScope:
    """item 20 (2026-09-26): `group_members` is meaningless outside a
    group's own page (its render function resolves a group from
    `config["label_name"]`, which Home/a plain label page never carry) --
    excluded from those two scopes the same way `spaces_projects` is
    excluded from a plain project page."""

    def test_excluded_from_home(self, conn):
        dashboard_router.add_widget(
            source="group_members", view="group_members_view", range="", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", style="", scope="", show=[], space_uid="", conn=conn,
        )
        assert db.list_dashboard_widgets(conn) == []

    def test_excluded_from_a_plain_label_page(self, conn):
        db.upsert_label_config(conn, {"name": "Solo"})
        dashboard_router.add_widget(
            source="group_members", view="group_members_view", range="", title="", project_uid="Solo", tags="",
            task_list_uids=[], calendar_uids=[], limit="", style="", scope="", show=[], space_uid="", conn=conn,
        )
        assert db.list_dashboard_widgets(conn, label_name="Solo") == []
