"""Dashboard usability & functionality rework (2026-08-07,
features/dashboard.md, refined by direct follow-up
instructions):

  1. Default dashboard reset-to-default, surfaced via Settings (Home) and
     a label page's own edit-mode toolbar (Space/Project).
  2. New "At a Glance" widget type -- overdue/due-today/due-this-week
     counts, each linking to the matching filtered Tasks view.
  3. Dynamic time-of-day greeting header on Home ("Good morning/
     afternoon/evening[, name]"), with an optional Settings-configured
     display name.
  4. Quick-add merged into ONE "+" button (2026-08-10) opening a single
     Task/Event-tabbed modal (quick_add.html), on both Home and a label
     page -- replacing the earlier pair of separate New task/New event
     buttons and modals.
  5. Feature parity: a Space/Project page's default widgets now include
     At a Glance and Overdue Tasks, same as Home.

Also covers the pre-existing scoping bug found during planning: every
tasks/events-backed widget type (today_agenda, weekly_overview,
overdue_tasks, upcoming_events, mini_month_calendar, calendar_agenda,
and now at_a_glance) silently ignored config["label_name"] entirely --
a Project/Space page's own widgets showed the *whole app's* data, not
just that page's own. Fixed via the shared _effective_tags_filter
helper -- see its own docstring in routers/dashboard.py for the full
finding. That regression test comes first, per the house rule that this
is the important one."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from src import db, deps
from src.routers import dashboard as dashboard_router
from src.routers import labels as labels_router
from src.routers import settings as settings_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_task(conn, uid, due_at=None, tags=None, status="active"):
    db.upsert_task(conn, {
        "uid": uid,
        "title": uid, "description": "", "status": status, "due_at": due_at,
        "tags": tags or [], "created_at": _now(),
    })


def _request(path="/"):
    # query_string included (2026-08-30) -- settings_general.html now reads
    # request.query_params.get('note'/'error') for its "Login & security"
    # cards' flash messages (routers/settings.py::change_login_password/
    # change_radicale_password), and starlette's Request.query_params
    # property KeyErrors without this ASGI-spec-mandatory scope key.
    return Request(
        {"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": []}
    )


def _make_space(conn, name):
    db.upsert_label_config(conn, {"name": name, "generate_space": 1, "created_at": _now()})


def _make_project(conn, name):
    db.upsert_label_config(conn, {"name": name, "created_at": _now()})


class TestScopingBugFix:
    """The important regression test, per the task instructions -- a
    Project page's today_agenda/overdue_tasks/weekly_overview widgets now
    correctly exclude tasks that don't carry that label, instead of
    silently showing the whole app's data."""

    def test_today_agenda_scoped_to_project_label(self, conn):
        _make_project(conn, "CS101")
        today = date.today().isoformat()
        _seed_task(conn, "in_scope", due_at=today, tags=["CS101"])
        _seed_task(conn, "out_of_scope", due_at=today)
        data = dashboard_router._render_agenda(conn, {"label_name": "CS101", "range": "today", "show": ["tasks"]})
        uids = {t["uid"] for t in data["tasks"]}
        assert uids == {"in_scope"}

    def test_overdue_tasks_scoped_to_project_label(self, conn):
        _make_project(conn, "CS101")
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _seed_task(conn, "in_scope", due_at=yesterday, tags=["CS101"])
        _seed_task(conn, "out_of_scope", due_at=yesterday)
        data = dashboard_router._render_agenda(conn, {"label_name": "CS101", "range": "today", "show": ["overdue"]})
        uids = {t["uid"] for t in data["overdue_tasks"]}
        assert uids == {"in_scope"}

    def test_weekly_overview_scoped_to_project_label(self, conn):
        _make_project(conn, "CS101")
        today = date.today().isoformat()
        _seed_task(conn, "in_scope", due_at=today, tags=["CS101"])
        _seed_task(conn, "out_of_scope", due_at=today)
        data = dashboard_router._render_agenda(conn, {"label_name": "CS101", "range": "next_7_days", "show": ["tasks"]})
        all_uids = {t["uid"] for day in data["days"] for t in day["tasks"]}
        assert all_uids == {"in_scope"}

    def test_upcoming_events_scoped_to_project_label(self, conn):
        _make_project(conn, "CS101")
        now = datetime.now(timezone.utc)
        db.upsert_event(conn, {
            "uid": "in_scope", "title": "in_scope", "description": "", "status": "active",
            "all_day": 0, "start_at": (now + timedelta(days=1)).isoformat(),
            "tags": ["CS101"], "created_at": _now(),
        })
        db.upsert_event(conn, {
            "uid": "out_of_scope", "title": "out_of_scope", "description": "", "status": "active",
            "all_day": 0, "start_at": (now + timedelta(days=1)).isoformat(),
            "tags": [], "created_at": _now(),
        })
        data = dashboard_router._render_agenda(conn, {"label_name": "CS101", "range": "all_upcoming", "show": ["events"]})
        uids = {e["uid"] for e in data["events"]}
        assert uids == {"in_scope"}

    def test_space_page_scoping_pools_child_labels(self, conn):
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        today = date.today().isoformat()
        _seed_task(conn, "in_scope", due_at=today, tags=["CS101"])
        _seed_task(conn, "out_of_scope", due_at=today)
        data = dashboard_router._render_agenda(conn, {"label_name": "Uni", "range": "today", "show": ["tasks"]})
        uids = {t["uid"] for t in data["tasks"]}
        assert uids == {"in_scope"}

    def test_home_unaffected_by_the_fix_no_label_name(self, conn):
        # No label_name at all (Home's own widgets) -- effective_tags_filter
        # must resolve to whatever config["tags"] already was, unaffected.
        today = date.today().isoformat()
        _seed_task(conn, "t1", due_at=today, tags=["personal"])
        _seed_task(conn, "t2", due_at=today)
        data = dashboard_router._render_agenda(conn, {"range": "today", "show": ["tasks"]})
        assert {t["uid"] for t in data["tasks"]} == {"t1", "t2"}

    def test_effective_tags_filter_combines_explicit_tags_with_label_name(self, conn):
        _make_project(conn, "CS101")
        tags_filter = dashboard_router._effective_tags_filter(conn, {"tags": ["urgent"], "label_name": "CS101"})
        assert set(tags_filter) == {"urgent", "CS101"}

    def test_contact_list_behavior_unchanged_after_refactor(self, conn):
        # _render_contact_list now calls the shared helper too -- must
        # still behave exactly as before (its own pre-existing tests in
        # test_dashboard_router.py already cover this in depth; this is a
        # quick sanity check the refactor didn't regress it).
        _make_space(conn, "Uni")
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Alice", "tags": ["CS101"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c2", "full_name": "Bob", "tags": ["Personal"], "created_at": _now()})
        data = dashboard_router._render_contact_list(conn, {"label_name": "Uni"})
        assert {c["uid"] for c in data["contacts"]} == {"c1"}


