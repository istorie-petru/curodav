"""Phase 2 (label-space rework) acceptance tests -- see
features/architecture.md §3 Phase 2's own acceptance criteria and this
phase's task spec, item 8:

  * rename propagates to object_labels and children's parent_name;
  * merge unions membership correctly;
  * no delete endpoint exists (there is no DELETE-shaped route for a
    label at all -- "clear" empties membership instead);
  * a generate_space=1 label's page renders the right aggregated content;
  * dashboard_widgets.label_name migration correctness;
  * habits correctly filter by label now.

2026-08-07: TestDatabasesFilterByLabel and
test_databases_project_uid_backfilled_as_object_labels (which exercised
the now-removed Databases feature's project-link-as-label behavior) are
deleted -- see features/architecture.md's Grades/Databases removal
note. Everything else in this file covers habits/label management,
unaffected by that removal.

2026-08-15: TestScheduleClassesFilterByLabel is deleted -- the whole
Schedule module (and the class-as-real-recurring-event mechanism it
relied on) is removed, see plans/STATE.md's removal entry.
`test_schedule_classes_project_uid_backfilled_as_a_real_tag` stays: it
exercises `migrate_labels.py`'s legacy pre-1.6 `schedule_classes`-table
backfill path directly against a synthetic table, unrelated to
routers/schedule.py.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import migrate_labels  # noqa: E402
import migrate_spaces_direct_tags  # noqa: E402

from src.routers import banners as banners_router
from src.routers import dashboard as dashboard_router
from src.routers import habits as habits_router
from src.routers import labels as labels_router
from src.routers import projects as projects_router
from src.routers import spaces as spaces_router


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    with db.connect(db_path) as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/labels"):
    return Request(
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


# --------------------------------------------------------------------- #
# Icon persistence (2026-09-03 bug fix -- direct report: "chose icons
# individually and they don't save"). label_form_modal.html's icon picker
# (_icon_swatch_picker.html, `name="icon"` radios) has posted into this
# form since it existed; routers/labels.py's create_label/update_label
# never declared an `icon` Form param to receive it, so FastAPI silently
# dropped the field on every submit and db.upsert_label_config's own
# partial-update contract ("only touch what you're told to") meant the
# icon just... never changed. Fixed by declaring `icon` on both routes.
# --------------------------------------------------------------------- #


class TestModalHeaderAppearanceButtons:
    """Direct request, 2026-09-21: "the color, icon, banner buttons in the
    header, as small circular buttons, that look like the close 'X'
    button, that for pressing each opens each menu." label_form_modal.html
    moves Color/Icon/Banner out of the body field-grid into
    .modal-header-actions; quick_add.html's Label panel (shared header
    across 4 tabs, no natural home for these) keeps them inline, unchanged."""

    def test_edit_modal_header_has_the_three_appearance_buttons(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "color": "yellow", "icon": "shopping-cart", "created_at": _now()})
        resp = labels_router.edit_label_modal("Groceries", _request("/settings/labels/Groceries/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="modal-header-actions"' in body
        assert 'class="color-swatch-current cal-yellow"' in body
        assert 'class="icon-picker-current"' in body
        assert '/banners/editor?scope=Groceries' in body
        assert 'from_modal=1' in body

    def test_edit_modal_body_no_longer_has_inline_color_icon_banner_fields(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "color": "yellow", "created_at": _now()})
        resp = labels_router.edit_label_modal("Groceries", _request("/settings/labels/Groceries/edit"), conn=conn)
        body = resp.body.decode()
        assert "<label>Color</label>" not in body
        assert "<label>Icon</label>" not in body
        assert "<label>Banner</label>" not in body

    def test_new_label_modal_also_gets_header_buttons_but_no_banner(self, conn):
        resp = labels_router.new_label_modal(_request("/settings/labels/new"), conn=conn)
        body = resp.body.decode()
        assert 'class="modal-header-actions"' in body
        assert 'class="color-swatch-current cal-blue"' in body  # default, unsaved yet
        assert "/banners/editor" not in body  # no name yet to key a banner off of

    def test_grouped_label_shows_readonly_swatch_and_no_banner_button_in_header(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "purple", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "green", "created_at": _now()})
        resp = labels_router.edit_label_modal("Historiography", _request("/settings/labels/Historiography/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="modal-header-swatch cal-purple"' in body
        assert "color-swatch-current" not in body  # no interactive trigger
        assert "/banners/editor" not in body  # follows the Space's banner, no button

    def test_quick_add_label_tab_keeps_inline_appearance_fields(self, conn):
        resp = dashboard_router.quick_add_form(_request("/quick/add"), default_tab="label", conn=conn)
        body = resp.body.decode()
        assert "<label>Color</label>" in body
        assert "<label>Icon</label>" in body
        assert 'class="modal-header-actions"' not in body


class TestBannerEditorFromModal:
    """Direct request: "if a button allows the user to navigate from one
    modal to the other, instead of the 'Done' there should always be a
    'Go back' button... 'Page banner' modal window that opens from the
    label edit modal window has 'Done' instead of 'Cancel'." """

    def test_from_modal_renders_cancel_and_swaps_back(self, conn):
        resp = banners_router.banner_editor(
            _request("/banners/editor"), scope="Groceries", page_url="/settings/labels/Groceries/edit", from_modal=True, conn=conn,
        )
        body = resp.body.decode()
        assert ">Cancel</a>" in body or "Cancel" in body
        assert 'href="/settings/labels/Groceries/edit" class="btn ghost" data-modal' in body

    def test_not_from_modal_still_renders_done_and_closes(self, conn):
        # Home/Space/Project's own edit-mode banner button -- opened from
        # a real page, not another modal, so closing (not swapping back
        # into a modal fragment) is still correct.
        resp = banners_router.banner_editor(_request("/banners/editor"), scope="", page_url="/", conn=conn)
        body = resp.body.decode()
        assert 'href="/" class="btn ghost" data-modal-cancel' in body
        assert "Done" in body


class TestIconPersistence:
    # Every Form(...) param is passed explicitly here, including ones this
    # test doesn't otherwise care about (role/start_date/end_date/
    # description/parent_name) -- calling a FastAPI route function
    # directly (not through the app) bypasses Form()'s normal request-body
    # resolution, so any parameter left at its Python default literally
    # holds FastAPI's own `Form(...)` marker object, not the string a real
    # submit would inject (same caveat routers/labels.py's own
    # `set_label`/`create_label` already document for `abbreviation`).

    def test_create_label_saves_the_chosen_icon(self, conn):
        labels_router.create_label(new_name="Garden", color="green", icon="  leaf  ", parent_name="", role="none", start_date="", end_date="", conn=conn)
        cfg = db.get_label_config(conn, "Garden")
        assert cfg["icon"] == "leaf"

    def test_update_label_saves_a_newly_chosen_icon(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="leaf", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] == "leaf"

    def test_update_label_changes_an_existing_icon(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "icon": "leaf", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="flag", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] == "flag"

    def test_update_label_no_icon_radio_clears_it(self, conn):
        # The picker's "No icon" option submits icon="" (_icon_swatch_
        # picker.html) -- an explicit clear, not "leave unchanged".
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "icon": "leaf", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="green", icon="", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["icon"] is None

    def test_update_label_still_saves_parent_alongside_icon(self, conn):
        # Regression guard: adding the new `icon` param shouldn't disturb
        # the fields that already worked. `parent_name` (2026-09-14,
        # replaces the old free-text `label_group`) must name a real Space.
        #
        # 2026-09-21 (final labels-page iteration, direct request: "remove
        # the ability to have colors... for labels or projects grouped
        # under a space") -- a submitted `color` is no longer saved once
        # `parent_name` is set; the label's prior stored color ("green")
        # is preserved untouched instead of being overwritten with
        # whatever the (now-hidden-in-the-UI) picker happened to submit.
        # See TestColorInheritance below for the read-side half.
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="purple", icon="leaf", parent_name="Home", description="", role="none", start_date="", end_date="", conn=conn)
        cfg = db.get_label_config(conn, "Garden")
        assert cfg["icon"] == "leaf"
        assert cfg["color"] == "green"
        assert cfg["parent_name"] == "Home"


