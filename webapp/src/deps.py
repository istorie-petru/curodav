"""FastAPI dependencies shared by all routers: a per-request SQLite
connection (reads/most-writes go through the cache) and the app-wide
CalDavBridge singleton (writes go through this to reach Radicale)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import db
from .caldav_bridge import CalDavBridge

_BASE_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _BASE_DIR / "static"

templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _static_url(filename: str) -> str:
    """Cache-busting for static assets. Every template used to reference
    `/static/style.css`/`/static/app.js` etc. with no version string, so a
    browser that had already cached an old copy kept serving it until a
    hard refresh forced a bypass -- exactly the friction reported after a
    session of repeated CSS/JS edits. Appending the file's mtime as a
    query string means the *URL itself* changes the moment the file
    changes, so a normal (non-hard) reload always fetches the new version
    -- the browser has no way to conflate the old and new URLs.

    Deliberately re-stats the file on every call rather than caching the
    computed version in memory: this process doesn't run with `--reload`
    (see main.py's `uvicorn.run(..., reload=False)`), but static files are
    still served fresh off disk per-request regardless -- if the version
    string were computed once and cached, editing a static file while the
    server keeps running would serve new *content* at a URL that never
    changed, silently reintroducing the exact staleness this exists to
    fix. `Path.stat()` is a single cheap syscall, not a file read, so
    doing this per-request costs nothing meaningful at this app's scale.

    Falls back to an unversioned URL if the file can't be stat'd (e.g. a
    typo'd filename) rather than raising -- a missing query string just
    means "no cache-busting," not a reason to fail the whole page render.
    """
    try:
        version = int((_STATIC_DIR / filename).stat().st_mtime)
    except OSError:
        return f"/static/{filename}"
    return f"/static/{filename}?v={version}"


templates.env.globals["static_url"] = _static_url


def _icon(name: str, cls: str = "") -> Markup:
    """Renders a `<use>` reference into the sprite in
    templates/_icons_sprite.html (included once in base.html) -- registered
    as a Jinja global (rather than a per-template `{% from %} import`) so
    every template can call `{{ icon('trash') }}` with no per-file
    boilerplate, including ones that `{% extends %}` base.html (a child
    template's own top-level scope doesn't automatically inherit a parent
    template's macro imports, but Jinja globals are visible everywhere).
    See _icons_sprite.html's own header comment for why this is a local,
    inline sprite instead of an external icons.svg + cross-file <use>."""
    extra = f" {cls}" if cls else ""
    return Markup(f'<svg class="icon{extra}" aria-hidden="true"><use href="#icon-{name}"></use></svg>')


templates.env.globals["icon"] = _icon


def _avatar(contact: dict | None, cls: str = "") -> Markup:
    """Renders a contact's avatar -- their uploaded photo (data URI, from
    contacts.photo_b64/photo_type -- see vcard_rows.py) if they have one,
    otherwise the same initials-in-a-circle fallback every avatar spot
    used before photos existed. One global (registered the same way as
    `icon()` above, for the same reason) instead of duplicating this
    if/else across contacts_list.html, contact_detail.html, and
    contact_form.html's photo preview -- all three now render the exact
    same markup for "this contact's avatar," which is the actual
    UI-consistency fix, not just three separately-hand-matched copies of
    similar-looking HTML."""
    contact = contact or {}
    classes = f"avatar-circle {cls}".strip()
    photo_b64 = contact.get("photo_b64")
    if photo_b64:
        # `photo_type` is normally one of this app's own known-safe values
        # (routers/contacts.py's upload allowlist), but a contact synced in
        # from another CardDAV client could carry an arbitrary TYPE=...
        # param -- re-validate against the same fixed set rather than
        # trusting it into a `data:image/...` URI unescaped. `photo_b64`
        # itself is base64 (a fixed safe alphabet), so it doesn't need the
        # same treatment.
        photo_type = str(contact.get("photo_type") or "").lower()
        if photo_type not in ("jpeg", "png", "gif", "webp"):
            photo_type = "jpeg"
        return Markup(f'<img class="{classes}" src="data:image/{photo_type};base64,{escape(photo_b64)}" alt="">')
    initial = escape((contact.get("full_name") or "?")[:1].upper())
    return Markup(f'<span class="{classes}">{initial}</span>')


templates.env.globals["avatar"] = _avatar


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with db.connect(request.app.state.settings.db_path) as conn:
        yield conn


def get_bridge(request: Request) -> CalDavBridge:
    return request.app.state.bridge
