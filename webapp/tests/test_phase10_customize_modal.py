"""Tests for the Customize-dashboard modal (dashboard_customize.html).

The modal provides a two-pane Widget Builder with a config form on the
left and an always-live preview on the right, plus Add widget / Done buttons.
It scopes widgets to the current dashboard or Space via the hidden space_uid
field. The builder form POSTs to /dashboard/widgets on submit."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import db
from src.routers import dashboard as dashboard_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/dashboard/customize", query: bytes = b""):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


class TestCustomizeRoute:
    def test_renders_builder_with_seeded_defaults(self, conn):
        dashboard_router._ensure_default_widgets(conn)
        req = _request()
        resp = dashboard_router.dashboard_customize(req, conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Customize dashboard" in body
        assert 'id="modal-target"' in body
        assert "Add widget" in body
        assert "Done" in body  # Done button closes the modal

    def test_renders_builder_with_no_widgets(self, conn):
        # No widgets exist, but the builder form is always shown -- the
        # single "Add widget" button in the footer does the add-and-close
        # (2026-08-07 rework: no more separate Done/cancel, no stay-open
        # flow). "Customize dashboard" is the modal's only h1.
        req = _request()
        resp = dashboard_router.dashboard_customize(req, conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Customize dashboard" in body
        assert "Add widget" in body
        assert body.count("<h1>") == 1

    def test_get_does_not_seed_or_mutate(self, conn):
        # The modal page is read-only presentation -- a bare GET must not
        # call _ensure_default_widgets (that's dashboard_view's job).
        req = _request()
        dashboard_router.dashboard_customize(req, conn=conn)
        assert db.list_dashboard_widgets(conn) == []

    def test_space_scoped_modal(self, conn):
        db.upsert_label_config(
            conn, {"name": "Math", "generate_space": 1, "color": "blue", "created_at": _now()}
        )
        dashboard_router._ensure_default_label_widgets(conn, "Math")
        req = _request(query=b"space_uid=Math")
        resp = dashboard_router.dashboard_customize(req, space_uid="Math", conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Customize Space dashboard" in body
        # The add form keeps its hidden space_uid so new widgets land here.
        assert 'name="space_uid" value="Math"' in body

    def test_customize_url_query_param_is_scoped_like_the_page(self, conn):
        # The template's own Customize trigger on a Space page targets
        # /dashboard/customize?space_uid=..., and the add form hidden field
        # must carry the same scope.
        db.upsert_label_config(
            conn, {"name": "Work", "generate_space": 1, "color": "green", "created_at": _now()}
        )
        dashboard_router._ensure_default_label_widgets(conn, "Work")
        resp = dashboard_router.dashboard_customize(_request(), space_uid="Work", conn=conn)
        body = resp.body.decode()
        assert 'name="space_uid" value="Work"' in body


class TestCustomizeForms:
    def test_builder_form_is_single_button_no_stay_open(self, conn):
        # 2026-08-07 rework: the form has no data-builder (no stay-open
        # flow with an "Added to dashboard." Duplicate/Edit bar) -- it is a
        # plain modal.js form whose single Add-widget submit closes the
        # dialog on success. Asserting the removed machinery is gone keeps
        # this from silently regressing back.
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'id="widget-builder-form" method="post" action="/dashboard/widgets"' in body
        assert 'data-preview-url="/dashboard/widgets/preview"' in body
        assert 'id="widget-builder-added"' not in body
        assert 'data-builder-duplicate' not in body
        assert 'data-builder-edit' not in body
        # The stay-open confirmation bar's container is gone (its label only
        # survives in the template's historical comment, which is fine).
        assert 'class="widget-builder-added-bar"' not in body

    def test_add_widget_button_in_footer_no_cancel(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        # Add widget is the footer's primary action, submitting the builder
        # form; there is no separate Done/cancel button any more (2026-08-07).
        assert 'id="widget-builder-form"' in body
        assert "Add widget" in body
        assert 'data-modal-cancel' not in body

    def test_customize_modal_has_a_footer_with_add_widget(self, conn):
        # 2026-08-07 rework: the modal now has a real modal-footer holding
        # the single Add widget button (it used to keep buttons inline in
        # the body). Assert the footer exists and is populated with it.
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert '<div class="modal-footer">' in body
        assert 'form="widget-builder-form"' in body

    def test_builder_is_two_pane_with_always_live_preview(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="widget-builder"' in body
        assert 'class="widget-builder-config"' in body
        assert 'class="widget-builder-preview"' in body
        assert 'id="widget-preview-content"' in body

    def test_edit_form_button_not_in_builder(self, conn):
        # The customize modal is for adding widgets only -- no existing
        # widget edit/delete/reorder forms.
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        builder_section = body.split('class="widget-builder"')[1] if 'class="widget-builder"' in body else body
        assert "widget-customize-row" not in builder_section


class TestBuilderFieldsRework:
    """2026-08-07 (modal-input-design Phase A) -- Source/View/Range/Limit/
    Labels in _widget_builder_fields.html moved from raw select/number/
    text-with-datalist to a tile picker, segmented controls, a stepper, and
    a chip multiselect. These check the new markup shape; the underlying
    add/edit behavior is covered separately in test_dashboard_router.py."""

    def test_source_is_a_tile_radio_group_with_every_source_value(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="tile-select widget-source-select"' in body
        for key in dashboard_router.WIDGET_SOURCES:
            assert f'<input type="radio" name="source" value="{key}"' in body
        # Exactly one tile-radio is checked by default (the first source).
        assert body.count('name="source"') == len(dashboard_router.WIDGET_SOURCES)
        assert body.count('name="source" value="calendar_tasks" class="tile-radio" checked') == 1

    def test_view_and_range_are_single_select_multiselects(self, conn):
        # 2026-08-08 follow-up: View/Range are the single-choice variant of
        # the app's checkbox-dropdown (_widget_list_multiselect.html,
        # ms_mode="single") -- real radio inputs inside a .multiselect, not
        # native <select>s (whose open-list chrome is unstyleable).
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert '<div class="multiselect widget-list-multiselect widget-view-select"' in body
        assert '<div class="multiselect widget-list-multiselect widget-range-select"' in body
        assert '<select name="view"' not in body
        assert '<select name="range"' not in body
        for key, spec in dashboard_router.WIDGET_VIEWS.items():
            has_range = "1" if spec["has_range"] else ""
            assert (
                f'<input type="radio" name="view" value="{key}"\n'
                f'                       form="widget-builder-form"\n'
                f'                       data-source="{spec["source"]}" data-has-range="{has_range}"'
            ) in body
        for key, spec in dashboard_router.WIDGET_RANGES.items():
            assert f'<input type="radio" name="range" value="{key}"\n' in body
            # views is a set -- order isn't guaranteed, so just check the
            # option itself carries a data-views attribute.
            assert f'data-views="' in body

    def test_limit_is_a_stepper_wrapping_a_real_number_input(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="stepper"' in body
        assert 'class="stepper-btn stepper-dec"' in body
        assert 'class="stepper-btn stepper-inc"' in body
        assert 'name="limit"' in body
        # min="0" (2026-08-31 direct feedback: "add a way to set the limit
        # to 0 (0 = unlimited)") -- was min="1", which blocked reaching 0.
        assert '<input type="number" name="limit" class="widget-preview-field stepper-input" min="0"' in body

    def test_labels_is_a_chip_multiselect_over_known_label_names(self, conn):
        db.upsert_task(conn, {
            "uid": "t1", "title": "t1", "description": "", "status": "active",
            "due_at": None, "tags": ["Work", "Urgent"], "created_at": _now(),
        })
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'name="tags_labels" value="Work"' in body
        assert 'name="tags_labels" value="Urgent"' in body
        # No more free-text tags field with the old datalist wiring on this form.
        assert 'class="tag-input widget-preview-field"' not in body


class TestFlattenCustomize:
    def test_flattens_plain_and_stacked_contexts(self):
        a = {"is_stack": False, "widget": {"uid": "a", "title": "A"}}
        stack = {
            "is_stack": True,
            "widget": {"uid": "s", "title": None, "type": "stack"},
            "children": [
                {"widget": {"uid": "x", "title": "X"}},
                {"widget": {"uid": "y", "title": "Y"}},
            ],
        }
        flat = dashboard_router._flatten_customize([a, stack])
        assert [f["widget"]["uid"] for f in flat] == ["a", "s", "x", "y"]
        assert [f.get("in_stack") for f in flat] == [False, None, True, True]
        assert flat[1]["is_stack_header"] is True

    def test_flat_empty_input(self):
        assert dashboard_router._flatten_customize([]) == []
