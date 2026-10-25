"""Core tests for the modal contract (rules/frontend-conventions.md): every modal template calls the `modal` macro from `_modal.html`,
sets no `footer_*` variable, and the macro keeps Back in the header, Cancel in the footer and Archive and Delete inside
the retire button. EXEMPT_PAGES lists the pages that also open as a modal (Settings pages, Taxonomy) and a few special
dialogs (widget and banner editors, flairs, citation filters); they keep their own layout and the old footer include.
"""

import re
from pathlib import Path

import pytest

from src.deps import templates

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "templates"
EXEMPT_PAGES = {
    "_widget_edit_modal.html",
    "banner_editor.html",
    "dashboard_customize.html",
    "notebook_citations_filters_modal.html",
    "notebook_citations_list.html",
    "settings_appearance.html",
    "settings_data_maintenance.html",
    "settings_flairs.html",
    "settings_general.html",
    "settings_notebook.html",
    "settings_notifications.html",
    "settings_university.html",
    "settings_your_profile.html",
    "taxonomy.html",
}


def _modal_templates() -> dict[str, str]:
    skip = {"base.html", "_modal.html"}
    return {p.name: p.read_text() for p in TEMPLATES.glob("*.html") if "modal-target" in p.read_text() and p.name not in skip}


def _render(kind, args=""):
    source = "{% from '_modal.html' import modal %}{% call modal(kind='" + kind + "', title='T'" + (", " + args if args else "") + ") %}BODY{% endcall %}"
    return templates.env.from_string(source).render()


def _footer(html):
    return html.split('<div class="modal-footer">')[1]


def test_every_modal_calls_the_macro():
    bare = {n for n, t in _modal_templates().items() if "import modal " not in t}
    assert bare - EXEMPT_PAGES == set(), f"Modals must call the modal macro: {sorted(bare - EXEMPT_PAGES)}"
    assert EXEMPT_PAGES - bare == set(), f"Migrated, remove from the exempt list: {sorted(EXEMPT_PAGES - bare)}"


def test_no_migrated_modal_sets_footer_variables():
    offenders = {n for n, t in _modal_templates().items() if re.search(r"set footer_", t)} - EXEMPT_PAGES
    assert offenders == set(), f"Migrated modals may not set footer_* variables: {sorted(offenders)}"


def test_unknown_kind_or_size_is_refused():
    with pytest.raises(ValueError):
        _render("dialog")
    with pytest.raises(ValueError):
        _render("form", "size='huge'")


def test_back_only_in_header_and_cancel_only_in_footer():
    html = _render("form", "back='/x', back_name='X', form='f'")
    header, footer = html.split('<div class="modal-footer">')
    assert "modal-header-back" in header and "Cancel" not in header
    assert "modal-header-back" not in footer and "Cancel" in footer
    assert "modal-header-back" not in _render("form", "form='f'")


def test_view_has_done_and_no_cancel():
    footer = _footer(_render("view", "edit_url='/e'"))
    assert "Done" in footer and "Cancel" not in footer and "Edit" in footer


def test_archive_and_delete_only_inside_the_retire_button():
    retire = "retire=[{'action': 'archive', 'url': '/a', 'restore_url': '/r'}, {'action': 'delete', 'url': '/d', 'mode': 'confirm', 'label': 'x'}]"
    footer = _footer(_render("form", "form='f', " + retire))
    before, menu = footer.split("modal-retire")
    assert "Archive" in menu and "Delete" in menu
    assert "Archive" not in before and "Delete" not in before


def test_single_retire_action_opens_no_menu():
    html = _render("form", "form='f', retire=[{'action': 'delete', 'url': '/d', 'mode': 'confirm', 'label': 'x'}]")
    assert "modal-retire" not in html and 'aria-label="Delete"' in html


def test_split_primary_never_holds_a_destructive_action():
    html = _render("form", "form='f', save_options=[{'label': 'Save all', 'icon': 'check-square', 'form': 'f', 'name': 'scope', 'value': 'all'}]")
    split = html.split("btn-split-more")[1]
    assert "Delete" not in split and "Archive" not in split


def test_a_question_has_no_save_button():
    assert 'type="submit"' not in _render("question", "form='f'")


def test_footer_slots_keep_their_order():
    """Cancel or Done first, the retire button next, the spacer, then extras, and the primary last."""
    retire = "retire=[{'action': 'delete', 'url': '/d', 'mode': 'confirm', 'label': 'x'}]"
    footer = _footer(_render("form", "form='f', extra_html='<a class=\"btn ghost\">Open</a>', " + retire))
    positions = [footer.index(m) for m in ("Cancel", 'aria-label="Delete"', 'class="spacer"', "Open", 'class="btn primary"')]
    assert positions == sorted(positions)
    assert footer.rstrip().endswith("</div>\n</div>") or footer.index('class="btn primary"') > footer.index("Open")


def test_cancel_and_done_carry_no_icon():
    for kind in ("form", "pick", "question", "view", "manage"):
        footer = _footer(_render(kind, "form='f', edit_url='/e'"))
        first = footer.split("</a>")[0]
        assert "icon" not in first, kind


def test_a_form_says_create_for_a_new_object_and_save_for_an_existing_one():
    assert "Create" in _footer(_render("form", "form='f', creating=true")) and "Save" not in _footer(_render("form", "form='f', creating=true"))
    assert "Save" in _footer(_render("form", "form='f'"))
    assert "Merge" in _footer(_render("pick", "form='f', save_label='Merge'"))
