"""Tests for item 20 of Peter's queued list (2026-09-26): "Redesign the
toolbar's 'group-labels' as a custom dashboard widget: show every label/
project under a group with its related data, in the same spirit as the
Unscheduled Work mockup." Built together with item 11 per direct
instruction ("start work on item 11 and 20 because they have shared
components") -- the shared piece is `_action_menu.html` (the "..." kebab
macro), first extracted for item 11's redesigned Unscheduled Work row and
reused here for each member row's own kebab.

Covers: `routers/dashboard.py::_render_group_members` (the render function
-- counts/next-due aggregation), the new `group_members` WIDGET_TYPES
registration + its Home/plain-label scope exclusion (the CRUD-level
exclusion itself is covered by test_dashboard_router.py::
TestGroupMembersWidgetScope, not repeated here), the always-seeded
`_ensure_group_members_widget`, and the rendered `_widget_group_members.html`
template shape."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import dashboard as dashboard_router
from src.routers import label_pages


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/groups/Uni"):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []})


def _group(conn, name="Uni", members=("Art", "Maths")):
    db.upsert_label_config(conn, {"name": name, "generate_space": 1})
    for m in members:
        db.upsert_label_config(conn, {"name": m, "label_group": name})
    db.set_group_members(conn, name, list(members))
    return db.group_page_key(name)


def _task(conn, uid, tags, status="active", due_at=None):
    db.upsert_task(conn, {
        "uid": uid, "title": uid, "description": "", "status": status,
        "tags": tags, "due_at": due_at, "created_at": _now(),
    })


def _event(conn, uid, tags, start_at=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid, "description": "", "start_at": start_at,
        "end_at": None, "all_day": False, "status": "active", "tags": tags,
        "created_at": _now(), "updated_at": _now(),
    })


class TestRenderGroupMembers:
    def test_not_a_group_page_renders_no_rows(self, conn):
        assert dashboard_router._render_group_members(conn, {}) == {"rows": []}
        db.upsert_label_config(conn, {"name": "Solo"})
        assert dashboard_router._render_group_members(conn, {"label_name": "Solo"}) == {"rows": []}

    def test_every_member_gets_a_row_even_with_no_data(self, conn):
        key = _group(conn)
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        assert [r["label"]["name"] for r in data["rows"]] == ["Art", "Maths"]
        assert all(r["open_task_count"] == 0 for r in data["rows"])
        assert all(r["upcoming_event_count"] == 0 for r in data["rows"])
        assert all(r["next_due"] is None for r in data["rows"])

    def test_open_task_count_excludes_done_and_archived(self, conn):
        key = _group(conn)
        _task(conn, "t1", ["Art"], status="active")
        _task(conn, "t2", ["Art"], status="active")
        _task(conn, "t3", ["Art"], status="done")
        _task(conn, "t4", ["Art"], status="archived")
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        row = next(r for r in data["rows"] if r["label"]["name"] == "Art")
        assert row["open_task_count"] == 2

    def test_upcoming_event_count_excludes_past_events(self, conn):
        key = _group(conn)
        now = datetime.now(timezone.utc)
        _event(conn, "e-future", ["Maths"], start_at=(now + timedelta(days=1)).isoformat())
        _event(conn, "e-past", ["Maths"], start_at=(now - timedelta(days=1)).isoformat())
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        row = next(r for r in data["rows"] if r["label"]["name"] == "Maths")
        assert row["upcoming_event_count"] == 1

    def test_next_due_is_the_soonest_of_task_due_or_event_start(self, conn):
        key = _group(conn)
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(days=1)).isoformat()
        later = (now + timedelta(days=5)).isoformat()
        _task(conn, "t1", ["Art"], due_at=later)
        _event(conn, "e1", ["Art"], start_at=soon)
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        row = next(r for r in data["rows"] if r["label"]["name"] == "Art")
        assert row["next_due"] == soon

    def test_a_task_with_no_due_date_never_becomes_next_due(self, conn):
        key = _group(conn)
        _task(conn, "t1", ["Art"], due_at=None)
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        row = next(r for r in data["rows"] if r["label"]["name"] == "Art")
        assert row["next_due"] is None

    def test_data_is_never_mixed_across_members(self, conn):
        key = _group(conn)
        _task(conn, "t1", ["Art"])
        _task(conn, "t2", ["Maths"])
        _task(conn, "t3", ["Maths"])
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        by_name = {r["label"]["name"]: r for r in data["rows"]}
        assert by_name["Art"]["open_task_count"] == 1
        assert by_name["Maths"]["open_task_count"] == 2


class TestWidgetTypeRegistration:
    def test_registered_with_full_width_default(self):
        spec = dashboard_router.WIDGET_TYPES["group_members"]
        assert spec["template"] == "_widget_group_members.html"
        assert spec["default_width"] == "full"
        assert spec["uses"] == {"tasks", "events"}

    def test_excluded_from_home_and_plain_label_scopes(self):
        assert "group_members" in dashboard_router._excluded_widget_types("")
        assert "group_members" in dashboard_router._excluded_widget_types("project")
        assert "group_members" not in dashboard_router._excluded_widget_types("space")


class TestAlwaysSeededOnGroupPages:
    def test_group_page_auto_seeds_the_widget(self, conn):
        key = _group(conn)
        dashboard_router._ensure_group_members_widget(conn, key)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        matches = [w for w in widgets if w["type"] == "group_members"]
        assert len(matches) == 1
        assert matches[0]["config"]["label_name"] == key
        assert matches[0]["position"] == -1.0  # renders before Today's Agenda (0.0)

    def test_seeding_is_one_time_and_respects_a_later_full_delete(self, conn):
        key = _group(conn)
        dashboard_router._ensure_group_members_widget(conn, key)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        for w in widgets:
            if w["type"] == "group_members":
                db.delete_dashboard_widget(conn, w["uid"])
        # A second visit (the seeded_key is already set) must NOT bring it
        # back -- same "seed once" contract every other one-time seed here
        # follows.
        dashboard_router._ensure_group_members_widget(conn, key)
        assert not [w for w in db.list_dashboard_widgets(conn, label_name=key) if w["type"] == "group_members"]

    def test_group_page_route_seeds_it_end_to_end(self, conn):
        _group(conn)
        resp = label_pages.group_page("Uni", _request(), conn=conn)
        assert resp.status_code == 200
        widgets = db.list_dashboard_widgets(conn, label_name="group:Uni")
        assert any(w["type"] == "group_members" for w in widgets)


class TestRenderedWidgetTemplate:
    def test_rows_show_counts_and_edit_kebab(self, conn):
        key = _group(conn)
        _task(conn, "t1", ["Art"])
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        from src.deps import templates

        html = templates.get_template("_widget_group_members.html").render(
            data=data, icon=lambda *a, **k: "", relative_date=lambda v: v
        )
        assert 'class="group-member-list"' in html
        assert 'href="/labels/Art"' in html
        assert "1 open task" in html
        assert "action-menu-trigger" in html
        assert "/settings/labels/Art/edit" in html

    def test_empty_state_when_group_has_no_members(self, conn):
        db.upsert_label_config(conn, {"name": "Empty", "generate_space": 1})
        db.set_group_members(conn, "Empty", [])
        key = db.group_page_key("Empty")
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        from src.deps import templates

        html = templates.get_template("_widget_group_members.html").render(
            data=data, icon=lambda *a, **k: "", relative_date=lambda v: v
        )
        assert "No labels in this group yet." in html
        assert 'class="group-member-list"' not in html
