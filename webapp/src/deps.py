"""FastAPI dependencies shared by all routers: a per-request SQLite
connection (reads/most-writes go through the cache) and the app-wide
CalDavBridge singleton (writes go through this to reach Radicale)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from . import db
from .caldav_bridge import CalDavBridge

# app_meta keys for the two general-purpose display preferences added
# 2026-08-08 (Settings > General) -- both read via the memoized helper
# below rather than routers/settings.py threading them through every
# single calendar/schedule route's own context dict, same reasoning as
# sidebar_spaces() above: these two affect pages all over the app (Month/
# Week/Day/Agenda, Schedule, every dashboard widget that shows a time),
# and "add week_start/time_format to this route's context too" is exactly
# the kind of easy-to-miss-one-of duplication that would drift the moment
# one call site is missed.
WEEK_START_KEY = "calendar_week_start"
TIME_FORMAT_KEY = "display_time_format"
# 2026-08-09 -- "Show icons next to labels" (Settings > Appearance) -- a
# third app-wide display preference, same memoized-read pattern as the
# two above. Off by default ("", which is exactly an existing install's
# state: nothing was ever written here), "1" when on.
SHOW_LABEL_ICONS_KEY = "show_label_icons"
# 2026-08-11 -- "4-Week view: current week" (Settings > General) -- which
# row of the Calendar 4-Week view's four week rows the current week (the
# week containing today, or the anchor date) occupies: "1".."4", default
# "1" (current week on the first row -- what an existing install that has
# never touched this sees, and the least surprising "the period I'm in
# starts at the top" layout). Read by routers/calendar.py's four_week_view
# via _four_week_position below; written by routers/settings.py's
# set_four_week_position.
FOUR_WEEK_POSITION_KEY = "calendar_four_week_position"
# 1.6 ("Configurable terminology", open-priority.md § Schedule &
# recurrence rework): "standard" (default) or "playful" -- which set of
# labels the recurrence editor's holiday-calendar/weekend-exclusion
# controls use. Presentation-layer only, per the spec: "the database,
# APIs, synchronization logic, and internal documentation keep neutral
# terminology" -- the underlying fields (holiday_calendar/exclude_
# saturday/exclude_sunday) never change name or meaning; only their
# on-screen label does. Same memoized app_meta pattern as every other
# display preference here.
RECURRENCE_TERMINOLOGY_KEY = "recurrence_terminology"
# 2026-08-14 -- "Show the Relations card" (Settings > Appearance) -- whether
# the Relations card renders on task/event detail and edit modals (the merged
# Relations/subtasks card, _task_relations.html/_event_relations.html). Same
# memoized app_meta pattern as the others; the default is ON ("1" -- an
# install that's never touched this stores nothing, which reads as the
# default and shows the card, matching the behavior that predates the
# setting), "0" hides it.
SHOW_RELATIONS_CARD_KEY = "show_relations_card"

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


def _sidebar_spaces(request: Request) -> list[dict]:
    """Every Space (generate_space=1 label) for the nav rail's own sidebar
    list (base.html, 2026-08-08) -- registered as a Jinja global (like
    icon()/static_url()/avatar() above) rather than threaded through every
    single router's own context dict, since base.html renders on literally
    every page in the app and adding this to every one of those routers'
    return values would be exactly the kind of easy-to-miss-one-of
    duplication this app avoids elsewhere (see app.js's dashboard masonry
    comment on the same principle). Opens its own short-lived connection
    off `request.app.state.settings.db_path` -- the same value get_db's
    own per-request connection already uses -- rather than depending on
    whatever `conn` a given route happens to have already opened, since
    this needs to work identically regardless of which route is
    rendering.

    2026-08-08 follow-up: this used to be a *pinned* subset (a separate
    per-label opt-in flag on top of generate_space) -- removed same-day
    per direct feedback: a label worth turning into a Space is a label
    worth finding quickly, so a second manual step just to make it show
    up in the rail was friction with no real benefit. Every Space shows
    here now, no pin/unpin step at all -- this is just db.list_space_labels.

    Broad try/except is deliberate, not sloppy: `request.app` doesn't
    exist on the bare `Request({...})` objects this app's own test suite
    constructs by hand (no ASGI `app` in their scope dict) -- every one of
    those tests renders templates that extend base.html, so a hard
    failure here would break the entire test suite, not just tests that
    care about the sidebar. Any other failure (a mid-migration database, a
    locked file) degrades the same way: an empty rail section, not a
    broken page load -- the sidebar is a shortcut, not something any page
    depends on to render at all."""
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            return db.list_space_labels(conn)
    except Exception:
        return []


templates.env.globals["sidebar_spaces"] = _sidebar_spaces


def _cached_app_meta(request: Request, key: str, default: str) -> str:
    """Reads one app_meta value, memoized on `request.state` for the rest
    of that single request -- week_start()/time_format() below (and the
    fmt_time/fmt_hour filters, which call time_format() once per event/
    hour-label rendered) would otherwise open a fresh sqlite connection
    once per call, which on a page showing dozens of events is dozens of
    redundant round trips for a value that cannot change mid-request.
    `request.state` is a plain per-request namespace (Starlette), safe to
    stash arbitrary attributes on -- nothing here persists across
    requests. Same broad try/except + graceful default as sidebar_spaces()
    above, for the same reason (this app's own test suite constructs bare
    `Request({...})` objects with no real ASGI `app` in scope)."""
    cache_attr = "_cc_app_meta_cache"
    cache = getattr(request.state, cache_attr, None)
    if cache is None:
        cache = {}
        setattr(request.state, cache_attr, cache)
    if key in cache:
        return cache[key]
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            value = db.get_app_meta(conn, key) or default
    except Exception:
        value = default
    cache[key] = value
    return value


def _four_week_position_from_value(value: str | None) -> int:
    """Shared parse for the "4-Week view: current week" position
    (Settings > General, 2026-08-11): "1".."4" -> 1..4, anything else
    (unset, tampered, an old DB that never wrote it) -> 1, the default
    (current week on the first row). Used by both _four_week_position
    below (the per-request reader) and routers/settings.py (the setting's
    own page context + POST validation), so the two can't drift on what a
    bad value means."""
    try:
        pos = int(value)
    except (TypeError, ValueError):
        return 1
    return pos if 1 <= pos <= 4 else 1


def _four_week_position(request: Request) -> int:
    """Which of the four rows the Calendar 4-Week view's current week
    occupies (1-4) -- read by routers/calendar.py's four_week_view to
    compute where the 28-day window starts relative to the anchor week."""
    return _four_week_position_from_value(_cached_app_meta(request, FOUR_WEEK_POSITION_KEY, "1"))


def _week_start(request: Request) -> str:
    """"monday" (default, matches this app's original hardcoded behavior
    -- an existing install with nothing ever set here sees no change) or
    "sunday". Read by routers/calendar.py's month/week grid builders
    (_week_bounds/_month_grid) and calendar_month.html's weekday header
    order."""
    return _cached_app_meta(request, WEEK_START_KEY, "monday")


templates.env.globals["week_start"] = _week_start


def _time_format(request: Request) -> str:
    """"24h" (default, matches this app's original hardcoded HH:MM
    display) or "12h". Exposed as a Jinja global (for the rare template
    that needs the raw value, e.g. base.html's `data-time-format` body
    attribute for static/calendar.js's/schedule_grid.js's drag-preview
    labels) -- most templates should use the `fmt_time`/`fmt_hour`
    filters below instead of calling this directly."""
    return _cached_app_meta(request, TIME_FORMAT_KEY, "24h")


templates.env.globals["time_format"] = _time_format


def _show_label_icons(request: Request) -> bool:
    """Whether label icons render next to label names (Settings >
    Appearance's "Show icons next to labels", 2026-08-09). Reads the
    app_meta flag via the same per-request-memoized helper as
    week_start()/time_format(). Off is the default: labels show as
    plain text pills until the user turns the toggle on."""
    return _cached_app_meta(request, SHOW_LABEL_ICONS_KEY, "") == "1"


templates.env.globals["show_label_icons"] = _show_label_icons


def _recurrence_terminology(request: Request) -> str:
    """"standard" (default) or "playful" -- see RECURRENCE_TERMINOLOGY_KEY
    above. Read by _event_form_fields.html/schedule_classes.html/schedule_
    class_form.html to pick which label set the holiday-calendar/weekend-
    exclusion controls display; never read by any router or db.py
    accessor, since the fields themselves are unaffected."""
    return _cached_app_meta(request, RECURRENCE_TERMINOLOGY_KEY, "standard")


templates.env.globals["recurrence_terminology"] = _recurrence_terminology


def _show_relations_card(request: Request) -> bool:
    """Whether the Relations card renders on task/event detail and edit
    modals (Settings > Appearance's "Show the Relations card", 2026-08-14).
    Reads the app_meta flag via the same per-request-memoized helper as
    week_start()/time_format(). On by default -- an install that has never
    touched this stores nothing, which reads as the default "1" and shows
    the card exactly as it always has; "0" hides it."""
    return _cached_app_meta(request, SHOW_RELATIONS_CARD_KEY, "1") == "1"


templates.env.globals["show_relations_card"] = _show_relations_card


def _label_icon(request: Request, label: str) -> str:
    """The icon name (e.g. "star") a label should render next to its
    name, or "" when there is none -- the one helper every label pill
    uses so the setting is honored in exactly one place. Honors the
    toggle: when "Show icons next to labels" is off (the default), this
    always returns "" so every label pill collapses to its plain name
    regardless of whether the label has an icon assigned. When on, it
    returns the label's assigned icon from `label_config` (matched case-
    insensitively, since labels are deduped case-insensitively), or ""
    if the label has none -- a label without an icon stays text-only.
    Resolved icons are memoized on `request.state` per request (labels
    repeat heavily on Tasks/Calendar pages; a cached lookup makes the
    second and third mention of the same label free). Same broad
    try/except + graceful "" as sidebar_spaces() above, for the same
    reason (this app's own test suite constructs bare Request({...})
    objects with no real ASGI app in scope)."""
    if not _show_label_icons(request):
        return ""
    cache_attr = "_cc_label_icon_cache"
    cache = getattr(request.state, cache_attr, None)
    if cache is None:
        cache = {}
        setattr(request.state, cache_attr, cache)
    if label in cache:
        return cache[label]
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            cfg = db.effective_label_config_ci(conn, label or "")
            icon_name = cfg.get("icon") or ""
    except Exception:
        icon_name = ""
    cache[label] = icon_name
    return icon_name


templates.env.globals["label_icon"] = _label_icon


def _format_time_value(value: str, fmt: str) -> str:
    """Shared formatting core for the two filters below -- accepts either
    a full ISO datetime ("2026-08-08T14:30:00") or a bare "HH:MM" string
    (schedule_classes.html's start_time/end_time columns store just the
    latter). Anything that doesn't parse as a plausible HH:MM is returned
    unchanged rather than raising -- a display filter degrading to "the
    original value" on bad input is a much smaller problem than a broken
    page."""
    if not value:
        return ""
    time_part = value[11:16] if "T" in value else value[:5]
    if len(time_part) < 4 or time_part[2] != ":":
        return value
    try:
        hh = int(time_part[:2])
        mm = time_part[3:5]
        int(mm)
    except ValueError:
        return value
    if fmt != "12h":
        return f"{hh:02d}:{mm}"
    period = "AM" if hh < 12 else "PM"
    hh12 = hh % 12 or 12
    return f"{hh12}:{mm} {period}"


@pass_context
def _fmt_time(ctx, value: str) -> str:
    """Jinja filter: `{{ e.start_at | fmt_time }}` instead of the old
    `{{ e.start_at[11:16] }}` slicing repeated across every calendar/
    schedule/widget template -- reads the "24-hour time" Settings >
    General preference via the request already in every template's own
    context (Jinja2Templates always injects "request"), so call sites
    don't need to separately fetch and pass the format themselves.
    `@pass_context` is what gives a *filter* (normally just a plain
    value-in-value-out function) access to that context at all."""
    request = ctx.get("request")
    fmt = _time_format(request) if request is not None else "24h"
    return _format_time_value(value, fmt)


templates.env.filters["fmt_time"] = _fmt_time


@pass_context
def _fmt_hour(ctx, hour: int) -> str:
    """Jinja filter for the time-grid gutter labels (Calendar Week/Day,
    Schedule) -- `{{ h | fmt_hour }}` instead of `"%02d:00"|format(h)`,
    same 24h/12h preference as fmt_time above, just for a bare hour
    integer (0-23) rather than a stored time value."""
    request = ctx.get("request")
    fmt = _time_format(request) if request is not None else "24h"
    if fmt != "12h":
        return f"{hour:02d}:00"
    period = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12} {period}"


templates.env.filters["fmt_hour"] = _fmt_hour


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with db.connect(request.app.state.settings.db_path) as conn:
        yield conn


def get_bridge(request: Request) -> CalDavBridge:
    return request.app.state.bridge
