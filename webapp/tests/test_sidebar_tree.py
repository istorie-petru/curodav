"""2026-08-29 sidebar redesign slice 13a (plans/STATE.md item 13a) --
collapsible nested Spaces/Projects tree in the nav rail.

Covers: a Space's child labels (label_config.parent_name -- the same
relationship label_detail.html's own "Projects" section already reads via
db.list_child_labels) render nested under it in base.html, with a chevron
toggle only when it actually has children; a child that's itself a Space
links to its generated page, a plain child label links to its settings
edit page; visiting a child's own page marks both that child link and its
parent's toggle active/open by default; the rail-wide expand toggle is
present whenever there's a Spaces section at all, absent otherwise; and
none of this leaks into pages/labels that aren't part of any tree.

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
from src.routers import labels as labels_router
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
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-space-name="Uni"' in body
        assert "sidebar-tree-item has-children" not in body
        assert "sidebar-tree-toggle" not in body
        assert "sidebar-tree-children" not in body

    def test_space_with_plain_child_label_nests_it_with_settings_link(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'data-space-name="Uni"' in body
        assert "sidebar-tree-item has-children" in body
        assert "sidebar-tree-toggle" in body
        assert 'href="/settings/labels/CS101" class="tab-btn tab-btn-child' in body

    def test_space_child_that_is_itself_a_space_links_to_spaces_page(self, conn):
        _make_space(conn, "Uni")
        _make_space(conn, "Thesis", parent_name="Uni")
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/spaces/Thesis" class="tab-btn tab-btn-child' in body
        # Not the settings-page form -- it's a Space, not a plain label.
        assert 'href="/settings/labels/Thesis" class="tab-btn tab-btn-child' not in body

    def test_child_page_marks_child_link_active_and_parent_toggle_open(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/settings/labels/CS101", conn), conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/labels/CS101" class="tab-btn tab-btn-child active"' in body
        assert 'aria-expanded="true" aria-label="Toggle Uni projects"' in body

    def test_other_page_leaves_parent_toggle_closed_by_default(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'aria-expanded="false" aria-label="Toggle Uni projects"' in body

    def test_plain_label_with_no_space_children_relationship_is_unaffected(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = labels_router.label_detail("Solo", _request("/settings/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert "data-space-name" not in body
        assert "sidebar-tree-toggle" not in body


class TestExpandToggle:
    def test_expand_toggle_present_when_spaces_exist(self, conn):
        _make_space(conn, "Uni")
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni", conn), conn=conn)
        body = resp.body.decode()
        assert 'id="sidebar-expand-toggle"' in body

    def test_expand_toggle_absent_with_no_spaces(self, conn):
        db.upsert_label_config(conn, {"name": "Solo", "created_at": _now()})
        resp = labels_router.label_detail("Solo", _request("/settings/labels/Solo", conn), conn=conn)
        body = resp.body.decode()
        assert 'id="sidebar-expand-toggle"' not in body
