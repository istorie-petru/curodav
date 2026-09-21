"""Inline field-level validation (design-system unification pass, 2026-09-17,
shared spec at /home/peter/Claude/Projects/DESIGN_SYSTEM.md): a 422 response
from a modal form used to surface only as a global toast, with no way to
tell which input on a longer form (task/event/contact/...) was actually
wrong. modal.js's applyFieldErrors now marks the matching `.field` wrapper
(`.has-error` + a `.field-error` line) for anything it can find by name,
falling back to the toast only for entries it can't match to a visible
input. Same "check the rendered markup / script structurally" convention
test_holiday_date_sync.py uses for its own client-side-only behavior --
there's no server-side state to assert against, this is pure DOM wiring."""

from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "static"


class TestApplyFieldErrors:
    def test_modal_js_defines_apply_field_errors(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "function applyFieldErrors(form, text)" in script
        assert "function clearFieldErrors(form)" in script

    def test_matches_by_the_last_loc_segment_against_a_form_field(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert 'd.loc[d.loc.length - 1]' in script
        assert 'form.querySelector(`[name="${CSS.escape(String(fieldName))}"]`)' in script

    def test_marks_the_field_wrapper_not_just_the_input(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert 'input.closest(".field")' in script
        assert 'field.classList.add("has-error")' in script
        assert 'className = "field-error"' in script

    def test_focuses_the_first_invalid_field(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "firstInvalid.focus()" in script

    def test_unmatched_errors_still_fall_back_to_a_toast(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "unmatched.push(" in script
        assert "unmatched.length" in script

    def test_submit_handler_calls_apply_field_errors_on_failure(self):
        script = (_STATIC_DIR / "modal.js").read_text()
        assert "const unmatched = applyFieldErrors(form, text);" in script


class TestFieldErrorStyles:
    def test_style_css_defines_has_error_and_field_error(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".field.has-error" in css
        assert ".field-error{" in css
        assert "var(--danger)" in css.split(".field-error{", 1)[1].split("}", 1)[0]
