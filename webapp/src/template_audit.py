"""Template audit behind the input core tests (rules/frontend-conventions.md,
Inputs). It lists, per template, the bare form controls (every non-hidden
`input`, `select` and `textarea`, since the named components do not exist as
macros yet) and every `placeholder=` attribute, ignoring comments."""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
# Templates that implement a named component (the inputs, the form rows, the
# upload zone, the multiselect and its filter variant, the look picker and the
# date and time fields). Their markup is the component, so it is not counted.
COMPONENTS = {
    "_inputs.html", "_form_rows.html", "_upload_zone.html",
    "_widget_list_multiselect.html", "_filter_dropdown.html", "_look_picker.html",
    "_date_time_fields.html",
}
_COMMENTS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.S)
_CONTROL = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.S)


def _strip(text: str) -> str:
    return _COMMENTS.sub("", text)


def audit() -> dict[str, dict[str, int]]:
    """{template: {"controls": n, "placeholders": n}} for templates with any."""
    found = {}
    for path in sorted(TEMPLATES.glob("*.html")):
        if path.name in COMPONENTS:
            continue
        text = _strip(path.read_text(encoding="utf-8"))
        controls = placeholders = 0
        for tag, attrs in _CONTROL.findall(text):
            if tag == "input" and re.search(r"""type\s*=\s*["']hidden["']""", attrs):
                continue
            controls += 1
            if re.search(r"placeholder\s*=", attrs):
                placeholders += 1
        if controls:
            found[path.name] = {"controls": controls, "placeholders": placeholders}
    return found
