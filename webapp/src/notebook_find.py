"""Find and replace inside Notebook documents' block JSON: text segments only, never markup, code or formulas."""

from __future__ import annotations

import copy
import html
import re
from dataclasses import dataclass, field

TAG = re.compile(r"(<[^>]*>)")


@dataclass
class Report:
    count: int = 0
    snippets: list[str] = field(default_factory=list)


def _pattern(query: str, case: bool, whole: bool) -> re.Pattern:
    body = re.escape(query)
    if whole:
        body = r"(?<!\w)" + body + r"(?!\w)"
    return re.compile(body, 0 if case else re.IGNORECASE)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    left = text[max(0, start - radius):start]
    right = text[end:end + radius]
    return ("..." if start > radius else "") + left + text[start:end] + right + ("..." if end + radius < len(text) else "")


def _is_formula(cell: str) -> bool:
    plain = html.unescape(TAG.sub("", cell or "")).strip()
    return plain.startswith("=")


def map_html(markup: str, pattern: re.Pattern, replacement: str | None, report: Report) -> str:
    """Applies the pattern to each text segment between tags. Matches that span two tags are not found."""
    out = []
    for part in TAG.split(markup or ""):
        if part.startswith("<") and part.endswith(">"):
            out.append(part)
            continue
        text = html.unescape(part)
        hits = list(pattern.finditer(text))
        if not hits:
            out.append(part)
            continue
        report.count += len(hits)
        for m in hits:
            if len(report.snippets) < 3:
                report.snippets.append(_snippet(text, m.start(), m.end()))
        out.append(part if replacement is None else _escape(pattern.sub(lambda _m: replacement, text)))
    return "".join(out)


def _list_items(items, fn):
    result = []
    for item in items or []:
        if isinstance(item, str):
            result.append(fn(item))
        elif isinstance(item, dict):
            new = dict(item)
            if isinstance(new.get("content"), str):
                new["content"] = fn(new["content"])
            if "items" in new:
                new["items"] = _list_items(new["items"], fn)
            result.append(new)
        else:
            result.append(item)
    return result


def map_blocks(blocks: list[dict], fn) -> list[dict]:
    """Returns a copy of the blocks with `fn(html)` applied to every searchable text field."""
    out = copy.deepcopy(blocks or [])
    for block in out:
        kind, data = block.get("type"), block.get("data") or {}
        if kind in ("paragraph", "header", "quote", "callout"):
            for key in ("text", "caption", "title"):
                if isinstance(data.get(key), str):
                    data[key] = fn(data[key])
        elif kind == "list":
            data["items"] = _list_items(data.get("items"), fn)
        elif kind == "table":
            data["content"] = [[cell if (not isinstance(cell, str) or _is_formula(cell)) else fn(cell) for cell in row]
                               for row in data.get("content") or []]
    return out


def find(blocks: list[dict], query: str, case: bool = False, whole: bool = False) -> Report:
    report = Report()
    if query:
        pattern = _pattern(query, case, whole)
        def look(markup: str) -> str:
            map_html(markup, pattern, None, report)
            return markup

        map_blocks(blocks, look)
    return report


def replace(blocks: list[dict], query: str, replacement: str, case: bool = False, whole: bool = False) -> tuple[list[dict], int]:
    report = Report()
    if not query:
        return blocks, 0
    pattern = _pattern(query, case, whole)
    return map_blocks(blocks, lambda markup: map_html(markup, pattern, replacement, report)), report.count
