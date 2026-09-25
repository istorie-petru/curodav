"""The nav rail's Groups tree and Pinned section (base.html,
deps.py::_sidebar_groups/_sidebar_pinned). Originally the collapsible
Spaces/Projects tree (2026-08-29 sidebar redesign slice 13a); rewritten for
labels-as-modules slice c (2026-09-25): every group (the text label_group)
gets an entry linking to /groups/<name>, its chevron reveals its members
that have "Pin to sidebar" on, and pinned labels with no group are listed
flat under "Pinned". The rail-wide expand toggle is present on every page.

Uses a request with a fake app because deps.py's sidebar helpers open their
own connection off request.app.state.settings.db_path."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db
from src.routers import contacts as contacts_router
from src.routers import label_pages
from src.routers import labels as labels_router
from src.routers import projects as projects_router
from src.routers import spaces as spaces_router


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _request(path, conn):
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


def _label(conn, name, **extra):
    row = {"name": name, "created_at": _now()}
    row.update(extra)
    db.upsert_label_config(conn, row)


def _page(conn, name="Solo"):
    if not db.get_label_config(conn, name):
        _label(conn, name)
    return label_pages.label_page(name, _request(f"/labels/{name}", conn), conn=conn).body.decode()


class TestGroupsTree:
    def test_group_without_pinned_members_has_no_chevron(self, conn):
        _label(conn, "CS101", label_group="Uni")
        body = _page(conn)
        assert '<div class="sidebar-section-label" aria-hidden="true">Groups</div>' in body
        assert 'href="/groups/Uni" class="tab-btn tab-btn-space' in body
        assert 'data-space-name="Uni"' in body
        assert "sidebar-tree-toggle" not in body
        assert "sidebar-tree-children" not in body

    def test_pinned_members_nest_under_the_group(self, conn):
        _label(conn, "CS101", label_group="Uni", sidebar_pin=1)
        _label(conn, "Art", label_group="Uni")
        body = _page(conn)
        assert "sidebar-tree-item has-children" in body
        assert 'aria-label="Toggle Uni labels"' in body
        assert 'href="/labels/CS101" class="tab-btn tab-btn-child' in body
        assert 'href="/labels/Art" class="tab-btn' not in body  # not pinned

    def test_child_page_marks_child_active_and_opens_its_group(self, conn):
        _label(conn, "CS101", label_group="Uni", sidebar_pin=1)
        body = _page(conn, "CS101")
        assert 'href="/labels/CS101" class="tab-btn tab-btn-child active"' in body
        assert 'aria-expanded="true" aria-label="Toggle Uni labels"' in body

    def test_other_page_leaves_the_group_closed(self, conn):
        _label(conn, "CS101", label_group="Uni", sidebar_pin=1)
        body = _page(conn)
        assert 'aria-expanded="false" aria-label="Toggle Uni labels"' in body

    def test_group_page_marks_its_own_entry_active(self, conn):
        _label(conn, "CS101", label_group="Uni")
        body = label_pages.group_page("Uni", _request("/groups/Uni", conn), conn=conn).body.decode()
        assert 'href="/groups/Uni" class="tab-btn tab-btn-space active"' in body

    def test_no_groups_no_section(self, conn):
        body = _page(conn)
        assert ">Groups</div>" not in body


class TestPinnedSection:
    def test_pinned_ungrouped_label_is_listed_flat(self, conn):
        _label(conn, "Website", is_project=1, sidebar_pin=1)
        body = _page(conn)
        assert '<div class="sidebar-section-label" aria-hidden="true">Pinned</div>' in body
        assert 'href="/labels/Website" class="tab-btn tab-btn-project' in body

    def test_pinned_grouped_label_is_not_listed_twice(self, conn):
        _label(conn, "Thesis", label_group="Uni", sidebar_pin=1)
        body = _page(conn)
        assert "tab-btn-project" not in body
        assert ">Pinned</div>" not in body

    def test_archived_or_unpinned_labels_are_left_out(self, conn):
        _label(conn, "Old", sidebar_pin=1)
        db.archive_project(conn, "Old")
        _label(conn, "Quiet")
        body = _page(conn)
        assert "tab-btn-project" not in body


class TestExpandToggle:
    def test_expand_toggle_present_with_groups(self, conn):
        _label(conn, "CS101", label_group="Uni")
        assert 'id="sidebar-expand-toggle"' in _page(conn)

    def test_expand_toggle_present_with_nothing(self, conn):
        assert 'id="sidebar-expand-toggle"' in _page(conn)

    def test_expand_toggle_uses_the_dedicated_sidebar_icon_not_a_chevron(self, conn):
        # A chevron already means "expand this one tree item" on the same
        # rail, so the whole-sidebar toggle uses `icon-sidebar`.
        body = _page(conn)
        toggle_start = body.index('id="sidebar-expand-toggle"')
        toggle_markup = body[toggle_start : toggle_start + 200]
        assert "#icon-sidebar" in toggle_markup
        assert "#icon-chevron-right" not in toggle_markup


class TestChevronFitsInTheExpandedRail:
    """2026-09-25 bug report: the chevron was "invisible regardless of
    sidebar width". The expanded rail's `.tab-btn{width:100%}` made the
    group link take the whole row and push the chevron past the rail's
    clipped edge. Guard the CSS fix that lets the link shrink."""

    def test_expanded_and_mobile_rules_let_the_link_shrink(self):
        css = (Path(__file__).resolve().parent.parent / "src" / "static" / "style.css").read_text()
        assert "html[data-sidebar-expanded] .sidebar-tree-row > .tab-btn{flex:1 1 auto; width:auto; min-width:0;}" in css
        assert "  .sidebar-tree-row > .tab-btn{flex:1 1 auto; width:auto; min-width:0;}" in css


class TestSidebarQuickAdd:
    def test_default_page_points_quick_add_at_task_event_modal(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        # label_detail's own active_tab is "label" (a single label's page,
        # distinct from the "labels" manage table) -- 2026-09-14: this
        # still defaults quick-add to the Label tab, same as the manage
        # page, not the generic "task" fallback other pages get.
        assert 'href="/quick/add?default_tab=label" data-modal class="tab-btn sidebar-quick-add"' in body

    def test_contacts_page_points_quick_add_at_contact_tab(self, conn):
        # 2026-09-14 (direct request, "the quick add should support both
        # contacts and labels"): quick_add.html grew a Contact tab, so the
        # sidebar's global "+" no longer special-cases Contacts into its
        # own standalone /contacts/new modal -- it opens the same merged
        # /quick/add modal as every other page, just pre-focused on
        # Contact via `default_tab`.
        resp = contacts_router.list_contacts(_request("/contacts", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/quick/add?default_tab=contact" data-modal class="tab-btn sidebar-quick-add"' in body

    def test_labels_manage_page_points_quick_add_at_label_tab(self, conn):
        resp = labels_router.manage_labels(_request("/settings/labels", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/quick/add?default_tab=label" data-modal class="tab-btn sidebar-quick-add"' in body
