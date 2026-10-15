"""Core tests for the search, input and modal rules (rules/frontend-conventions.md).

- One search box: every search or add box is the `search_input` macro in
  `_inputs.html` (script-built ones go through `CCSearchField.wrap`), so the
  magnifier, the look and the aria-label are never rebuilt by hand.
- No native browser controls: no `<select>`, `<datalist>` or native date, time,
  colour or range input, in a template or in a script. A choice is the custom
  dropdown, a date or time is the date and time field.
- No placeholder text in a script-built input (Settings entries are the only
  place hint text lives).
- Every modal is header, body and footer: a template with a modal body has a
  header and the shared footer, and a script-built dialog builds all three.
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
TEMPLATES_DIR = SRC_DIR / "templates"
STATIC_DIR = SRC_DIR / "static"
_COMMENTS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)
_JS_COMMENTS = re.compile(r"/\*.*?\*/|(?<![:\"'])//[^\n]*", re.S)

# Where a native control may still appear (none today).
NATIVE_CONTROL_TEMPLATES: set[str] = set()
# A script that sets a placeholder, with the reason: the typed phrase of the
# reset-database confirm sheet (a Settings action) is its only hint.
PLACEHOLDER_SCRIPTS = {"toast.js"}
# Templates with a modal body that are not themselves a modal.
NOT_A_MODAL = {"base.html"}


def _templates():
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        yield path.name, _COMMENTS.sub("", path.read_text(encoding="utf-8"))


def _scripts():
    for path in sorted(STATIC_DIR.rglob("*.js")):
        if "vendor" in path.parts:
            continue
        yield path.relative_to(STATIC_DIR).as_posix(), _JS_COMMENTS.sub("", path.read_text(encoding="utf-8"))


def test_search_boxes_are_only_built_by_the_search_component():
    offenders = []
    for name, text in _templates():
        if name == "_inputs.html":
            continue
        if "search-field" in text:
            offenders.append(f"{name}: hand-built search-field")
        if re.search(r"""type\s*=\s*["']search["']|\},\s*'search'\)""", text):
            offenders.append(f"{name}: native type=search")
        if re.search(r"text_input\(\{[^}]*(?i:search)[^}]*\}", text):
            offenders.append(f"{name}: a search box built with text_input")
    assert not offenders, f"Use search_input from _inputs.html: {offenders}"


def test_script_built_search_boxes_use_the_search_wrapper():
    offenders = []
    for name, text in _scripts():
        if name == "search_field.js":
            continue
        builds_input = 'createElement("input")' in text or "createElement('input')" in text
        labelled_search = re.search(r"""aria-label["']\s*,\s*["'](?:Search|Link to)""", text)
        if builds_input and labelled_search and "CCSearchField.wrap" not in text:
            offenders.append(name)
    assert not offenders, f"Wrap script-built search inputs with CCSearchField.wrap: {offenders}"


def test_no_native_select_datalist_or_picker_inputs_in_templates():
    native = re.compile(
        r"<select\b|<datalist\b|select_input|"
        r"""type\s*=\s*["']?(?:date|time|datetime-local|month|week|color|range)\b|"""
        r"""type\s*=\s*['"](?:date|time|datetime-local|month|week|color|range)['"]|"""
        r"""\},\s*['"](?:date|time|datetime-local|month|week|color|range)['"]\)"""
    )
    offenders = sorted(name for name, text in _templates() if name not in NATIVE_CONTROL_TEMPLATES and native.search(text))
    assert not offenders, f"Native controls are not allowed (custom dropdown, date and time fields): {offenders}"


def test_no_native_controls_built_by_scripts():
    native = re.compile(
        r"""createElement\(["'](?:select|datalist)["']\)|<select\b|<datalist\b|"""
        r"""\.type\s*=\s*["'](?:date|time|datetime-local|month|week|color|range)["']|"""
        r"""type=["'](?:date|time|datetime-local|month|week|color|range)["']"""
    )
    offenders = sorted(name for name, text in _scripts() if native.search(text))
    assert not offenders, f"Scripts must not build native controls: {offenders}"


def test_scripts_do_not_set_placeholder_text():
    placeholder = re.compile(r"""\.placeholder\s*=|placeholder=["']""")
    offenders = sorted(
        name for name, text in _scripts() if placeholder.search(text) and name not in PLACEHOLDER_SCRIPTS
    )
    assert not offenders, f"Use an aria-label, not placeholder text: {offenders}"


def test_every_modal_template_has_a_header_and_a_footer():
    offenders = []
    for name, text in _templates():
        if name in NOT_A_MODAL or 'class="modal-body"' not in text:
            continue
        if 'class="modal-header"' not in text:
            offenders.append(f"{name}: no modal-header")
        if '{% include "_modal_footer.html" %}' not in text and 'class="modal-footer"' not in text:
            offenders.append(f"{name}: no modal footer")
    assert not offenders, f"Modals are header, body and footer: {offenders}"


def test_script_built_modals_have_a_footer():
    offenders = []
    for name, text in _scripts():
        if name == "modal.js":
            continue
        builds_modal = 'createElement("dialog")' in text or "CCModal.openCustom(" in text
        if builds_modal and "modal-footer" not in text and "CCModal.footer(" not in text:
            offenders.append(name)
    assert not offenders, f"A script-built modal needs a footer (CCModal.footer): {offenders}"


def test_modal_input_rows_never_wrap():
    css = re.sub(r"/\*.*?\*/", "", (STATIC_DIR / "style.css").read_text(encoding="utf-8"), flags=re.S)
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    wrapping = [sel.strip() for sel, body in rules if "flex-wrap:wrap" in body.replace(" ", "") and ".modal-body" in sel]
    assert not wrapping, f"Modal rows must not wrap: {wrapping}"
    nowrap = [sel for sel, body in rules if ".modal-body" in sel and "flex-wrap:nowrap" in body.replace(" ", "")]
    assert nowrap and all(row in nowrap[0] for row in (".contact-multi-row", ".work-session-edit-fields"))


def test_archive_button_lives_only_in_the_edit_footer():
    offenders = []
    for name, text in _templates():
        if name in {"_modal_footer.html", "_icons_sprite.html"}:
            continue
        if re.search(r"""action="[^"]*/(un)?archive\b[^"]*"[^>]*>\s*<button[^>]*class="btn""", text):
            offenders.append(name)
    assert not offenders, f"Archive is an icon-only footer button (footer_archive_url): {offenders}"


def test_empty_states_are_only_built_by_the_empty_state_component():
    """An empty list, page or dropdown uses `empty_state`, so its icon, title and action look the same everywhere."""
    offenders = [
        name
        for name, text in _templates()
        if name not in ("_empty_state.html", "_empty_state_row.html") and re.search(r'class="(?:[^"]*\s)?empty-state[\s"]', text)
    ]
    assert not offenders, f"hand-built empty state in: {offenders}; use the empty_state macro"


def test_scripts_build_empty_states_only_with_the_shared_helper():
    """A script that shows "nothing here" calls `ccEmptyState`, the script-built twin of the macro."""
    offenders = [
        name
        for name, text in _scripts()
        if re.search(r"className\s*=\s*[\"'][^\"']*(?:empty-state|-empty)[\"']", text)
    ]
    assert not offenders, f"hand-built empty state in: {offenders}; use window.ccEmptyState"


def _dropdown_html(template: str, count: int) -> str:
    from src.deps import templates

    if template == "_filter_dropdown.html":
        context = {"fd_name": "x", "fd_label": "Thing", "fd_items": [{"value": str(i), "name": f"Item {i}"} for i in range(count)], "fd_selected": []}
    else:
        context = {"ms_name": "x", "ms_label": "Thing", "ms_items": [{"uid": str(i), "name": f"Item {i}"} for i in range(count)], "ms_selected": []}
    return templates.env.get_template(template).render(**context)


def test_a_dropdown_gets_its_search_box_only_above_seven_items():
    """Seven items fit on screen without searching; more than seven need the search box, with no per-site flag."""
    for template in ("_filter_dropdown.html", "_widget_list_multiselect.html"):
        assert "multiselect-search-input" not in _dropdown_html(template, 7), template
        assert "multiselect-search-input" in _dropdown_html(template, 8), template


def test_there_is_only_one_modal_window_so_modals_never_nest():
    """base.html owns the one modal overlay; a template or script that builds its own would nest a window over a window."""
    own_overlay = re.compile(r"""(?:id|class)=["'][^"']*modal-(?:overlay|dialog)|className\s*=\s*["'][^"']*modal-(?:overlay|dialog)""")
    offenders = [name for name, text in _templates() if name != "base.html" and own_overlay.search(text)]
    offenders += [name for name, text in _scripts() if own_overlay.search(text)]
    assert not offenders, f"builds its own modal window: {offenders}"

# Each canonical row's own markup, and the one template that may contain it.
CANONICAL_ROW_MARKUP = {
    "look-trigger": "_look_picker.html",
    "look-panel": "_look_picker.html",
    "recurrence-input": "_form_rows.html",
    "reminders-input": "_form_rows.html",
}


def test_canonical_rows_are_only_built_by_their_macro():
    """The look picker, recurrence and reminder rows are written once, so a hand-built copy cannot drift from them."""
    offenders = [
        f"{name} ({marker})"
        for name, text in _templates()
        for marker, owner in CANONICAL_ROW_MARKUP.items()
        if name != owner and re.search(rf'class="[^"]*\b{marker}\b', text)
    ]
    assert not offenders, f"hand-built canonical row: {offenders}"
