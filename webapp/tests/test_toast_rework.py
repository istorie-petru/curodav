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
  - Persistent mode (`persistent: true`): no countdown/progress bar, no
    dedupe, and the handle gains `set()`/`isAlive()` for in-place updates.
  - ccConfirmSheet is now a persistent error toast in the bottom-right
    stack (Cancel + confirmLabel action row) instead of a button-anchored
    popover.
  - The main success/warning call sites were split into title + short body.
  - The four toast status icons exist in _icons_sprite.html so the chip's
    <use> references never dangle, and style.css still styles the new
    anatomy while keeping the confirm-toast rules.
  - The sync status indicator (static/offline_status.js) now renders as
    bottom-right toasts -- persistent for offline/pending/synchronizing, a
    brief "Synced" toast only on a real non-synced -> synced transition.
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

    def test_css_styles_new_anatomy_and_keeps_confirm_toast(self):
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
            ".toast-confirm{",
            ".toast-actions{",
            ".toast-confirm .toast-action.toast-confirm-ok{",
            ".toast-confirm .toast-action.toast-confirm-cancel{",
        ]:
            assert expected in css, expected
        # The old button-anchored confirm-sheet styles are gone -- replaced
        # by the confirm toast above.
        assert ".confirm-sheet{" not in css

    def test_persistent_mode_skips_countdown_and_dedupe(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            "persistent = false",
            "if (!persistent && recent.has(key)",
            "if (!persistent) recent.set(key, now)",
            "let progress = null",
            "if (!persistent) {",
            "if (!persistent) arm(duration)",
            'return { dismiss, set, isAlive: () => !dismissed }',
        ]:
            assert expected in js, expected

    def test_persistent_handle_gains_set_for_in_place_updates(self):
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            "function set(newOpts) {",
            "if (dismissed) return false",
            "titleEl.textContent = newOpts.title || cfg.title",
            "bodyEl.hidden = true",
        ]:
            assert expected in js, expected

    def test_confirm_sheet_is_now_a_persistent_confirm_toast(self):
        # ccConfirmSheet no longer builds a button-anchored popover: it is a
        # persistent error toast in the bottom-right stack with a Cancel +
        # confirmLabel action row.
        js = (_STATIC_DIR / "toast.js").read_text(encoding="utf-8")
        for expected in [
            "title: \"Please confirm\"",
            "variant: \"error\"",
            "persistent: true",
            'className: "toast-confirm"',
            'className: "toast-confirm-cancel"',
            'className: "toast-confirm-ok"',
            "confirmLabel = \"Delete\"",
            # The confirm action must run the caller's onConfirm -- an earlier
            # draft wired `onAction` here, a name that doesn't exist in
            # ccConfirmSheet's destructure, which made every confirm crash
            # with a ReferenceError the moment it was opened (caught by the
            # smoke run, not this suite's structure-level asserts).
            "onAction: onConfirm",
        ]:
            assert expected in js, expected
        assert '"confirm-sheet"' not in js
        assert "getBoundingClientRect" not in js


class TestSyncStatusToasts:
    """2026-08-16 follow-up -- the sync status indicator (offline_status.js)
    is now rendered as bottom-right toasts like every other announcement,
    not a top-right pill: persistent for the offline/pending/synchronizing
    states, a brief "Synced" toast only on a real non-synced -> synced
    transition. Same structural-check level as the rest of this file."""

    def test_status_renders_through_ccToast_as_persistent_toasts(self):
        js = (_STATIC_DIR / "offline_status.js").read_text(encoding="utf-8")
        for expected in [
            "window.ccToast",
            "persistent: true",
            ".set(cfg)",
            ".isAlive()",
            'title: "You\'re offline"',
            'title: "Changes pending"',
            'title: "Syncing…"',
            'title: "Synced"',
        ]:
            assert expected in js, expected

    def test_synced_only_shows_a_brief_toast_on_a_real_transition(self):
        js = (_STATIC_DIR / "offline_status.js").read_text(encoding="utf-8")
        assert "wasNonSynced" in js
        assert "duration: 3000" in js
        # Still renderer-only -- no IndexedDB or network calls of its own.
        assert "indexedDB.open" not in js
        assert "fetch(" not in js

    def test_pill_css_removed(self):
        css = (_STATIC_DIR / "style.css").read_text(encoding="utf-8")
        assert ".sync-status-pill" not in css
        assert "sync-status-dot" not in css