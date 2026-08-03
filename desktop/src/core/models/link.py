"""Associative links between objects (ARCHITECTURE.md §4.4)."""

from __future__ import annotations

from dataclasses import dataclass


class LinkType:
    related = "related"
    blocks = "blocks"
    references = "references"
    mentions = "mentions"


@dataclass
class Link:
    id: str
    from_id: str
    to_id: str
    link_type: str = LinkType.related
    created_at: str = ""
    deleted_at: str | None = None