class TestAtAGlanceWidget:
    def test_registered_in_widget_types(self, conn):
        assert "at_a_glance" in dashboard_router.WIDGET_TYPES
        spec = dashboard_router.WIDGET_TYPES["at_a_glance"]
        # Corrected from "full" to "third" (2026-08-07, automatic-width
        # pass) -- it's just three number+label stat blocks, not content
        # that needs a full row; matches the `.widget-card[data-span="2"|
        # "3"]` At a Glance font-scaling rule in static/style.css, which
        # was otherwise unreachable dead CSS while this default was "full".
        assert spec["default_width"] == "third"
        assert "default_height" not in spec

    def test_registered_in_selection_tables(self, conn):
        assert ("at_a_glance_view", None) in dashboard_router._SELECTION_TO_TYPE
        assert ("at_a_glance", None) in dashboard_router._TYPE_TO_SELECTION

    def test_counts_are_correct(self, conn):
        today = date.today()
        _seed_task(conn, "overdue1", due_at=(today - timedelta(days=3)).isoformat())
        _seed_task(conn, "overdue2", due_at=(today - timedelta(days=1)).isoformat())
        _seed_task(conn, "today1", due_at=today.isoformat())
        _seed_task(conn, "this_week1", due_at=(today + timedelta(days=3)).isoformat())
        _seed_task(conn, "out_of_range", due_at=(today + timedelta(days=10)).isoformat())
        # A done task, even if overdue, must not count -- _filtered_tasks
        # is open-only by default.
        _seed_task(conn, "done_overdue", due_at=(today - timedelta(days=5)).isoformat(), status="done")
        data = dashboard_router._render_at_a_glance(conn, {})
        assert data["overdue_count"] == 2
        assert data["today_count"] == 1
        # "this week" is today..today+6 inclusive -- today1 and this_week1
        # both fall in that window.
        assert data["week_count"] == 2

    def test_zero_counts_still_present_not_suppressed(self, conn):
        data = dashboard_router._render_at_a_glance(conn, {})
        assert data["overdue_count"] == 0
        assert data["today_count"] == 0
        assert data["week_count"] == 0

    def test_links_use_real_tasks_date_filters(self, conn):
        # 2026-08-28 "major rework" session: Status/Importance/Urgency
        # filtering is gone from the Tasks page entirely (item 3) -- overdue_
        # link now just points at the plain Table view; today_link/week_link
        # are unchanged since `date_filter` is still a real Tasks page param.
        data = dashboard_router._render_at_a_glance(conn, {})
        assert data["overdue_link"] == "/tasks"
        assert data["today_link"] == "/tasks?date_filter=today"
        assert data["week_link"] == "/tasks?date_filter=this_week"

    def test_links_no_longer_append_label_since_the_tasks_label_filter_is_gone(self, conn):
        # 2026-08-28 "major rework" session: was `&label=CS101` (the Tasks
        # page's label filter, now removed, item 3) -- links are scope-
        # agnostic now, same for every label page.
        _make_project(conn, "CS101")
        data = dashboard_router._render_at_a_glance(conn, {"label_name": "CS101"})
        assert data["overdue_link"] == "/tasks"
        assert data["today_link"] == "/tasks?date_filter=today"
        assert data["week_link"] == "/tasks?date_filter=this_week"

    def test_scoped_to_project_label_excludes_other_tasks(self, conn):
        _make_project(conn, "CS101")
        today = date.today().isoformat()
        _seed_task(conn, "in_scope", due_at=today, tags=["CS101"])
        _seed_task(conn, "out_of_scope", due_at=today)
        data = dashboard_router._render_at_a_glance(conn, {"label_name": "CS101"})
        assert data["today_count"] == 1


