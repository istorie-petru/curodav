"""Core tests for template rules: a computed style value goes through
`data-style` (the CSP drops a literal `style="...{{ }}"`), and every modal
template routes its footer through the shared partial."""

import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
TEMPLATES_DIR = SRC_DIR / "templates"
DYNAMIC_STYLE_ATTR = re.compile(r'(?<!data-)style="[^"]*\{\{')

MODAL_TEMPLATES = [
    "contact_detail.html", "contact_form.html", "event_detail.html", "event_form.html",
    "habit_task_form.html", "label_merge_modal.html", "quick_add.html", "task_detail.html",
    "task_form.html", "banner_editor.html", "_widget_edit_modal.html",
    "_modal_widget_customize.html", "settings_flairs.html",
]


def test_no_template_uses_a_literal_style_attribute_for_a_computed_value():
    offenders = []
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        text = path.read_text()
        for match in DYNAMIC_STYLE_ATTR.finditer(text):
            offenders.append(f"{path.name}:{text.count(chr(10), 0, match.start()) + 1}")
    assert offenders == [], f"Use data-style for computed values: {offenders}"


def test_python_built_markup_uses_data_style_for_the_avatar_swatch():
    source = (SRC_DIR / "deps.py").read_text()
    assert re.search(r'(?<!data-)style="--tile-swatch:', source) is None


def test_every_modal_template_includes_the_shared_footer():
    missing = [
        name for name in MODAL_TEMPLATES
        if '{% include "_modal_footer.html" %}' not in (TEMPLATES_DIR / name).read_text()
    ]
    assert missing == [], f"Not using the shared footer partial: {missing}"
