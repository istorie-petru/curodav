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


def _tag(conn, name, space, **extra):
    db.ensure_group(conn, space)
    _label(conn, name, label_group=space, **extra)


def _page(conn, path="/tasks"):
    return label_pages.group_page("Uni", _request("/groups/Uni", conn), conn=conn).body.decode() if path == "/groups/Uni" else \
        labels_router.manage_labels(_request("/settings/labels", conn), conn=conn).body.decode()


class TestSpacesTree:
    def test_a_space_without_tags_has_no_chevron(self, conn):
        db.ensure_group(conn, "Uni")
        conn.commit()
        body = _page(conn)
        assert '<div class="sidebar-section-label" aria-hidden="true">Spaces</div>' in body
        assert 'href="/groups/Uni" class="tab-btn tab-btn-space' in body
        assert "sidebar-tree-toggle" not in body

    def test_every_tag_of_a_space_is_listed_under_it(self, conn):
        _tag(conn, "CS101", "Uni")
        _tag(conn, "Art", "Uni")
        body = _page(conn)
        assert "sidebar-tree-item has-children" in body
        assert 'aria-label="Toggle Uni tags"' in body
        assert 'href="/groups/Uni?tag=CS101" class="tab-btn tab-btn-child' in body
        assert 'href="/groups/Uni?tag=Art" class="tab-btn tab-btn-child' in body

    def test_an_archived_tag_is_left_out(self, conn):
        _tag(conn, "Old", "Uni")
        db.archive_project(conn, "Old")
        assert "tag=Old" not in _page(conn)

    def test_the_space_page_marks_its_own_entry_active(self, conn):
        _tag(conn, "CS101", "Uni")
        body = _page(conn, "/groups/Uni")
        assert 'href="/groups/Uni" class="tab-btn tab-btn-space active"' in body

    def test_no_spaces_no_section(self, conn):
        assert ">Spaces</div>" not in _page(conn)

    def test_there_is_no_pinned_section(self, conn):
        _tag(conn, "CS101", "Uni", sidebar_pin=1)
        assert ">Pinned</div>" not in _page(conn)


class TestExpandToggle:
    def test_expand_toggle_present_with_spaces(self, conn):
        _tag(conn, "CS101", "Uni")
        assert 'id="sidebar-expand-toggle"' in _page(conn)

    def test_expand_toggle_present_with_nothing(self, conn):
        assert 'id="sidebar-expand-toggle"' in _page(conn)

    def test_expand_toggle_uses_the_dedicated_sidebar_icon_not_a_chevron(self, conn):
        body = _page(conn)
        toggle_start = body.index('id="sidebar-expand-toggle"')
        toggle_markup = body[toggle_start : toggle_start + 200]
        assert "#icon-sidebar" in toggle_markup
        assert "#icon-chevron-right" not in toggle_markup


class TestSidebarQuickAdd:

    def test_contacts_page_points_quick_add_at_contact_tab(self, conn):
        # 2026-09-14 (direct request, "the quick add should support both
        # contacts and labels"): quick_add.html grew a Contact tab, so the
        # sidebar's global "+" no longer special-cases Contacts into its
        # own standalone /contacts/new modal -- it opens the same merged
        # /quick/add modal as every other page, just pre-focused on
        # Contact via `default_tab`.
        resp = contacts_router.list_contacts(_request("/contacts", conn), conn=conn)
        body = resp.body.decode()
        assert 'class="header-add" href="/quick/add?default_tab=contact"' in body

    def test_labels_manage_page_points_quick_add_at_label_tab(self, conn):
        resp = labels_router.manage_labels(_request("/settings/labels", conn), conn=conn)
        body = resp.body.decode()
        assert 'class="header-add" href="/quick/add?default_tab=label"' in body


def test_spaces_can_be_hidden_and_reordered(conn):
    from src import deps

    for name, space in (("Work", "Work space"), ("Home", "Home space")):
        _tag(conn, name, space)
    db.set_group_sidebar(conn, "Work space", True, 2)
    db.set_group_sidebar(conn, "Home space", True, 1)
    groups = deps._sidebar_groups(_request("/", conn))
    assert [g["name"] for g in groups] == ["Home space", "Work space"]
    assert [c["href"] for c in groups[1]["children"]] == ["/groups/Work%20space?tag=Work"]
    db.set_group_sidebar(conn, "Home space", False, 1)
    assert [g["name"] for g in deps._sidebar_groups(_request("/", conn))] == ["Work space"]