class TestDefaultSeedIncludesNewWidgets:
    def test_home_default_seed_includes_at_a_glance_and_overdue_tasks(self, conn):
        # 2026-08-07 (screenshot-driven default-layout rework): the target
        # screenshot leads with Today's Agenda, with At a Glance/Overdue
        # Tasks now nested inside the stack beside it, not standalone
        # full-width top-level entries.
        # 2026-08-15 widget consolidation: "Overdue Tasks" is now an
        # `agenda` widget configured with show=["overdue"] rather than its
        # own type -- see _DEFAULT_STACK_MEMBER_TYPES. 2026-09-03: that
        # Show list widened to ["overdue", "tasks", "events"] (direct
        # follow-up to a live "Today" widget showing "Nothing to show"
        # bug report) -- still the same third stack member, just showing
        # more than overdue-only now.
        dashboard_router._ensure_default_widgets(conn)
        widgets = db.list_dashboard_widgets(conn)
        types = [w["type"] for w in widgets]
        assert "at_a_glance" in types
        assert any(w["type"] == "agenda" and w["config"].get("show") == ["overdue", "tasks", "events"] for w in widgets)
        top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
        assert top_level[0]["type"] == "agenda"

    def test_fresh_project_label_seed_includes_at_a_glance_and_overdue_tasks(self, conn):
        _make_project(conn, "CS101")
        dashboard_router._ensure_default_label_widgets(conn, "CS101")
        widgets = db.list_dashboard_widgets(conn, label_name="CS101")
        types = [w["type"] for w in widgets]
        assert "at_a_glance" in types
        assert any(w["type"] == "agenda" and w["config"].get("show") == ["overdue", "tasks", "events"] for w in widgets)

    def test_fresh_space_label_seed_includes_at_a_glance_and_overdue_tasks(self, conn):
        _make_space(conn, "Uni")
        dashboard_router._ensure_default_label_widgets(conn, "Uni")
        widgets = db.list_dashboard_widgets(conn, label_name="Uni")
        types = [w["type"] for w in widgets]
        assert "at_a_glance" in types
        assert any(w["type"] == "agenda" and w["config"].get("show") == ["overdue", "tasks", "events"] for w in widgets)

    def test_new_label_widgets_auto_scoped_with_label_name(self, conn):
        _make_project(conn, "CS101")
        dashboard_router._ensure_default_label_widgets(conn, "CS101")
        widgets = db.list_dashboard_widgets(conn, label_name="CS101")
        at_a_glance = next(w for w in widgets if w["type"] == "at_a_glance")
        overdue = next(w for w in widgets if w["type"] == "agenda" and w["config"].get("show") == ["overdue", "tasks", "events"])
        assert at_a_glance["config"]["label_name"] == "CS101"
        assert overdue["config"]["label_name"] == "CS101"


