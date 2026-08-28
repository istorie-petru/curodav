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


def _request_with_radicale(path, db_path=None, backup_dir=None):
    """routers/published_lists.py/export.py both read
    `request.app.state.settings.radicale_base_url` -- a bare `_request()`
    has no ASGI `app` in scope at all, so those two specifically need
    this fuller fake instead. `db_path`/`backup_dir` default to None and
    can be supplied by the tests that render the merged Data &
    Maintenance page, whose route reads all three."""
    from types import SimpleNamespace

    fake_app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(
                radicale_base_url="http://localhost:5232",
                db_path=db_path,
                backup_dir=backup_dir,
            )
        )
    )
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
        for name in ("General", "Appearance", "Labels", "Holidays", "Sleep &amp; Leisure Time", "Data &amp; Maintenance", "Published lists"):
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
            "/settings/labels",
            "/settings/holidays",
            "/settings/time-blocks",
            "/settings/data-maintenance",
            "/published-lists",
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


class TestSyncConflictHubBadge:
    """2026-08-17 (SETTINGS_UI_GUIDE.md): the hub's Data & Maintenance row
    carries an unresolved-sync-conflict count badge, so a category with 3
    conflicts doesn't look identical to one with 0."""

    def test_no_badge_when_there_are_no_conflicts(self, conn):
        resp = settings_router.settings_index(_request(), conn=conn)
        assert resp.context["conflict_count"] == 0
        body = resp.body.decode()
        assert "unresolved sync conflict" not in body

    def test_badge_shows_the_conflict_count(self, conn):
        db.create_sync_conflict(conn, "event", "e1", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        db.create_sync_conflict(conn, "event", "e2", "start_at", "2026-08-10T11:00:00", (1000, 0, "device-b"), (2000, 0, "device-a"))
        resp = settings_router.settings_index(_request(), conn=conn)
        assert resp.context["conflict_count"] == 2
        body = resp.body.decode()
        assert 'href="/settings/data-maintenance"' in body
        assert ">2<" in body
        assert "unresolved sync conflicts" in body


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

    def test_habits_list_page_is_retired_redirects_to_tasks(self, conn):
        # 2026-08-28 "major rework" session (item 2): the standalone Habits
        # list page (and its "straight to Settings" breadcrumb) is gone --
        # every Habit entity now renders as a row in the Tasks table's own
        # Habits group instead (routers/tasks.py's _habit_group_items).
        resp = habits_router.list_habits_redirect()
        assert resp.status_code == 302
        assert resp.headers["location"] == "/tasks"

    def test_published_lists_page_breadcrumbs_straight_to_settings(self, conn):
        resp = published_lists_router.list_index(_request_with_radicale("/published-lists"), conn=conn)
        assert resp.context["crumbs"] == [{"url": "/settings", "name": "Settings"}]

    def test_export_page_redirects_to_data_maintenance(self, conn):
        # 2026-08-08 follow-up: /export stopped being its own page
        # entirely (not just re-parented under Advanced) -- direct
        # feedback: "export and backup should be fully with all buttons...
        # in the advanced page." Every download/import button is inlined
        # into settings_data_maintenance.html's "Export & import" section
        # now (Advanced's old home, folded into that page 2026-08-17);
        # /export is just a redirect for old links/bookmarks.
        resp = export_router.export_index(_request_with_radicale("/export"), conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/data-maintenance"

    def test_export_import_live_in_sync_menu_dialogs_not_on_the_page(self, conn, tmp_path):
        # 2026-08-26 third pass: the standalone Export & import card is
        # gone from the merged page entirely -- Export… / Import… are menu
        # items on the Sync status card now, each opening its own dialog;
        # the Backup card's "Restore a file…" opens the same Import one
        # (restoring a downloaded data.json goes through it too).
        resp = settings_router.settings_data_maintenance(_request_with_radicale("/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn)
        body = resp.body.decode()
        assert 'href="/export/modal" data-modal' in body
        assert body.count('href="/export/import-modal" data-modal') == 2  # Sync menu + Backup card
        # Neither form lives on the page anymore.
        assert "/export/download" not in body
        assert "/export/import/auto" not in body

    def test_export_modal_renders_the_download_form(self, conn):
        resp = export_router.export_modal(_request_with_radicale("/export/modal"), conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'action="/export/download"' in body
        assert 'method="get"' in body
        assert "data-modal-get" in body  # keeps modal.js's POST interceptor out of the way
        assert "data-dm-preview=" in body
        assert "Includes:" in body

    def test_import_modal_renders_the_drop_zone(self, conn):
        resp = export_router.import_modal(_request_with_radicale("/export/import-modal"))
        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'action="/export/import/auto"' in body
        assert "data-dm-dropzone" in body
        assert "auto-detects type" in body
        assert 'name="merge"' in body


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
    """2026-08-07 -- two explicit, confirmed-destructive purge actions.
    2026-08-17 they lived on the merged Data & Maintenance page's "Danger
    zone" section; 2026-08-26's second-pass redesign removed that section
    entirely: "Purge completed" is routine housekeeping now (a grey button
    in the Maintenance & cleanup card), and purge-all lives behind the
    Database status card's own "Reset database (purge all)" menu item,
    which opens a confirmation dialog carrying the typed-DELETE-ALL check
    (check first, then delete)."""

    def test_purge_completed_on_page_and_purge_all_behind_the_modal(self, conn, tmp_path):
        resp = settings_router.settings_data_maintenance(_request_with_radicale("/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn)
        assert resp.context["active_tab"] == "settings_data_maintenance"
        body = resp.body.decode()
        # Housekeeping purge is a plain form on the page...
        assert 'action="/settings/purge-completed"' in body
        # ...while the full wipe is NOT on the page at all anymore -- it's
        # reachable only through the Database card's modal trigger.
        assert 'action="/settings/purge-all"' not in body
        assert 'href="/settings/purge-confirm" data-modal' in body

    def test_purge_confirm_modal_carries_the_typed_phrase_gate(self, conn):
        resp = settings_router.purge_confirm_page(_request_with_radicale("/settings/purge-confirm"))
        assert resp.status_code == 200
        body = resp.body.decode()
        assert 'action="/settings/purge-all"' in body
        assert "data-purge-phrase" in body
        assert 'placeholder="DELETE ALL"' in body
        # The gate doesn't depend on JS: the button ships disabled.
        assert "data-purge-btn disabled" in body
        assert "Permanently Delete Everything" in body

    def test_also_has_reset_layout_now_that_widgets_folded_in(self, conn, tmp_path):
        # 2026-08-08: "Widgets" (Custom widgets toggle + reset layout) was
        # folded into Advanced when the toggle itself was removed -- see
        # routers/settings.py's module docstring; 2026-08-17 that folded
        # page became Data & Maintenance's "Maintenance & upkeep" section.
        resp = settings_router.settings_data_maintenance(_request_with_radicale("/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn)
        body = resp.body.decode()
        assert 'action="/dashboard/reset"' in body
        assert "data-confirm-sheet" in body

    def test_completed_task_count_shown(self, conn, tmp_path):
        _make_task(conn, "t1", status="done")
        _make_task(conn, "t2", status="archived")
        _make_task(conn, "t3", status="active")
        resp = settings_router.settings_data_maintenance(_request_with_radicale("/settings/data-maintenance", db_path=tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups"), conn=conn)
        assert resp.context["completed_task_count"] == 2

    def test_purge_completed_deletes_only_done_and_archived_tasks(self, conn):
        _make_task(conn, "t1", status="done")
        _make_task(conn, "t2", status="archived")
        _make_task(conn, "t3", status="active")
        deleted = db.delete_completed_tasks(conn)
        assert deleted == 2
        remaining = {t["uid"] for t in db.list_tasks(conn)}
        assert remaining == {"t3"}

    def test_purge_completed_route_redirects_to_data_maintenance_page(self, conn):
        _make_task(conn, "t1", status="done")
        resp = settings_router.purge_completed(conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/data-maintenance"
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
        db.upsert_time_block(conn, {"uid": "tb1", "kind": "sleep", "label": "Night", "start_time": "00:00", "end_time": "05:59", "days": "Monday"})
        db.set_app_meta(conn, "some_flag", "1")

        db.purge_all_data(conn)

        assert db.list_tasks(conn) == []
        assert db.list_events(conn) == []
        assert db.list_contacts(conn) == []
        assert db.list_labels(conn) == []
        assert db.list_habits(conn) == []
        assert db.list_time_blocks(conn) == []
        assert db.get_app_meta(conn, "some_flag") is None

    def test_purge_all_route_redirects_to_data_maintenance_page(self, conn):
        from types import SimpleNamespace

        _make_task(conn, "t1")
        # purge_all reads request.app.state (to drop the memoized auth
        # secret, see test_auth.py::TestPurgeAllInvalidatesSession), so it
        # needs a request whose scope carries an `app` -- the bare _request
        # helper doesn't have one.
        fake_app = SimpleNamespace(state=SimpleNamespace())
        req = Request(
            {
                "type": "http", "method": "POST", "path": "/settings/purge-all",
                "query_string": b"", "scheme": "http", "server": ("testserver", 80),
                "root_path": "", "headers": [], "app": fake_app,
            }
        )
        resp = settings_router.purge_all(req, conn=conn)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings/data-maintenance"
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
