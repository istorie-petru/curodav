"""Icons: the full Lucide library is available by name and unknown names fall back to a neutral icon."""

from __future__ import annotations


def test_any_icon_of_the_full_library_renders_and_unknown_names_fall_back():
    from src.deps import templates
    render = templates.env.globals["icon"]
    assert "#icon-a-arrow-down" in str(render("a-arrow-down"))
    assert "#icon-tag" in str(render("definitely-not-an-icon"))