def _canonical_default_type_order(widgets):
    """Widget `position` is only comparable *within* a scope (top-level vs.
    one stack's own members -- see dashboard.py's group_uid docstrings),
    so a flat `ORDER BY position` over a mixed set of top-level widgets
    and stack members can tie/interleave. This resolves the same layout
    _seed_agenda_stack_layout writes into one flat, deterministic list for
    equality assertions: top-level widgets by position, with a "stack"
    entry's own members (by position) spliced in immediately after it."""
    top_level = sorted((w for w in widgets if not w.get("group_uid")), key=lambda w: w["position"])
    order = []
    for w in top_level:
        order.append(w["type"])
        if w["type"] == "stack":
            members = sorted((m for m in widgets if m.get("group_uid") == w["uid"]), key=lambda m: m["position"])
            order.extend(m["type"] for m in members)
    return order


_DEFAULT_LAYOUT_TYPE_ORDER = ["agenda", "stack", "at_a_glance", "agenda", "agenda"]


class TestResetToDefault:
    def test_home_reset_deletes_and_reseeds(self, conn):
        dashboard_router._ensure_default_widgets(conn)
        original_count = len(db.list_dashboard_widgets(conn))
        # User customizes: add one more widget, delete one default.
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="Custom", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        assert len(db.list_dashboard_widgets(conn)) == original_count + 1

        resp = dashboard_router.reset_dashboard(label_name="", conn=conn)
        assert resp.headers["location"] == "/"
        widgets = db.list_dashboard_widgets(conn)
        assert [w["title"] for w in widgets] == [None] * len(widgets)  # back to plain defaults, no "Custom"
        assert _canonical_default_type_order(widgets) == _DEFAULT_LAYOUT_TYPE_ORDER

    def test_home_reset_route_directly(self, conn):
        # Full route call, no pre-existing widgets -- confirms it seeds a
        # fresh default layout even from empty (not just after a delete).
        resp = dashboard_router.reset_dashboard(label_name="", conn=conn)
        assert resp.status_code == 303
        assert _canonical_default_type_order(db.list_dashboard_widgets(conn)) == _DEFAULT_LAYOUT_TYPE_ORDER

    def test_label_reset_deletes_and_reseeds(self, conn):
        _make_project(conn, "CS101")
        dashboard_router._ensure_default_label_widgets(conn, "CS101")
        original_types = [w["type"] for w in db.list_dashboard_widgets(conn, label_name="CS101")]

        for w in db.list_dashboard_widgets(conn, label_name="CS101"):
            db.delete_dashboard_widget(conn, w["uid"])
        assert db.list_dashboard_widgets(conn, label_name="CS101") == []

        resp = dashboard_router.reset_dashboard(label_name="CS101", conn=conn)
        assert resp.headers["location"] == "/settings/labels/CS101"
        types = [w["type"] for w in db.list_dashboard_widgets(conn, label_name="CS101")]
        assert types == original_types

    def test_label_reset_does_not_touch_home_or_other_labels(self, conn):
        dashboard_router._ensure_default_widgets(conn)
        _make_project(conn, "CS101")
        _make_project(conn, "MATH201")
        dashboard_router._ensure_default_label_widgets(conn, "CS101")
        dashboard_router._ensure_default_label_widgets(conn, "MATH201")
        home_count = len(db.list_dashboard_widgets(conn))
        math_count = len(db.list_dashboard_widgets(conn, label_name="MATH201"))

        dashboard_router.reset_dashboard(label_name="CS101", conn=conn)

        assert len(db.list_dashboard_widgets(conn)) == home_count
        assert len(db.list_dashboard_widgets(conn, label_name="MATH201")) == math_count

    def test_reset_reseeds_immediately_not_a_blank_grid(self, conn):
        # "revert to default should show the default right away" -- after
        # reset, _ensure_default_widgets must not re-seed a *second* time
        # on the next normal page load (still a one-time-per-scope seed).
        dashboard_router.reset_dashboard(label_name="", conn=conn)
        count_after_reset = len(db.list_dashboard_widgets(conn))
        dashboard_router._ensure_default_widgets(conn)  # simulates the next page load
        assert len(db.list_dashboard_widgets(conn)) == count_after_reset


