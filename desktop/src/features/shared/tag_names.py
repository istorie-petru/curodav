"""Process-wide cache of every tag name currently in use.

Refreshed once per data reload (`MainWindow._refresh_current_module`) from
the full object list, rather than each tag-entry field independently
querying the SQLite cache/Database -- powers autocomplete suggestions on
every place a tag gets typed (inspector, Table view's Tags cell, and
anywhere else `install_tag_completer` is wired up) without a DB handle
being threaded through each of them.
"""

from __future__ import annotations

_known_tags: set[str] = set()


def refresh_known_tags(objects) -> None:
    global _known_tags
    _known_tags = {t for o in objects for t in (getattr(o, "tags", None) or [])}


def known_tags() -> list[str]:
    return sorted(_known_tags)


def add_known_tag(name: str) -> None:
    """Make a brand-new tag suggestable immediately, without waiting for
    the next full object-list refresh (used right after a tag is created,
    e.g. from the Settings Tags tab)."""
    if name:
        _known_tags.add(name)
