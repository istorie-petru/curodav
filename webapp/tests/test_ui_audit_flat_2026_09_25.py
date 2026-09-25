"""UI audit 2026-09-25, card-model removal sweep (F- findings) -- string-level
regressions in the same style as test_responsive_tables.py: the audit's
measurements were done in a real browser, these pin the rules that produced
them so a later pass can't quietly undo one."""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_CSS = (_SRC / "static" / "style.css").read_text()
_TPL = _SRC / "templates"


def _rule(selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\{([^}]*)\}", _CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_f1_one_page_inset_token_matches_banner_inner_edge():
    # --page-inset = .page-header-narrow's 1px border + --space-3 (12px)
    # horizontal padding, so content starts under the banner's icon.
    assert "--page-inset:13px;" in _CSS
    banner = _rule(".page-header-narrow")
    assert "padding:var(--space-2) var(--space-3)" in banner
    assert "border:1px solid" in banner
    assert "padding:var(--space-4) var(--page-inset)" in _rule(".card")
    assert ".card table :is(th, td):first-child{padding-left:0;}" in _CSS
    assert "padding:var(--space-3) 0;" in _rule(".settings-field-row")
    assert "padding-inline:var(--page-inset)" in _rule(".search-page-results")


def test_f17_habits_page_uses_the_page_inset_not_a_centred_column():
    body = _rule(".habits-body")
    assert "max-width" not in body and "margin:0 auto" not in body
    assert "padding-inline:var(--page-inset)" in body


def test_f2_settings_row_controls_can_shrink():
    assert ".settings-field-row .settings-field-label{min-width:0;" in _CSS
    assert "min-width:120px" in _CSS


def test_f3_detail_card_has_no_hover_lift():
    assert ".detail-card:hover" not in _CSS


def test_f4_no_duplicate_top_app_bar_on_search_or_notes():
    for name in ("search.html", "notes.html"):
        html = (_TPL / name).read_text()
        assert 'class="toolbar top-app-bar"' not in html
        assert '<h1 class="sr-only">' in html
    # the search page's autofocus script must carry the CSP nonce
    assert '<script nonce="{{ csp_nonce() }}">' in (_TPL / "search.html").read_text()


def test_f5_settings_groups_have_dividers():
    assert ".settings-divider{" in _CSS
    for name, n in (("settings_general.html", 1), ("settings_your_profile.html", 1), ("settings_data_maintenance.html", 2)):
        assert (_TPL / name).read_text().count('<hr class="settings-divider">') == n


def test_f7_status_tiles_are_flat():
    body = _rule(".status-card")
    for chrome in ("background", "box-shadow", "border-radius"):
        assert chrome not in body
    assert ".status-card.healthy{" not in _CSS


def test_f9_row_hover_token_is_visible_in_both_themes():
    assert "--row-hover:rgba(0,0,0,.055);" in _CSS
    assert "--row-hover:rgba(255,255,255,.07);" in _CSS
    assert "tbody tr:hover{background:var(--row-hover);}" in _CSS


def test_f10_dark_tertiary_text_clears_aa_on_the_dark_body():
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    dark = _CSS[_CSS.index('[data-theme="dark"]{'):]
    fg = re.search(r"--fg-tertiary:(#[0-9a-f]{6})", dark).group(1)
    sec = re.search(r"--fg-secondary:(#[0-9a-f]{6})", dark).group(1)
    body = re.search(r"--bg-elevated:(#[0-9a-f]{6})", dark).group(1)
    ratio = (lum(fg) + 0.05) / (lum(body) + 0.05)
    assert ratio >= 4.5
    assert lum(fg) < lum(sec)  # tertiary stays a step dimmer than secondary


def test_f12_no_9px_text_left_in_widget_chrome():
    assert "at-a-glance-stat .widget-section-label{font-size:9px" not in _CSS
    assert ".toolbar-filters-badge" not in _CSS


def test_f13_dropdown_checked_option_uses_the_accent():
    assert '.multiselect-option input:is([type="radio"], [type="checkbox"]){accent-color:var(--accent);}' in _CSS


def test_f15_widget_builder_columns_are_not_framed_panels():
    for sel in (".widget-builder-config",):
        body = _rule(sel)
        assert "box-shadow" not in body and "background" not in body
    m = re.search(r"\.widget-builder-preview\{([^}]*)\}", _CSS)
    assert "box-shadow" not in m.group(1) and "background" not in m.group(1)


def test_f16_dead_rules_are_gone():
    for dead in (".project-card-square", ".widget-customize-card", ".habit-card-header",
                 ".habit-card-heatmap-full", ".habit-card-expand-btn", ".habit-log-card{",
                 "--surface-0:"):
        assert dead + ("" if dead.endswith(("{", ":")) else "{") not in _CSS, dead


def test_f19_widget_checkbox_does_not_set_row_height():
    assert ".widget-row-icon .icon-btn{margin-block:-4px;}" in _CSS
