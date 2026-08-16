"""Phase 8 (command-center-rework) -- Settings restructure.

`/settings` goes from a plain redirect to the first section (the old tab
drill-through) to a real hub page.

2026-08-07 (features/settings.md): reworked from the Global/Space/
Project three-section split into four honest groups on one page
(Organization/Data/Appearance/Widgets + a Danger zone).

2026-08-08: reworked again, this time into a real hub-and-children area
instead of one long page -- originally six categories on the hub
(General/Appearance/Labels/Data & backup/Widgets/Advanced), each its own
route/template, sharing one back-navigation breadcrumb component
(_settings_breadcrumb.html) so Settings behaves as its own navigable
environment (Settings → Labels → Back returns to Settings, never out to
whatever page was open before Settings was entered).

Same day, reworked twice more per direct feedback: "Widgets" (a toggle +
reset layout) lost the toggle and folded its one remaining action into
Advanced; "Data & backup" (Habits/Published lists/Export) was deleted
outright -- Export moved into Advanced, and Published lists promoted to
a direct hub category. A further 2026-08-08 follow-up removed Habits from
the hub too: it's reached from Tasks > Habits (its contextual home), so a
hub shortcut would be pure mirroring. Current five: General/Appearance/
Labels/Published lists/Advanced. This file's tests were rewritten to match
each time; every manage page must stay reachable and unchanged in
behavior."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import dashboard as dashboard_router
from src.routers import export as export_router
from src.routers import habits as habits_router
from src.routers import published_lists as published_lists_router
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/settings"):
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


def _request_with_radicale(path):
    """routers/published_lists.py/export.py both read
    `request.app.state.settings.radicale_base_url` -- a bare `_request()`
    has no ASGI `app` in scope at all, so those two specifically need
    this fuller fake instead."""
    from types import SimpleNamespace

    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(radicale_base_url="http://localhost:5232")))
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [], "app": fake_app,
        }
    )


class TestSettingsHub:
    def test_renders_the_hub_categories(self, conn):
        resp = settings_router.settings_index(_request(), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        for name in ("General", "Appearance", "Labels", "Holidays", "Published lists", "Advanced"):
            assert name in body
        # Habits is not a hub category (2026-08-08 follow-up #3): it's
        # reached from Tasks > Habits, so a hub shortcut would duplicate
        # an already-contextual destination.
        assert ">Habits<" not in body
        # "Widgets" was its own category (Custom widgets toggle + reset
        # layout) -- removed 2026-08-08 when the toggle itself was removed
        # (see routers/settings.py's module docstring); the one remaining
        # action (reset layout) folded into Advanced instead of keeping a
        # whole page for a single row.
        assert ">Widgets<" not in body
        # "Data & backup" -- a sub-hub of Habits/Published lists/Export --
        # is gone the same day: Export moved into Advanced, and Habits/
        # Published lists were promoted to direct hub categories, leaving
        # nothing in that layer but indirection.
        assert "Data &amp; backup" not in body

    def test_active_tab_is_settings(self, conn):
        resp = settings_router.settings_index(_request(), conn=conn)
        assert resp.context["active_tab"] == "settings"

    def test_every_category_links_somewhere_real(self, conn):
        resp = settings_router.settings_index(_request(), conn=conn)
        urls = {c["url"] for c in resp.context["categories"]}
        assert urls == {
            "/settings/general",
            "/settings/appearance",
            "/labels",
            "/settings/holidays",
            "/settings/time-blocks",
            "/settings/data-health",
            "/settings/sync-conflicts",
            "/published-lists",
            "/settings/advanced",
        }

    def test_hub_is_a_short_list_not_a_page_of_every_control(self, conn):
        # The old hub rendered every setting's actual control inline
        # (a text input, a switch, purge buttons...) -- the redesigned hub
        # only links out to focused child pages, so none of those controls
        # should appear on the hub itself.
        resp = settings_router.settings_index(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="themeSegmented"' not in body
        assert 'name="display_name"' not in body
        assert 'action="/settings/purge-all"' not in body


class TestSettingsGeneral:
    def test_renders_display_name_field(self, conn):
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        assert resp.context["active_tab"] == "settings_general"
        body = resp.body.decode()
        assert 'name="display_name"' in body
        assert 'href="/settings"' in body  # breadcrumb back to the hub

    def test_display_name_autosaves_no_separate_save_button(self, conn):
        # 2026-08-08: direct feedback ("text inputs once written should
        # auto save") -- this was the one remaining manual-Save text
        # field in Settings; every other control on this page already
        # autosubmitted on change.
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        body = resp.body.decode()
        assert 'name="display_name"' in body
        assert 'onchange="this.form.requestSubmit()"' in body
        assert ">Save<" not in body

    def test_passes_display_name(self, conn):
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        assert resp.context["display_name"] == ""
        db.set_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY, "Petru")
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        assert resp.context["display_name"] == "Petru"

    def test_set_display_name_route_redirects_to_general(self, conn):
        resp = settings_router.set_display_name(display_name="Petru", conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/general"
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == "Petru"

    def test_set_display_name_strips_and_allows_clearing(self, conn):
        settings_router.set_display_name(display_name="  Petru  ", conn=conn)
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == "Petru"
        settings_router.set_display_name(display_name="   ", conn=conn)
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == ""


class TestSettingsAppearance:
    def test_renders_system_light_dark_segmented_control(self, conn):
        resp = settings_router.settings_appearance(_request("/settings/appearance"), conn=conn)
        assert resp.context["active_tab"] == "settings_appearance"
        body = resp.body.decode()
        assert 'id="themeSegmented"' in body
        assert 'data-theme-choice="system"' in body
        assert 'data-theme-choice="light"' in body
        assert 'data-theme-choice="dark"' in body


class TestDataAndBackupCategoryRemoved:
    """2026-08-08 -- direct feedback: "export and backup buttons should go
    into advanced. Published lists should be a separate page. Data &
    backup won't have a use then, delete it." Export & backup moved into
    Settings > Advanced; Habits and Published lists were promoted to
    direct Settings hub categories; the old "Data & backup" sub-hub
    (settings_data.html, GET /settings/data) is gone outright, not just
    unlinked."""

    def test_settings_module_has_no_data_route_or_entries(self):
        assert not hasattr(settings_router, "settings_data")
        assert not hasattr(settings_router, "DATA_ENTRIES")

    def test_habits_page_breadcrumbs_straight_to_settings(self, conn):
        resp = habits_router.list_habits(_request("/habits"), conn=conn)
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]

    def test_published_lists_page_breadcrumbs_straight_to_settings(self, conn):
        resp = published_lists_router.list_index(_request_with_radicale("/published-lists"), conn=conn)
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]

    def test_export_page_redirects_to_advanced(self, conn):
        # 2026-08-08 follow-up: /export stopped being its own page
        # entirely (not just re-parented under Advanced) -- direct
        # feedback: "export and backup should be fully with all
        # buttons... in the advanced page." Every download/import button
        # is inlined into settings_advanced.html now; /export is just a
        # redirect for old links/bookmarks.
        resp = export_router.export_index(_request_with_radicale("/export"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/advanced"

    def test_advanced_page_has_the_export_buttons_inlined(self, conn):
        resp = settings_router.settings_advanced(_request_with_radicale("/settings/advanced"), conn=conn)
        body = resp.body.decode()
        assert "standard formats" in body
        assert 'href="/export/events.ics"' in body
        assert 'href="/export/data.json"' in body
        assert 'action="/export/import/events"' in body
        assert 'action="/export/import/json"' in body


class TestCustomWidgetsToggleRemoved:
    """2026-08-08 -- direct feedback: remove the "Custom widgets" toggle
    entirely, not just from Settings. It was a boolean whose only effect
    was hiding the Widget Builder (the one way to add a widget) inside
    the Customize modal -- not a real preference. The Widget Builder is
    unconditionally available now; there is no route, no app_meta key, no
    Settings > Widgets page left for it."""

    def test_settings_module_has_no_custom_widgets_route(self):
        assert not hasattr(settings_router, "set_custom_widgets")
        assert not hasattr(settings_router, "settings_widgets")

    def test_dashboard_module_has_no_custom_widgets_helpers(self):
        assert not hasattr(dashboard_router, "CUSTOM_WIDGETS_ENABLED_KEY")
        assert not hasattr(dashboard_router, "custom_widgets_enabled")

    def test_customize_route_no_longer_reports_custom_widgets_enabled(self, conn):
        resp = dashboard_router.dashboard_customize(_request("/dashboard/customize"), conn=conn)
        assert "custom_widgets_enabled" not in resp.context

    def test_customize_modal_always_renders_the_builder(self, conn):
        resp = dashboard_router.dashboard_customize(_request("/dashboard/customize"), conn=conn)
        body = resp.body.decode()
        assert 'id="widget-builder-form"' in body
        assert "widget-builder-disabled" not in body


class TestSettingsAdvanced:
    """2026-08-07 -- two explicit, confirmed-destructive purge actions,
    now living on their own Settings > Advanced page rather than a
    "Danger zone" section at the bottom of one long hub. Scope confirmed
    directly with the user before building: "Purge completed" is
    tasks-only; "Purge all" is a full data wipe across the whole app, not
    just tasks."""

    def test_renders_both_purge_actions(self, conn):
        resp = settings_router.settings_advanced(_request_with_radicale("/settings/advanced"), conn=conn)
        assert resp.context["active_tab"] == "settings_advanced"
        body = resp.body.decode()
        assert 'action="/settings/purge-completed"' in body
        assert 'action="/settings/purge-all"' in body

    def test_also_has_reset_layout_now_that_widgets_folded_in(self, conn):
        # 2026-08-08: "Widgets" (Custom widgets toggle + reset layout) was
        # folded into Advanced when the toggle itself was removed -- see
        # routers/settings.py's module docstring.
        resp = settings_router.settings_advanced(_request_with_radicale("/settings/advanced"), conn=conn)
        body = resp.body.decode()
        assert 'action="/dashboard/reset"' in body
        assert "data-confirm-sheet" in body

    def test_completed_task_count_shown(self, conn):
        _make_task(conn, "t1", status="done")
        _make_task(conn, "t2", status="archived")
        _make_task(conn, "t3", status="active")
        resp = settings_router.settings_advanced(_request_with_radicale("/settings/advanced"), conn=conn)
        assert resp.context["completed_task_count"] == 2

    def test_purge_completed_deletes_only_done_and_archived_tasks(self, conn):
        _make_task(conn, "t1", status="done")
        _make_task(conn, "t2", status="archived")
        _make_task(conn, "t3", status="active")
        deleted = db.delete_completed_tasks(conn)
        assert deleted == 2
        remaining = {t["uid"] for t in db.list_tasks(conn)}
        assert remaining == {"t3"}

    def test_purge_completed_route_redirects_to_advanced_page(self, conn):
        _make_task(conn, "t1", status="done")
        resp = settings_router.purge_completed(conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/advanced"
        assert db.list_tasks(conn) == []

    def test_purge_completed_cascades_object_labels(self, conn):
        _make_task(conn, "t1", status="done", tags=["Work"])
        db.delete_completed_tasks(conn)
        assert db.list_labels_for_object(conn, "task", "t1") == []

    def test_purge_all_wipes_every_table(self, conn):
        _make_task(conn, "t1", status="active", tags=["Work"])
        db.upsert_event(conn, {"uid": "e1", "title": "E", "description": "", "status": "active", "all_day": 0, "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Ada", "created_at": _now(), "updated_at": _now()})
        db.upsert_label_config(conn, {"name": "Work", "color": "blue", "created_at": _now()})
        db.upsert_habit(conn, {"uid": "h1", "name": "Read", "created_at": _now(), "updated_at": _now()})
        db.set_app_meta(conn, "some_flag", "1")

        db.purge_all_data(conn)

        assert db.list_tasks(conn) == []
        assert db.list_events(conn) == []
        assert db.list_contacts(conn) == []
        assert db.list_labels(conn) == []
        assert db.list_habits(conn) == []
        assert db.get_app_meta(conn, "some_flag") is None

    def test_purge_all_route_redirects_to_advanced_page(self, conn):
        _make_task(conn, "t1")
        resp = settings_router.purge_all(conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/advanced"
        assert db.list_tasks(conn) == []

    def test_purge_all_lets_home_reseed_fresh(self, conn):
        # app_meta's seeded-dashboard flag is cleared by purge_all_data,
        # so the next visit to Home re-seeds a default layout instead of
        # landing on a permanently empty grid.
        from src.routers import dashboard as dashboard_router

        dashboard_router._ensure_default_widgets(conn)
        assert db.list_dashboard_widgets(conn)

        db.purge_all_data(conn)
        assert db.list_dashboard_widgets(conn) == []

        dashboard_router._ensure_default_widgets(conn)
        assert db.list_dashboard_widgets(conn)


def _make_task(conn, uid, status="active", **overrides):
    row = {
        "uid": uid, "title": f"Task {uid}", "description": "", "status": status,
        "created_at": _now(), "updated_at": _now(),
    }
    row.update(overrides)
    db.upsert_task(conn, row)
    return uid
