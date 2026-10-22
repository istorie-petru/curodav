"""Icons as text: every Lucide icon name has one fixed character, and the `:` picker hands it back."""

from __future__ import annotations

from src import icon_font, notebook_mentions


def test_an_icon_name_maps_to_one_private_use_character():
    glyph = icon_font.glyph("star")
    assert len(glyph) == 1 and 0xE000 <= ord(glyph) <= 0xF8FF
    assert icon_font.glyph("not-an-icon") == ""


def test_codes_are_unique_per_character_except_for_renamed_icons():
    codes = icon_font.codes()
    assert icon_font.glyph("alert-circle") == icon_font.glyph("circle-alert")
    assert len(set(codes.values())) > 1500


def test_the_picker_returns_the_character():
    rows = notebook_mentions.icons(["star", "star-off", "sun"], "star")
    assert [r["name"] for r in rows] == ["star", "star-off"]
    assert rows[0]["char"] == icon_font.glyph("star")
