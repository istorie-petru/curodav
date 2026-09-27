"""Tests for item 3 of Peter's queued list (2026-09-27): "Switch the whole
icon library to Lucide (https://lucide.dev/icons/), AGAIN, fully
(templates/_icons_sprite.html + every icon name used; check routers/
labels.py ICON_GROUPS / habit_view.HABIT_ICONS names). Add a rule: a
minimum icon size, and an icon is the same size as the text next to it.
Icons are never transparent; the icon/avatar style in the narrow header
must be visually consistent across pages, spaces, projects, labels, etc."

This is the third icon-set swap this app has been through (hand-authored
Feather-style stroke icons -> real Material Design Icons, 2026-09-24 ->
real Lucide stroke icons, this pass) -- every `icon-<name>` symbol id is
UNCHANGED from the MDI pass (deps.py's `_icon()` global renders `<use
href="#icon-name">` regardless of what's inside the sprite's own
`<symbol>`), so this suite mostly checks the sprite's own internals and
the CSS class governing every icon's rendering, not individual template
call sites (those were already covered when the MDI pass shipped and
didn't need to change again)."""

from __future__ import annotations

import re
from pathlib import Path

from src.routers import labels as labels_router

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "templates"
_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"

# The exact 190 names the sprite defined under the MDI pass -- every one
# of them must still exist under Lucide too, since nothing anywhere in
# the app (a template call site, ICON_GROUPS, HABIT_ICONS, a user's
# already-stored label/habit icon choice in an existing database) was
# updated to reference a different name for this swap.
_EXPECTED_NAMES = frozenset("""
activity address-book airplay alert-circle alert-triangle anchor aperture
archive atom at-sign award baby backpack balloon bar-chart bar-chart-2
battery bell bluetooth book bookmark book-open box briefcase cake
calculator calendar camera candle cast chalkboard check-circle check-square
chevron-down chevron-left chevron-right chevron-up clipboard clock cloud
cloud-rain code coffee columns command compass confetti corner-down-right
cpu credit-card crosshair database disc dollar-sign download droplet edit
edit-3 external-link eye family-tree feather file file-text film filter
flag folder folder-minus folder-plus gavel gift git-branch git-commit
github git-pull-request globe graduation-cap grid handshake hard-drive
hash headphones heart home home-heart id-card image inbox info key
layers layout life-buoy link link-2 list lock mail map map-pin medal
megaphone merge message-circle message-square mic minus monitor moon
more move music navigation navigation-2 notebook package paperclip
party-popper pause pencil pen-tool phone pie-chart play plus podium
printer quote radio repeat ribbon rotate-ccw rss ruler scale school
scissors send server settings share share-2 shield shopping-bag
shopping-cart shuffle sidebar sliders smartphone smile sparkles speaker
square star stop-circle sun sunrise sunset tablet tag target terminal
thermometer thumbs-up tool trash trash-2 trending-down trending-up trophy
truck tv type umbrella unlock upload user user-check user-plus users
video volume-2 watch wifi wind x x-circle zap zap-off
""".split())


def _sprite_text() -> str:
    return (_TEMPLATES_DIR / "_icons_sprite.html").read_text()


def _sprite_ids() -> set[str]:
    return set(re.findall(r'<symbol id="icon-([a-z0-9-]+)"', _sprite_text()))


class TestEveryPreExistingNameSurvivedTheSwap:
    def test_exactly_190_names_both_before_and_after(self):
        assert len(_EXPECTED_NAMES) == 190
        assert len(_sprite_ids()) == 190

    def test_no_name_dropped_or_added(self):
        ids = _sprite_ids()
        assert ids == _EXPECTED_NAMES, f"diff: missing={_EXPECTED_NAMES - ids}, extra={ids - _EXPECTED_NAMES}"

    def test_label_icons_still_all_resolve(self):
        # Same assertion test_modal_input_phaseC_swatch_grid.py's own
        # TestLabelIconPicker::test_every_icon_exists_in_the_sprite makes
        # -- repeated here so this file is a self-contained record of the
        # swap's own acceptance criteria, not just a cross-reference.
        missing = set(labels_router.LABEL_ICONS) - _sprite_ids()
        assert not missing


class TestSpriteIsNowRealStrokeBasedLucide:
    """Distinguishes "real Lucide SVG data" from "the old MDI single-path
    fills happened to still be there" -- a Lucide icon almost always has
    multiple primitives (paths/circles/rects), and none of them carry
    curve-heavy single-path MDI-style data anymore."""

    def test_no_symbol_carries_its_own_hardcoded_color(self):
        # Individual symbols inherit color from the .icon CSS class, same
        # "class sets it, symbol only varies geometry" rule both the old
        # Feather and MDI sprites already followed -- no symbol may set a
        # literal color (a hex/named/rgb value). One legitimate exception,
        # straight off Lucide's own real source data (not this app's
        # doing): "tag"'s small eyelet dot is `fill="currentColor"` in the
        # upstream icons/tag.svg file itself (Lucide fills a few tiny
        # decorative accents solid even in an otherwise all-stroke icon)
        # -- `currentColor` still resolves to the same class-driven color
        # everything else uses, so this isn't a hardcoded color at all,
        # just a different (correct, upstream) way of applying it.
        text = _sprite_text()
        symbols = re.findall(r"<symbol[^>]*>.*?</symbol>", text)
        assert len(symbols) == 190
        for s in symbols:
            for attr in re.findall(r'(?:fill|stroke)="([^"]*)"', s):
                assert attr == "currentColor", f"hardcoded color in: {s}"
        assert 'fill="currentColor"' in text  # the one known exception above

    def test_a_known_multi_path_lucide_icon_has_more_than_one_primitive(self):
        # "trash" is a 4-primitive Lucide icon (lid, two tick marks, can
        # body) -- the old MDI trash can was a single <path>.
        text = _sprite_text()
        m = re.search(r'<symbol id="icon-trash" viewBox="0 0 24 24">(.*?)</symbol>', text)
        assert m
        primitives = re.findall(r"<(path|circle|rect|line|polyline|polygon)\b", m.group(1))
        assert len(primitives) >= 4

    def test_house_icon_exists_under_the_old_home_id(self):
        # "home" is one of the ~30 names Lucide renamed (house.svg is the
        # real source) -- the app's own id stays "home" either way.
        text = _sprite_text()
        m = re.search(r'<symbol id="icon-home" viewBox="0 0 24 24">(.*?)</symbol>', text)
        assert m
        assert "<path" in m.group(1)


