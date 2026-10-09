"""Per-space widget grids: scoping, redirects and independence from Home."""

from __future__ import annotations

import json

from src import db
from src.routers import dashboard as dashboard_router


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
        assert resp.headers["location"] == "/labels/space1"

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
        assert resp.headers["location"] == "/labels/space1"

    def test_delete_widget_redirects_to_its_own_space(self, conn):
        w = self._add(conn, "A", space_uid="space1")
        resp = dashboard_router.delete_widget(w["uid"], conn=conn)
        assert resp.headers["location"] == "/labels/space1"
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
