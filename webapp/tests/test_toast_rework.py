"""Toast/snackbar rework (static/toast.js, 2026-08-16) -- direct feedback
asks on the ccToast component: "don't show duplicate toasts (small time
barrier)", "more appealing: icon + clear header + short body", "hovering
must not make them disappear; leaving makes them disappear after a few
seconds", "consistent look", and "actionable (revert/confirm)". Pure
client-side behavior can't be exercised by this app's router-function-call
pytest convention (no browser here), so these are structural source checks
against toast.js / the icon sprite / the toast CSS, the same style of check
test_pwa_shell.py and test_settings_time_blocks.py use for JS-only changes.

Covered here:

  - ccToast's DOM anatomy: an icon chip + title header + optional body +
    optional action + close, with chip/icon derived per variant.
  - The dedupe time barrier (same variant+title+message dropped within
    BARRIER_MS) and hover-pause (mouseenter stops the countdown,
    mouseleave restarts it capped at a short grace).
  - The expiry bar (.toast-progress) draining 100% -> 0% in lockstep with
    that countdown.
  - The main success/warning call sites were split into title + short body.
  - The four toast status icons exist in _icons_sprite.html so the chip's
    <use> references never dangle, and style.css still styles the new
    anatomy while keeping the confirm-sheet rules.
"""

from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "templates"


class TestToastRework:
    def test_ccToast_builds_icon_chip_title_body_and_actions(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            'className = "toast-icon"',
            'className = "toast-content"',
            'className = "toast-title"',
            'className = "toast-body"',
            'className = "toast-action"',
            'className = "toast-close"',
            "VARIANT_CONFIG",
        ]:
            assert expected in js, expected

    def test_variant_config_maps_icon_and_default_title(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            'default: { icon: "check-circle", title: "Done" }',
            'error: { icon: "alert-circle", title: "Something went wrong" }',
            'warning: { icon: "alert-triangle", title: "Heads up" }',
        ]:
            assert expected in js, expected

    def test_dedupe_time_barrier_and_hover_pause(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            "BARRIER_MS = 4000",
            "recent.has(key) && now - recent.get(key) < BARRIER_MS",
            'el.addEventListener("mouseenter"',
            'el.addEventListener("mouseleave"',
            "HOVER_GRACE_MS",
        ]:
            assert expected in js, expected

    def test_expiry_bar_tracks_the_countdown(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            'className = "toast-progress"',
            "requestAnimationFrame(tick)",
            'progress.style.transform = "scaleX("',
            "cancelAnimationFrame(timer)",
        ]:
            assert expected in js, expected

    def test_call_sites_pass_title_and_short_message(self):
        # The warning's old "Heads up: " message prefix became the title.
        time_blocks = (_STATIC_DIR / "time_blocks.js").read_text(encoding="utf-8")
        assert 'title: "Heads up"' in time_blocks
        assert "This overlaps" in time_blocks
        assert "Heads up: this overlaps" not in time_blocks
        app_js = (_STATIC_DIR / "app.js").read_text(encoding="utf-8")
        assert 'title: "Archived"' in app_js
        assert 'title: "Deleted"' in app_js

    def test_toast_icons_exist_in_the_sprite(self):
        sprite = (_TEMPLATES_DIR / "_icons_sprite.html").read_text()
        for name in ("alert-triangle", "alert-circle", "info", "check-circle"):
            assert f'id="icon-{name}"' in sprite, name

    def test_css_styles_new_anatomy_and_keeps_confirm_sheet(self):
        css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
        for expected in [
            ".toast-icon{",
            ".toast-title{",
            ".toast-body{",
            ".toast-error .toast-icon{",
            ".toast-warning .toast-icon{",
            ".toast-progress{",
            ".toast-error .toast-progress{",
            ".toast-warning .toast-progress{",
            ".confirm-sheet{",
        ]:
            assert expected in css, expected