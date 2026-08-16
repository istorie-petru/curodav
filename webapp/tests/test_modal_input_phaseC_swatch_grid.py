"""Tests for modal-input-design Phase C: reviving the dormant
`.color-picker`/`.icon-picker` swatch-grid popover (built once for the
pre-rework calendars/projects pages, then orphaned when those templates
were deleted -- see features/design-system.md §1 pattern 3) into
habit_form.html (color select + free-text emoji icon input) and
labels_manage.html (originally a per-row color select; 2026-08-15 side
work moved it into the label edit modal instead -- see
label_edit_modal.html and routers/labels.py::edit_label_modal). label_
detail.html's own inline "Edit label" form once offered the same pickers
but was removed (the edit modal is the one place to edit a label now).

Markup-shape assertions mirror test_modal_input_phaseB_chip_multiselect.py's
own style: assert the old plain `<select name="...">`/free-text-input shape
is gone and the new `.color-picker`/`.icon-picker` radio-grid markup is
present, then separately assert the router-level create/edit flows still
store whichever value was picked.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from src import db
from src.routers import habits as habits_router
from src.routers import labels as labels_router


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request(path="/", query_string=b""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string,
            "scheme": "http",
            "server": ("testserver", 80),
            "root_path": "",
            "headers": [],
        }
    )


def _seed_habit(conn, uid, **overrides):
    row = {"uid": uid, "name": uid, "color": "blue", "target_per_day": 1, "created_at": _now(), "updated_at": _now()}
    row.update(overrides)
    db.upsert_habit(conn, row)
    return db.get_habit(conn, uid)


class TestHabitFormRendersSwatchGridNotSelectOrTextInput:
    def test_new_habit_form_has_color_and_icon_pickers(self, conn):
        resp = habits_router.new_habit_form(_request("/habits/new"), conn=conn)
        body = resp.body.decode()
        assert '<select name="color">' not in body
        assert 'class="project-icon-input"' not in body
        assert 'class="color-picker"' in body
        assert 'class="icon-picker"' in body
        # Every color/icon radio still submits with the real "habit-form".
        assert 'form="habit-form"' in body

    def test_edit_habit_form_preselects_current_color_and_icon(self, conn):
        _seed_habit(conn, "h1", color="purple", icon="star")
        resp = habits_router.edit_habit_form("h1", _request("/habits/h1/edit"), conn=conn)
        body = resp.body.decode()
        assert 'color-swatch-current cal-purple' in body
        assert 'value="purple" class="color-swatch cal-purple"' in body
        assert 'value="star" class="icon-swatch" checked' in body


class TestHabitCreateEditStoresColorAndIcon:
    def test_create_habit_with_color_and_icon(self, conn):
        habits_router.create_habit(
            name="Read", description="", color="green", icon="book-open",
            target_per_day="1", tags="", project_uid="", conn=conn,
        )
        habit = next(h for h in db.list_habits(conn) if h["name"] == "Read")
        assert habit["color"] == "green"
        assert habit["icon"] == "book-open"

    def test_edit_habit_updates_color_and_icon(self, conn):
        uid = _seed_habit(conn, "h1", color="blue", icon=None)["uid"]
        habits_router.edit_habit(
            uid, name="h1", description="", color="orange", icon="target",
            target_per_day="1", tags="", project_uid="", conn=conn,
        )
        habit = db.get_habit(conn, uid)
        assert habit["color"] == "orange"
        assert habit["icon"] == "target"


class TestLabelsManageRowRendersSwatchGridNotSelect:
    """2026-08-15 side work moved every per-label editing control (Color/
    Icon included) off the manage list's own rows and into the label edit
    modal (label_edit_modal.html, routers/labels.py::edit_label_modal) --
    the list itself is now read-only display + an Edit button. These
    assertions moved with it: the manage page (`manage_labels`) no longer
    renders any picker at all, and the modal's own single Save form (id
    `label-edit-form`) is what the color/icon radios' `form="..."` now
    points at, not a per-row `label-set-...` id (there's only ever one
    form per modal, not one per table row)."""

    def test_manage_page_has_no_color_picker_at_all(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        resp = labels_router.manage_labels(_request("/labels"), conn=conn)
        body = resp.body.decode()
        assert '<select name="color" class="filter-select"' not in body
        assert 'class="color-picker"' not in body

    def test_edit_modal_has_color_picker_not_select(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        resp = labels_router.edit_label_modal("Uni", _request("/labels/Uni/edit"), conn=conn)
        body = resp.body.decode()
        assert '<select name="color" class="filter-select"' not in body
        assert 'class="color-picker"' in body
        assert 'color-swatch-current cal-blue' in body

    def test_edit_modal_color_radio_form_attr_matches_the_one_edit_form(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "green", "created_at": _now()})
        resp = labels_router.edit_label_modal("Uni", _request("/labels/Uni/edit"), conn=conn)
        body = resp.body.decode()
        # The radio's form="..." must reference an id that actually exists
        # on the page (the picker's grid gets reparented out to
        # #color-popover on open, and only the explicit form="" attribute
        # keeps it part of the real form's submission).
        assert 'id="label-edit-form"' in body
        assert 'form="label-edit-form"' in body


class TestLabelsManageRowColorAutoSubmit:
    def test_set_label_color_via_router(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        labels_router.set_label(
            name="Uni", color="pink", icon="", description="", parent_name="",
            generate_space="", return_to="", conn=conn,
        )
        cfg = db.get_label_config(conn, "Uni")
        assert cfg["color"] == "pink"


class TestLabelDetailInlineEditStoresColorAndIcon:
    def test_set_label_from_inline_edit_form(self, conn):
        db.upsert_label_config(conn, {"name": "CS101", "color": "blue", "created_at": _now()})
        labels_router.set_label(
            name="CS101", color="purple", icon="star", description="", parent_name="",
            generate_space="", return_to="/labels/CS101", conn=conn,
        )
        cfg = db.get_label_config(conn, "CS101")
        assert cfg["color"] == "purple"
        assert cfg["icon"] == "star"


class TestExpandedPaletteAndGroupedIcons:
    """2026-08-08 -- direct feedback: "more colors options (16) with small
    label under each color. also more icons grouped into very usefull
    icons." COLORS grew from 8 to 16 (routers/labels.py); LABEL_ICONS grew
    from ~100 to 138 and is now sourced from ICON_GROUPS, a dict of named
    categories, rather than one flat list. Both shared swatch pickers
    (_color_swatch_picker.html/_icon_swatch_picker.html) render the new
    shape; habits.py imports the same COLORS/ICON_GROUPS rather than
    keeping its own separate copies."""

    def test_colors_has_sixteen_entries_no_duplicates(self):
        assert len(labels_router.COLORS) == 16
        assert len(set(labels_router.COLORS)) == 16

    def test_icon_groups_flatten_to_label_icons_with_no_duplicates_or_gaps(self):
        flattened = [name for group in labels_router.ICON_GROUPS.values() for name in group]
        assert flattened == labels_router.LABEL_ICONS
        assert len(labels_router.LABEL_ICONS) == len(set(labels_router.LABEL_ICONS))
        assert len(labels_router.LABEL_ICONS) > 130

    def test_every_icon_exists_in_the_sprite(self):
        import re
        from pathlib import Path

        sprite = Path("src/templates/_icons_sprite.html").read_text()
        sprite_ids = set(re.findall(r'id="icon-([a-z0-9-]+)"', sprite))
        missing = set(labels_router.LABEL_ICONS) - sprite_ids
        assert not missing, f"icons referenced but not in the sprite: {missing}"

    def test_label_edit_modal_shows_all_sixteen_colors_with_names(self, conn):
        # Moved off the manage-list page onto the edit modal, 2026-08-15
        # side work -- see TestLabelsManageRowRendersSwatchGridNotSelect's
        # own class docstring above.
        db.upsert_label_config(conn, {"name": "Uni", "color": "teal", "created_at": _now()})
        resp = labels_router.edit_label_modal("Uni", _request("/labels/Uni/edit"), conn=conn)
        body = resp.body.decode()
        assert body.count('class="color-swatch-label"') == 16
        for name in ("Red", "Lime", "Mint", "Teal", "Cyan", "Indigo", "Magenta", "Brown", "Slate"):
            assert f">{name}<" in body

    def test_label_edit_modal_groups_icons_with_headers(self, conn):
        db.upsert_label_config(conn, {"name": "Uni", "color": "blue", "created_at": _now()})
        resp = labels_router.edit_label_modal("Uni", _request("/labels/Uni/edit"), conn=conn)
        body = resp.body.decode()
        for group_name in labels_router.ICON_GROUPS:
            escaped = group_name.replace("&", "&amp;")
            assert f'<div class="icon-group-label">{escaped}</div>' in body

    def test_habit_form_shows_all_sixteen_colors_from_the_shared_partial(self, conn):
        # label_detail.html's own copy of this picker is gone (its inline
        # "Edit label" form was removed; the manage page /labels is the one
        # place to edit a label now) -- habit_form.html is the remaining
        # non-manage-page consumer of the shared 16-color partial.
        habit_resp = habits_router.new_habit_form(_request("/habits/new"), conn=conn)
        habit_body = habit_resp.body.decode()
        assert habit_body.count('class="color-swatch-label"') == 16
        for group_name in habits_router.ICON_GROUPS:
            escaped = group_name.replace("&", "&amp;")
            assert f'<div class="icon-group-label">{escaped}</div>' in habit_body

    def test_habits_colors_and_icon_groups_are_imported_not_duplicated(self):
        assert habits_router.COLORS is labels_router.COLORS
        assert habits_router.ICON_GROUPS is labels_router.ICON_GROUPS
