"""Core test for the readability rule (rules/frontend-conventions.md, Color
and readability): every accent stands out against both themes and keeps
readable text on its fill."""

import readability


def test_every_accent_is_readable_in_both_themes():
    assert readability.failures() == []


def test_nudge_moves_an_unreadable_fill_in_the_right_direction():
    dark = readability.nudge("#575dcf", "dark")
    assert readability.luminance(dark) > readability.luminance("#575dcf")
    light = readability.nudge("#f5f5f5", "light")
    assert readability.luminance(light) < readability.luminance("#f5f5f5")
