"""Markdown while writing: block markers, inline markers, selections and links, run under node.

Each case mirrors a row of the tables in curodav-notes/documentation/features/notebook-rework/markdown.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TYPING_JS = Path(__file__).resolve().parent.parent / "src" / "static" / "notebook" / "notebook_typing.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(expression: str):
    script = f"const T=require(process.argv[1]); console.log(JSON.stringify({expression}))"
    out = subprocess.run(["node", "-e", script, str(TYPING_JS)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def block(before, key="Space", rest=""):
    return run(f"T.blockMarker({json.dumps(before)}, {json.dumps(key)}, {json.dumps(rest)})")


def inline(before, after, typed):
    return run(f"T.inlineRule({json.dumps(before)}, {json.dumps(after)}, {json.dumps(typed)})")


@pytest.mark.parametrize("marker, expected", [
    ("#", {"type": "header", "level": 1}), ("##", {"type": "header", "level": 2}), ("#####", {"type": "header", "level": 5}),
    ("-", {"type": "list", "style": "unordered"}), ("*", {"type": "list", "style": "unordered"}), ("+", {"type": "list", "style": "unordered"}),
    ("1.", {"type": "list", "style": "ordered"}), ("12)", {"type": "list", "style": "ordered"}),
    (">", {"type": "quote"}),
    ("[ ]", {"type": "list", "style": "checklist", "checked": False}), ("[x]", {"type": "list", "style": "checklist", "checked": True}),
])
def test_a_block_marker_before_the_caret_converts_the_block(marker, expected):
    assert block(marker) == expected


def test_six_hashes_is_not_a_heading():
    assert block("######") is None


def test_dividers_need_enter_and_nothing_after_the_caret():
    for marker in ("---", "***", "___", "-----"):
        assert block(marker, "Enter") == {"type": "delimiter"}
    assert block("---", "Enter", rest="text after") is None


def test_the_code_fence_needs_enter():
    assert block("```", "Enter") == {"type": "code"}
    assert block("```") is None


def test_a_marker_in_the_middle_of_text_does_nothing():
    assert block("some text #") is None
    assert block("a ---", "Enter") is None


def test_heading_level_changes_when_hashes_are_typed_at_its_start():
    assert run('T.headingLevelMarker("##")') == 2
    assert run('T.headingLevelMarker("text ##")') == 0


@pytest.mark.parametrize("before, typed, tags, content", [
    ("say **hi**", "*", ["b"], "hi"), ("say *hi*", "*", ["i"], "hi"), ("say _hi_", "_", ["i"], "hi"),
    ("say ~~gone~~", "~", ["s"], "gone"), ("say `code`", "`", ["code"], "code"), ("say ***both***", "*", ["b", "i"], "both"),
])
def test_closing_a_marker_converts_the_span(before, typed, tags, content):
    rule = inline(before, "", typed)
    assert rule["tags"] == tags and rule["content"] == content


def test_text_after_the_caret_does_not_stop_a_closing_marker():
    rule = inline("a **bold**", " and more", "*")
    assert rule["content"] == "bold" and rule["consume"] == 0


def test_an_opening_marker_before_text_that_already_has_its_closer_converts_it():
    rule = inline("a **", "word** tail", "*")
    assert rule["tags"] == ["b"] and rule["content"] == "word" and rule["consume"] == 6
    rule = inline("*", "word*", "*")
    assert rule["tags"] == ["i"] and rule["consume"] == 5


def test_markers_inside_words_stay_text():
    assert inline("snake_case_", "", "_") is None
    assert inline("a_b", "_c", "_") is None


def test_spaces_next_to_markers_mean_no_span():
    assert inline("2 * 3 *", "", "*") is None
    assert inline("a ** b **", "", "*") is None


def test_a_backslash_keeps_a_marker_as_text():
    assert inline("x \\*no*", "", "*") is None


def test_a_link_converts_when_the_closing_parenthesis_is_typed():
    rule = inline("see [site](https://a.org)", "", ")")
    assert rule["tags"] == ["a"] and rule["content"] == "site" and rule["href"] == "https://a.org"


def test_a_link_needs_a_safe_address():
    assert inline("[x](javascript:alert(1))", "", ")") is None


def test_a_marker_over_a_selection_picks_the_tag_and_a_second_star_makes_it_bold():
    assert run('[T.selectionTag("*", false), T.selectionTag("*", true), T.selectionTag("_", false), T.selectionTag("~", false), T.selectionTag("`", false), T.selectionTag("a", false)]') == ["i", "b", "i", "s", "code", None]


def test_the_typed_form_of_a_conversion_is_what_backspace_restores():
    assert run('T.typedForm(T.inlineRule("x **hi**", "", "*"))') == "**hi**"
    assert run('T.typedForm(T.inlineRule("x [a](https://b.org)", "", ")"))') == "[a](https://b.org)"
