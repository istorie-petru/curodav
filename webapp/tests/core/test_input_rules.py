"""Core tests for the input rules (rules/frontend-conventions.md, Inputs).

`placeholder=` is not used outside Settings entries. Bare form controls are
counted per template (component templates such as _inputs.html are exempt) by src/template_audit.py; BARE_CONTROLS is the allow-list
of today's counts. It only shrinks: a template may not gain a bare control, and
an entry that reached its target is removed. A rule is done when the list is
empty. It is empty: every control now goes through a component in _inputs.html.
"""

import template_audit

BARE_CONTROLS: dict[str, int] = {}


def test_no_placeholder_outside_settings():
    offenders = sorted(
        name
        for name, counts in template_audit.audit().items()
        if counts["placeholders"] and not name.startswith("settings_")
    )
    assert not offenders, f"placeholder= is only allowed in Settings entries: {offenders}"


def test_no_template_gains_a_bare_control():
    audit = template_audit.audit()
    grown = {
        name: (counts["controls"], BARE_CONTROLS.get(name, 0))
        for name, counts in audit.items()
        if counts["controls"] > BARE_CONTROLS.get(name, 0)
    }
    assert not grown, f"New bare controls (found, allowed): {grown}"


def test_allow_list_has_no_stale_entries():
    audit = template_audit.audit()
    stale = {
        name: allowed
        for name, allowed in BARE_CONTROLS.items()
        if audit.get(name, {}).get("controls", 0) < allowed
    }
    assert not stale, f"Lower these allow-list counts (fixed): {stale}"
