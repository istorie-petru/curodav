"""Floating menus and bars in the Notebook editor all close through one shared rule."""

from pathlib import Path

NOTEBOOK_JS = Path(__file__).resolve().parents[2] / "src" / "static" / "notebook"


def test_every_script_that_floats_a_menu_registers_it_with_the_shared_rule():
    offenders = []
    for path in sorted(NOTEBOOK_JS.glob("*.js")):
        text = path.read_text()
        floats = "document.body.appendChild(menu)" in text or 'className = "nbt-bar"' in text
        if floats and "NotebookFloating.open" not in text:
            offenders.append(path.name)
    assert not offenders, f"floating menus must register with NotebookFloating.open: {offenders}"
