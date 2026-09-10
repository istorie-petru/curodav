"""Sidebar redesign item 13e (2026-08-29, plans/sidebar-redesign.md §
"The Standard Header") -- the "Standard Page Header (Narrow Variant)": a
thin gradient strip with the page's icon + title, rendered by
_page_header_narrow.html's page_header_narrow() macro at the top of every
real top-level destination page.

2026-08-29 follow-up (direct request): Tasks/Contacts/Calendar's own
`.toolbar.top-app-bar.toolbar-2row` row is gone outright now (their
"+ New"/inline-search controls were redundant with the sidebar's own
global quick-add/Search) -- whatever real controls they had (filters,
prev/next nav, the Month|Day subnav) fold into the header's own
`{% call %}` actions slot instead. The header also grew an optional
single background banner image, set once in Settings > Appearance and
reused everywhere (deps.py's PAGE_HEADER_BANNER_SCOPE) -- a different
mechanism from Home/label pages' own per-page banners.
TestPageHeaderNarrowRollout covers the plain icon+title rollout;
TestNarrowHeaderActionsSlot covers the folded-in toolbar controls;
TestPageHeaderBanner covers the banner.

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


class TestNarrowHeaderActionsSlot:
    """2026-08-29 follow-up (direct request): Tasks/Contacts/Calendar's
    old `.toolbar.top-app-bar.toolbar-2row` row is gone -- real controls
    (filters, nav, the Month|Day subnav) now render inside the narrow
    header's own actions slot, and the redundant "+ New"/inline-search
    controls are dropped outright, not relocated."""

    def test_tasks_toolbar_row_is_gone(self, conn):
        resp = tasks_router.list_tasks(_bare_request("/tasks"), conn=conn)
        body = resp.body.decode()
        assert 'class="toolbar top-app-bar toolbar-2row"' not in body
        # '/tasks/new' still appears once, legitimately -- the empty-state
        # "New task" button in _tasks_body.html, unrelated to the removed
        # toolbar button -- so this checks the visible search box's own
        # markup specifically rather than a broader, collision-prone
        # substring.
        assert 'type="search" name="q"' not in body
        assert "filter-dropdown-trigger" in body  # Date filter survives, relocated

    def test_contacts_toolbar_row_is_gone(self, conn):
        resp = contacts_router.list_contacts(_bare_request("/contacts"), conn=conn)
        body = resp.body.decode()
        assert 'class="toolbar top-app-bar toolbar-2row"' not in body
        assert 'type="search"' not in body

    def test_calendar_month_toolbar_row_is_gone_subnav_survives(self, conn):
        resp = calendar_router.month_view(_bare_request("/calendar"), year=2026, month=8, conn=conn)
        body = resp.body.decode()
        assert 'class="toolbar top-app-bar toolbar-2row"' not in body
        assert 'href="/events/new"' not in body
        assert 'class="segmented calendar-subnav"' in body  # Month|Day switcher survives, relocated

    def test_calendar_day_back_link_survives_in_header(self, conn):
        from datetime import date

        today_iso = date.today().isoformat()
        resp = calendar_router.day_view(today_iso, _bare_request(f"/calendar/day/{today_iso}"), conn=conn)
        body = resp.body.decode()
        assert 'class="toolbar top-app-bar toolbar-2row"' not in body
        assert 'href="/calendar/fourweek"' in body  # "Back to Calendar" survives, relocated

    def test_every_folded_page_still_has_exactly_one_h1(self, conn):
        # Each toolbar carried the page's only real (sr-only) <h1> -- must
        # not have been silently dropped when the toolbar was.
        import re

        pages = [
            tasks_router.list_tasks(_bare_request("/tasks"), conn=conn),
            contacts_router.list_contacts(_bare_request("/contacts"), conn=conn),
            calendar_router.month_view(_bare_request("/calendar"), conn=conn),
            calendar_router.week_view(_bare_request("/calendar/week"), conn=conn),
            calendar_router.four_week_view(_bare_request("/calendar/fourweek"), conn=conn),
        ]
        for resp in pages:
            body = resp.body.decode()
            assert len(re.findall(r"<h1[ >]", body)) == 1, body


class TestNarrowHeaderBackPosition:
    """2026-09-11 (direct request): "the page-header-narrow-back, it
    should be on the left most, not right most." The crumbs-driven back
    arrow now renders as the header's first child (before the icon+
    title), not inside the right-aligned `.page-header-narrow-actions`
    slot -- see the macro's own comment."""

    def test_back_arrow_precedes_icon_and_title(self, conn):
        resp = settings_router.settings_holidays(_bare_request("/settings/holidays"), conn=conn)
        body = resp.body.decode()
        back_pos = body.index("page-header-narrow-back")
        icon_pos = body.index("page-header-narrow-icon")
        title_pos = body.index("page-header-narrow-title")
        assert back_pos < icon_pos < title_pos

    def test_back_arrow_renders_without_an_actions_slot(self, conn):
        # Settings pages pass crumbs but no {% call %} block -- proves the
        # back arrow no longer depends on (or lives inside)
        # .page-header-narrow-actions, unlike before this slice.
        resp = settings_router.settings_holidays(_bare_request("/settings/holidays"), conn=conn)
        body = resp.body.decode()
        assert "page-header-narrow-back" in body
        assert "page-header-narrow-actions" not in body


