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

    def test_renders_empty_state_for_builder(self, conn):
        # No widgets exist, but the builder form is always shown
        req = _request()
        resp = dashboard_router.dashboard_customize(req, conn=conn)
        assert resp.status_code == 200
        body = resp.body.decode()
        assert "Add widget" in body
        assert "Done" in body
        assert "Add a widget" in body  # builder header

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
    def test_builder_form_has_data_builder(self, conn):
        # The Widget Builder form is marked data-builder so modal.js's
        # generic form handler skips it -- CCWidgetBuilder.init owns the
        # submit (keeps modal open, refreshes, shows confirmation).
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'id="widget-builder-form" method="post" action="/dashboard/widgets"' in body
        assert 'data-builder' in body
        assert 'data-preview-url="/dashboard/widgets/preview"' in body

    def test_builder_is_two_pane_with_always_live_preview(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="widget-builder"' in body
        assert 'class="widget-builder-config"' in body
        assert 'class="widget-builder-preview"' in body
        assert 'id="widget-preview-content"' in body

    def test_builder_added_state_bar_with_duplicate_and_edit(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'id="widget-builder-added"' in body
        assert "hidden" in body  # hidden until the first successful Add (JS)
        assert 'data-builder-duplicate' in body
        assert 'data-builder-edit' in body
        assert "Added to dashboard." in body

    def test_add_and_done_buttons_in_form(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        # Add widget and Done buttons are inside the builder form
        assert "Add widget" in body
        # Done is a cancel button that closes the modal
        assert 'data-modal-cancel' in body
        assert "Done" in body

    def test_no_custom_modal_footer_content(self, conn):
        # The customize modal has the same body structure as the widget edit
        # modal -- no custom modal-footer content, buttons are inside the form body.
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        # The modal-footer div exists in base.html but customize doesn't populate it
        # Check that our template doesn't output any modal-footer div with content
        assert '<div class="modal-footer">' not in body

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

    def test_view_and_range_are_real_selects(self, conn):
        # 2026-08-07 follow-up ("view, range, priority, reminders should be
        # real drop downs") -- View/Range reverted from the segmented radio
        # group back to plain `<select>`s; data-source/data-has-range/
        # data-views now live on `<option>` elements instead of radios.
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert '<select name="view" class="widget-view-select">' in body
        assert '<select name="range" class="widget-range-select">' in body
        for key, spec in dashboard_router.WIDGET_VIEWS.items():
            has_range = "1" if spec["has_range"] else ""
            assert (
                f'<option value="{key}" data-source="{spec["source"]}" '
                f'data-has-range="{has_range}"'
            ) in body
        for key, spec in dashboard_router.WIDGET_RANGES.items():
            # views is a set -- order isn't guaranteed, so just check the
            # option itself carries a data-views attribute.
            assert f'<option value="{key}" data-views="' in body

    def test_limit_is_a_stepper_wrapping_a_real_number_input(self, conn):
        body = dashboard_router.dashboard_customize(_request(), conn=conn).body.decode()
        assert 'class="stepper"' in body
        assert 'class="stepper-btn stepper-dec"' in body
        assert 'class="stepper-btn stepper-inc"' in body
        assert 'name="limit"' in body
        assert '<input type="number" name="limit" class="widget-preview-field stepper-input" min="1"' in body

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
