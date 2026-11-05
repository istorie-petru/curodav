"""The Library search box: free words plus `key:value` terms (type:film status:current year:2000-2010 author:"le guin" tag:x shelf:y source:file).

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import re

from . import media

_TERM = re.compile(r'(?<!\S)(\w+):("[^"]*"|\S+)')
KEYS = ("type", "status", "author", "year", "tag", "shelf", "source")
_ALIASES = {"kind": "type", "by": "author", "label": "tag"}
_YEAR = re.compile(r"^(?:(\d{1,4})(?:\s*(?:-|\.\.)\s*(\d{1,4}))?|([<>]=?)\s*(\d{1,4}))$")


def _status_keys(value: str) -> list[str]:
    """A status by key or by any of its words in a kind's own wording ("current", "reading", "in progress")."""
    value = value.lower()
    if value in ("none", "no", "nostatus"):
        return ["none"]
    found = [k for k in media.STATUS_KEYS if k == value]
    if not found:
        for verb in media.VERBS:
            found += [k for k in media.STATUS_KEYS if media.status_label(k, verb).lower() == value and k not in found]
    return found


def parse(text: str, type_names: dict[str, str]) -> dict:
    """Splits the box into the words left for full-text search and the filters the terms stand for; an unknown term stays a word."""
    out = {"text": "", "types": [], "statuses": [], "tags": [], "shelves": [], "sources": [], "year_lo": None, "year_hi": None}
    by_name = {name.lower(): key for key, name in type_names.items()} | {key.lower(): key for key in type_names}

    def take(match: re.Match) -> str:
        key = _ALIASES.get(match.group(1).lower(), match.group(1).lower())
        value = match.group(2).strip('"').strip()
        if key not in KEYS or not value:
            return match.group(0)
        if key == "type":
            hit = by_name.get(value.lower())
            if not hit:
                return match.group(0)
            out["types"].append(hit)
        elif key == "status":
            hits = _status_keys(value)
            if not hits:
                return match.group(0)
            out["statuses"] += hits
        elif key == "year":
            m = _YEAR.match(value)
            if not m:
                return match.group(0)
            if m.group(3):
                n = int(m.group(4))
                n += {">": 1, "<": -1}.get(m.group(3), 0) if len(m.group(3)) == 1 else 0
                out["year_lo" if m.group(3)[0] == ">" else "year_hi"] = n
            else:
                out["year_lo"] = int(m.group(1))
                out["year_hi"] = int(m.group(2) or m.group(1))
        elif key == "source":
            if value.lower() not in ("file", "url", "link", "none"):
                return match.group(0)
            out["sources"].append("url" if value.lower() == "link" else value.lower())
        elif key == "author":
            return value  # the search index already holds the authors, so a name is just words to find
        else:
            out[{"tag": "tags", "shelf": "shelves"}[key]].append(value)
        return ""

    out["text"] = " ".join(_TERM.sub(take, text or "").split())
    return out