# --------------------------------------------------------------------- #
# Color validation + reserved-name guard (2026-09-07 fixes, both flagged
# in an earlier audit): `color` used to be written to storage unchecked
# (`color or "blue"`, accepting literally any string), and nothing stopped
# a label from being named after one of the sentinel banner scopes
# (db.PAGE_HEADER_BANNER_SCOPE / db.SEASON_BANNER_SCOPES), which live in
# the exact same app_meta namespace a label's own banner does.
# --------------------------------------------------------------------- #


class TestColorValidation:
    def test_create_label_rejects_an_unknown_color(self, conn):
        labels_router.create_label(new_name="Garden", color="not-a-real-color", icon="", parent_name="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"

    def test_create_label_accepts_a_real_color(self, conn):
        labels_router.create_label(new_name="Garden", color="teal", icon="", parent_name="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "teal"

    def test_update_label_rejects_an_unknown_color(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="<script>", icon="", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"

    def test_set_label_rejects_an_unknown_color(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.set_label(name="Garden", color="whatever", icon="", description="", parent_name="", generate_space="", abbreviation="", return_to="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "blue"


class TestReservedLabelNameGuard:
    def test_create_label_rejects_the_page_header_scope_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name=db.PAGE_HEADER_BANNER_SCOPE, color="blue", icon="", parent_name="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, db.PAGE_HEADER_BANNER_SCOPE) is None

    def test_create_label_rejects_a_season_scope_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name=db.SEASON_BANNER_SCOPES["summer"], color="blue", icon="", parent_name="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400

    def test_update_label_rejects_renaming_into_a_reserved_name(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.update_label(name="Garden", new_name=db.PAGE_HEADER_BANNER_SCOPE, color="green", icon="", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400
        # Rejected before the rename happened -- the label is untouched.
        assert db.get_label_config(conn, "Garden") is not None

    def test_update_label_editing_in_place_is_unaffected(self, conn):
        # Sanity check the guard only fires on an actual name *change* --
        # every ordinary edit (new_name == name) must keep working.
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        labels_router.update_label(name="Garden", new_name="Garden", color="teal", icon="", parent_name="", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Garden")["color"] == "teal"

    def test_rename_endpoint_rejects_a_reserved_destination(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.rename_label(name="Garden", new_name=db.PAGE_HEADER_BANNER_SCOPE, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, "Garden") is not None

    def test_merge_rejects_a_reserved_destination(self, conn):
        db.upsert_label_config(conn, {"name": "Garden", "color": "green", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.merge_label(name="Garden", dest_name=db.PAGE_HEADER_BANNER_SCOPE, conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, "Garden") is not None

    def test_set_label_rejects_a_reserved_name(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.set_label(name=db.PAGE_HEADER_BANNER_SCOPE, color="blue", icon="", description="", parent_name="", generate_space="", abbreviation="", return_to="", conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, db.PAGE_HEADER_BANNER_SCOPE) is None


# --------------------------------------------------------------------- #
# Space-link dropdown (Spaces -- labels-as-membership rework slice 1,
# 2026-09-14): _label_form_fields.html's old free-text `label_group`
# input is replaced by a `parent_name` <select> populated from
# db.list_space_labels; create_label/update_label validate it against
# that same set instead of accepting arbitrary text.
# --------------------------------------------------------------------- #


class TestLabelSelectorScope:
    """Direct request: "On space's dashboard, project pages or label's
    page, the label selector should only have labels from that group...
    this should work for any space > labels grouped under it"."""

    def test_a_space_scopes_to_its_own_children(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Ancient History", "parent_name": "University", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Unrelated", "created_at": _now()})
        assert db.label_selector_scope(conn, "University") == ["Ancient History", "Historiography"]

    def test_a_project_grouped_under_a_space_scopes_to_its_siblings(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "is_project": 1, "parent_name": "University", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "created_at": _now()})
        # Includes CS101 itself -- list_child_labels(University) returns
        # every label grouped under it, siblings and self alike; a picker
        # that dropped the page's own label while keeping every other
        # sibling would be an arbitrary, unrequested exclusion.
        assert db.label_selector_scope(conn, "CS101") == ["CS101", "Historiography"]

    def test_a_plain_label_grouped_under_a_space_scopes_to_its_siblings(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Ancient History", "parent_name": "University", "created_at": _now()})
        assert db.label_selector_scope(conn, "Historiography") == ["Ancient History", "Historiography"]

    def test_a_standalone_project_with_no_parent_space_is_unscoped(self, conn):
        db.upsert_label_config(conn, {"name": "Website Relaunch", "is_project": 1, "created_at": _now()})
        assert db.label_selector_scope(conn, "Website Relaunch") is None

    def test_a_standalone_plain_label_is_unscoped(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "created_at": _now()})
        assert db.label_selector_scope(conn, "Groceries") is None


class TestColorInheritance:
    """Final labels-page iteration (direct request, 2026-09-21): "the
    labels/projects grouped by space should follow the space's color...
    remove the ability to have colors or banners for labels or projects
    grouped under a space." """

    def test_grouped_plain_label_inherits_the_spaces_color(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "purple", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "green", "created_at": _now()})
        assert db.effective_label_config(conn, "Historiography")["color"] == "purple"

    def test_grouped_project_inherits_the_spaces_color(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "orange", "created_at": _now()})
        db.upsert_label_config(
            conn, {"name": "CS101", "is_project": 1, "parent_name": "University", "color": "red", "start_date": "2026-01-01", "end_date": "2026-12-31", "created_at": _now()}
        )
        assert db.effective_label_config(conn, "CS101")["color"] == "orange"

    def test_ungrouped_label_keeps_its_own_color(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "color": "yellow", "created_at": _now()})
        assert db.effective_label_config(conn, "Groceries")["color"] == "yellow"

    def test_a_space_never_inherits_even_if_parent_name_is_somehow_set(self, conn):
        # Defensive -- the app's own UI never lets a Space have a
        # parent_name (_validate_parent_name/role=space form handling),
        # but a stored row shouldn't be able to paint a Space with
        # someone else's color even if one exists on disk regardless.
        db.upsert_label_config(conn, {"name": "Other", "generate_space": 1, "color": "red", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "purple", "parent_name": "Other", "created_at": _now()})
        assert db.effective_label_config(conn, "University")["color"] == "purple"

    def test_case_insensitive_lookup_also_inherits(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "teal", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "green", "created_at": _now()})
        assert db.effective_label_config_ci(conn, "historiography")["color"] == "teal"

    def test_edit_modal_shows_readonly_swatch_for_a_grouped_label(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "color": "purple", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "green", "created_at": _now()})
        resp = labels_router.edit_label_modal("Historiography", _request("/settings/labels/Historiography/edit"), conn=conn)
        body = resp.body.decode()
        assert "Follows University" in body
        assert 'name="color" value="purple"' not in body  # no interactive swatch radios rendered

    def test_edit_modal_shows_interactive_picker_for_an_ungrouped_label(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "color": "yellow", "created_at": _now()})
        resp = labels_router.edit_label_modal("Groceries", _request("/settings/labels/Groceries/edit"), conn=conn)
        body = resp.body.decode()
        assert "Follows" not in body

    def test_update_label_preserves_stored_color_once_grouped(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "color": "green", "created_at": _now()})
        labels_router.update_label(
            name="Historiography", new_name="Historiography", color="red", icon="", parent_name="University",
            description="", role="none", start_date="", end_date="", conn=conn,
        )
        # Stored value is untouched ("green"), even though the (hidden)
        # form submitted "red" -- effective_label_config still resolves
        # to the Space's own color regardless of what's stored.
        assert db.get_label_config(conn, "Historiography")["color"] == "green"
        assert db.effective_label_config(conn, "Historiography")["color"] is not None


class TestBannerInheritance:
    def test_grouped_labels_page_shows_the_spaces_banner_not_its_own(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "created_at": _now()})
        db.set_page_banner(conn, "University", {"kind": "remote", "image_url": "https://example.com/uni.jpg", "alt": "x"})
        db.set_page_banner(conn, "Historiography", {"kind": "remote", "image_url": "https://example.com/own.jpg", "alt": "x"})
        ctx = dashboard_router._page_banner_context(conn, "Historiography")
        assert ctx["banner"]["image_url"] == "https://example.com/uni.jpg"
        assert ctx["banner_grouped_under"] == "University"
        assert ctx["has_own_banner"] is False

    def test_ungrouped_label_still_shows_its_own_banner(self, conn):
        db.upsert_label_config(conn, {"name": "Groceries", "created_at": _now()})
        db.set_page_banner(conn, "Groceries", {"kind": "remote", "image_url": "https://example.com/own.jpg", "alt": "x"})
        ctx = dashboard_router._page_banner_context(conn, "Groceries")
        assert ctx["banner"]["image_url"] == "https://example.com/own.jpg"
        assert ctx["banner_grouped_under"] is None
        assert ctx["has_own_banner"] is True

    def test_edit_label_modal_hides_add_change_banner_control_for_a_grouped_label(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "created_at": _now()})
        resp = labels_router.edit_label_modal("Historiography", _request("/settings/labels/Historiography/edit"), conn=conn)
        body = resp.body.decode()
        assert "Add banner" not in body
        assert "Change banner" not in body
        assert "Follows University" in body

    def test_project_page_hides_the_banner_button_when_grouped(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(
            conn, {"name": "CS101", "is_project": 1, "parent_name": "University", "start_date": "2026-01-01", "end_date": "2026-12-31", "created_at": _now()}
        )
        db.set_app_meta(conn, "edit_mode_enabled", "1")
        resp = projects_router.project_detail("CS101", _request("/projects/CS101"), conn=conn)
        body = resp.body.decode()
        assert "Add banner" not in body
        assert "Change banner" not in body


class TestLabelParentNameDropdown:
    def test_create_label_writes_a_valid_parent_name(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        labels_router.create_label(new_name="Homework", color="blue", icon="", parent_name="University", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Homework")["parent_name"] == "University"

    def test_create_label_rejects_a_parent_name_that_is_not_a_space(self, conn):
        # "Homework" exists but isn't generate_space=1 -- not a valid Space
        # to link under.
        db.upsert_label_config(conn, {"name": "Homework", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name="Essay", color="blue", icon="", parent_name="Homework", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400
        assert db.get_label_config(conn, "Essay") is None

    def test_create_label_rejects_a_parent_name_naming_nothing_at_all(self, conn):
        with pytest.raises(Exception) as excinfo:
            labels_router.create_label(new_name="Essay", color="blue", icon="", parent_name="Nonexistent Space", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400

    def test_create_label_blank_parent_name_is_ungrouped(self, conn):
        labels_router.create_label(new_name="Essay", color="blue", icon="", parent_name="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Essay")["parent_name"] is None

    def test_create_label_role_space_ignores_any_submitted_parent_name(self, conn):
        # Spaces don't nest -- a label becoming a Space can't also carry a
        # parent, regardless of what a raw POST submits alongside role=space.
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        labels_router.create_label(new_name="Work", color="blue", icon="", parent_name="University", role="space", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Work")["parent_name"] is None

    def test_update_label_writes_a_valid_parent_name(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Homework", "created_at": _now()})
        labels_router.update_label(name="Homework", new_name="Homework", color="blue", icon="", parent_name="University", description="", role="none", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Homework")["parent_name"] == "University"

    def test_update_label_rejects_a_parent_name_that_is_not_a_space(self, conn):
        db.upsert_label_config(conn, {"name": "Homework", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Essay", "created_at": _now()})
        with pytest.raises(Exception) as excinfo:
            labels_router.update_label(name="Essay", new_name="Essay", color="blue", icon="", parent_name="Homework", description="", role="none", start_date="", end_date="", conn=conn)
        assert excinfo.value.status_code == 400

    def test_update_label_role_space_ignores_any_submitted_parent_name(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Work", "created_at": _now()})
        labels_router.update_label(name="Work", new_name="Work", color="blue", icon="", parent_name="University", description="", role="space", start_date="", end_date="", conn=conn)
        assert db.get_label_config(conn, "Work")["parent_name"] is None

    def test_edit_modal_renders_a_space_dropdown_not_a_text_input(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Homework", "parent_name": "University", "created_at": _now()})
        resp = labels_router.edit_label_modal("Homework", _request("/settings/labels/Homework/edit"), conn=conn)
        body = resp.body.decode()
        assert '<select name="parent_name">' in body
        assert 'name="label_group"' not in body
        assert '<option value="University" selected>University</option>' in body
        assert '<option value="">No space</option>' in body

    def test_edit_modal_hides_the_dropdown_when_editing_a_space_itself(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        resp = labels_router.edit_label_modal("University", _request("/settings/labels/University/edit"), conn=conn)
        body = resp.body.decode()
        assert 'class="field label-parent-field" hidden' in body

    def test_new_label_modal_renders_every_space_as_an_option(self, conn):
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "created_at": _now()})
        resp = labels_router.new_label_modal(_request("/settings/labels/new"), conn=conn)
        body = resp.body.decode()
        assert '<option value="University"' in body
        assert '<option value="Home"' in body


# --------------------------------------------------------------------- #
# Rename
# --------------------------------------------------------------------- #


class TestRename:
    def test_rename_rewrites_object_labels(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert db.list_labels_for_object(conn, "task", "t1") == ["university"]
        assert db.list_object_ids_for_label(conn, "task", "uni") == []

    def test_rename_updates_own_label_config_row(self, conn):
        db.upsert_label_config(conn, {"name": "uni", "color": "purple", "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert db.get_label_config(conn, "uni") is None
        cfg = db.get_label_config(conn, "university")
        assert cfg is not None and cfg["color"] == "purple"

    def test_rename_updates_childrens_parent_name(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "MATH201", "parent_name": "Uni", "created_at": _now()})
        db.rename_label(conn, "Uni", "University")
        assert db.get_label_config(conn, "CS101")["parent_name"] == "University"
        assert db.get_label_config(conn, "MATH201")["parent_name"] == "University"

    def test_rename_colliding_with_an_existing_label_merges_instead(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "Y", "description": "", "status": "active",
                               "tags": ["university"], "created_at": _now()})
        db.rename_label(conn, "uni", "university")
        assert sorted(db.list_object_ids_for_label(conn, "task", "university")) == ["t1", "t2"]

    def test_case_only_rename_is_not_treated_as_a_merge(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.rename_label(conn, "uni", "Uni")
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_rename_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        resp = labels_router.rename_label("uni", new_name="university", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == ["university"]


# --------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------- #


class TestMerge:
    def test_merge_unions_membership(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "Y", "description": "", "status": "active",
                                "all_day": 0, "tags": ["dest"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Z", "tags": ["source"], "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.list_object_ids_for_label(conn, "task", "dest") == ["t1"]
        assert db.list_object_ids_for_label(conn, "event", "dest") == ["e1"]
        assert db.list_object_ids_for_label(conn, "contact", "dest") == ["c1"]
        assert db.list_object_ids_for_label(conn, "task", "source") == []

    def test_merge_does_not_duplicate_an_object_already_carrying_both(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source", "dest"], "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.list_labels_for_object(conn, "task", "t1") == ["dest"]

    def test_merge_repoints_source_children(self, conn):
        db.upsert_label_config(conn, {"name": "dest", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "source", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "child", "parent_name": "source", "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.get_label_config(conn, "child")["parent_name"] == "dest"

    def test_merge_removes_sources_own_config_row(self, conn):
        db.upsert_label_config(conn, {"name": "source", "color": "red", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "dest", "color": "blue", "created_at": _now()})
        db.merge_labels(conn, "source", "dest")
        assert db.get_label_config(conn, "source") is None

    def test_merge_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["source"], "created_at": _now()})
        resp = labels_router.merge_label("source", dest_name="dest", conn=conn)
        assert resp.status_code == 303
        assert db.list_object_ids_for_label(conn, "task", "dest") == ["t1"]


# --------------------------------------------------------------------- #
# No delete endpoint -- "clear" empties membership instead (§0.1)
# --------------------------------------------------------------------- #


class TestNoDeleteJustClear:
    def test_labels_router_exposes_delete_route_that_clears(self, conn):
        """Delete endpoint exists but clears membership instead of deleting config (§0.1)."""
        route_paths = {r.path for r in labels_router.router.routes}
        assert any(p.endswith("/delete") for p in route_paths)

    def test_clear_empties_membership_but_keeps_config_row(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        db.upsert_label_config(conn, {"name": "uni", "color": "purple", "created_at": _now()})
        db.clear_label(conn, "uni")
        assert db.list_object_ids_for_label(conn, "task", "uni") == []
        # The config row is left alone -- harmless stale metadata, not
        # cleaned up (per the plan's own "no delete" semantics).
        assert db.get_label_config(conn, "uni") is not None

    def test_clear_router_endpoint(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["uni"], "created_at": _now()})
        resp = labels_router.clear_label("uni", conn=conn)
        assert resp.status_code == 303
        assert db.list_labels_for_object(conn, "task", "t1") == []


# --------------------------------------------------------------------- #
# Generated Space page
# --------------------------------------------------------------------- #


class TestGeneratedSpacePage:
    def test_space_page_aggregates_by_child_label_membership(self, conn):
        # 2026-09-14 (Spaces -- labels-as-membership rework slice 3):
        # reverses the direct-membership-only behavior this test used to
        # assert (see git history for the pre-slice-3 version) -- a
        # Space's page now shows items tagged with any of its child
        # labels, and NO LONGER shows items tagged directly with the
        # Space's own name (that tag still exists in the UI today, see
        # spaces.py::_label_scope's own docstring on why, but has no
        # effect here anymore).
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_label_config(conn, {"name": "MATH201", "parent_name": "Uni", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "ChildOnly", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t3", "title": "OtherChild", "description": "", "status": "active",
                               "tags": ["MATH201"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t4", "title": "Unrelated", "description": "", "status": "active",
                               "tags": ["Groceries"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "status": "active",
                                "all_day": 0, "tags": ["CS101"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Prof", "tags": ["MATH201"], "created_at": _now()})
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni"), conn=conn)
        assert resp.status_code == 200
        assert {t["uid"] for t in resp.context["tasks"]} == {"t2", "t3"}
        assert {e["uid"] for e in resp.context["events"]} == {"e1"}
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}
        assert resp.context["is_space"] is True
        assert [c["name"] for c in resp.context["children"]] == ["CS101", "MATH201"]

    def test_space_page_scopes_the_sidebar_quick_add_link_to_itself(self, conn):
        # Direct request: "the label selector should only have labels
        # from that group." base.html's quick-add link reads
        # page_label_scope to append &scope=<name>.
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        resp = spaces_router.space_detail("Uni", _request("/spaces/Uni"), conn=conn)
        assert resp.context["page_label_scope"] == "Uni"
        assert "/quick/add?default_tab=task&amp;scope=Uni" in resp.body.decode()

    def test_space_with_no_children_shows_nothing(self, conn):
        db.upsert_label_config(conn, {"name": "Empty Space", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Empty Space"], "created_at": _now()})
        resp = spaces_router.space_detail("Empty Space", _request("/spaces/Empty Space"), conn=conn)
        assert resp.context["tasks"] == []

    def test_plain_label_page_shows_its_own_kanban_task_and_agenda_event(self, conn):
        # 2026-09-16 (direct request: "plain labels should generate pages
        # like projects, with agenda and kanban, not dashboards") -- a
        # plain label's page is no longer the widget-grid dashboard (no
        # more `is_space`/`tasks`/`events` context keys), it's the same
        # Kanban+Agenda shape a Project's page uses: a task tagged with
        # the label lands in its status column on the board, a future
        # event tagged with it lands in the Agenda list.
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "HW", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        future = (date.today() + timedelta(days=1)).isoformat()
        db.upsert_event(conn, {"uid": "e1", "title": "Lecture", "description": "", "status": "active",
                                "all_day": 0, "start_at": f"{future}T10:00:00", "tags": ["CS101"], "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert {t["uid"] for t in resp.context["columns"]["active"]} == {"t1"}
        assert {e["uid"] for e in resp.context["agenda_items"]} == {"e1"}

    def test_plain_label_page_shows_contacts_tagged_with_it(self, conn):
        # 2026-09-16 (direct request: "the same plain label page should
        # also show below the agenda and above the kanban a contacts list
        # widget filtered for that label") -- every contact directly
        # tagged with the label appears in `contacts`, rendered through
        # the same _widget_contact_list.html partial the Dashboard's own
        # Contact List widget uses. An untagged contact is excluded.
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Jane Doe", "tags": ["CS101"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c2", "full_name": "No Tag", "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert {c["uid"] for c in resp.context["contacts"]} == {"c1"}
        body = resp.body.decode()
        assert "Jane Doe" in body
        assert "No Tag" not in body

    def test_contacts_card_rows_show_avatar_and_open_in_a_modal(self, conn):
        # 2026-09-16 (direct follow-up request: "the contacts widget
        # should also contain the contact's photo and on click should
        # open a modal window, not a page") -- each row now leads with
        # deps.py's avatar() (initials-on-color fallback here, no photo
        # set) and the link carries data-modal instead of navigating away.
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "Jane Doe", "tags": ["CS101"], "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        body = resp.body.decode()
        assert 'href="/contacts/c1" data-modal' in body
        assert 'class="avatar-circle avatar-colored"' in body

    def test_plain_label_grouped_under_a_space_scopes_the_quick_add_link(self, conn):
        # Direct request: "the label selector should only have labels
        # from that group." A plain label with a parent Space passes its
        # own name as page_label_scope (db.label_selector_scope then
        # resolves that to the Space's other children).
        db.upsert_label_config(conn, {"name": "University", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "University", "created_at": _now()})
        resp = labels_router.label_detail("CS101", _request("/labels/CS101"), conn=conn)
        assert resp.context["page_label_scope"] == "CS101"
        # default_tab=label, not task -- this page's own active_tab is
        # "label" (base.html's _qa_defaults maps that to the Label tab).
        assert "/quick/add?default_tab=label&amp;scope=CS101" in resp.body.decode()

    def test_label_with_no_config_row_still_renders(self, conn):
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": ["adhoc"], "created_at": _now()})
        resp = labels_router.label_detail("adhoc", _request("/labels/adhoc"), conn=conn)
        assert resp.status_code == 200
        assert resp.context["label"]["color"] == "blue"  # default, sane


# --------------------------------------------------------------------- #
# dashboard_widgets.label_name
# --------------------------------------------------------------------- #


class TestDashboardWidgetsLabelName:
    def test_upsert_and_list_by_label_name(self, conn):
        db.upsert_dashboard_widget(
            conn, {"uid": "w1", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "label_name": "Uni"}
        )
        db.upsert_dashboard_widget(
            conn, {"uid": "w2", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "label_name": None}
        )
        assert [w["uid"] for w in db.list_dashboard_widgets(conn, label_name="Uni")] == ["w1"]
        assert [w["uid"] for w in db.list_dashboard_widgets(conn)] == ["w2"]

    def test_space_uid_project_uid_are_aliases_for_label_name(self, conn):
        # Backward-compat accessors -- both old param names collapse onto
        # the one label_name column now (Phase 2 item 4).
        db.upsert_dashboard_widget(
            conn, {"uid": "w1", "type": "today_agenda", "title": None, "config": {}, "position": 0.0,
                   "created_at": _now(), "project_uid": "CS101"}
        )
        widget = db.get_dashboard_widget(conn, "w1")
        assert widget["label_name"] == "CS101"
        assert widget["space_uid"] == "CS101"
        assert widget["project_uid"] == "CS101"
        assert [w["uid"] for w in db.list_dashboard_widgets(conn, space_uid="CS101")] == ["w1"]


# --------------------------------------------------------------------- #
# habits filter by label
# --------------------------------------------------------------------- #


class TestHabitsFilterByLabel:
    def test_habit_project_link_is_a_label(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        habits_router.create_habit(
            name="Study", description="", color="blue", icon="", target_per_day="1",
            tags="", project_uid="Uni", conn=conn,
        )
        habits_router.create_habit(
            name="Read", description="", color="blue", icon="", target_per_day="1",
            tags="", project_uid="", conn=conn,
        )
        scoped = db.list_habits(conn, project_uid="Uni")
        assert [h["name"] for h in scoped] == ["Study"]


# --------------------------------------------------------------------- #
# migrate_labels.py -- generate_space + habit/schedule_class
# backfill (Phase 2 extensions to the Phase 1 script)
# --------------------------------------------------------------------- #


class TestMigrationExtensions:
    def test_project_groups_migrate_with_generate_space_set(self, conn):
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO project_groups VALUES ('g1', 'University', 'orange', ?)", (_now(),))
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'purple', 'g1', ?, ?)", (_now(), _now()))
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        assert db.get_label_config(conn, "University")["generate_space"] == 1
        assert db.get_label_config(conn, "CS101")["generate_space"] == 0

    def test_habits_project_uid_backfilled_as_object_labels(self, conn):
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'blue', NULL, ?, ?)", (_now(), _now()))
        conn.execute("ALTER TABLE habits ADD COLUMN project_uid TEXT")
        conn.execute(
            "INSERT INTO habits (uid, name, description, color, target_per_day, project_uid, created_at, updated_at) "
            "VALUES ('h1', 'Study', '', 'blue', 1, 'p1', ?, ?)", (_now(), _now())
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        assert db.project_label_for(conn, "habit", "h1") == "CS101"
        # A project link is a real tag now (2026-08-06 correction) -- it
        # must show up in the habit's own `tags` list, not just the
        # derived `project_uid` view, or a Space page's aggregation would
        # never find this habit.
        assert "CS101" in db.get_habit(conn, "h1")["tags"]

    def test_schedule_classes_project_uid_backfilled_as_a_real_tag(self, conn):
        # 1.6 dropped `schedule_classes` from SCHEMA_SQL entirely (see
        # db.py's removal note) -- this test simulates a genuinely pre-1.6
        # database that still physically has the table on disk, which
        # migrate_labels.py's _PROJECT_LINKED_SOURCES still knows how to
        # read (that legacy migration path is unaffected by 1.6; it's
        # about *labels*, not about how a class is represented today).
        conn.execute(
            "CREATE TABLE schedule_classes (uid TEXT PRIMARY KEY, day TEXT, start_time TEXT, "
            "end_time TEXT, name TEXT, credits REAL, parity TEXT, enrolled INTEGER, created_at TEXT, updated_at TEXT)"
        )
        conn.execute("CREATE TABLE project_groups (uid TEXT PRIMARY KEY, name TEXT, color TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE projects (uid TEXT PRIMARY KEY, name TEXT, description TEXT, color TEXT, group_uid TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO projects VALUES ('p1', 'CS101', '', 'blue', NULL, ?, ?)", (_now(), _now()))
        conn.execute("ALTER TABLE schedule_classes ADD COLUMN project_uid TEXT")
        conn.execute(
            "INSERT INTO schedule_classes (uid, day, start_time, end_time, name, credits, parity, enrolled, project_uid, created_at, updated_at) "
            "VALUES ('c1', 'Monday', '09:00', '10:00', 'Algorithms', 6, 'all', 1, 'p1', ?, ?)", (_now(), _now())
        )
        conn.commit()

        result = migrate_labels.run_migration(conn)
        assert "collisions" not in result
        # A real tag, not the display-only pseudo-type habits/databases use.
        assert "CS101" in db.list_labels_for_object(conn, "schedule_class", "c1")


# --------------------------------------------------------------------- #
# scripts/migrate_spaces_direct_tags.py -- Spaces -- labels-as-membership
# rework slice 6 (2026-09-14, the last of the six slices): strips legacy
# direct Space-label tags left dead-but-visible by slice 3's aggregation
# change.
# --------------------------------------------------------------------- #


class TestMigrateSpacesDirectTags:
    def test_removes_a_direct_space_tag_from_a_task(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {"Uni": 1}, "total_removed": 1}
        assert db.list_labels_for_object(conn, "task", "t1") == []

    def test_removes_direct_space_tags_across_every_object_type(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_event(conn, {"uid": "e1", "title": "E", "description": "", "status": "active",
                                "all_day": 0, "tags": ["Uni"], "created_at": _now()})
        db.upsert_contact(conn, {"uid": "c1", "full_name": "C", "tags": ["Uni"], "created_at": _now()})
        # A habit's project_uid is folded into object_labels as a real tag
        # (db.py's _apply_tags_and_project) -- a direct Space-name project
        # link is exactly the same kind of legacy row this migration
        # targets, not a separate case to special-case.
        db.upsert_habit(conn, {"uid": "h1", "name": "H", "project_uid": "Uni", "created_at": _now(), "updated_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {"Uni": 4}, "total_removed": 4}
        assert db.list_labels_for_object(conn, "task", "t1") == []
        assert db.list_labels_for_object(conn, "event", "e1") == []
        assert db.list_labels_for_object(conn, "contact", "c1") == []
        assert db.project_label_for(conn, "habit", "h1") is None

    def test_leaves_child_label_tags_untouched(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "CS101", "parent_name": "Uni", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "Child", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        migrate_spaces_direct_tags.run_migration(conn)
        assert db.list_labels_for_object(conn, "task", "t1") == []
        assert db.list_labels_for_object(conn, "task", "t2") == ["CS101"]

    def test_leaves_a_plain_labels_own_direct_tags_untouched(self, conn):
        # Only generate_space=1 labels are in scope -- a plain/project
        # label's own direct tagging is real, intended usage (its own
        # page's whole scope), not legacy dead data.
        db.upsert_label_config(conn, {"name": "CS101", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active",
                               "tags": ["CS101"], "created_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {}, "total_removed": 0}
        assert db.list_labels_for_object(conn, "task", "t1") == ["CS101"]

    def test_dry_run_counts_without_writing(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn, dry_run=True)
        assert result == {"per_space_removed": {"Uni": 1}, "total_removed": 1}
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_idempotent_second_run_is_a_no_op(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "Direct", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        migrate_spaces_direct_tags.run_migration(conn)
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {}, "total_removed": 0}

    def test_multiple_spaces_reported_independently(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        db.upsert_label_config(conn, {"name": "Home", "generate_space": 1, "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "T1", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t2", "title": "T2", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        db.upsert_task(conn, {"uid": "t3", "title": "T3", "description": "", "status": "active",
                               "tags": ["Home"], "created_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {"Uni": 2, "Home": 1}, "total_removed": 3}

    def test_a_space_with_nothing_to_clean_is_omitted_from_the_report(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "created_at": _now()})
        result = migrate_spaces_direct_tags.run_migration(conn)
        assert result == {"per_space_removed": {}, "total_removed": 0}

    def test_label_group_column_is_left_alone(self, conn):
        # Slice 6's own scope note (open.md): label_group's now-unused
        # legacy text values are deliberately left alone -- nothing in
        # the UI reads them after slice 2.
        db.upsert_label_config(conn, {"name": "Uni", "generate_space": 1, "label_group": "Legacy", "created_at": _now()})
        db.upsert_task(conn, {"uid": "t1", "title": "T", "description": "", "status": "active",
                               "tags": ["Uni"], "created_at": _now()})
        migrate_spaces_direct_tags.run_migration(conn)
        assert db.get_label_config(conn, "Uni")["label_group"] == "Legacy"

    def test_cli_reports_no_database(self, conn, tmp_path, capsys):
        missing = tmp_path / "does-not-exist.sqlite"
        exit_code = migrate_spaces_direct_tags.main(["--db-path", str(missing)])
        assert exit_code == 0
        assert "nothing to migrate" in capsys.readouterr().out


# --------------------------------------------------------------------- #
# Sidebar Spaces (2026-08-08 -- nav rail, base.html/deps.py)
# --------------------------------------------------------------------- #
#
# 2026-08-08 follow-up: this used to be a TestPinnedSpaces class covering
# a separate opt-in "pin to sidebar" flag on top of generate_space --
# removed the same day, per direct feedback: a label worth turning into a
# Space is a label worth finding quickly, so a second manual step just to
# make it show up in the rail was friction with no real benefit. Every
# Space shows in the rail automatically now (db.list_space_labels,
# already covered by TestGeneratedSpacePage above) -- nothing left here
# to test that isn't already covered by the plain Space-page/rename/merge
# tests elsewhere in this file, or by db.list_space_labels' own use in
# deps.py.


# --------------------------------------------------------------------- #
# Abbreviations (2026-08-09 -- max-5-char synonym per label)
# --------------------------------------------------------------------- #


class TestLabelAbbreviation:
    def _set(self, name, abbreviation="", generate_space=""):
        return labels_router.set_label(
            name,
            color="blue",
            icon="",
            description="",
            parent_name="",
            generate_space=generate_space,
            abbreviation=abbreviation,
            conn=self.conn,
        )

    def _conn(self, conn):
        self.conn = conn

    def test_set_label_stores_abbreviation_and_effective_config_exposes_it(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        cfg = db.effective_label_config(conn, "University")
        assert cfg["abbreviation"] == "Uni"
        assert db.get_label_config(conn, "University")["abbreviation"] == "Uni"

    def test_set_label_truncates_longer_than_five_and_blank_clears(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Universitas")
        assert db.get_label_config(conn, "University")["abbreviation"] == "Unive"
        self._set("University", abbreviation="")
        assert db.get_label_config(conn, "University")["abbreviation"] is None

    def test_set_object_labels_resolves_abbreviation_to_full_name(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        db.upsert_task(conn, {"uid": "t1", "title": "X", "description": "", "status": "active",
                               "tags": [], "created_at": _now()})
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        # Stored as the full name, not a brand-new "Uni" label.
        assert db.list_labels_for_object(conn, "task", "t1") == ["University"]
        assert db.list_object_ids_for_label(conn, "task", "University") == ["t1"]

    def test_abbreviation_resolution_is_case_insensitive(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="uni")
        db.set_object_labels(conn, "task", "t1", ["UNI"])
        assert db.list_labels_for_object(conn, "task", "t1") == ["University"]

    def test_real_label_name_wins_over_an_abbreviation_collision(self, conn):
        # A genuine label literally named "Uni" (here: its own config row)
        # must not be rewritten just because another label abbreviated to
        # the same string.
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        db.upsert_label_config(conn, {"name": "Uni", "created_at": _now()})
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_duplicate_abbreviation_stays_inert(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni")
        self._set("Unified", abbreviation="Uni")
        db.set_object_labels(conn, "task", "t1", ["Uni"])
        # Ambiguous -- passed through as-is rather than guessing a label.
        assert db.list_labels_for_object(conn, "task", "t1") == ["Uni"]

    def test_list_space_labels_carries_abbreviation(self, conn):
        self._conn(conn)
        self._set("University", abbreviation="Uni", generate_space="1")
        spaces = db.list_space_labels(conn)
        assert [(s["name"], s["abbreviation"]) for s in spaces] == [("University", "Uni")]


class TestSystemLabelsExcludedFromThePicker:
    """2026-09-13 direct request: "the Birthday label should be hidden, as
    well for the habits one, because they are not intended to be applied
    by the user directly." Scoped (follow-up clarification) to the single
    choke point every "apply a label to this object" chip picker goes
    through -- db.list_tag_names_in_use (-> list_all_known_label_names) --
    not db.list_labels (Settings > Labels, still shows everything) or
    db.list_all_label_names (published-lists' own filter, also
    unaffected)."""

    def test_birthday_excluded_even_though_in_use(self, conn):
        db.set_object_labels(conn, "event", "e1", ["Birthday"])
        assert "Birthday" not in db.list_tag_names_in_use(conn)
        # The underlying "every label ever applied" list is untouched --
        # only the picker-facing function filters.
        assert "Birthday" in db.list_all_label_names(conn)

    def test_birthday_excluded_case_insensitively(self, conn):
        db.set_object_labels(conn, "event", "e1", ["birthday"])
        assert "birthday" not in db.list_tag_names_in_use(conn)

    def test_default_habit_label_excluded(self, conn):
        db.set_object_labels(conn, "task", "t1", ["Habit"])
        assert "Habit" not in db.list_tag_names_in_use(conn)

    def test_renamed_habit_label_is_excluded_not_the_old_default(self, conn):
        # habit_label is user-renameable (Settings) -- the exclusion must
        # track the LIVE configured value, not a hardcoded "Habit" string.
        db.save_task_habit_settings(conn, "Routines")
        db.set_object_labels(conn, "task", "t1", ["Routines", "Habit"])
        names = db.list_tag_names_in_use(conn)
        assert "Routines" not in names
        # "Habit" is no longer the configured habit label, so a real
        # object still tagged with it (e.g. before the rename) stays
        # visible/pickable like any other ordinary label.
        assert "Habit" in names

    def test_ordinary_labels_unaffected(self, conn):
        db.set_object_labels(conn, "task", "t1", ["Birthday", "Habit", "Focus"])
        assert db.list_tag_names_in_use(conn) == ["Focus"]


class TestSettingsLabelsTableSortOrder:
    """2026-09-13 direct request, last of a 9-item pre-v2.2.0 batch: "the
    label table inside settings should be sorted by Groups first, then by
    type (space first, then projects, then plain), then alphabetically."
    Was flat-alphabetical-by-name only (routers/labels.py::_labels_context
    used to override db.list_labels's own name-only sort with an
    identical one). No prior test asserted row order here.

    2026-09-14 (Spaces -- labels-as-membership rework slice 1): the sort's
    primary key moved from the old free-text `label_group` to the real
    `parent_name` FK -- `_label` below writes directly via
    db.upsert_label_config (bypassing the router's now-added "must name a
    real Space" validation), so the `group` param here is just an
    arbitrary string in `parent_name`, same as it always was in
    `label_group`; the sort itself doesn't validate what it points at."""

    def _label(self, conn, name, group="", role="none"):
        db.upsert_label_config(conn, {
            "name": name,
            "parent_name": group or None,
            "generate_space": 1 if role == "space" else 0,
            "is_project": 1 if role == "project" else 0,
            "created_at": _now(),
        })

    def _order(self, conn):
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        return [l["name"] for l in ctx["labels"]]

    def test_type_order_within_the_same_group_is_space_then_project_then_plain(self, conn):
        self._label(conn, "Zebra Project", group="Work", role="project")
        self._label(conn, "Alpha Space", group="Work", role="space")
        self._label(conn, "Middle Plain", group="Work", role="plain")
        assert self._order(conn) == ["Alpha Space", "Zebra Project", "Middle Plain"]

    def test_alphabetical_within_the_same_group_and_type(self, conn):
        self._label(conn, "Zebra", group="Work")
        self._label(conn, "Alpha", group="Work")
        self._label(conn, "Middle", group="Work")
        assert self._order(conn) == ["Alpha", "Middle", "Zebra"]

    def test_group_is_the_primary_sort_key_above_type_and_name(self, conn):
        # A plain label in an earlier (alphabetically) group sorts before
        # a Space-type label in a later group -- Group beats type/name.
        self._label(conn, "Owns the Zoo group", group="Zoo", role="plain")
        self._label(conn, "In Aardvark space", group="Aardvark", role="space")
        assert self._order(conn) == ["In Aardvark space", "Owns the Zoo group"]

    def test_manage_labels_route_renders_in_the_sorted_order(self, conn):
        # End-to-end through the actual route, not just the helper --
        # confirms the sort survives all the way to the template context.
        self._label(conn, "Zebra Project", group="Work", role="project")
        self._label(conn, "Alpha Space", group="Work", role="space")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        assert [l["name"] for l in resp.context["labels"]] == ["Alpha Space", "Zebra Project"]


class TestSettingsLabelsTableIconInsteadOfDot:
    """2026-09-14 direct request: "The table list of labels in settings
    should instead of colored dots have the label icon, and both the
    icon and string should be colored the label's color." Was a plain
    `.color-dot cal-*` + `.label-name` (default text color) pair in both
    labels_manage.html (initial page load) and _labels_table_body.html
    (async-CRUD region refresh, routers/labels.py's `/regions?region=list`)
    -- neither route had a test asserting the Name cell's own markup
    before this."""

    def _label(self, conn, name, color=None, icon_name=None):
        db.upsert_label_config(conn, {
            "name": name,
            "color": color or "blue",
            "icon": icon_name,
            "created_at": _now(),
        })

    def test_manage_page_renders_icon_not_color_dot(self, conn):
        self._label(conn, "Urgent", color="red", icon_name="alert-triangle")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert "color-dot" not in body
        assert "#icon-alert-triangle" in body
        # Both the icon wrapper and the name text carry the label's own
        # accent color, not a shared default. `data-style`, not `style=`
        # (2026-09-15 fix, see _labels_table_body.html's own header
        # comment) -- CSP's style-src silently drops a literal `style=`
        # attribute in a real browser; dynamic_styles.js applies
        # `data-style` via the CSSOM instead, which style-src doesn't
        # govern at all.
        assert 'class="label-cell-icon" data-style="color: var(--cal-accent-red)"' in body
        assert 'class="label-name" data-style="color: var(--cal-accent-red)">Urgent<' in body

    def test_manage_page_falls_back_to_tag_icon_when_none_configured(self, conn):
        # Same "always render *something*" behavior the old color-dot had
        # regardless of configuration -- "tag" is this page's own header
        # icon (page_header_narrow("Labels", "tag")), reused as the
        # generic per-row fallback.
        self._label(conn, "Plain Label")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert "#icon-tag" in body
        assert 'data-style="color: var(--cal-accent-blue)"' in body

    def test_async_region_fragment_matches_the_same_treatment(self, conn):
        self._label(conn, "Focus", color="purple", icon_name="target")
        resp = labels_router.labels_regions("list", _request("/settings/labels/regions"), conn=conn)
        body = resp.body.decode()
        assert "color-dot" not in body
        assert "#icon-target" in body
        assert 'class="label-cell-icon" data-style="color: var(--cal-accent-purple)"' in body
        assert 'class="label-name" data-style="color: var(--cal-accent-purple)">Focus<' in body


# --------------------------------------------------------------------- #
# Settings > Labels: one table per Space (Spaces -- labels-as-membership
# rework slice 2, 2026-09-14). `_labels_context` now also returns
# `label_groups` (one `{space, labels}` per generate_space=1 label,
# `labels` = the Space's own row + its children) and `ungrouped_labels`
# (everything else with no parent_name, Spaces themselves excluded --
# they head their own group instead). labels_manage.html/
# _labels_table_body.html render one `<table>` per group instead of the
# old single flat table + `label_group` text-badge column.
# --------------------------------------------------------------------- #


class TestSettingsLabelsGroupedTables:
    def _space(self, conn, name, color="blue", icon_name=None):
        db.upsert_label_config(conn, {
            "name": name, "generate_space": 1, "color": color, "icon": icon_name, "created_at": _now(),
        })

    def _label(self, conn, name, parent_name=None, color="blue"):
        db.upsert_label_config(conn, {
            "name": name, "parent_name": parent_name, "color": color, "created_at": _now(),
        })

    def test_label_groups_has_one_entry_per_space_with_its_own_row_first(self, conn):
        self._space(conn, "University")
        self._label(conn, "Homework", parent_name="University")
        self._label(conn, "Essay", parent_name="University")
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert len(ctx["label_groups"]) == 1
        group = ctx["label_groups"][0]
        assert group["space"]["name"] == "University"
        # Space's own row first (rank 0), then its plain-role children
        # alphabetically -- same (role_rank, name) order the flat
        # `labels` sort already establishes; this just filters it.
        assert [l["name"] for l in group["labels"]] == ["University", "Essay", "Homework"]

    def test_a_space_with_no_children_still_gets_its_own_group(self, conn):
        self._space(conn, "Empty Space")
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert len(ctx["label_groups"]) == 1
        assert [l["name"] for l in ctx["label_groups"][0]["labels"]] == ["Empty Space"]

    def test_space_groups_are_sorted_alphabetically_by_space_name(self, conn):
        self._space(conn, "Zebra Space")
        self._space(conn, "Aardvark Space")
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert [g["space"]["name"] for g in ctx["label_groups"]] == ["Aardvark Space", "Zebra Space"]

    def test_ungrouped_excludes_spaces_and_labels_with_a_real_parent(self, conn):
        self._space(conn, "University")
        self._label(conn, "Homework", parent_name="University")
        self._label(conn, "Loose Label")
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert [l["name"] for l in ctx["ungrouped_labels"]] == ["Loose Label"]

    def test_stale_parent_name_pointing_at_a_non_space_falls_back_to_ungrouped(self, conn):
        # A label whose parent_name names something that isn't (or no
        # longer is) a real Space -- e.g. a Space demoted back to a plain
        # label without the child being repointed -- shouldn't vanish.
        self._label(conn, "Not A Space")
        self._label(conn, "Orphaned Child", parent_name="Not A Space")
        ctx = labels_router._labels_context(conn, _request("/settings/labels"))
        assert ctx["label_groups"] == []
        assert {l["name"] for l in ctx["ungrouped_labels"]} == {"Not A Space", "Orphaned Child"}

    def test_manage_page_renders_a_single_table_with_no_repeated_headers(self, conn):
        # 2026-09-16 (direct request: "don't want the header repeated for
        # every group" / "don't want separate behavior for the labels
        # that are not assigned") -- replaces the old "one <table> per
        # Space plus a separate Ungrouped table" design with one table,
        # one <thead>, everything (Space rows, their children, and every
        # ungrouped label) in one <tbody>.
        self._space(conn, "University", color="teal")
        self._label(conn, "Homework", parent_name="University")
        self._label(conn, "Loose Label")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert body.count("<table") == 1
        assert body.count("<thead>") == 1
        assert 'data-label-group="University"' in body
        assert 'data-label-group=""' in body
        assert "Group" not in body.split("<thead>")[1].split("</thead>")[0]  # no Group column header
        assert 'name="label_group"' not in body

    def test_space_row_uses_a_plain_icon_not_a_colored_tile(self, conn):
        # 2026-09-16 (direct request: "the .label-icon-tile for spaces is
        # unnecessary, show only the icon like for any plain label") --
        # a Space's own row now renders its icon the same way any plain
        # label row does (.label-cell-icon, no .label-icon-tile squircle).
        # The row still reads as a "card" via a colored background/rounded
        # corners set through one `data-style` on the <tr> itself, per
        # `dynamic_styles.js`'s CSP-safe convention (2026-09-15 fix --
        # style-src silently drops a literal `style="..."` attribute in a
        # real enforcing browser, confirmed via headless-Chrome; this test
        # only proves the markup is right, not that a browser applies it).
        self._space(conn, "University", color="teal", icon_name="graduation-cap")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert "label-icon-tile" not in body
        assert 'class="labels-space-row"' in body
        assert 'data-style="--row-tint: var(--tag-teal-bg)"' in body
        assert "#icon-graduation-cap" in body
        # 2026-09-21, final word (direct report, all caps: "MAKE THEM THE
        # DEFAULT TEXT COLOR NOT STUPID COLORFUL TEXT THAT I CAN'T READ")
        # -- no per-span color at all on the Space row's own icon/name;
        # the tinted background alone carries the "this is University"
        # signal, colored text on top of it read badly.
        assert 'class="label-cell-icon">' in body
        assert 'class="label-name">University<' in body

    def test_add_label_row_always_present(self, conn):
        self._space(conn, "University")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/labels/new"' in body

    def test_empty_state_shows_when_truly_no_labels_or_spaces_exist(self, conn):
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert "No labels yet" in body

    def test_async_region_fragment_renders_the_same_single_table(self, conn):
        self._space(conn, "University")
        self._label(conn, "Homework", parent_name="University")
        resp = labels_router.labels_regions("list", _request("/settings/labels/regions"), conn=conn)
        body = resp.body.decode()
        assert body.count("<table") == 1
        assert 'data-label-group="University"' in body

    def test_space_and_its_children_are_editable_and_deletable_rows(self, conn):
        # The Space's own row (not just its children) keeps the same
        # Edit/Delete row_action_buttons every other label row has --
        # it's no longer reachable as a flat-table row, so this is its
        # only remaining path from this page.
        self._space(conn, "University")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert 'href="/settings/labels/University/edit"' in body
        assert 'action="/settings/labels/University/delete"' in body

    def test_actions_column_links_to_each_rows_own_generated_page(self, conn):
        # Direct request: "in the actions column, I would like a button
        # that allows the user to navigate to that label's page (either
        # it a space, project or plain label)."
        self._space(conn, "University")
        db.upsert_label_config(
            conn, {"name": "CS101", "is_project": 1, "parent_name": "University", "start_date": "2026-01-01", "end_date": "2026-12-31", "created_at": _now()}
        )
        self._label(conn, "Groceries")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert 'href="/spaces/University" class="icon-btn" title="Open label page"' in body
        assert 'href="/projects/CS101" class="icon-btn" title="Open label page"' in body
        assert 'href="/settings/labels/Groceries" class="icon-btn" title="Open label page"' in body

    def test_grouped_rows_get_the_tinted_background_ungrouped_rows_dont(self, conn):
        # Follow-up direct request -- first tried a colored left bar,
        # direct feedback "I don't like this, I like the background color
        # more": a row grouped under a Space now shares the exact same
        # tinted-background treatment (--row-tint) the Space's own row
        # gets, in the group's own (already Space-inherited) color. An
        # ungrouped label has no group color to link to, so it gets
        # neither the class nor the tint.
        self._space(conn, "University", color="green")
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "red", "created_at": _now()})
        self._label(conn, "Groceries")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        # "red" (Historiography's own stored color) never appears -- a
        # grouped row's l.color is already resolved to the Space's own
        # color (db.effective_label_config's _resolve_inherited_color).
        assert 'class="labels-child-row" data-style="--row-tint: var(--tag-green-bg)"' in body
        groceries_row = body.split('data-label-name="Groceries"')[0].rsplit("<tr", 1)[1]
        assert "labels-child-row" not in groceries_row

    def test_grouped_row_text_stays_the_default_color_not_a_tag_fg_pairing(self, conn):
        # Direct request, same-day follow-up: "the font color should be
        # the default one or one that contrasts with the bg color" --
        # --row-tint-fg (a small-pill-tuned color, read low-contrast at
        # full-row size) is gone; text/icon simply inherit the app's own
        # default color, no override at all.
        self._space(conn, "University", color="green")
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "red", "created_at": _now()})
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        assert "--row-tint-fg" not in body

    def test_grouped_rows_own_icon_name_have_no_color_override_ungrouped_still_do(self, conn):
        # Final word (direct report, all caps: "MAKE THEM THE DEFAULT
        # TEXT COLOR NOT STUPID COLORFUL TEXT THAT I CAN'T READ") -- a
        # grouped row's own tinted background already carries the color
        # signal; colored text on top of it read badly, so neither
        # _group_row's nor a grouped _label_row's icon/name spans get a
        # per-span data-style color at all. An ungrouped row has no tint
        # to clash with and keeps its pre-existing colored icon/name
        # unchanged.
        self._space(conn, "University", color="green")
        db.upsert_label_config(conn, {"name": "Historiography", "parent_name": "University", "color": "red", "created_at": _now()})
        self._label(conn, "Groceries", color="orange")
        resp = labels_router.manage_labels(_request("/settings/labels"), conn=conn)
        body = resp.body.decode()
        historiography_row = body.split('data-label-name="Historiography"')[1].split("</tr>")[0]
        assert "data-style" not in historiography_row.split("</td>")[1]  # the label-cell <td>
        groceries_row = body.split('data-label-name="Groceries"')[1].split("</tr>")[0]
        assert 'data-style="color: var(--cal-accent-orange)"' in groceries_row

    def test_only_the_space_row_is_bold(self):
        # Direct request: "remove the bold from labels that are not
        # spaces." .label-name's own base rule is font-weight:500, which
        # still read bold-ish at this row size/on a tinted background --
        # .labels-table scopes a plain 400 back in for every row, and
        # .labels-space-row's own pre-existing 600 override (declared
        # later in the cascade, same specificity) still wins for a
        # Space's own row specifically.
        css = (Path(__file__).resolve().parent.parent / "src" / "static" / "style.css").read_text()
        # font-weight tokenized 2026-09-24 (design-token-tightening slice);
        # --font-weight-regular/--font-weight-bold are still literal 400/600.
        assert ".labels-table .label-name{font-weight:var(--font-weight-regular);}" in css
        assert ".labels-space-row .label-name{font-weight:var(--font-weight-bold);}" in css
        table_rule_pos = css.index(".labels-table .label-name{font-weight:var(--font-weight-regular);}")
        space_rule_pos = css.index(".labels-space-row .label-name{font-weight:var(--font-weight-bold);}")
        assert table_rule_pos < space_rule_pos  # later wins at equal specificity