class TestPageHeaderBanner:
    """2026-08-29 follow-up (direct request): one banner image, set once
    in Settings > Appearance, reused as the background on every standard
    page's narrow header (deps.py's page_header_banner()/
    PAGE_HEADER_BANNER_SCOPE) -- a different mechanism from Home/label
    pages' own per-page banners (db.get_page_banner's `page_key` is a
    free-form string; this is one more fixed sentinel value)."""

    def _set_banner(self, conn):
        db.set_page_banner(conn, "__page_header__", {
            "kind": "upload", "image_b64": "Zm9v", "image_type": "jpeg", "version": "abc123",
        })

    def test_no_banner_by_default(self, conn, tmp_path):
        resp = tasks_router.list_tasks(_request_with_app("/tasks", tmp_path / "cache.sqlite"), conn=conn)
        body = resp.body.decode()
        assert 'class="page-header-narrow"' in body
        assert "page-header-narrow-bg" not in body

    def test_banner_renders_on_a_standard_page(self, conn, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._set_banner(conn)
        resp = tasks_router.list_tasks(_request_with_app("/tasks", db_path), conn=conn)
        body = resp.body.decode()
        assert 'class="page-header-narrow has-banner"' in body
        assert 'src="/banners/image?scope=__page_header__&amp;v=abc123"' in body

    def test_banner_is_shared_across_different_pages(self, conn, tmp_path):
        db_path = tmp_path / "cache.sqlite"
        self._set_banner(conn)
        tasks_body = tasks_router.list_tasks(_request_with_app("/tasks", db_path), conn=conn).body.decode()
        contacts_body = contacts_router.list_contacts(_request_with_app("/contacts", db_path), conn=conn).body.decode()
        assert 'class="page-header-narrow has-banner"' in tasks_body
        assert 'class="page-header-narrow has-banner"' in contacts_body

    def test_settings_appearance_shows_add_banner_by_default(self, conn):
        resp = settings_router.settings_appearance(_bare_request("/settings/appearance"), conn=conn)
        body = resp.body.decode()
        # Checked against the link's own exact text, not a bare substring
        # -- this page's Edit mode row legitimately mentions "Add/Change
        # banner" in prose (a different, pre-existing feature: the
        # dashboard/label edit-mode toolbar's own per-page banner button).
        assert 'scope=__page_header__' in body
        link_start = body.index('scope=__page_header__')
        link_end = body.index("</a>", link_start)
        link = body[link_start:link_end]
        assert "Add banner" in link
        assert "Change banner" not in link

    def test_settings_appearance_shows_change_banner_once_set(self, conn):
        self._set_banner(conn)
        resp = settings_router.settings_appearance(_bare_request("/settings/appearance"), conn=conn)
        body = resp.body.decode()
        assert "Change banner" in body

    def test_banner_editor_accepts_the_page_header_scope(self, conn):
        from src.routers import banners as banners_router

        self._set_banner(conn)
        resp = banners_router.banner_editor(_bare_request("/banners/editor"), scope="__page_header__", page_url="/settings/appearance", conn=conn)
        body = resp.body.decode()
        assert "Remove" in body
        assert 'name="scope" value="__page_header__"' in body
