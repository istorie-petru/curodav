"""FastAPI dependencies shared by all routers: a per-request SQLite
connection (reads/most-writes go through the cache) and the app-wide
CalDavBridge singleton (writes go through this to reach Radicale)."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from . import db, habit_heatmap
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
# 2026-08-28 -- "Habit streak terminology" (Settings > General) -- "standard"
# (default) or "playful" wording for the Habits group's streak readout
# (Tasks table, _habit_row.html). Same presentation-layer-only pattern as
# RECURRENCE_TERMINOLOGY_KEY above (1.6): the underlying current_streak
# integer (habit_heatmap.streaks) never changes, only how it's phrased --
# see habit_heatmap.streak_text for the actual wording.
HABIT_STREAK_TERMINOLOGY_KEY = "habit_streak_terminology"
# 2026-08-29 (sidebar redesign item 13d) -- "Edit mode" (Settings >
# Appearance): whether the widget grid's edit controls (move/resize/
# reorder/delete a widget, New widget, Reset layout, Add/Change banner)
# show on every dashboard/label/Space page. Used to be a per-page
# `?edit=1` query param with its own "Edit mode"/"Done" toggle buttons on
# dashboard.html/label_detail.html; replaced by this single persistent,
# app-wide setting (routers/settings.py's set_edit_mode), read straight
# off app_meta by routers/dashboard.py::widget_page_context -- no
# per-request-memoized global registered here, unlike the other keys
# above: nothing outside the three widget-grid pages needs it.
EDIT_MODE_KEY = "edit_mode_enabled"
# 2026-08-29 (sidebar redesign item 13e follow-up, direct request) -- the
# Standard Page Header's own optional banner image, set once in Settings >
# Appearance and reused as the background on every standard page's narrow
# header (Tasks/Calendar/Planner/Contacts/Search/Notes/Settings/Labels/
# Published Lists -- see _page_header_narrow.html). Not a per-page banner
# like Home/label pages have (db.get_page_banner/set_page_banner's own
# `page_key` is just a free-form string, "" for Home / the label name for
# a label page) -- this is one more `page_key`, a fixed sentinel picked to
# never collide with a real label name. Reuses the *entire* existing
# banner editor/upload/remove machinery (routers/banners.py) unchanged --
# `/banners/editor?scope=__page_header__&page_url=/settings/appearance`
# is a real, working banner scope with no new routes needed.
#
# 2026-09-07: the literal now lives in db.py (db.PAGE_HEADER_BANNER_SCOPE)
# instead of here -- db.banner_for_object needed it for the new task/event
# season/default banner fallback, and db.py can't import deps.py (deps.py
# already imports db, so the reverse would be circular). Re-exported under
# the same name so every existing `from ..deps import
# PAGE_HEADER_BANNER_SCOPE` call site is unaffected.
PAGE_HEADER_BANNER_SCOPE = db.PAGE_HEADER_BANNER_SCOPE
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


@pass_context
def _csp_nonce(ctx) -> str:
    """`{{ csp_nonce() }}` for every real inline `<script>`/`<style>` tag
    left in the templates (audit-fixes-2.0.md item 11 -- CSP's script-src/
    style-src moved off `'unsafe-inline'` onto nonces). Registered as a
    Jinja global rather than templates reaching into `request.state`
    directly, same reasoning as `icon`/`static_url` above: one place to
    read from, and it stays usable from a child template that only
    `{% extends %}` base.html. `SecurityHeadersMiddleware` (security_
    headers.py) is what actually generates the nonce and stashes it on
    `scope["state"]["csp_nonce"]` before this app even runs -- by the
    time a template renders, `request.state.csp_nonce` is always already
    set for every real HTTP request. Only falls back to `""` for the rare
    context with no nonce at all (e.g. a template rendered directly in a
    unit test with a hand-built request, no SecurityHeadersMiddleware in
    the stack) rather than raising -- a missing nonce there just means
    the rendered tag's `nonce=""` attribute won't match any real CSP
    header, not a reason to fail the render."""
    request = ctx.get("request")
    if request is None:
        return ""
    return getattr(request.state, "csp_nonce", "")


templates.env.globals["csp_nonce"] = _csp_nonce


# Same 16 names as routers/labels.py's COLORS -- not imported directly,
# since deps.py is imported by every router including labels.py itself
# (importing back would be circular); duplicated here as a short, stable
# list rather than restructuring the import graph just for this.
_STABLE_COLOR_NAMES = (
    "red", "orange", "yellow", "lime", "green", "mint", "teal", "cyan",
    "blue", "indigo", "purple", "magenta", "pink", "brown", "gray", "slate",
)


def _stable_color(seed: str) -> str:
    """Deterministic `.cal-*`/`--cal-accent-*` color name for something
    with no color of its own (2026-09-03, contact detail-view cover
    banner -- Variant B's baseline header treatment needs an accent for
    every entity type's gradient-fallback cover, but contacts have no
    color field the way events (calendar_color) and tasks (status) do.
    A flat neutral cover for every contact would read as "nothing was
    designed here"; a name-derived color instead gives each contact a
    stable, distinct identity across visits without adding a real color
    field/picker to the contact model. Seed on `contact.uid` (stable for
    the contact's lifetime), not `full_name` (would jump on a rename)."""
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return _STABLE_COLOR_NAMES[int(digest, 16) % len(_STABLE_COLOR_NAMES)]


templates.env.globals["stable_color"] = _stable_color


def _avatar(contact: dict | None, cls: str = "") -> Markup:
    """Renders a contact's (or the app user's own profile) avatar -- their
    uploaded photo if they have one, otherwise the same initials-in-a-
    circle fallback every avatar spot used before photos existed. One
    global (registered the same way as `icon()` above, for the same
    reason) instead of duplicating this if/else across contacts_list.html,
    contact_detail.html, contact_form.html's photo preview,
    settings_general.html's profile-picture row, and _page_banner.html's
    dashboard-header avatar -- all five now render the exact same markup
    for "this photo," which is the actual UI-consistency fix, not just
    five separately-hand-matched copies of similar-looking HTML.

    2026-08-29 (direct request: "better cache these images... convert...
    to webp or compress them") -- prefers a real, separately cacheable
    `photo_url` (routers/contacts.py's contact_photo_image / routers/
    settings.py's profile_photo_image, each `?v=`-versioned so an
    immutable Cache-Control is safe) over embedding the photo inline as a
    `data:` URI, which every caller here used to do unconditionally: that
    put the full base64 blob in the HTML of every page showing it (a
    contact list row, or -- worse -- the profile photo, rendered on every
    dashboard/label/Space page via the header avatar overlap), the exact
    "2MB inline blob made the page slow" problem routers/banners.py's own
    banner_image already existed to solve for banners. `photo_url` is set
    by each call site's own router (contacts.py/settings.py), not derived
    here -- this function has no way to know a contact's uid or whether a
    profile photo's version has been backfilled yet. Falls back to the
    inline `data:` URI when no `photo_url` is given (a brand-new, not-yet-
    saved contact has no uid to build a real URL from) or when `photo_b64`
    is present without one (defensive -- keeps working for any caller that
    hasn't been updated to attach `photo_url` yet)."""
    contact = contact or {}
    classes = f"avatar-circle {cls}".strip()
    photo_url = contact.get("photo_url")
    photo_b64 = contact.get("photo_b64")
    if photo_url:
        return Markup(f'<img class="{classes}" src="{escape(photo_url)}" alt="">')
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
    depends on to render at all.

    2026-08-29 (sidebar redesign slice 13a, plans/STATE.md): each space
    dict now also carries `children` -- `db.list_child_labels(conn,
    l["name"])`, the same parent_name relationship label_detail.html's own
    Space page already uses for its "Projects" section (a label pointing
    `parent_name` at a Space is, by that existing convention, one of its
    projects). Fetched inside the same connection/try-except as the
    spaces themselves rather than a second global, so the nested rail
    tree degrades exactly the same way (empty, not broken) under the same
    failure conditions."""
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            spaces = db.list_space_labels(conn)
            for space in spaces:
                space["children"] = db.list_child_labels(conn, space["name"])
            return spaces
    except Exception:
        return []


templates.env.globals["sidebar_spaces"] = _sidebar_spaces


def _sidebar_projects(request: Request) -> list[dict]:
    """Every *standalone* project (is_project=1 label with no parent_name)
    for the nav rail's own "Projects" section (base.html, 2026-08-29
    sidebar redesign follow-up -- plans/sidebar-redesign.md's source doc
    explicitly asks for Spaces/Projects/Private as separate group headers,
    which this app had no direct equivalent of: is_project=1 labels only
    ever showed up in the Tasks table's own Project grouping, never in the
    rail itself).

    Deliberately excludes any project whose parent_name points at a Space
    -- those already render nested under that Space via _sidebar_spaces'
    own `children` (label_edit_modal.html's parent_name dropdown only ever
    offers Space names as options, so "has a parent_name" and "nested
    under a Space elsewhere in the rail" are the same condition here).
    Showing a project in both places would be the exact kind of
    duplication this app avoids elsewhere -- see _sidebar_spaces' own
    docstring on the same principle.

    Same broad try/except + short-lived connection pattern as
    _sidebar_spaces above, for the same reasons (bare test Request objects
    with no `.app`, graceful empty-section degradation on any DB error)."""
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            return [p for p in db.list_project_labels(conn) if not p.get("parent_name")]
    except Exception:
        return []


templates.env.globals["sidebar_projects"] = _sidebar_projects


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


def _page_header_banner(request: Request) -> dict | None:
    """The Standard Page Header's own optional banner image (Settings >
    Appearance, 2026-08-29 sidebar redesign item 13e follow-up) -- see
    PAGE_HEADER_BANNER_SCOPE's own comment above. Same per-request-
    memoized-connection, broad-try/except-on-a-bare-test-Request pattern
    as _cached_app_meta below, but returns a banner dict (or None)
    straight from db.get_page_banner instead of a plain string, so it
    isn't built on top of that helper. Called by _page_header_narrow.html
    (imported `with context`, so `request` is in scope at the call site)
    -- every standard page gets this for free without its own route
    needing to fetch and thread it through its context dict."""
    cache_attr = "_cc_page_header_banner_cache"
    if hasattr(request.state, cache_attr):
        return getattr(request.state, cache_attr)
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            banner = db.get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE)
    except Exception:
        banner = None
    setattr(request.state, cache_attr, banner)
    return banner


templates.env.globals["page_header_banner"] = _page_header_banner


def _recurrence_terminology(request: Request) -> str:
    """"standard" (default) or "playful" -- see RECURRENCE_TERMINOLOGY_KEY
    above. Read by _event_form_fields.html/schedule_classes.html/schedule_
    class_form.html to pick which label set the holiday-calendar/weekend-
    exclusion controls display; never read by any router or db.py
    accessor, since the fields themselves are unaffected."""
    return _cached_app_meta(request, RECURRENCE_TERMINOLOGY_KEY, "standard")


templates.env.globals["recurrence_terminology"] = _recurrence_terminology


def _habit_streak_terminology(request: Request) -> str:
    """"standard" (default) or "playful" -- see HABIT_STREAK_TERMINOLOGY_KEY
    above. Read directly by settings_general.html's toggle; every other
    caller should use habit_streak_text() below instead of reading this
    and calling habit_heatmap.streak_text itself."""
    return _cached_app_meta(request, HABIT_STREAK_TERMINOLOGY_KEY, "standard")


templates.env.globals["habit_streak_terminology"] = _habit_streak_terminology


def _habit_streak_text(request: Request, days) -> str:
    """The Habits group's streak readout (_habit_row.html), phrased per
    HABIT_STREAK_TERMINOLOGY_KEY -- "3 day streak" (standard) or "This
    week has been full" (playful) for the same `current_streak` integer
    either way. `days` arrives as whatever _habit_group_items stored
    (an int already, but tolerate None/a stray float defensively rather
    than letting a template render crash on a bad value)."""
    try:
        days_int = int(days or 0)
    except (TypeError, ValueError):
        days_int = 0
    playful = _habit_streak_terminology(request) == "playful"
    return habit_heatmap.streak_text(days_int, playful)


templates.env.globals["habit_streak_text"] = _habit_streak_text


def _recurrence_label(rrule) -> str:
    """"Daily"/"Weekly"/"Monthly"/"Yearly"/"Custom" for an RRULE string --
    see habit_heatmap.recurrence_label's own docstring for why this never
    renders the raw "FREQ=DAILY" text. A plain jinja global (no request
    needed, unlike habit_streak_text) since the phrasing doesn't depend on
    any per-app terminology setting."""
    return habit_heatmap.recurrence_label(rrule)


templates.env.globals["recurrence_label"] = _recurrence_label


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


def _label_color(request: Request, label: str) -> str:
    """The `.cal-*` swatch name (e.g. "teal") a label's own pill should
    paint with -- the read side of the same `label_config.color` field
    the picker in `_color_swatch_picker.html` writes. Unlike `_label_icon`
    above, this is NOT gated behind the "Show icons next to labels"
    toggle -- color isn't an opt-in decoration, every label already has
    one (`_LABEL_CONFIG_DEFAULTS["color"]` is "blue", so an unconfigured
    label resolves to the same blue every `.cell-tag tag-blue` hardcode
    used to paint everywhere, before this existed -- purely additive for
    any label that's actually picked a color). Same per-request memoize +
    broad try/except-on-bare-Request pattern as `_label_icon`, own cache
    attr so the two never fight over one dict shape."""
    cache_attr = "_cc_label_color_cache"
    cache = getattr(request.state, cache_attr, None)
    if cache is None:
        cache = {}
        setattr(request.state, cache_attr, cache)
    if label in cache:
        return cache[label]
    try:
        with db.connect(request.app.state.settings.db_path) as conn:
            cfg = db.effective_label_config_ci(conn, label or "")
            color = cfg.get("color") or "blue"
    except Exception:
        color = "blue"
    cache[label] = color
    return color


templates.env.globals["label_color"] = _label_color


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


def _fmt_birthday(value: str | None) -> str:
    """Jinja filter for Contacts field parity slice 4 of 6 (Birthday) --
    `{{ contact.birthday | fmt_birthday }}` to render the stored raw
    "YYYY-MM-DD"/"--MM-DD" string as "May 17, 1990"/"May 17". No @pass_context
    needed (unlike fmt_time/fmt_hour) -- birthday display has no per-request
    Settings preference the way 24h/12h time format does, it's a pure
    function of the stored value (db.format_contact_birthday)."""
    return db.format_contact_birthday(value)


templates.env.filters["fmt_birthday"] = _fmt_birthday


def _relative_date(value: str | None) -> str:
    """Jinja filter for a short/relative date -- `{{ t.due_at[:10] |
    relative_date }}` instead of a raw "2026-09-05" (2026-08-31 direct
    feedback on the Dashboard's Agenda widget: "make the dates ...
    shorthand or relative"). Today/Tomorrow/Yesterday for the immediate
    cases (the ones worth naming instead of counting), otherwise "5 Sep"
    -- same day-drop-year-unless-different convention static/
    datetime_picker.js's own `.dtp--compact` fmtDate already established
    for the Tasks table's Date column (2026-08-30, praised then as "reads
    at a glance"); this is that same convention's server-rendered
    equivalent for read-only widget text rather than an editable picker's
    trigger label. No @pass_context needed (unlike fmt_time/fmt_hour) --
    pure function of the stored value and today's date, no per-request
    Settings preference involved. Expects a plain "YYYY-MM-DD" (or a
    longer ISO timestamp -- only the first 10 chars are read); anything
    that doesn't parse is returned unchanged, same "display filter
    degrades to the original value" rule as fmt_time/fmt_dt above."""
    if not value:
        return value
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return value
    today = date.today()
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    day_month = f"{d.day} {d.strftime('%b')}"
    return day_month if d.year == today.year else f"{day_month} {d.year}"


templates.env.filters["relative_date"] = _relative_date


def _format_datetime_value(value: str, fmt: str) -> str:
    """Shared formatting core for the fmt_dt filter below -- one stored ISO
    timestamp ("2026-08-25T20:57:05", UTC like every timestamp this app
    writes) rendered human-readably as "Aug 25, 2026, 8:57 PM" (12h pref)
    or "Aug 25, 2026, 20:57" (24h pref). Aware timestamps are converted to
    the server's local zone first (a backup made at 22:57 UTC should read
    as the wall-clock time it was actually made at); naive ones are taken
    as-is. Anything that doesn't parse is returned unchanged -- same
    "display filter degrades to the original value" rule as
    _format_time_value above."""
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    date_part = f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    hh = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    if fmt != "12h":
        return f"{date_part}, {dt.hour:02d}:{minute}"
    period = "AM" if dt.hour < 12 else "PM"
    return f"{date_part}, {hh}:{minute} {period}"


@pass_context
def _fmt_dt(ctx, value: str) -> str:
    """Jinja filter for whole-datetime display ("Aug 25, 2026, 8:57 PM")
    -- Data & Maintenance's backup facts (2026-08-26 redesign: all raw ISO
    timestamps on that page became human-readable ones). Same @pass_context
    12h/24h-preference read as fmt_time above."""
    request = ctx.get("request")
    fmt = _time_format(request) if request is not None else "24h"
    return _format_datetime_value(value, fmt)


templates.env.filters["fmt_dt"] = _fmt_dt


def _fmt_address(addr: dict) -> str:
    """Jinja filter for Contacts field parity slice 5 of 6 (Address) --
    `{{ a | fmt_address }}` to render one structured {"po_box", "extended",
    "street", "city", "region", "postal_code", "country"} dict as vCard's
    own multi-line address layout. Same "pure function of the stored
    value, no per-request Settings preference" shape as fmt_birthday above."""
    return db.format_contact_address(addr)


templates.env.filters["fmt_address"] = _fmt_address


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with db.connect(request.app.state.settings.db_path) as conn:
        yield conn


def get_bridge(request: Request) -> CalDavBridge:
    return request.app.state.bridge


# Async-CRUD dual-mode responses (features/async-crud.md): every mutation
# endpoint keeps its plain-HTML 303 Redirect default (a form works with no
# JS at all), but returns JSON when the request carries `X-Requested-With:
# fetch` (static/async_crud.js always sends it). Read via a FastAPI Header
# param (default None) rather than a Request object because this suite's
# direct-call tests invoke the router functions as plain Python functions
# without building a Request -- those keep getting the redirect default.
def wants_json(x_requested_with: str | None) -> bool:
    return x_requested_with == "fetch"


def respond(
    x_requested_with: str | None,
    redirect_url: str,
    *,
    status_code: int = 200,
    **payload,
):
    if wants_json(x_requested_with):
        return JSONResponse({"ok": True, **payload}, status_code=status_code)
    return RedirectResponse(url=redirect_url, status_code=303)
