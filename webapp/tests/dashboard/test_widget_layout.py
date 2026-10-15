"""Widget width, edit-mode chrome and the dashboard page render."""

from __future__ import annotations

import pytest

from dashboard_seed import now_iso

from src import db, deps
from src.routers import dashboard as dashboard_router


pytestmark = pytest.mark.usefixtures("home_is_dashboard")


class TestWidgetHeightRemoved:
    """2026-08-07 -- the manual height editor/drag-resize feature (four
    fixed height presets, a drag handle, its own resize endpoint) was
    fully removed per direct feedback: a widget's height should just be
    "how much content it is", no scrollbar, unless it goes over a max
    height. These are regression guards against any of that quietly
    coming back, not tests of behavior that still exists."""

    def _add(self, conn, view="agenda", range_="today"):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        return db.list_dashboard_widgets(conn)[-1]



    def test_edit_widget_does_not_carry_height_through(self, conn):
        w = self._add(conn)
        row = dict(db.get_dashboard_widget(conn, w["uid"]))
        row["config"] = dict(row.get("config") or {})
        row["config"]["height"] = "xl"  # simulate a stale value from before removal
        db.upsert_dashboard_widget(conn, row)
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="next_7_days", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert "height" not in updated["config"]



class TestWidgetWidthAutomatic:
    """2026-08-07 -- the manual width picker/drag-resize feature (a Width
    <select> in the widget builder form, a drag handle on each card, its
    own /resize endpoint) was fully removed per direct feedback: "auto-fit
    by content" -- each widget type gets a natural width from its own
    default_width, no per-instance override. The Width-field half of that
    removal was reversed 2026-08-30 (TestWidgetWidthManualOverride below,
    after the automatic masonry layout kept producing an arrangement the
    user didn't want even with a same-day best-fit packing pass) and
    stuck. The drag-handle/`.../resize` half was ALSO reversed the same
    day, direct follow-up ("i don't really like the settings width
    settings and much rather would mouse resize them") -- and then
    removed again just as quickly, a second direct follow-up that it
    still didn't drag correctly even after a first fix attempt ("remove
    it... the dashboard customise is fine"). So the drag-handle/endpoint
    tests below are back to asserting absence, same as before either
    reversal -- only the Width field itself survived. (Height's own
    removal is the one part of the original 2026-08-07 change that was
    never touched at all -- no per-widget height concept came back.)"""

    def _add(self, conn, view="agenda", range_="today", **extra):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn, **extra,
        )
        return db.list_dashboard_widgets(conn)[-1]


    def test_created_widget_always_renders_at_its_types_default_width(self, conn):
        # calendar_tasks/agenda_view resolves to agenda, whose
        # default_width is "half" -- confirm that's what actually renders
        # when nothing overrides it (the common case -- no width= in the
        # form submission below, same as _add's default call shape).
        w = self._add(conn)
        assert w["type"] == "agenda"
        wc = dashboard_router._widget_context(conn, w)
        assert wc["width"]["key"] == "half"


    def test_edit_mode_renders_no_width_resize_handle(self, conn):
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        assert 'class="widget-resize-handle"' not in resp.body.decode()