def _css_no_comments() -> str:
    """style.css's own /* ... */ prose (this test file's own additions
    included) routinely quotes real CSS-shaped snippets like
    "`.icon{width:...}`" while explaining a rule -- a plain substring/regex
    search over the raw file text can false-positive-match those exactly
    the way an HTML comment's own prose can collide with a bare class-name
    substring check (a pitfall this app's own test suite has hit before).
    Stripping comments first is the fix, same as searching only the
    rendered `class="..."` attribute instead of a bare class name would be
    for that other case."""
    return re.sub(r"/\*.*?\*/", "", (_STATIC_DIR / "style.css").read_text(), flags=re.DOTALL)


def _rule_block(css: str, selector: str) -> str:
    """The first real `selector{...}` rule's own body (selector index
    found in the comment-stripped text, sliced from the ORIGINAL text at
    that same offset so multi-rule blocks spanning a later `}` still read
    correctly)."""
    idx = css.index(selector)
    end = css.index("}", idx) + 1
    return css[idx:end]


class TestIconCssIsStrokeBased:
    def test_icon_class_uses_stroke_not_fill(self):
        block = _rule_block(_css_no_comments(), ".icon{")
        assert "fill:none" in block
        assert "stroke:currentColor" in block
        assert "stroke-width:2" in block
        assert "fill:currentColor" not in block

    def test_round_caps_and_joins_match_lucides_own_default(self):
        block = _rule_block(_css_no_comments(), ".icon{")
        assert "stroke-linecap:round" in block
        assert "stroke-linejoin:round" in block


class TestNewSizingRules:
    """Direct request: "Add a rule: a minimum icon size, and an icon is
    the same size as the text next to it." """

    def test_base_icon_sizes_off_its_own_font_size(self):
        block = _rule_block(_css_no_comments(), ".icon{")
        assert "width:1em" in block
        assert "height:1em" in block

    def test_minimum_size_floor_present(self):
        block = _rule_block(_css_no_comments(), ".icon{")
        assert "min-width:12px" in block
        assert "min-height:12px" in block

    def test_icon_sm_and_lg_are_also_em_relative(self):
        css = _css_no_comments()
        assert re.search(r"\.icon-sm\{[^}]*width:0\.85em", css)
        assert re.search(r"\.icon-lg\{[^}]*width:1\.35em", css)

    def test_no_below_floor_pixel_override_survives_the_audit(self):
        # Every remaining `.icon{width:Npx}`-shaped override in the file
        # must be >= 12px (the floor) -- style.css's own comment documents
        # the one violator found (status-card-status, fixed below) and
        # that no others existed under the old MDI-era sizing.
        css = _css_no_comments()
        for m in re.finditer(r"\.[\w.-]*icon[\w.-]*\s*\{[^}]*\}", css):
            rule = m.group(0)
            for size_m in re.finditer(r"(?:width|height):\s*(\d+)px", rule):
                assert int(size_m.group(1)) >= 12, f"below-floor rule: {rule}"

    def test_status_card_dot_now_matches_its_own_adjacent_text(self):
        css = _css_no_comments()
        assert ".status-card-status .icon{width:1em; height:1em" in css
        # The old fixed-10px icon override is gone -- scoped to icon rules
        # specifically (style.css has unrelated non-icon 10px rules, e.g.
        # the calendar "now" line's own dot, that this must not flag).
        assert "status-card-status .icon{width:10px" not in css


class TestIconsAreNeverTransparent:
    def test_base_icon_is_fully_opaque(self):
        block = _rule_block(_css_no_comments(), ".icon{")
        assert "opacity:1" in block


class TestNarrowHeaderIconConsistency:
    """Direct request: "the icon/avatar style in the narrow header must be
    visually consistent across pages, spaces, projects, labels, etc." --
    found one real inconsistency during this pass: a label/group page
    with both a banner and its own color pinned its header icon to a
    fixed 18px while every other narrow-header variant sizes off the
    shared 1.15em rule."""

    def test_no_more_fixed_pixel_override_for_the_banner_plus_color_variant(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".page-header-narrow.has-banner .page-header-narrow-icon.has-color .icon{width:18px" not in css

    def test_every_narrow_header_variant_now_shares_the_one_sizing_rule(self):
        css = (_STATIC_DIR / "style.css").read_text()
        assert ".page-header-narrow-icon .icon{width:1.15em; height:1.15em;}" in css
