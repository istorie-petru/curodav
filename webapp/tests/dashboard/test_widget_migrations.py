"""The one-time migration that retired old widget types, and the retired types staying gone."""

from __future__ import annotations

from dashboard_seed import now_iso

from src import db
from src.routers import dashboard as dashboard_router


class TestWidgetRemovalMigration:
    """2026-08-30 -- _migrate_widget_removal_2026_08_30, the one-time
    migration for the same session's quick_links merge + next_deadline/
    organize_today/streak removal, so an existing dashboard doesn't lose a
    widget (or end up with a dead "Unknown widget type" card) just because
    this version is running."""

    def _seed_row(self, conn, uid, wtype, config=None, group_uid=None):
        db.upsert_dashboard_widget(conn, {
            "uid": uid, "type": wtype, "title": None, "config": config or {},
            "position": 1, "created_at": now_iso(), "group_uid": group_uid,
        })

    def test_quick_links_becomes_spaces_projects_cards(self, conn):
        self._seed_row(conn, "w1", "quick_links")
        dashboard_router._migrate_widget_removal_2026_08_30(conn)
        w = db.get_dashboard_widget(conn, "w1")
        assert w["type"] == "spaces_projects"
        assert w["config"]["style"] == "cards"

    def test_quick_links_migration_preserves_other_config(self, conn):
        self._seed_row(conn, "w1", "quick_links", config={"tags": ["Uni"]})
        dashboard_router._migrate_widget_removal_2026_08_30(conn)
        w = db.get_dashboard_widget(conn, "w1")
        assert w["config"]["tags"] == ["Uni"]
        assert w["config"]["style"] == "cards"

    def test_next_deadline_organize_today_streak_deleted(self, conn):
        self._seed_row(conn, "w1", "next_deadline")
        self._seed_row(conn, "w2", "organize_today")
        self._seed_row(conn, "w3", "streak")
        self._seed_row(conn, "w4", "agenda")  # untouched control
        dashboard_router._migrate_widget_removal_2026_08_30(conn)
        remaining = {w["uid"] for w in db.list_all_dashboard_widgets(conn)}
        assert remaining == {"w4"}

    def test_runs_exactly_once(self, conn):
        self._seed_row(conn, "w1", "quick_links")
        dashboard_router._migrate_widget_removal_2026_08_30(conn)
        # Simulate a user re-adding a fresh quick_links row after the
        # migration already ran once (shouldn't happen in practice since
        # the type is gone from the builder, but the guard itself -- "ran
        # once, never touches new rows again" -- is what's under test).
        self._seed_row(conn, "w2", "quick_links")
        dashboard_router._migrate_widget_removal_2026_08_30(conn)
        w2 = db.get_dashboard_widget(conn, "w2")
        assert w2["type"] == "quick_links"  # untouched -- guard already tripped

    def test_wired_into_widget_page_context(self, conn):
        self._seed_row(conn, "w1", "next_deadline")
        dashboard_router.widget_page_context(conn)
        assert db.get_dashboard_widget(conn, "w1") is None

