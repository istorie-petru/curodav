"""Stacking widgets into one slot, unstacking, and reordering inside and outside a stack."""

from __future__ import annotations

import pytest

from src import db
from src.routers import dashboard as dashboard_router


pytestmark = pytest.mark.usefixtures("home_is_dashboard")


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
