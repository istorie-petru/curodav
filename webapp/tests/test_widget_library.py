"""Tests for the shared widget-body component library (_widget_items.html).

2026-08-17 widget uniformity pass -- see features/design-system.md's
"Widget bodies" section and plans/STATE.md. The visual dashboard widgets
used to hand-roll the same row / pill / stat / empty-state / filled-card
markup with small differences (a bare `.cell-tag` with no color class
rendered as a transparent pill, three arbitrary fixed-width time columns,
inconsistent empty-state markup); they now compose those pieces from one
library. These structural tests lock the convention so a future widget that
reintroduces a hand-rolled variant fails CI instead of waiting for another
manual audit -- the same grep-the-templates sweep style as
test_modal_uniformization.py's TestFullAppModalSweep (no browser in this
test environment, same ceiling the app's other CSS-shape tests accept)."""

import pathlib
import re

VISUAL_WIDGETS = [
    "_widget_agenda.html",
    "_widget_at_a_glance.html",
    "_widget_contact_list.html",
    "_widget_habit_checkin.html",
    "_widget_mini_month_calendar.html",
    "_widget_scheduled_work_today.html",
    "_widget_spaces_projects.html",
    "_widget_weekly_schedule.html",
]

# Widgets whose body genuinely uses none of the shared pieces -- a pure
# custom layout that already renders inside the shared card chrome
# (_widget_inner.html), so importing the body library would be dead code.
NO_IMPORT_ALLOWLIST = {"_widget_mini_month_calendar.html"}

# The one legit `.cell-tag` use in a widget body: Spaces & Projects' list
# style project pill is a `.cell-tag.cal-*` swatch -- the label's own
# identity color (UI guide §6's allowed identity palette), a genuinely
# different kind of chip from a status pill. Documented at the top of
# _widget_spaces_projects.html.
CELL_TAG_ALLOWLIST = {"_widget_spaces_projects.html"}


def _read(name):
    templates = pathlib.Path(__file__).resolve().parents[1] / "src" / "templates"
    return (templates / name).read_text()


class TestWidgetsComposeTheLibrary:
    def test_every_visual_widget_imports_the_library(self):
        for name in VISUAL_WIDGETS:
            if name in NO_IMPORT_ALLOWLIST:
                continue
            assert '{% from "_widget_items.html" import' in _read(name), (
                f"{name} doesn't import the shared widget library"
            )

    def test_no_hand_rolled_empty_state_or_section_label(self):
        for name in VISUAL_WIDGETS:
            text = _read(name)
            assert '<div class="empty-state"' not in text, (
                f"{name} hand-rolls an empty state instead of widget_empty()"
            )
            assert '<div class="widget-section-label">' not in text, (
                f"{name} hand-rolls a section label instead of widget_section_label()"
            )

    def test_no_hand_rolled_status_pill(self):
        for name in VISUAL_WIDGETS:
            if name in CELL_TAG_ALLOWLIST:
                continue
            text = _read(name)
            assert "class=\"cell-tag" not in text and "cell-tag " not in text, (
                f"{name} hand-rolls a .cell-tag pill instead of widget_pill()"
            )

    def test_no_hand_rolled_row_styles(self):
        # widget_link_row's leading/right cells use the .widget-row-* classes
        # instead of inline fixed widths / text-align (the audit's clearest
        # "hand-rolled where a class should be" signal). The spaces_projects
        # progress bar's `style="width:{{ ... }}%"` is a dynamic value, not a
        # fixed column, so only flag fixed pixels / text-align.
        for name in VISUAL_WIDGETS:
            text = _read(name)
            assert not re.search(r'style="(?:width:\s*\d|text-align:right)', text), (
                f"{name} hand-rolls a cell width/alignment instead of a .widget-row-* class"
            )


class TestLibraryItself:
    def test_pill_family_covers_the_full_identity_palette(self):
        # widget_pill can be called with any of the 16 identity colors; the
        # .pill-* family must exist for all of them (completed 2026-08-17 --
        # the old 7-color pill family made e.g. a pink pill render bare).
        css = pathlib.Path(__file__).resolve().parents[1] / "src" / "static" / "style.css"
        css_text = css.read_text()
        for color in ["gray", "orange", "green", "blue", "red", "purple", "yellow",
                      "brown", "pink", "lime", "mint", "teal", "cyan", "indigo",
                      "magenta", "slate"]:
            assert f".pill-{color}{{" in css_text, f"missing .pill-{color}"

    def test_library_macros_exist(self):
        lib = pathlib.Path(__file__).resolve().parents[1] / "src" / "templates" / "_widget_items.html"
        text = lib.read_text()
        for macro in ["widget_empty", "widget_section_label", "widget_pill",
                      "stat_block", "filled_card", "widget_link_row",
                      "relative_due", "widget_complete_button"]:
            assert ("{% macro " + macro + "(") in text, f"missing {macro} macro"
