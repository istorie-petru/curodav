"""2026-08-07 nav rework + Databases/Grades removal acceptance tests.

Two related changes, both covered here:

  1. Contacts restored as a primary tabbar destination
     (Home/Calendar/Tasks/Contacts/Settings), Databases removed
     from the tabbar entirely -- see base.html's nav comment and
     routers/settings.py/_settings_nav.html's own removal notes for what
     moved out of the Settings hub as a result.
  2. Databases (and Grades, built on top of it) deactivated and deleted
     entirely -- routers/databases.py, routers/grades.py, src/grades.py,
     src/formula_engine.py, every template, and the `databases`/
     `database_columns`/`database_rows`/`grades` tables are all gone, not
     just unlinked. See features/architecture.md's Grades/Databases
     removal note and db.py's own removal comments.

This file replaces test_databases_router.py/test_databases_db.py/
test_phase9_grades.py/test_formula_engine.py (deleted outright, per §4's
standing rule -- their whole subject no longer exists) and complements
the in-place fixes made to test_phase2_labels.py/test_phase4_modules.py/
test_phase10_export.py/test_phase8_settings_hub.py, which each covered
other things too and so were edited rather than deleted.

2026-08-15: the Schedule tab/tests (TestActiveTabHighlighting's Schedule
cases, `test_tabbar_includes_schedule_and_contacts_not_databases`) were
removed/edited along with the whole Schedule module -- see
plans/STATE.md's removal entry."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router
from src.routers import dashboard as dashboard_router
from src.routers import labels as labels_router


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _request(path="/"):
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


# --------------------------------------------------------------------- #
# 1. Tabbar contents
# --------------------------------------------------------------------- #


class TestTabbarContents:
    def test_tabbar_includes_contacts_not_databases_or_schedule(self, conn):
        db.set_app_meta(conn, dashboard_router._MINI_CALENDAR_BACKFILL_KEY, "1")
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        body = resp.body.decode()
        assert 'data-tab="contacts"' in body
        assert 'href="/contacts"' in body
        # Databases is gone from the tabbar entirely -- no tab, no link.
        assert 'data-tab="databases"' not in body
        assert 'href="/databases"' not in body
        # 2026-08-15: Schedule is gone entirely too -- no tab, no link.
        assert 'data-tab="schedule"' not in body
        assert 'href="/schedule"' not in body

    def test_dashboard_see_more_no_longer_links_databases_or_contacts(self, conn):
        # Contacts is a primary tab now (no longer needed in the mobile
        # "See more" overflow list); Databases is gone outright. The old
        # `dashboard-see-more` overflow list itself is gone too -- it was
        # removed with the 2026-08-07 dashboard rework (the single "+" quick
        # add + edit-mode buttons replaced the old page-actions bar).
        db.set_app_meta(conn, dashboard_router._MINI_CALENDAR_BACKFILL_KEY, "1")
        resp = dashboard_router.dashboard_view(_request("/"), conn=conn)
        body = resp.body.decode()
        assert "dashboard-see-more" not in body
        assert 'href="/databases"' not in body


# --------------------------------------------------------------------- #
# 2. active_tab highlighting on Contacts pages and sub-pages
# --------------------------------------------------------------------- #


class TestActiveTabHighlighting:
    def test_contacts_list_page_sets_and_highlights_contacts_tab(self, conn):
        resp = contacts_router.list_contacts(_request("/contacts"), conn=conn)
        assert resp.context["active_tab"] == "contacts"
        body = resp.body.decode()
        assert 'data-tab="contacts" class="tab-btn active"' in body

    def test_contact_detail_and_edit_sub_pages_highlight_contacts_tab(self, conn):
        db.upsert_contact(conn, {"uid": "p1", "full_name": "Ada Lovelace", "created_at": _now(), "updated_at": _now()})
        detail = contacts_router.contact_detail("p1", _request("/contacts/p1"), conn=conn)
        edit = contacts_router.edit_contact_form("p1", _request("/contacts/p1/edit"), conn=conn)
        assert detail.context["active_tab"] == "contacts"
        assert edit.context["active_tab"] == "contacts"


class TestSpacePageNavHighlighting:
    """A Space/label's own generated page is an independent destination
    (2026-08-09): its own rail link is the only thing that highlights --
    the Settings gear must NOT, even though the Labels *manage* page
    (/labels) still does (it lives inside Settings). Before this fix the
    detail page shared active_tab="labels" with the manage page, so every
    Space/Project page lit the Settings icon AND its own rail link."""

    def _space_page_request(self, path, conn):
        from pathlib import Path
        from types import SimpleNamespace

        db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
        fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path)))
        req = Request(
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
        req.scope["app"] = fake_app
        return req

    def _make_space(self, conn, name):
        db.upsert_label_config(conn, {"name": name, "generate_space": 1, "created_at": _now()})

    def test_label_detail_sets_independent_active_tab(self, conn):
        self._make_space(conn, "Uni")
        resp = labels_router.label_detail("Uni", self._space_page_request("/labels/Uni", conn), conn=conn)
        assert resp.context["active_tab"] == "label"

    def test_space_page_highlights_only_its_own_rail_link(self, conn):
        self._make_space(conn, "Uni")
        resp = labels_router.label_detail("Uni", self._space_page_request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/labels/Uni" class="tab-btn tab-btn-space active"' in body
        assert 'data-tab="settings" class="tab-btn active"' not in body

    def test_plain_label_page_has_no_settings_or_rail_highlight(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        resp = labels_router.label_detail("CS101", self._space_page_request("/labels/CS101", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-tab="settings" class="tab-btn active"' not in body
        # CS101 isn't a Space, so it has no rail link to light up either.
        assert 'href="/labels/CS101" class="tab-btn tab-btn-space' not in body

    def test_labels_manage_page_still_highlights_settings(self, conn):
        self._make_space(conn, "Uni")
        resp = labels_router.manage_labels(self._space_page_request("/labels", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-tab="settings" class="tab-btn active"' in body


# --------------------------------------------------------------------- #
# 3. Databases/Grades feature is gone, not just unlinked
# --------------------------------------------------------------------- #


class TestDatabasesFeatureRemoved:
    def test_databases_and_grades_tables_do_not_exist(self, conn):
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "databases" not in tables
        assert "database_columns" not in tables
        assert "database_rows" not in tables
        assert "grades" not in tables

    def test_db_module_no_longer_exposes_database_or_grade_accessors(self):
        for name in (
            "upsert_database", "get_database", "list_databases",
            "archive_database", "unarchive_database", "delete_database",
            "upsert_database_column", "get_database_column", "list_database_columns",
            "upsert_database_row", "get_database_row", "list_database_rows",
            "set_database_row_value",
            "upsert_grade", "get_grade", "list_grades", "delete_grade", "delete_grades_by_class",
        ):
            assert not hasattr(db, name), f"db.{name} should have been removed"

    def test_no_databases_router_or_grades_router_modules(self):
        import importlib

        # 2026-08-08: src.label_modules joins this list -- the Phase 4
        # "Sections" checkbox group/module-gating mechanism it defined is
        # removed entirely, not just deactivated, same treatment as the
        # three modules already covered here. See routers/labels.py's own
        # removal note.
        #
        # 2026-08-15: src.routers.schedule/src.schedule join this list too
        # -- the whole Schedule module is removed entirely, not just
        # unlinked. See plans/STATE.md's removal entry.
        for module_name in (
            "src.routers.databases", "src.routers.grades", "src.grades",
            "src.formula_engine", "src.label_modules",
            "src.routers.schedule", "src.schedule",
        ):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)

    def test_no_widget_type_offers_databases(self):
        assert "databases" not in dashboard_router.WIDGET_TYPES
        assert "grades" not in dashboard_router.WIDGET_TYPES


# --------------------------------------------------------------------- #
# 4. Routes are unregistered, not just unlinked -- 404 (not just missing
#    a nav link) is the real acceptance for "deleted", not "deactivated".
# --------------------------------------------------------------------- #


class TestRoutesNotRegistered:
    def _registered_paths(self):
        from src.main import app

        return {getattr(r, "path", None) for r in app.routes}

    def test_databases_routes_are_gone(self):
        paths = self._registered_paths()
        assert "/databases" not in paths
        assert "/databases/{uid}" not in paths
        assert "/databases/new" not in paths

    def test_grades_routes_are_gone(self):
        paths = self._registered_paths()
        assert not any(p and p.startswith("/grades") for p in paths)

    def test_schedule_routes_are_gone(self):
        paths = self._registered_paths()
        assert not any(p and p.startswith("/schedule") for p in paths)
