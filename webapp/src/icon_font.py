"""Lucide icons as text: each icon name has one fixed character in the bundled icon font.

A note stores the character itself, so an icon can be typed, pasted and searched like any letter. The codes come from
lucide-static's own codepoint list and are never reassigned; a new Lucide release only adds names.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_CODES = Path(__file__).resolve().parent / "static" / "icons" / "lucide-codepoints.json"


@lru_cache(maxsize=1)
def codes() -> dict[str, int]:
    return json.loads(_CODES.read_text(encoding="utf-8"))


def glyph(name: str) -> str:
    """The character for an icon name, or an empty string for an unknown name."""
    code = codes().get(name)
    return chr(code) if code else ""


TOOLBAR_ICONS = (
    "bold", "code", "eraser", "git-commit-vertical", "hash", "image", "italic", "link", "list", "list-checks",
    "list-ordered", "megaphone", "minus", "palette", "redo-2", "strikethrough", "subscript", "superscript", "table",
    "underline", "undo-2", "plus", "braces", "quote", "chevron-down", "table-properties", "trash-2", "brackets", "ellipsis", "arrow-up", "arrow-down", "copy",
)


def toolbar_icons() -> str:
    """JSON map of the editor toolbar's icon names to their characters."""
    return json.dumps({name: glyph(name) for name in TOOLBAR_ICONS})
