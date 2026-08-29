"""Sidebar redesign item 13e (2026-08-29, plans/sidebar-redesign.md §
"The Standard Header") -- the "Standard Page Header (Narrow Variant)": a
thin gradient strip with the page's icon + title, added above every real
top-level destination page's own existing content
(_page_header_narrow.html, included right after {% block content %}).
Purely additive -- doesn't replace any page's own toolbar/breadcrumb/h1,
so these tests just confirm the new markup is present with the right
title/icon per page, not that anything else changed.

Out of scope, not covered here (see STATE.md's own note on this slice):
dashboard.html (keeps its full hero banner), label_detail.html/space
pages (already have the full banner system), and entity detail pages
(task/event/contact/habit detail -- record views, not nav destinations)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db
from src.routers import calendar as calendar_router
from src.routers import contacts as contacts_router
from src.routers import labels as labels_router
from src.routers import notes as notes_router
from src.routers import published_lists as published_lists_router
from src.routers import search as search_router
from src.routers import settings as settings_router
from src.routers import tasks as tasks_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bare_request(path="/"):
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "", "headers": [],
        }
    )


def _request_with_app(path, db_path, backup_dir=None):
    """Same helper as test_display_prefs_settings.py's own -- needed for
    routes (published_lists' list_index, settings_data_maintenance) that
    read request.app.state directly rather than going through the `conn`
    dependency alone."""
    fake_app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
        db_path=db_path, backup_dir=backup_dir, radicale_base_url="http://localhost:5232",
    )))
    return Request(
        {
            "type": "http", "method": "GET", "path": path, "query_string": b"",
            "scheme": "http", "server": ("testserver", 80), "root_path": "",
            "headers": [], "app": fake_app,
        }
    )


def _assert_narrow_header(body: str, title: str, icon_name: str) -> None:
    assert 'class="page-header-narrow"' in body
    assert f'class="page-header-narrow-title">{title}</h2>' in body
    assert f'#icon-{icon_name}' in body


class TestPageHeaderNarrowRollout:
    def test_tasks(self, conn):
        resp = tasks_router.list_tasks(_bare_request("/tasks"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Tasks", "check-square")

    def test_calendar_fourweek(self, conn):
        resp = calendar_router.four_week_view(_bare_request("/calendar/fourweek"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Calendar", "calendar")

    def test_calendar_week_is_planner(self, conn):
        # Week's own tabbar identity is "Planner" (icon('clock')), not
        # "Calendar" -- see calendar_week.html's own comment.
        resp = calendar_router.week_view(_bare_request("/calendar/week"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Planner", "clock")

    def test_contacts(self, conn):
        resp = contacts_router.list_contacts(_bare_request("/contacts"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Contacts", "address-book")

    def test_search(self, conn):
        resp = search_router.search_page(_bare_request("/search"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Search", "command")

    def test_notes(self, conn):
        resp = notes_router.list_notes(_bare_request("/notes"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Notes", "file-text")

    def test_settings_index(self, conn):
        resp = settings_router.settings_index(_bare_request("/settings"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Settings", "settings")

    def test_settings_general(self, conn):
        resp = settings_router.settings_general(_bare_request("/settings/general"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "General", "user")

    def test_settings_appearance(self, conn):
        resp = settings_router.settings_appearance(_bare_request("/settings/appearance"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Appearance", "sun")

    def test_labels_manage(self, conn):
        resp = labels_router.manage_labels(_bare_request("/settings/labels"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Labels", "tag")

    def test_settings_holidays(self, conn):
        resp = settings_router.settings_holidays(_bare_request("/settings/holidays"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Holidays", "calendar")

    def test_settings_time_blocks(self, conn):
        resp = settings_router.settings_time_blocks(_bare_request("/settings/time-blocks"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Sleep &amp; Leisure Time", "moon")

    def test_settings_data_maintenance(self, conn, tmp_path):
        req = _request_with_app("/settings/data-maintenance", tmp_path / "cache.sqlite", backup_dir=tmp_path / "backups")
        resp = settings_router.settings_data_maintenance(req, conn=conn)
        _assert_narrow_header(resp.body.decode(), "Data &amp; Maintenance", "database")

    def test_published_lists(self, conn, tmp_path):
        resp = published_lists_router.list_index(_request_with_app("/published-lists", tmp_path / "cache.sqlite"), conn=conn)
        _assert_narrow_header(resp.body.decode(), "Published Lists", "share-2")

    def test_dashboard_unaffected(self, conn):
        # Home keeps its own full hero banner/greeting -- no narrow header.
        from src.routers import dashboard as dashboard_router

        resp = dashboard_router.dashboard_view(_bare_request("/"), conn=conn)
        assert 'class="page-header-narrow"' not in resp.body.decode()

    def test_label_page_unaffected(self, conn):
        # Space/label pages keep the full banner system -- not converted
        # to the narrow variant in this slice (see STATE.md's own note).
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        resp = labels_router.label_detail("CS101", _bare_request("/labels/CS101"), conn=conn)
        assert 'class="page-header-narrow"' not in resp.body.decode()
