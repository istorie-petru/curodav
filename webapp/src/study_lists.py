"""Parser for a pasted list of themes: one theme per line, an optional leading number and optional trailing stars for importance.

`1. Cell structure ***`, `2) Membranes`, `3 Transport *` and a bare `Osmosis` all parse. A line without a number takes the next
number after the previous line, and three stars is the most importance a theme can carry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_STARS = 3
_LEAD = re.compile(r"^\s*(\d+)\s*[.)\-:]?\s+(?=\S)|^\s*(\d+)\s*[.)\-:]\s*")
_STARS = re.compile(r"\s*(\*+)\s*$")


@dataclass(frozen=True)
class Theme:
    number: int
    title: str
    importance: int


def parse_themes(text: str) -> list[Theme]:
    """The themes of a pasted list, in order; blank lines are skipped and a line with nothing but a number or stars is ignored."""
    themes: list[Theme] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        importance = 0
        stars = _STARS.search(line)
        if stars:
            importance = min(len(stars.group(1)), MAX_STARS)
            line = line[: stars.start()]
        number = None
        lead = _LEAD.match(line)
        if lead:
            number = int(lead.group(1) or lead.group(2))
            line = line[lead.end():]
        title = line.strip()
        if not title:
            continue
        themes.append(Theme(number if number is not None else (themes[-1].number + 1 if themes else 1), title, importance))
    return themes
