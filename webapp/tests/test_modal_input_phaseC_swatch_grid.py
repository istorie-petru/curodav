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
        assert 'id="label-form"' in body
        assert 'form="label-form"' in body


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