class TestWidgetWidthManualOverride:
    """2026-08-30, direct request after the automatic masonry layout
    (static/app.js) kept producing an arrangement the user didn't want,
    even after a same-day best-fit packing pass: "can't we have a width
    setting in edit mode (100%,75%,50%,25%), or maybe actually fix the
    automatic one." Reverses the 2026-08-07 "no manual override" decision
    above for width specifically -- see WIDGET_WIDTHS/_widget_width's own
    comment in routers/dashboard.py. Grid also widened 6->12 virtual
    columns the same day so 25%/75% land on exact column counts."""

    def _add(self, conn, view="agenda", range_="today", **extra):
        dashboard_router.add_widget(
            source="calendar_tasks", view=view, range=range_, title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn, **extra,
        )
        return db.list_dashboard_widgets(conn)[-1]



    def test_add_widget_stores_a_real_width_choice(self, conn):
        w = self._add(conn, width="three_quarters")
        stored = db.get_dashboard_widget(conn, w["uid"])
        assert stored["config"]["width"] == "three_quarters"

    def test_add_widget_ignores_blank_width_auto(self, conn):
        w = self._add(conn, width="")
        stored = db.get_dashboard_widget(conn, w["uid"])
        assert "width" not in stored["config"]

    def test_add_widget_rejects_a_width_not_in_the_four_offered_choices(self, conn):
        # "third"/"two_thirds" are real WIDGET_WIDTHS keys (still used as
        # type defaults) but not offered by the Width field itself --
        # WIDGET_WIDTH_CHOICES is the four literally asked for
        # (100%/75%/50%/25%), so a stale/forged submission of either
        # doesn't get stored as if it were a legitimate manual choice.
        w = self._add(conn, width="third")
        stored = db.get_dashboard_widget(conn, w["uid"])
        assert "width" not in stored["config"]

    def test_manual_width_wins_over_the_types_default(self, conn):
        w = self._add(conn, width="quarter")
        wc = dashboard_router._widget_context(conn, w)
        assert wc["width"]["key"] == "quarter"
        assert wc["width"]["span"] == 3

    def test_editing_a_widget_can_set_a_width_override(self, conn):
        w = self._add(conn)
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="today", title="Renamed",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="",
            width="full", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert updated["config"]["width"] == "full"
        wc = dashboard_router._widget_context(conn, updated)
        assert wc["width"]["key"] == "full"
        assert wc["width"]["span"] == 12

    def test_editing_a_widget_back_to_auto_clears_the_override(self, conn):
        w = self._add(conn, width="full")
        dashboard_router.edit_widget(
            w["uid"], source="calendar_tasks", view="agenda", range="today", title="",
            project_uid="", tags="", task_list_uids=[], calendar_uids=[], limit="",
            width="", conn=conn,
        )
        updated = db.get_dashboard_widget(conn, w["uid"])
        assert "width" not in updated["config"]
        wc = dashboard_router._widget_context(conn, updated)
        assert wc["width"]["key"] == "half"  # agenda's own default_width, back in charge

    def test_builder_fields_partial_has_a_width_field(self, conn):
        # The Add-widget form only renders inside the Customize modal
        # (GET /dashboard/customize), not inline on the dashboard itself
        # (2026-08-08 -- "New widget" opens the modal instead), so this
        # has to hit that route rather than dashboard_view.
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/dashboard/customize", "headers": []})
        resp = dashboard_router.dashboard_customize(req, conn=conn)
        body = resp.body.decode()
        assert 'name="width"' in body
        assert 'value="quarter"' in body
        assert 'value="three_quarters"' in body

    def test_widget_widths_span_out_of_twelve(self):
        # 2026-08-30: grid widened 6 -> 12 columns so 25%/75% land exactly
        # (6 has no integer quarter). Every pre-existing span doubled;
        # real-world proportions unchanged (2/6 == 4/12, 3/6 == 6/12, ...).
        assert dashboard_router.WIDGET_WIDTHS["quarter"]["span"] == 3
        assert dashboard_router.WIDGET_WIDTHS["third"]["span"] == 4
        assert dashboard_router.WIDGET_WIDTHS["half"]["span"] == 6
        assert dashboard_router.WIDGET_WIDTHS["two_thirds"]["span"] == 8
        assert dashboard_router.WIDGET_WIDTHS["three_quarters"]["span"] == 9
        assert dashboard_router.WIDGET_WIDTHS["full"]["span"] == 12

    def test_width_choices_are_exactly_the_four_percentages_asked_for(self):
        assert set(dashboard_router.WIDGET_WIDTH_CHOICES) == {"quarter", "half", "three_quarters", "full"}

    def test_stack_own_width_unaffected_by_the_choices_restriction(self, conn):
        # A stack (spec=None) still reads its own raw config["width"]
        # directly, any WIDGET_WIDTHS key -- WIDGET_WIDTH_CHOICES only
        # gates what a *type-having* widget's manual override can be, per
        # _widget_width's own branch order.
        stack = {"type": "stack", "config": {"width": "two_thirds"}}
        wc_width = dashboard_router._widget_width(stack, None)
        assert wc_width["key"] == "two_thirds"
        assert wc_width["span"] == 8


