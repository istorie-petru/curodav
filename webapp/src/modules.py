"""The modules that plug into the app: each has a key, a title and the Settings page that owns what it manages.

A module registers itself once (`register`) and may add a page type (`register_page_type`) that a shelf can use, with its own
render function, and a Settings entry under Modules. A module that manages a shelf marks it (`label_config.managed_by`); the
shared shelf and tag edit functions then refuse changes from anyone else (`tags.assert_writable`). The app holds no
module-specific code. A module is off until it is turned on in Settings, General (stored in the database), or listed in the `CC_MODULES`
environment variable (comma separated keys), which forces it on.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Module:
    key: str
    title: str
    settings_url: str
    icon: str = "puzzle"
    description: str = ""


@dataclass(frozen=True)
class PageType:
    key: str
    label: str
    module: str
    render: Callable[..., Any]  # render(conn, request, name, label) -> Response, for a shelf set to this page type


MODULES: dict[str, Module] = {}
PAGE_TYPES: dict[str, PageType] = {}


def register(module: Module) -> Module:
    MODULES[module.key] = module
    return module


def register_page_type(page_type: PageType) -> PageType:
    PAGE_TYPES[page_type.key] = page_type
    return page_type


def get(key: str) -> Module:
    return MODULES.get(key) or Module(key, key.capitalize(), "/settings")


STORE_KEY = "modules_enabled"
_stored: set[str] = set()  # the modules turned on in Settings, read from the database at start and kept in step by `set_enabled`


def forced_keys() -> set[str]:
    return {k.strip() for k in os.environ.get("CC_MODULES", "").split(",") if k.strip()}


def load_stored(conn) -> None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (STORE_KEY,)).fetchone()
    _stored.clear()
    _stored.update(k for k in ((row[0] if row else "") or "").split(",") if k)


def set_enabled(conn, key: str, on: bool) -> None:
    """Turns a module on or off for good: the choice is stored in the database and takes effect at once."""
    if key not in MODULES:
        raise KeyError(key)
    (_stored.add if on else _stored.discard)(key)
    conn.execute("INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (STORE_KEY, ",".join(sorted(_stored))))
    conn.commit()


def enabled_keys() -> set[str]:
    return forced_keys() | _stored


def is_enabled(key: str) -> bool:
    return key in MODULES and key in enabled_keys()


def settings_items() -> list[tuple[str, str]]:
    """The Settings entries of the enabled modules, as (title, url)."""
    return [(m.title, m.settings_url) for m in MODULES.values() if m.key in enabled_keys()]


def page_types() -> dict[str, str]:
    """Page type key to label for the enabled modules' page types."""
    return {k: p.label for k, p in PAGE_TYPES.items() if p.module in enabled_keys()}
