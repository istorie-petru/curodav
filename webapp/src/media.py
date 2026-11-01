"""Media kinds, tracking statuses, progress and the custom rating math; no database access.

Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    icon: str
    verb: str  # read, watch, play or listen
    unit: str  # pages, chapters, volumes, episodes or none
    uploads: bool = False
    link: bool = True
    screen: bool = False  # a film, series or anime: no editions, publisher or ISBN
    custom: bool = False
    types: tuple[str, ...] = field(default=())


VERBS = {
    "read": ("To read", "Reading", "Read"),
    "watch": ("To watch", "Watching", "Watched"),
    "play": ("To play", "Playing", "Played"),
    "listen": ("To listen", "Listening", "Listened"),
}
UNITS = {"pages": "Pages", "chapters": "Chapters", "volumes": "Volumes", "episodes": "Episodes", "hours": "Hours", "none": "None"}
ICONS = ("book-open", "book", "film", "tv", "monitor", "gamepad-2", "music", "headphones", "mic", "newspaper", "star", "folder")

BUILTIN = {
    "book": Kind("book", "Book", "book-open", "read", "pages", uploads=True),
    "manga": Kind("manga", "Manga", "book", "read", "chapters", uploads=True),
    "article-journal": Kind("article-journal", "Article", "newspaper", "read", "pages"),
    "film": Kind("film", "Film", "film", "watch", "none", screen=True),
    "tv": Kind("tv", "TV series", "tv", "watch", "episodes", screen=True),
    "anime": Kind("anime", "Anime", "monitor", "watch", "episodes", screen=True),
}
# The remaining citation types keep their old meaning: read, link only.
_READ_TYPES = {"chapter": "Book chapter", "webpage": "Web page", "thesis": "Thesis", "report": "Report",
               "conference-paper": "Conference paper", "other": "Other"}

STATUS_KEYS = ("planned", "current", "paused", "finished", "dropped")
NEUTRAL_STATUSES = [("planned", "Planned"), ("current", "In progress"), ("paused", "On hold"), ("finished", "Finished"), ("dropped", "Dropped"), ("none", "No status")]
_LEGACY_STATUS = {"to_read": "planned", "reading": "current", "read": "finished"}
CUSTOM_PREFIX = "custom:"

SCALES = {
    "stars5": ("5 stars", 5, 1.0),
    "stars5half": ("5 stars with halves", 5, 0.5),
    "points10": ("10 points", 10, 1.0),
    "points100": ("100 points", 100, 1.0),
}
DEFAULT_SCALE = "stars5"


def kind_for(type_key: str, custom_kinds: dict[str, dict[str, Any]] | None = None) -> Kind:
    """The kind of a citation type: a built-in one, a custom one (`custom:<uid>`) or a plain reading type."""
    if type_key in BUILTIN:
        return BUILTIN[type_key]
    if type_key.startswith(CUSTOM_PREFIX):
        row = (custom_kinds or {}).get(type_key.removeprefix(CUSTOM_PREFIX))
        if row:
            return Kind(type_key, row["name"], row.get("icon") or "folder", row.get("verb") or "read", row.get("unit") or "none", custom=True)
        return Kind(type_key, "Other", "folder", "read", "none", custom=True)
    return Kind(type_key or "other", _READ_TYPES.get(type_key, "Other"), "book-open", "read", "pages" if type_key in ("chapter", "thesis", "report") else "none")


def status_label(status: str, verb: str = "read") -> str:
    planned, current, finished = VERBS.get(verb, VERBS["read"])
    return {"planned": planned, "current": current, "finished": finished, "paused": "On hold", "dropped": "Dropped"}.get(status, "No status")


def status_options(verb: str = "read") -> list[tuple[str, str]]:
    return [("", "No status"), *((k, status_label(k, verb)) for k in STATUS_KEYS)]


def normal_status(value: str) -> str:
    value = _LEGACY_STATUS.get(value or "", value or "")
    return value if value in STATUS_KEYS else ""


def parse_count(value: Any) -> int:
    try:
        n = int(str(value).strip() or 0)
    except ValueError:
        return 0
    return max(0, min(n, 1_000_000))


def advance(row: dict[str, Any], step: int, today: str) -> dict[str, Any]:
    """The tracking fields after moving progress by `step`: starting marks it current, reaching the total finishes it."""
    total = row.get("progress_total") or 0
    progress = max(0, (row.get("progress") or 0) + step)
    if total:
        progress = min(progress, total)
    out = {"progress": progress, "status": row.get("status") or "", "started_on": row.get("started_on") or "", "finished_on": row.get("finished_on") or ""}
    if progress and out["status"] in ("", "planned", "paused"):
        out["status"] = "current"
    if progress and not out["started_on"]:
        out["started_on"] = today
    if total and progress >= total and out["status"] != "finished":
        out["status"] = "finished"
        out["finished_on"] = out["finished_on"] or today
    return out


def on_status_change(old: dict[str, Any], status: str, today: str) -> dict[str, Any]:
    """Dates and progress that follow a status picked by hand."""
    out: dict[str, Any] = {}
    if status == "current" and not old.get("started_on"):
        out["started_on"] = today
    if status == "finished":
        if not old.get("finished_on") or old.get("status") != "finished":
            out["finished_on"] = today
        if old.get("progress_total"):
            out["progress"] = old["progress_total"]
        if not old.get("started_on"):
            out["started_on"] = today
    return out


def percent(progress: int, total: int) -> int:
    return round(100 * min(progress, total) / total) if total else 0


def to_scale(value: float | None, scale: str) -> float | None:
    """A stored 0 to 100 value in the chosen scale, rounded to its step."""
    if value is None:
        return None
    _, top, step = SCALES.get(scale, SCALES[DEFAULT_SCALE])
    raw = value * top / 100
    return round(math.floor(raw / step + 0.5 + 1e-9) * step, 2)


def from_scale(value: Any, scale: str) -> float | None:
    """A value typed or picked in the chosen scale, stored as 0 to 100; blank or 0 is no rating."""
    try:
        number = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    _, top, _ = SCALES.get(scale, SCALES[DEFAULT_SCALE])
    if number <= 0:
        return None
    return round(min(number, top) * 100 / top, 4)


def scale_choices(scale: str) -> list[tuple[str, str]]:
    """The values a dropdown offers for one rating in the chosen scale, best first; 100 points is typed instead."""
    _, top, step = SCALES.get(scale, SCALES[DEFAULT_SCALE])
    if top > 10:
        return []
    values, v = [], top
    while v >= step - 1e-9:
        values.append(v)
        v -= step
    return [("", "None"), *((format_value(x), format_value(x)) for x in values)]


def format_value(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def overall(manual: float | None, criteria: list[dict[str, Any]], values: dict[str, float]) -> float | None:
    """The overall rating: the weighted mean of the criteria that have a value (two and three stars make two and a half), else the one set by hand."""
    total = weight = 0.0
    for c in criteria:
        v = values.get(c["uid"])
        if v is not None and c.get("weight", 1) > 0:
            total += v * c["weight"]
            weight += c["weight"]
    return round(total / weight, 4) if weight else manual


def criteria_for(criteria: list[dict[str, Any]], type_key: str) -> list[dict[str, Any]]:
    """The criteria that apply to a kind: those naming it, and those naming no kind at all."""
    return [c for c in criteria if not c.get("kinds") or type_key in c["kinds"]]


def stars(value: float | None, scale: str) -> str:
    """The overall rating as text for a row: stars for star scales, "7 / 10" for points."""
    shown = to_scale(value, scale)
    if shown is None:
        return ""
    _, top, _ = SCALES.get(scale, SCALES[DEFAULT_SCALE])
    if top == 5:
        full = int(shown)
        return "★" * full + ("½" if shown - full >= 0.5 else "")
    return f"{format_value(shown)} / {top}"


_UNIT_WORDS = {"pages": ("p.", "pages"), "chapters": ("Ch.", "chapters"), "volumes": ("Vol.", "volumes"), "episodes": ("E", "episodes"), "hours": ("", "h")}


def progress_text(c: dict[str, Any], kind: Kind) -> str:
    """Progress as an orientative percent ("31%"), or for a film the day it was watched."""
    done, total = c.get("progress") or 0, c.get("progress_total") or 0
    if kind.unit == "none":
        finished = c.get("finished_on") or ""
        return f"{VERBS[kind.verb][2]} {finished}" if c.get("status") == "finished" and finished else ""
    if total:
        return f"{percent(done, total)}%"
    return f"{done}%" if done else ""


def step_words(delta: int, kind: Kind) -> str:
    """One day of the progress log: "+10%", "-10%"."""
    return f"{'+' if delta > 0 else ''}{delta}%"
