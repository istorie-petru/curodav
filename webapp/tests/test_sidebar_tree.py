"""2026-08-29 sidebar redesign slice 13a (plans/STATE.md item 13a) --
collapsible nested Spaces/Projects tree in the nav rail.

Covers: a Space's child labels (label_config.parent_name -- the same
relationship label_detail.html's own "Projects" section already reads via
db.list_child_labels) render nested under it in base.html, with a chevron
toggle only when it actually has children; a child that's itself a Space
links to its generated page, a plain child label links to its settings
edit page; visiting a child's own page marks both that child link and its
parent's toggle active/open by default; the rail-wide expand toggle
(2026-08-29 follow-up: relocated to a fixed spot at the top of the rail,
always rendered) is present on every page regardless of whether the
account has any Spaces at all; and none of this leaks into pages/labels
that aren't part of any tree.

Uses the same request-with-fake-app helper as
test_nav_and_deactivation.py::TestSpacePageNavHighlighting, for the same
reason: deps.py's sidebar_spaces() (now enriched with `children`) opens
its own connection off request.app.state.settings.db_path, which the
plain hand-built Request object this suite normally uses doesn't have."""

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


def _make_space(conn, name, **extra):
    row = {"name": name, "generate_space": 1, "created_at": _now()}
    row.update(extra)
    db.upsert_label_config(conn, row)


class TestNestedTreeRendering:
    def test_space_with_no_children_renders_no_toggle_or_children_div(self, conn):
        _make_space(conn, "Uni")
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-space-name="Uni"' in body
        assert "sidebar-tree-item has-children" not in body
        assert "sidebar-tree-toggle" not in body
        assert "sidebar-tree-children" not in body

    def test_spaces_section_gets_a_group_header_label(self, conn):
        # 2026-08-29 follow-up: plans/sidebar-redesign.md asked for "tiny,
        # uppercase, gray text" group headers -- expanded mode shows this
        # instead of the plain divider line (style.css hides/shows each via
        # html[data-sidebar-expanded], not tested here since this suite
        # only sees rendered markup, not applied CSS).
        _make_space(conn, "Uni")
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert '<div class="sidebar-section-label" aria-hidden="true">Spaces</div>' in body

    def test_no_group_header_label_with_no_spaces(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert "sidebar-section-label" not in body

    def test_space_with_plain_child_label_nests_it_with_settings_link(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-space-name="Uni"' in body
        assert "sidebar-tree-item has-children" in body
        assert "sidebar-tree-toggle" in body
        assert 'href="/labels/CS101" class="tab-btn tab-btn-child' in body

    def test_space_child_that_is_itself_a_space_links_to_its_label_page(self, conn):
        _make_space(conn, "Uni")
        _make_space(conn, "Thesis", parent_name="Uni")
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/labels/Thesis" class="tab-btn tab-btn-child' in body

    def test_child_page_marks_child_link_active_and_parent_toggle_open(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = label_pages.label_page("CS101", _request("/labels/CS101", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/labels/CS101" class="tab-btn tab-btn-child active"' in body
        assert 'aria-expanded="true" aria-label="Toggle Uni projects"' in body

    def test_other_page_leaves_parent_toggle_closed_by_default(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'aria-expanded="false" aria-label="Toggle Uni projects"' in body

    def test_plain_label_with_no_space_children_relationship_is_unaffected(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert "data-space-name" not in body
        assert "sidebar-tree-toggle" not in body


class TestExpandToggle:
    def test_expand_toggle_present_when_spaces_exist(self, conn):
        _make_space(conn, "Uni")
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'id="sidebar-expand-toggle"' in body

    def test_expand_toggle_present_even_with_no_spaces(self, conn):
        # 2026-08-29 follow-up: the toggle moved to a fixed spot at the top
        # of the rail (always rendered), no longer living inline above the
        # Spaces list where it only existed for accounts with >=1 Space --
        # see base.html's relocation comment.
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert 'id="sidebar-expand-toggle"' in body

    def test_expand_toggle_uses_the_dedicated_sidebar_icon_not_a_chevron(self, conn):
        # 2026-08-29 follow-up: a chevron already means "expand this one
        # tree item" elsewhere on the same rail (.sidebar-tree-toggle) --
        # the whole-sidebar toggle uses the sprite's own `icon-sidebar`
        # symbol instead, so the two controls don't share a glyph with two
        # different meanings.
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        toggle_start = body.index('id="sidebar-expand-toggle"')
        toggle_markup = body[toggle_start : toggle_start + 200]
        assert "#icon-sidebar" in toggle_markup
        assert "#icon-chevron-right" not in toggle_markup


class TestProjectsSection:
    """Standalone projects (is_project=1, no parent_name) get their own
    flat "Projects" rail section (deps.py::_sidebar_projects) -- a project
    nested under a Space instead shows up there, not duplicated here."""

    def _make_project(self, conn, name, **extra):
        row = {"name": name, "is_project": 1, "created_at": _now()}
        row.update(extra)
        db.upsert_label_config(conn, row)

    def test_standalone_project_gets_its_own_section(self, conn):
        # 2026-08-30: a standalone project's own page moved to
        # /projects/{name} (routers/projects.py::project_detail, a Kanban
        # board) -- label_detail now redirects a project there instead of
        # rendering, so this exercises the real page directly, same as
        # visiting it would.
        self._make_project(conn, "Website Relaunch")
        resp = label_pages.label_page(
            "Website Relaunch", _request("/labels/Website Relaunch", conn), conn=conn
        )
        body = resp.body.decode()
        assert '<div class="sidebar-section-label" aria-hidden="true">Projects</div>' in body
        assert 'href="/labels/Website Relaunch" class="tab-btn tab-btn-project' in body

    def test_project_nested_under_a_space_is_not_duplicated_in_projects_section(self, conn):
        _make_space(conn, "Uni")
        self._make_project(conn, "Thesis", parent_name="Uni")
        resp = label_pages.label_page("Uni", _request("/labels/Uni", conn), conn=conn)
        body = resp.body.decode()
        # Nested under Uni, as a child, now linking to its own Kanban page
        # (2026-08-30) rather than the generic label settings page...
        assert 'href="/labels/Thesis" class="tab-btn tab-btn-child' in body
        # ...not also flattened into a top-level Projects section.
        assert "tab-btn-project" not in body
        assert '>Projects</div>' not in body

    def test_no_projects_section_with_no_standalone_projects(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = label_pages.label_page("Solo", _request("/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert "tab-btn-project" not in body


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