class TestGreeting:
    def test_morning(self, conn):
        assert dashboard_router._greeting_for_hour(9) == "Good morning"

    def test_afternoon(self, conn):
        assert dashboard_router._greeting_for_hour(14) == "Good afternoon"

    def test_evening(self, conn):
        assert dashboard_router._greeting_for_hour(20) == "Good evening"

    def test_boundary_hours(self, conn):
        assert dashboard_router._greeting_for_hour(0) == "Good morning"
        assert dashboard_router._greeting_for_hour(11) == "Good morning"
        assert dashboard_router._greeting_for_hour(12) == "Good afternoon"
        assert dashboard_router._greeting_for_hour(17) == "Good afternoon"
        assert dashboard_router._greeting_for_hour(18) == "Good evening"
        assert dashboard_router._greeting_for_hour(23) == "Good evening"

    def test_includes_display_name_when_set(self, conn):
        assert dashboard_router._greeting_for_hour(9, "Petru") == "Good morning, Petru"

    def test_no_display_name_no_trailing_comma(self, conn):
        assert dashboard_router._greeting_for_hour(9, None) == "Good morning"
        assert dashboard_router._greeting_for_hour(9, "") == "Good morning"

    def test_dashboard_view_renders_greeting_in_context(self, conn):
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        assert "greeting" in resp.context
        assert resp.context["greeting"] in ("Good morning", "Good afternoon", "Good evening")

    def test_dashboard_view_uses_display_name_from_settings(self, conn):
        db.set_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY, "Petru")
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        assert resp.context["greeting"].endswith(", Petru")

    def test_settings_general_passes_display_name(self, conn):
        # 2026-08-08 Settings redesign: display name moved off the hub
        # itself onto its own focused page, Settings > General.
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        assert resp.context["display_name"] == ""
        db.set_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY, "Petru")
        resp = settings_router.settings_general(_request("/settings/general"), conn=conn)
        assert resp.context["display_name"] == "Petru"

    def test_set_display_name_route(self, conn):
        resp = settings_router.set_display_name(display_name="Petru", conn=conn)
        assert resp.status_code == 303
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == "Petru"

    def test_set_display_name_strips_and_allows_clearing(self, conn):
        settings_router.set_display_name(display_name="  Petru  ", conn=conn)
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == "Petru"
        settings_router.set_display_name(display_name="   ", conn=conn)
        assert db.get_app_meta(conn, dashboard_router.DISPLAY_NAME_KEY) == ""

    def test_dashboard_html_renders_greeting_not_static_dashboard_h1(self, conn):
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert "<h1 style=\"margin:0\">Dashboard</h1>" not in body
        assert resp.context["greeting"] in body


