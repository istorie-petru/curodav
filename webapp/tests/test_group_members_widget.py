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
TestGroupMembersWidgetScope, not repeated here), the rendered
`_widget_group_members.html` template shape, and (2026-09-28 redesign,
direct request) `group_members` being seeded as the quarter-width third
column of a group page's 25/50/25 row instead of a separate always-pinned
full-width widget -- both the fresh-seed path (`_ensure_default_label_
widgets`/`_seed_agenda_stack_layout`) and the migration that converts an
existing installation's old pinned widget
(`_migrate_group_layout_2026_09_28`)."""

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


class TestSeededAsQuarterColumn:
    """2026-09-28 (direct request: "I don't want the Labels in this group
    to be visible by default... for groups, copy the main dashboard
    design, but instead of the habits 25% column have a Groups & Labels
    List of this Space") -- `group_members` is no longer a second,
    always-pinned full-width widget (the old `_ensure_group_members_widget`,
    now removed). A group page gets the same 25/50/25 row Home does
    (`_seed_agenda_stack_layout`), with `group_members` standing in the
    quarter-width third column instead of Habit Check-in."""

    def test_group_page_seeds_the_widget_as_the_quarter_column(self, conn):
        key = _group(conn)
        dashboard_router._ensure_default_label_widgets(conn, key)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        matches = [w for w in widgets if w["type"] == "group_members"]
        assert len(matches) == 1
        assert matches[0]["config"]["label_name"] == key
        assert matches[0]["config"]["width"] == "quarter"
        assert matches[0]["position"] == 2.0  # after Today (0.0) and the stack (1.0)

    def test_today_agenda_is_quarter_width_on_a_group_page(self, conn):
        key = _group(conn)
        dashboard_router._ensure_default_label_widgets(conn, key)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        today = next(w for w in widgets if w["type"] == "agenda" and not w.get("group_uid"))
        stack = next(w for w in widgets if w["type"] == "stack")
        assert today["config"]["width"] == "quarter"
        assert stack["config"]["width"] == "half"

    def test_seeding_is_one_time_and_respects_a_later_full_delete(self, conn):
        key = _group(conn)
        dashboard_router._ensure_default_label_widgets(conn, key)
        for w in db.list_dashboard_widgets(conn, label_name=key):
            db.delete_dashboard_widget(conn, w["uid"])
        # A second visit (the seeded_key is already set) must NOT bring
        # anything back -- same "seed once" contract every other one-time
        # seed here follows.
        dashboard_router._ensure_default_label_widgets(conn, key)
        assert db.list_dashboard_widgets(conn, label_name=key) == []

    def test_group_page_route_seeds_it_end_to_end(self, conn):
        _group(conn)
        resp = label_pages.group_page("Uni", _request(), conn=conn)
        assert resp.status_code == 200
        widgets = db.list_dashboard_widgets(conn, label_name="group:Uni")
        matches = [w for w in widgets if w["type"] == "group_members"]
        assert len(matches) == 1
        assert matches[0]["config"]["width"] == "quarter"

    def test_not_visible_twice_and_not_pinned_above_today(self, conn):
        """The old design guaranteed a separate, always-visible row above
        Today's Agenda; the new one doesn't -- Today (position 0.0) is
        first, and there's exactly one group_members widget, not a pinned
        extra on top of whatever's in the quarter column."""
        key = _group(conn)
        dashboard_router._ensure_default_label_widgets(conn, key)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        assert [w["type"] for w in top_level] == ["agenda", "stack", "group_members"]


class TestMigrateExistingGroupLayout:
    """The one-time migration (`_migrate_group_layout_2026_09_28`) that
    converts an existing installation's old pinned, full-width
    `group_members` widget (position -1.0) into the new quarter-width
    third column, and widens that group's Today agenda from half to
    quarter -- run from `widget_page_context` alongside the other
    one-time widget migrations."""

    def _seed_old_style(self, conn, key):
        # Reproduces the pre-2026-09-28 shape by hand: half/half Today +
        # stack (the old default), plus a separately-pinned, full-width
        # group_members widget at position -1.0 (the old
        # _ensure_group_members_widget's own shape).
        now = _now()
        db.upsert_dashboard_widget(conn, {
            "uid": "agenda-uid", "type": "agenda", "title": "Today",
            "config": {"width": "half", "range": "today", "label_name": key},
            "position": 0.0, "created_at": now, "label_name": key,
        })
        db.upsert_dashboard_widget(conn, {
            "uid": "stack-uid", "type": "stack", "title": None,
            "config": {"width": "half"}, "position": 1.0, "created_at": now, "label_name": key,
        })
        db.upsert_dashboard_widget(conn, {
            "uid": "gm-uid", "type": "group_members", "title": "Labels in this group",
            "config": {"label_name": key}, "position": -1.0, "created_at": now, "label_name": key,
        })

    def test_converts_pinned_widget_to_quarter_column(self, conn):
        key = _group(conn)
        self._seed_old_style(conn, key)
        dashboard_router._migrate_group_layout_2026_09_28(conn)
        widgets = db.list_dashboard_widgets(conn, label_name=key)
        gm = next(w for w in widgets if w["type"] == "group_members")
        today = next(w for w in widgets if w["type"] == "agenda")
        assert gm["config"]["width"] == "quarter"
        assert gm["position"] == 2.0
        assert today["config"]["width"] == "quarter"

    def test_runs_once(self, conn):
        key = _group(conn)
        self._seed_old_style(conn, key)
        dashboard_router._migrate_group_layout_2026_09_28(conn)
        # Manually revert the widths to simulate "already migrated, don't
        # touch again" -- a second run must be a no-op even though the
        # data would otherwise match the old shape again.
        db.upsert_dashboard_widget(conn, {**db.get_dashboard_widget(conn, "gm-uid"), "position": -1.0})
        dashboard_router._migrate_group_layout_2026_09_28(conn)
        assert db.get_dashboard_widget(conn, "gm-uid")["position"] == -1.0

    def test_never_touches_a_plain_label_page(self, conn):
        db.upsert_label_config(conn, {"name": "Solo"})
        dashboard_router._ensure_default_label_widgets(conn, "Solo")
        before = db.list_dashboard_widgets(conn, label_name="Solo")
        dashboard_router._migrate_group_layout_2026_09_28(conn)
        after = db.list_dashboard_widgets(conn, label_name="Solo")
        assert before == after


class TestRenderedWidgetTemplate:
    def test_rows_show_as_cards(self, conn):
        """2026-09-28, fourth pass (direct request: "always use card
        grid") -- every row renders as a `filled_card` tile now, regardless
        of count; no per-row kebab (a `filled_card` is a whole-row `<a>`,
        same as every other `.filled-cards-grid` consumer -- editing a
        label from here means opening it)."""
        key = _group(conn)
        _task(conn, "t1", ["Art"])
        data = dashboard_router._render_group_members(conn, {"label_name": key})
        from src.deps import templates

        html = templates.get_template("_widget_group_members.html").render(
            data=data, icon=lambda *a, **k: "", relative_date=lambda v: v
        )
        assert 'class="filled-cards-grid"' in html
        assert 'href="/labels/Art"' in html
        assert "1 open task" in html
        assert "action-menu-trigger" not in html
        assert "/settings/labels/Art/edit" not in html

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
        assert 'class="filled-cards-grid"' not in html
