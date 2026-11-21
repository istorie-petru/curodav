"""The in-app book reader: its settings (kept in the Library settings), where each book was left off, and what formats it draws as pages.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import db

PAGED_FORMATS = ("epub", "mobi", "azw3", "azw", "fb2", "cbz", "pdf")
COMIC_FORMATS = ("cbz", "cbr", "cb7")  # in the order the reader prefers them

SETTINGS = {
    "font_size": ("Text size", "100", [("85", "85%"), ("100", "100%"), ("115", "115%"), ("130", "130%"), ("150", "150%"), ("175", "175%")]),
    "line_height": ("Spacing", "1.6", [("1.3", "1.3"), ("1.45", "1.45"), ("1.6", "1.6"), ("1.75", "1.75"), ("1.9", "1.9")]),
    "font": ("Font", "book", [("book", "The book's own"), ("serif", "Serif"), ("sans", "Sans"), ("mono", "Mono")]),
    "margin": ("Margins", "6", [("0", "None"), ("3", "Small"), ("6", "Normal"), ("10", "Wide"), ("15", "Wider")]),
    "brightness": ("Brightness", "100", [("50", "50%"), ("60", "60%"), ("70", "70%"), ("80", "80%"), ("90", "90%"), ("100", "100%")]),
    "theme": ("Theme", "app", [("app", "App"), ("light", "Light"), ("sepia", "Sepia"), ("dark", "Dark")]),
    "pdf_zoom": ("PDF zoom", "fit-page", [("fit-page", "Fit page"), ("fit-width", "Fit width")]),
    "layout": ("Layout", "auto", [("auto", "Auto"), ("single", "Single"), ("scrolled", "Scrolled")]),
    "direction": ("Comic direction", "auto", [("auto", "By kind"), ("ltr", "Left to right"), ("rtl", "Right to left")]),
    "voice": ("Read-aloud voice", "server", [("server", "The server's"), ("browser", "The browser's")]),
    "justify": ("Full justification", "on", [("on", "On"), ("off", "Off")]),
    "hyphenate": ("Auto-hyphenation", "on", [("on", "On"), ("off", "Off")]),
}
_PREFIX = "reader_"


def settings(conn: sqlite3.Connection) -> dict[str, str]:
    out = {}
    for key, (_, default, choices) in SETTINGS.items():
        value = db.get_app_meta(conn, _PREFIX + key) or default
        out[key] = value if value in [c[0] for c in choices] else default
    return out


def save_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    for key, (_, _, choices) in SETTINGS.items():
        if values.get(key) in [c[0] for c in choices]:
            db.set_app_meta(conn, _PREFIX + key, values[key])


def rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The settings as rows for the Library settings page: label, name, current value and the choices."""
    current = settings(conn)
    return [{"key": k, "label": label, "value": current[k], "choices": [{"uid": v, "name": n} for v, n in choices]}
            for k, (label, _, choices) in SETTINGS.items()]


def save_position(conn: sqlite3.Connection, citation_uid: str, cfi: str, fraction: float) -> None:
    conn.execute("INSERT INTO book_reading_state (citation_uid, cfi, fraction, updated_at) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(citation_uid) DO UPDATE SET cfi = excluded.cfi, fraction = excluded.fraction, updated_at = excluded.updated_at",
                 (citation_uid, cfi[:2000], max(0.0, min(1.0, float(fraction))), datetime.now(timezone.utc).isoformat()))
    conn.commit()


def position(conn: sqlite3.Connection, citation_uid: str) -> dict[str, Any]:
    row = conn.execute("SELECT cfi, fraction FROM book_reading_state WHERE citation_uid = ?", (citation_uid,)).fetchone()
    return {"cfi": row["cfi"], "fraction": row["fraction"]} if row else {"cfi": "", "fraction": 0.0}


LOOKUPS = [
    ("wikipedia", "Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search=%s", True),
    ("wiktionary", "Wiktionary", "https://en.wiktionary.org/wiki/Special:Search?search=%s", True),
    ("merriam", "Merriam-Webster", "https://www.merriam-webster.com/dictionary/%s", False),
    ("cambridge", "Cambridge Dictionary", "https://dictionary.cambridge.org/search/english/direct/?q=%s", False),
    ("dexonline", "DEX online", "https://dexonline.ro/definitie/%s", False),
]
_LOOKUP_KEY = "reader_lookups"


def _saved_lookups(conn: sqlite3.Connection) -> dict[str, Any]:
    import json

    try:
        data = json.loads(db.get_app_meta(conn, _LOOKUP_KEY) or "{}")
    except ValueError:
        data = {}
    return {"state": data.get("state", {}), "custom": data.get("custom", [])}


def lookups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The places a selected word can be looked up: the built-in sources, then the ones added by hand, each on or off."""
    saved = _saved_lookups(conn)
    state = saved["state"]
    out = [{"key": k, "name": n, "url": u, "on": state.get(k, default), "custom": False} for k, n, u, default in LOOKUPS]
    out += [{"key": c["key"], "name": c["name"], "url": c["url"], "on": state.get(c["key"], True), "custom": True} for c in saved["custom"]]
    return out


def save_lookups(conn: sqlite3.Connection, on_keys: list[str], add_name: str = "", add_url: str = "", remove: str = "") -> str | None:
    """Saves which sources are on, and adds or removes a custom one; returns an error message, or None."""
    import json
    import uuid

    saved = _saved_lookups(conn)
    custom = [c for c in saved["custom"] if c["key"] != remove]
    error = None
    on = set(on_keys)
    if add_name.strip() or add_url.strip():
        url = add_url.strip()
        if not url.startswith(("https://", "http://")) or "%s" not in url:
            error = "The address must start with https:// and hold %s where the selected text goes"
        elif not add_name.strip():
            error = "Give the source a name"
        else:
            key = "c" + uuid.uuid4().hex[:8]
            custom.append({"key": key, "name": add_name.strip()[:60], "url": url[:500]})
            on.add(key)
    state = {k: (k in on) for k, *_ in LOOKUPS}
    state.update({c["key"]: (c["key"] in on) for c in custom})
    db.set_app_meta(conn, _LOOKUP_KEY, json.dumps({"state": state, "custom": custom}))
    return error