class TestQuickAddButtons:
    def test_dashboard_html_has_no_quick_add_form(self, conn):
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'id="quick-add-form"' not in body
        assert 'name="title" placeholder="Quick-add a task and press Enter' not in body

    def test_dashboard_html_has_no_page_level_quick_add_button(self, conn):
        # 2026-08-10: the two New task/New event buttons merged into one
        # "+" that opened the shared quick_add.html modal, living in
        # .page-banner-actions. 2026-08-29 (direct request): that
        # page-level button is gone outright now -- obsolete once the
        # sidebar rail got its own global "+ New" (13c, base.html),
        # reachable from every page. Checked via `data-fab`, the removed
        # button's own distinguishing attribute -- the sidebar's own
        # quick-add link (always present, unrelated) has no data-fab, so
        # a bare `href="/quick/add"` substring check would false-positive
        # on it regardless of whether this page's own button still exists.
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert "data-fab" not in body
        assert 'href="/tasks/new"' not in body
        assert 'href="/events/new"' not in body
        assert 'class="page-banner-actions"' in body
        assert 'class="toolbar"' not in body

    def test_label_page_has_no_page_level_quick_add_button(self, conn):
        _make_project(conn, "CS101")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert "data-fab" not in body
        assert 'href="/tasks/new"' not in body
        assert 'href="/events/new"' not in body
        assert 'class="page-banner-actions"' in body
        assert 'class="toolbar"' not in body

    def test_dashboard_html_edit_mode_actions_present(self, conn):
        # 2026-08-07 (screenshot-driven toolbar rework): edit mode swaps
        # in New widget/Add-Change banner inside .page-banner-actions.
        # 2026-08-29 (sidebar redesign item 13d): edit mode is a
        # persistent Settings > Appearance toggle now (EDIT_MODE_KEY), not
        # a per-page `?edit=1` query param. 2026-08-29 (same day, direct
        # request): the non-edit-mode branch that used to render here
        # (the page-level quick-add button) is gone outright, not just
        # hidden in edit mode -- there's nothing left to "hide".
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert "data-fab" not in body
        assert 'New widget' in body
        assert 'Add banner' in body
        assert 'class="page-banner-actions"' in body

    def test_label_page_edit_mode_actions_present(self, conn):
        _make_project(conn, "CS101")
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert "data-fab" not in body
        assert 'New widget' in body
        assert 'Reset layout' in body
        assert 'class="page-banner-actions"' in body

    def test_dashboard_html_no_longer_has_a_separate_quick_add_row(self, conn):
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'dashboard-quick-add' not in body

    def test_label_page_no_longer_has_a_separate_quick_add_row(self, conn):
        _make_project(conn, "CS101")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert 'dashboard-quick-add' not in body

    def test_dashboard_html_no_longer_has_a_page_level_edit_mode_button(self, conn):
        # 2026-08-29 (sidebar redesign item 13d): the old page-level "Edit
        # mode" link (`<a href="?edit=1" ...>Edit mode</a>`) is gone --
        # edit mode is only reachable from Settings > Appearance now.
        # Checked by exact markup, not a bare substring: several code
        # comments on this page legitimately mention "Edit mode"/`?edit=1`
        # in prose while explaining the 2026-08-29 change itself.
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'href="?edit=1"' not in body
        assert '>Edit mode</a>' not in body


