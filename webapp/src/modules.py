"""The modules that plug into the app: each has a key, a title and the Settings page that owns what it manages.

A module registers itself once (`register`) and may add a page type (`register_page_type`) that a shelf can use, with its own
render function, and a Settings entry under Modules. A module that manages a shelf marks it (`label_config.managed_by`); the
shared shelf and tag edit functions then refuse changes from anyone else (`tags.assert_writable`). The app holds no
module-specific code. A module is off unless it is listed in the `CC_MODULES` environment variable (comma separated keys).
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


def enabled_keys() -> set[str]:
    return {k.strip() for k in os.environ.get("CC_MODULES", "").split(",") if k.strip()}


def is_enabled(key: str) -> bool:
    return key in MODULES and key in enabled_keys()


def settings_items() -> list[tuple[str, str]]:
    """The Settings entries of the enabled modules, as (title, url)."""
    return [(m.title, m.settings_url) for m in MODULES.values() if m.key in enabled_keys()]


def page_types() -> dict[str, str]:
    """Page type key to label for the enabled modules' page types."""
    return {k: p.label for k, p in PAGE_TYPES.items() if p.module in enabled_keys()}
