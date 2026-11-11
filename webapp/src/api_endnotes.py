"""Generated endnote citations for notes written through the API and MCP.

An endnote written as `[^1]: [@citation-uid, 45]` becomes the same marker the editor's Generate citation makes: the note text in the
user's citation style, the kind and the cited sources, so Regenerate works in the editor and the bibliography picks the source up on
save. Feature document: curodav-notes/documentation/features/api-and-mcp.md.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from typing import Any

from . import citation_formats, db

SUP = re.compile(r"<sup\b([^>]*)></sup>")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
MODE_KINDS = {"full": "page_citation", "cf.": "confer", "idem": "idem", "passim": "passim", "apud": "apud"}
SINGLE_KINDS = {"page_citation", "confer", "idem", "passim", "ibidem", "opere_citato"}


class CiteError(ValueError):
    """A citation note that cannot be written, with a message the caller can show."""


def _brief(c: dict[str, Any]) -> dict[str, Any]:
    return {"uid": c["uid"], "title": c["title"], "type": c["type"], "year": c.get("year") or "", "authors": c.get("authors") or [],
            "display": db.format_citation_display(c)}


class _Walk:
    def __init__(self, conn: sqlite3.Connection):
        self.conn, self.style = conn, db.get_citation_format(conn)
        self.last: str | None = None
        self.used: set[str] = set()

    def citation(self, uid: str) -> dict[str, Any]:
        c = db.get_citation(self.conn, uid)
        if c is None:
            raise CiteError(f"No citation with uid {uid}; list_citations lists the library")
        return c

    def marker(self, match: re.Match) -> str:
        attrs = dict(ATTR.findall(match.group(1)))
        if "cdx-footnote-ref" not in attrs.get("class", ""):
            return match.group(0)
        if "data-cite" not in attrs:
            self.remember(attrs)
            return match.group(0)
        spec = json.loads(html.unescape(attrs.pop("data-cite")))
        main = self.citation(spec["uid"])
        secondary = self.citation(spec["secondary"]) if spec["secondary"] else None
        mode, page = spec["mode"], spec["page"].strip()
        if mode == "apud" and secondary is None:
            raise CiteError("apud needs two sources: [apud @original in @secondary, page]")
        if mode == "auto":
            kind = "ibidem" if self.last == main["uid"] else "opere_citato" if main["uid"] in self.used else "page_citation"
        else:
            kind = MODE_KINDS[mode]
        text = citation_formats.repeated(kind, main, self.style, page, secondary=secondary)
        if kind == "apud":
            data: dict[str, Any] = {"citations": {"original": _brief(main), "secondary": _brief(secondary)}, "page": page}
        else:
            data = {"citation": _brief(main), "page": page}
        self.last = main["uid"] if kind in SINGLE_KINDS else None
        self.used.update({main["uid"]} | ({secondary["uid"]} if secondary else set()))
        attrs.update({"data-note": html.escape(text, quote=True), "data-footnote-kind": kind,
                      "data-footnote-data": html.escape(json.dumps(data), quote=True)})
        return "<sup " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "></sup>"

    def remember(self, attrs: dict[str, str]) -> None:
        """A marker already in the note: counts as the previous note for Ibid. and its sources as used."""
        try:
            data = json.loads(html.unescape(attrs.get("data-footnote-data", "")) or "{}")
        except ValueError:
            data = {}
        single = data.get("citation") or {}
        pair = data.get("citations") or {}
        uids = {c.get("uid") for c in (single, pair.get("original") or {}, pair.get("secondary") or {}) if c.get("uid")}
        self.used |= uids
        self.last = single.get("uid") if attrs.get("data-footnote-kind") in SINGLE_KINDS else None

    def walk(self, value: Any) -> Any:
        if isinstance(value, str):
            return SUP.sub(self.marker, value) if "cdx-footnote-ref" in value else value
        if isinstance(value, list):
            return [self.walk(v) for v in value]
        if isinstance(value, dict):
            return {k: self.walk(v) for k, v in value.items()}
        return value


def resolve(conn: sqlite3.Connection, blocks: list[dict[str, Any]]) -> None:
    """Fills every pending citation note in `blocks`, in document order, so Ibid. and op. cit. follow what came before."""
    if not any("data-cite=" in json.dumps(b) for b in blocks):
        return
    walker = _Walk(conn)
    blocks[:] = [walker.walk(b) for b in blocks]
