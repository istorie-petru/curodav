"""Tag definitions and object-tag assignments (ARCHITECTURE.md §7.12)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Tag:
    id: str
    name: str
    color: str | None = None
    created_at: str = ""
    deleted_at: str | None = None