class TestQuickAddModal:
    """The merged task/event quick-add modal (2026-08-10, quick_add.html):
    one route renders BOTH create-forms (each sharing its field grid with
    the standalone new/edit form via _task_form_fields.html /
    _event_form_fields.html); the client flips between them."""

    def test_route_renders_both_forms(self, conn):
        resp = dashboard_router.quick_add_form(_request("/quick/add"), conn=conn)
        body = resp.body.decode()
        assert 'id="task-form"' in body
        assert 'id="event-form"' in body
        # Task-specific field present...
        assert 'name="due_at"' in body
        # ...and event-specific fields present.
        assert 'name="start_at"' in body
        assert 'id="all_day"' in body

    def test_route_has_tab_switch_and_shared_save(self, conn):
        resp = dashboard_router.quick_add_form(_request("/quick/add"), conn=conn)
        body = resp.body.decode()
        assert 'data-quick-add-tab="task"' in body
        assert 'data-quick-add-tab="event"' in body
        # Footer Save defaults to the task form; quick_add.js retargets it
        # when the Event tab is picked.
        assert 'id="quick-add-save"' in body
        assert 'form="task-form"' in body

    def test_route_is_a_modal_target(self, conn):
        resp = dashboard_router.quick_add_form(_request("/quick/add"), conn=conn)
        body = resp.body.decode()
        assert 'id="modal-target"' in body
        assert 'class="modal-stable-height"' in body
        assert 'data-modal-cancel' in body

    def test_route_defaults_task_and_event_state(self, conn):
        resp = dashboard_router.quick_add_form(_request("/quick/add"), conn=conn)
        ctx = resp.context
        assert ctx["task"] is None
        assert ctx["event"] is None
        assert ctx["prefill_all_day"] is False
        assert ctx["prefill_start"] is None


class TestLabelPageResetButton:
    def test_reset_button_present_in_edit_mode(self, conn):
        _make_project(conn, "CS101")
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert '/dashboard/reset' in body
        assert 'data-confirm-sheet' in body

    def test_new_widget_comes_before_reset_layout_in_edit_mode_toolbar(self, conn):
        # 2026-08-07 (screenshot-driven toolbar rework) -- "creation
        # actions before mode/utility actions", same principle already
        # applied to the non-edit-mode row's New task/New event ordering.
        _make_project(conn, "CS101")
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert body.index('New widget') < body.index('Reset layout')

    def test_reset_button_absent_outside_edit_mode(self, conn):
        _make_project(conn, "CS101")
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        # The reset form itself (posts to /dashboard/reset) shouldn't be
        # present outside edit mode -- only the New/Customize links.
        assert '<form method="post" action="/dashboard/reset"' not in body


class TestHomeResetButton:
    # 2026-08-10: Home's edit-mode toolbar got the same Reset layout
    # control a label page already has (TestLabelPageResetButton above) --
    # /dashboard/reset with no label_name resets Home's scope.
    def test_reset_button_present_in_edit_mode(self, conn):
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert 'action="/dashboard/reset"' in body
        assert 'data-confirm-sheet' in body

    def test_new_widget_comes_before_reset_layout_in_edit_mode_toolbar(self, conn):
        # Same "creation actions before mode/utility actions" ordering the
        # label page's toolbar already follows.
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert body.index('New widget') < body.index('Reset layout')

    def test_reset_button_absent_outside_edit_mode(self, conn):
        resp = dashboard_router.dashboard_view(_request(), conn=conn)
        body = resp.body.decode()
        assert '<form method="post" action="/dashboard/reset"' not in body


class TestSettingsResetButton:
    def test_settings_data_maintenance_has_reset_button(self, conn, tmp_path):
        # 2026-08-08 Settings redesign: Reset to default layout lived on
        # Settings > Widgets, alongside the Custom widgets toggle it
        # shared a hub group with; that toggle was removed outright the
        # same day (see routers/settings.py's module docstring) and the
        # one remaining action folded into Settings > Advanced instead.
        # 2026-08-17 Advanced itself folded into the merged Data &
        # Maintenance page's "Maintenance & upkeep" section.
        #
        # The merged page also reads request.app.state.settings' db_path,
        # backup_dir and radicale_base_url and renders the note/error
        # query-param strip -- needs a fuller fake request than the bare
        # one this file's own _request() builds.
        from types import SimpleNamespace

        fake_app = SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    radicale_base_url="http://localhost:5232",
                    db_path=tmp_path / "cache.sqlite",
                    backup_dir=tmp_path / "backups",
                )
            )
        )
        req = Request(
            {
                "type": "http", "method": "GET", "path": "/settings/data-maintenance",
                "query_string": b"", "scheme": "http", "server": ("testserver", 80),
                "root_path": "", "headers": [], "app": fake_app,
            }
        )
        resp = settings_router.settings_data_maintenance(req, conn=conn)
        body = resp.body.decode()
        assert 'action="/dashboard/reset"' in body
        assert 'data-confirm-sheet' in body
