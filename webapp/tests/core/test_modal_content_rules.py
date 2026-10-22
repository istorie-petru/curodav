"""Core tests for modal content: no checkboxes and no hint text inside a modal (frontend-conventions.md).

A modal template is one with a `modal-target`. MODAL_CHECKBOXES is the allow-list of templates that still hold a
checkbox (weekday picks and bulk-select rows); it only shrinks.
"""

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "templates"
MODAL_CHECKBOXES = {"habit_task_form.html", "settings_time_blocks.html", "settings_notebook.html", "taxonomy.html"}


def _modal_templates() -> dict[str, str]:
    return {p.name: p.read_text() for p in TEMPLATES.glob("*.html") if "modal-target" in p.read_text()}


def _offenders(markers: tuple[str, ...]) -> set[str]:
    return {name for name, text in _modal_templates().items() if any(m in text for m in markers)}


def test_no_modal_gains_a_checkbox():
    grown = _offenders(("checkbox_input(", 'type="checkbox"')) - MODAL_CHECKBOXES
    assert not grown, f"Modals may not contain checkboxes: {sorted(grown)}"


def test_no_modal_has_hint_text():
    """Hint text is allowed only in Settings entries; a hint never stands in for a label."""
    found = {name for name in _offenders(("field-hint", "settings-hint")) if not name.startswith("settings_")}
    assert not found, f"Modals may not contain hint text: {sorted(found)}"