class TestWidgetCardRegionEditMode:
    """2026-08-30 bug fix, direct report ("saving a widget... not seeing
    the change only after a hard refresh"). Root cause: widget_card_region
    (GET /dashboard/widgets/{uid}, the async-CRUD single-widget region
    fragment) hardcoded edit_mode=False, and dashboard_widget_preview.js's
    Filters autosave never called it at all -- so an edited widget's own
    card behind the modal never updated live. Two independent fixes,
    tested here from the Python side (the JS side -- autosave calling
    refreshRegion -- has no test coverage in this suite, same "no browser
    in this test environment" ceiling every other JS-behavior change in
    this session accepted)."""

    def _add(self, conn):
        dashboard_router.add_widget(
            source="calendar_tasks", view="agenda", range="today", title="", project_uid="", tags="",
            task_list_uids=[], calendar_uids=[], limit="", space_uid="", conn=conn,
        )
        return db.list_dashboard_widgets(conn)[-1]

    def test_region_reflects_current_edit_mode_on(self, conn):
        w = self._add(conn)
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": f"/dashboard/widgets/{w['uid']}", "headers": []})
        resp = dashboard_router.widget_card_region(req, w["uid"], conn=conn)
        body = resp.body.decode()
        # Edit-mode-only chrome (the Filters/Edit link, the drag handle,
        # the delete form) should all be present -- confirms this isn't
        # silently rendering as if edit mode were off.
        assert "widget-drag-handle" in body

    def test_region_reflects_current_edit_mode_off(self, conn):
        w = self._add(conn)
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "0")
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": f"/dashboard/widgets/{w['uid']}", "headers": []})
        resp = dashboard_router.widget_card_region(req, w["uid"], conn=conn)
        body = resp.body.decode()
        assert "widget-drag-handle" not in body


class TestDashboardRoute:
    def test_renders_with_seeded_defaults(self, conn):
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        assert resp.status_code == 200
        # Top-level layout is Today's Agenda + one stack card (its members
        # render nested inside it) + Habit Check-in (item 15, 2026-09-24).
        assert len(resp.context["widget_contexts"]) == 3

    def test_renders_in_edit_mode_with_the_add_widget_form(self, conn):
        # Smoke test for the Add-widget form/Filters panel/masonry grid
        # markup moved into _widget_workspace.html (2026-08-02) -- only
        # rendered at all when edit_mode is truthy, so the non-edit render
        # above wouldn't have caught a syntax error in that branch.
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        assert resp.status_code == 200
        assert b'id="widget-grid"' in resp.body or b"widget-card" in resp.body

    def test_edit_mode_renders_no_height_resize_handle(self, conn):
        # 2026-08-07 -- the manual height editor/drag-resize handle was
        # fully removed; .widget-content now renders identically (no
        # data-height-key, no inline max-height style) for every widget,
        # regardless of type, with the fixed CSS max-height doing the
        # capping instead.
        from starlette.requests import Request

        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "1")
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert "widget-resize-handle-vertical" not in body
        assert "data-height-key" not in body
        # Every widget's .widget-content opens with the exact same bare
        # markup -- no per-widget/per-type variation left at all .
        assert body.count('<div class="card-body widget-content">') == len([w for w in db.list_dashboard_widgets(conn) if w["type"] != "stack"])


class TestBareTileWidgets:
    """2026-08-30, direct feedback ("i like the quick links grid but i'd
    like to not have them inside a div card") -- Spaces & Projects' own
    "cards" style renders .filled-cards-grid tiles, so a widget instance
    using that style opts its .card wrapper out of the chrome (border/
    shadow/background/padding -- see .widget-card--bare, static/style.css)
    via _widget_context's own "bare" key. Spaces & Projects' "list" style
    keeps its normal card chrome -- only the tile grid was the redundant-
    double-frame complaint. (The standalone "quick_links" widget type this
    originally also covered was retired the same day, merged into this
    "cards" style -- see TestSpacesProjectsCardsIncludesProjects.)"""

    def _widget(self, conn, wtype, config=None):
        w = {
            "uid": f"w-{wtype}-{(config or {}).get('style', 'x')}", "type": wtype, "title": None,
            "config": config or {}, "position": 1, "created_at": now_iso(),
        }
        db.upsert_dashboard_widget(conn, w)
        return w

    def test_spaces_projects_cards_style_is_bare(self, conn):
        w = self._widget(conn, "spaces_projects", {"style": "cards"})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is True

    def test_spaces_projects_list_style_keeps_card_chrome(self, conn):
        w = self._widget(conn, "spaces_projects", {"style": "list"})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_spaces_projects_default_style_keeps_card_chrome(self, conn):
        # style absent -- _render_spaces_projects defaults to "list", the
        # bare check has to agree with that same default rather than
        # reading config.get("style") == "cards" in isolation and getting
        # it right only when the key happens to be present.
        w = self._widget(conn, "spaces_projects", {})
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_other_widget_types_are_not_bare(self, conn):
        w = self._widget(conn, "at_a_glance")
        wc = dashboard_router._widget_context(conn, w)
        assert wc["bare"] is False

    def test_bare_class_rendered_on_dashboard(self, conn):
        db.set_app_meta(conn, deps.EDIT_MODE_KEY, "0")
        self._widget(conn, "spaces_projects", {"style": "cards"})
        from starlette.requests import Request

        req = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        resp = dashboard_router.dashboard_view(req, conn=conn)
        body = resp.body.decode()
        assert "widget-card--bare" in body
