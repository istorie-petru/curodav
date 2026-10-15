"""Dashboard widgets, banners, page types and time blocks.

Part of the db package; src/db/__init__.py re-exports every name.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any
from .. import flairs

from .core import _SEASON_DATE_FIELD, get_app_meta, month_for_date, season_for_date, set_app_meta
from .labels import GROUP_KEY_PREFIX, ensure_group, get_group, get_label_config, project_label_for


# --------------------------------------------------------------------- #
# Sleep Time / Leisure Time (see time_blocks' own CREATE TABLE comment) --
# same minimal shape as the schedule_holidays functions directly above
# (plain dict rows, upsert-by-uid, explicit commit).
# --------------------------------------------------------------------- #

TIME_BLOCK_KINDS = ("sleep", "leisure")
TIME_BLOCK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def upsert_time_block(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO time_blocks (uid, kind, label, start_time, end_time, days) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET kind=excluded.kind, label=excluded.label, "
        "start_time=excluded.start_time, end_time=excluded.end_time, days=excluded.days",
        (row["uid"], row["kind"], row.get("label", ""), row["start_time"], row["end_time"], row.get("days", "")),
    )
    conn.commit()


def get_time_block(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM time_blocks WHERE uid = ?", (uid,)).fetchone()
    return dict(row) if row else None


def delete_time_block(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM time_blocks WHERE uid = ?", (uid,))
    conn.commit()


def list_time_blocks(conn: sqlite3.Connection, kind: str | None = None) -> list[dict[str, Any]]:
    if kind:
        rows = conn.execute("SELECT * FROM time_blocks WHERE kind = ? ORDER BY start_time", (kind,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM time_blocks ORDER BY kind, start_time").fetchall()
    return [dict(r) for r in rows]


def time_block_days(row: dict[str, Any]) -> list[str]:
    """`row['days']` ("Monday,Wednesday,Friday") split back into a list --
    the one place both the settings table and the overlay/warning code
    parse this field, so they can't drift on the separator."""
    return [d.strip() for d in (row.get("days") or "").split(",") if d.strip()]


PAGE_TYPES = ("sections", "dashboard", "secretariat")
PAGE_TYPE_LABELS = {"sections": "Sections", "dashboard": "Widget dashboard", "secretariat": "Secretariat"}
_LABEL_PAGE_TYPE_MIGRATED_KEY = "label_page_type_migrated_v1"
HOME_PAGE_TYPE_KEY = "home_page_type"


def migrate_label_page_type(conn: sqlite3.Connection) -> None:
    """Replaces the old has_dashboard flag with page_type, once. The old
    column stays on disk, unused."""
    if get_app_meta(conn, _LABEL_PAGE_TYPE_MIGRATED_KEY):
        return
    conn.execute("UPDATE label_config SET page_type = 'dashboard' WHERE has_dashboard = 1")
    set_app_meta(conn, _LABEL_PAGE_TYPE_MIGRATED_KEY, "1")


def get_home_page_type(conn: sqlite3.Connection) -> str:
    value = get_app_meta(conn, HOME_PAGE_TYPE_KEY)
    return value if value in PAGE_TYPES else "secretariat"


def set_home_page_type(conn: sqlite3.Connection, page_type: str) -> None:
    if page_type in PAGE_TYPES:
        set_app_meta(conn, HOME_PAGE_TYPE_KEY, page_type)


def get_group_page_type(conn: sqlite3.Connection, group: str) -> str:
    row = get_group(conn, group) or {}
    return row.get("page_type") if row.get("page_type") in PAGE_TYPES else "dashboard"


def set_group_page_type(conn: sqlite3.Connection, group: str, page_type: str) -> None:
    if page_type in PAGE_TYPES:
        ensure_group(conn, group)
        conn.execute("UPDATE label_groups SET page_type = ? WHERE name = ?", (page_type, group.strip()))
        conn.commit()


def group_page_key(group: str) -> str:
    """The page key a group's dashboard is stored under. Groups are plain text (`label_config.label_group`)
        with no table of their own, so a group's dashboard widgets, "seeded"
        marker and banner reuse the same per-page storage a label's page uses
        (dashboard_widgets.label_name, app_meta), keyed "group:<name>". Label
        names can't start with this prefix (routers/labels.py's
        _reject_reserved_label_name), so the two can't collide.
    """
    return f"{GROUP_KEY_PREFIX}{group}"


def group_from_page_key(key: str | None) -> str | None:
    if key and key.startswith(GROUP_KEY_PREFIX):
        return key[len(GROUP_KEY_PREFIX):] or None
    return None


def _move_page_storage(conn: sqlite3.Connection, old_key: str, new_key: str) -> None:
    """Moves one page's per-page storage (dashboard widgets, the one-time
    "seeded" marker, the banner) from `old_key` to `new_key`, and repoints
    any widget anywhere whose own scope names `old_key`. Same moves
    migrate_spaces_to_groups makes for a Space -> group key, reused by
    rename_group. The caller commits."""
    rows = conn.execute("SELECT uid, label_name, config_json FROM dashboard_widgets").fetchall()
    for r in rows:
        try:
            cfg = json.loads(r["config_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        on_page = r["label_name"] == old_key
        scoped = cfg.get("label_name") == old_key
        if not (on_page or scoped):
            continue
        if scoped:
            cfg["label_name"] = new_key
        conn.execute(
            "UPDATE dashboard_widgets SET label_name = ?, config_json = ? WHERE uid = ?",
            (new_key if on_page else r["label_name"], json.dumps(cfg), r["uid"]),
        )
    for old_meta, new_meta in (
        (f"dashboard_label_{old_key}_seeded_v1", f"dashboard_label_{new_key}_seeded_v1"),
        (_page_banner_key(old_key), _page_banner_key(new_key)),
    ):
        value = get_app_meta(conn, old_meta)
        if value and not get_app_meta(conn, new_meta):
            set_app_meta(conn, new_meta, value)


# --------------------------------------------------------------------- #
# Dashboard widgets (Phase 8) -- local-only, see the `dashboard_widgets`
# CREATE TABLE comment above.
# --------------------------------------------------------------------- #


def upsert_dashboard_widget(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    data = dict(row)
    data["config_json"] = json.dumps(data.get("config") or {})
    # `label_name` (Phase 2, label-space rework) is the single page-scope
    # column that replaced `space_uid`/`project_uid` -- NULL means Home, a
    # set value is the label whose generated page this widget belongs to.
    # Accepts `space_uid`/`project_uid` as aliases (whichever is set wins)
    # so callers that haven't been renamed yet still work.
    if "label_name" not in data:
        data["label_name"] = data.get("project_uid") or data.get("space_uid")
    cols = ("uid", "type", "title", "config_json", "position", "created_at", "group_uid", "label_name")
    conn.execute(
        f"INSERT INTO dashboard_widgets ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
        f"ON CONFLICT(uid) DO UPDATE SET " + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uid"),
        [data.get(c) for c in cols],
    )
    conn.commit()


def _widget_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("config_json", "{}")
    try:
        d["config"] = json.loads(raw) if raw is not None else {}
    except (json.JSONDecodeError, TypeError):
        d["config"] = {}
    d.setdefault("space_uid", d.get("label_name"))
    d.setdefault("project_uid", d.get("label_name"))
    return d


def get_dashboard_widget(conn: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM dashboard_widgets WHERE uid = ?", (uid,)).fetchone()
    return _widget_row_to_dict(row) if row else None


def list_dashboard_widgets(
    conn: sqlite3.Connection, label_name: str | None = None,
    space_uid: str | None = None, project_uid: str | None = None,
) -> list[dict[str, Any]]:
    """Widgets for one page's grid -- Home (label_name=None, the default)
    or a specific label's generated page (label_name set). Includes both
    top-level widgets and stack members (callers that need to tell them
    apart filter on group_uid themselves -- see _build_widget_contexts).
    Use list_all_dashboard_widgets below instead when you need to look up
    a widget/stack by uid or group_uid without knowing which page it's on
    (e.g. dissolving a stack -- its uid is globally unique regardless of
    which page's grid it's in). `space_uid`/`project_uid` are accepted as
    aliases for `label_name` (pre-Phase-2 callers) -- whichever is set
    wins if more than one is passed."""
    label_name = label_name or project_uid or space_uid
    rows = conn.execute(
        "SELECT * FROM dashboard_widgets WHERE label_name IS ? ORDER BY position ASC", (label_name,)
    ).fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def list_all_dashboard_widgets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every widget on every page (Home + every label's page), regardless
    of label_name -- see list_dashboard_widgets' docstring for when to
    reach for this instead."""
    rows = conn.execute("SELECT * FROM dashboard_widgets ORDER BY position ASC").fetchall()
    return [_widget_row_to_dict(r) for r in rows]


def next_dashboard_widget_position(
    conn: sqlite3.Connection, label_name: str | None = None, _legacy_project_uid: str | None = None
) -> float:
    # Scoped to top-level widgets (group_uid IS NULL) on this one page --
    # always "the position that puts a widget at the end of *this page's*
    # top-level order" (a brand-new widget via add_widget, or one just
    # popped out of a stack via unstack_widget), never a stack member's
    # own position or another page's ordering. `_legacy_project_uid`
    # accepts a second positional arg so a pre-Phase-2 call site passing
    # (space_uid, project_uid) keeps working -- only the first non-empty
    # of the two is used.
    label_name = label_name or _legacy_project_uid
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM dashboard_widgets WHERE group_uid IS NULL AND label_name IS ?",
        (label_name,),
    ).fetchone()[0]
    return max_pos + 1


def delete_dashboard_widget(conn: sqlite3.Connection, uid: str) -> None:
    conn.execute("DELETE FROM dashboard_widgets WHERE uid = ?", (uid,))
    conn.commit()


def swap_dashboard_widget_positions(conn: sqlite3.Connection, uid_a: str, uid_b: str) -> None:
    """Same swap-with-neighbor reorder primitive the now-removed
    routers/databases.py's move_column used -- simplest correct "move up"/
    "move down" without renumbering the rest of the list."""
    a = get_dashboard_widget(conn, uid_a)
    b = get_dashboard_widget(conn, uid_b)
    if a is None or b is None:
        return
    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE uid = ?", (b["position"], uid_a))
    conn.execute("UPDATE dashboard_widgets SET position = ? WHERE uid = ?", (a["position"], uid_b))
    conn.commit()
_PAGE_BANNER_PREFIX = "page_banner_"

PAGE_HEADER_BANNER_SCOPE = "__page_header__"

SEASON_BANNER_SCOPES = {
    "spring": "__season_spring__",
    "summer": "__season_summer__",
    "autumn": "__season_autumn__",
    "winter": "__season_winter__",
}

MONTH_BANNER_SCOPES = {
    "january": "__month_january__",
    "february": "__month_february__",
    "march": "__month_march__",
    "april": "__month_april__",
    "may": "__month_may__",
    "june": "__month_june__",
    "july": "__month_july__",
    "august": "__month_august__",
    "september": "__month_september__",
    "october": "__month_october__",
    "november": "__month_november__",
    "december": "__month_december__",
}

_FLAIR_ELIGIBLE_TYPES = {"task", "event"}


def _page_banner_key(page_key: str) -> str:
    """app_meta key for one dashboard page's banner -- "" is Home, any
    other value is that label's generated page (/labels/{name}). Label
    names are opaque strings here (kept raw in the key itself); the
    routers own the page-key mapping, this is just key assembly."""
    return f"{_PAGE_BANNER_PREFIX}{page_key}"


def get_page_banner(conn: sqlite3.Connection, page_key: str) -> dict[str, Any] | None:
    """One dashboard page's banner, or None when unset. Stored as a single
        JSON blob; returns only well-formed {kind: 'remote'|'upload', ...}
        dicts -- anything corrupt (e.g. an interrupted write) reads as None
        rather than crashing the page render. See routers/banners.py for the
        two kinds; templates only read image_url/image_b64/image_type/alt/
        version, so the optional source_url attribution is harmless extra.
    """
    raw = get_app_meta(conn, _page_banner_key(page_key))
    if not raw:
        return None
    try:
        banner = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(banner, dict) or banner.get("kind") not in ("remote", "upload"):
        return None
    if banner.get("kind") == "upload" and not banner.get("version"):
        b64 = banner.get("image_b64") or ""
        banner["version"] = hashlib.md5(b64.encode("ascii")).hexdigest()[:12]
        set_app_meta(conn, _page_banner_key(page_key), json.dumps(banner))
    return banner


def _page_banner_explicitly_cleared(conn: sqlite3.Connection, page_key: str) -> bool:
    """Item 10: True only when this page's banner was
        deliberately cleared via `set_page_banner_cleared` below (banner_
        editor's "Clear banner" button) -- distinct from simply never having
        had a banner at all. `get_page_banner` itself can't tell the two apart
        (both read as None there, on purpose -- every EXISTING caller only
        ever needed "is there an image", not "was one explicitly refused"),
        so this reads the raw stored kind directly rather than going through
        it. The one thing this bool gates: whether `effective_page_banner`
        below is allowed to fall through to a flair match -- confirmed via
        AskUserQuestion that a flair default must stay genuinely removable,
        not a permanent floor under labels/groups/projects the way the
        original queued wording ("this default behavior can't be removed")
        literally read.
    """
    raw = get_app_meta(conn, _page_banner_key(page_key))
    if not raw:
        return False
    try:
        banner = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(banner, dict) and banner.get("kind") == "none"


def set_page_banner_cleared(conn: sqlite3.Connection, page_key: str) -> None:
    """Item 10: the banner editor's "Clear banner" button
        (routers/banners.py's `remove_banner`, renamed from "Remove banner"
        the same slice) -- stores an explicit "there is deliberately no image
        here" marker instead of `clear_page_banner`'s plain blank-out, so a
        label/group/project/task/event whose name happens to match a flair
        keyword can still end up with a real, sticky blank instead of the
        flair reappearing the moment the stored override goes away. Every
        EXISTING caller of get_page_banner keeps reading this exactly like
        "no banner" (kind="none" isn't in that function's own remote/upload
        allow-list) -- only `effective_page_banner` below, via
        `_page_banner_explicitly_cleared`, treats it as meaningfully different
        from "never set" at all.
    """
    set_app_meta(conn, _page_banner_key(page_key), json.dumps({"kind": "none"}))


def active_flair_languages(conn: sqlite3.Connection) -> list[str]:
    """Which of `flairs.FLAIR_KEYWORDS_BY_LANG`'s tables `flairs.
    match_flair` should search, per Settings > General's "Flair languages"
    checkbox-dropdown (routers/settings.py's `set_flair_languages`).
    Comma-stored, same convention as `reminders.py`'s `TYPES_KEY`/
    `enabled_types` -- but unlike that setting, missing OR an empty stored
    value both mean "English only" here, not "every language": turning on
    Romanian (or unchecking English) is a deliberate opt-in an install has
    to actually make, never a default every existing install silently
    gets just because a second language now exists, and "nothing
    selected" would otherwise mean match_flair searches zero tables --
    technically harmless (just never matches anything) but almost
    certainly not what a user who cleared a checkbox by accident wanted.
    A stored code that isn't in `flairs.FLAIR_LANGUAGES` any more (a
    since-removed language) is dropped rather than kept -- `match_flair`
    itself already tolerates an unknown code by skipping it, but filtering
    here too keeps this function's own return value trustworthy for any
    other caller (e.g. rendering the settings row's checked state) that
    doesn't want to re-derive that same guard."""
    raw = get_app_meta(conn, flairs.FLAIR_LANGUAGES_KEY)
    if not raw:
        return ["en"]
    langs = [lang for lang in raw.split(",") if lang in flairs.FLAIR_LANGUAGES]
    return langs or ["en"]


def effective_page_banner(conn: sqlite3.Connection, page_key: str, name: str | None = None) -> dict[str, Any] | None:
    """`get_page_banner`, extended with the flair default: an
        explicit upload/remote banner always wins first; failing that, a page
        explicitly cleared (`set_page_banner_cleared` above) stays blank on
        purpose rather than falling through; failing THAT, `name`'s own
        keyword match (`flairs.match_flair`) is the default, same as this
        page's Add/Change-banner button would show before the user ever
        touches it. `name` is optional (default None -- no flair at all) for
        every page this doesn't apply to: Home, the global page-header
        default, and the four season scopes (matched by DATE, not name --
        see banner_for_object's own season tier, which calls this the same
        way with name=None and its own flair lookup for the season photo
        itself instead).

        Callers: routers/dashboard.py's `_page_banner_context` (a label/
        group/project's own page banner) and `banner_for_object` below (an
        event/task's inherited label/Project/Space banner, and its own
        season/global fallback) -- both now resolve every tier through this
        one function instead of the raw `get_page_banner`, so a flair
        default is available everywhere an explicit banner already was.
    """
    banner = get_page_banner(conn, page_key)
    if banner:
        return banner
    if _page_banner_explicitly_cleared(conn, page_key):
        return None
    if name:
        flair_id = flairs.match_flair(name, active_flair_languages(conn))
        if flair_id:
            image_url = flairs.flair_image_url(flair_id)
            # A matched keyword with no actual file configured yet
            # (flairs.py's own docstring: an operator-supplied directory,
            # possibly still empty on a fresh install) is exactly "no
            # flair available", same as match_flair finding nothing.
            if image_url:
                return {"kind": "remote", "image_url": image_url, "scope": page_key}
    return None


def banner_for_object(conn: sqlite3.Connection, object_type: str, obj: dict[str, Any]) -> dict[str, Any] | None:
    """No new storage: a label's banner
        already exists (get_page_banner/routers/banners.py, keyed by label
        name) as the image a label's own generated dashboard page shows --
        this just resolves which one of an object's several labels wins, the
        same banner data either way.

        `object_type` is whatever `object_labels`/`project_label_for` already
        key on ("task", "event", "contact" -- anything `set_object_labels` is
        called with). `obj` needs `uid` (to look up its Project label) and
        `tags` (every router's own dict-building helper already attaches
        both -- routers/tasks.py's task dicts, _attach_tags(conn, "event"/
        "contact", ...), db.list_tasks rows). Every tag but the project's own
        is tried in list order before falling through to the project/Space
        tiers -- an object with both a Project label and a more specific
        plain label (e.g. "Client call") should show the specific one, not
        the broader project's, which is why the project tag itself is skipped
        in this first pass rather than tried alongside its siblings.

        The returned dict carries one extra key beyond get_page_banner's own
        shape: `scope` -- the label name the banner actually came from. A
        template needs this to build the /banners/image?scope=... URL (an
        uploaded banner's bytes are served per-scope, and the winning scope
        here is whichever label/project/Space matched, not the object itself,
        which has no scope of its own). Safe to inject: this dict is a fresh
        json.loads() from get_page_banner, never written back through
        set_page_banner, so the extra key can't leak into storage.

        Both the month and season tiers resolve the same way -- an explicit banner set on that scope
        through the normal /banners/editor still wins first (get_page_banner,
        unchanged), but failing that, `flairs.flair_image_url` is asked for
        the exact season/month word as an id (NOT `flairs.match_flair` --
        this is a direct lookup of the id `season_for_date`/`month_for_date`
        already computed, never a keyword scan of the object's title), so an
        operator can drop `summer.jpg`/`july.jpg` straight into flairs_dir
        exactly like any other flair and it just works, no banner-editor
        upload required. See SEASON_BANNER_SCOPES's own comment for why this
        still isn't a FLAIR_KEYWORDS entry despite now sharing flairs_dir as
        its photo source.
    """
    tags = obj.get("tags") or []
    project = project_label_for(conn, object_type, obj["uid"]) if obj.get("uid") else None
    for tag in tags:
        if tag == project:
            continue
        banner = effective_page_banner(conn, tag, name=tag)
        if banner:
            banner["scope"] = tag
            return banner
    if project:
        banner = effective_page_banner(conn, project, name=project)
        if banner:
            banner["scope"] = project
            return banner
        cfg = get_label_config(conn, project)
        group = ((cfg or {}).get("label_group") or "").strip()
        if group:
            key = group_page_key(group)
            banner = effective_page_banner(conn, key, name=group)
            if banner:
                banner["scope"] = key
                return banner
    if object_type in _FLAIR_ELIGIBLE_TYPES:
        _flair_langs = active_flair_languages(conn)
        flair_id = flairs.match_flair(obj.get("title"), _flair_langs)
        image_url = flairs.flair_image_url(flair_id) if flair_id else None
        if not image_url:
            desc_flair_id = flairs.match_flair(obj.get("description"), _flair_langs)
            if desc_flair_id:
                image_url = flairs.flair_image_url(desc_flair_id)
        if image_url:
            return {"kind": "remote", "image_url": image_url, "scope": object_type}
    date_field = _SEASON_DATE_FIELD.get(object_type)
    if date_field:
        month = month_for_date(obj.get(date_field))
        if month:
            month_scope = MONTH_BANNER_SCOPES[month]
            banner = get_page_banner(conn, month_scope)
            if banner:
                banner["scope"] = month_scope
                return banner
            image_url = flairs.flair_image_url(month)
            if image_url:
                return {"kind": "remote", "image_url": image_url, "scope": month_scope}
        season = season_for_date(obj.get(date_field))
        if season:
            season_scope = SEASON_BANNER_SCOPES[season]
            banner = get_page_banner(conn, season_scope)
            if banner:
                banner["scope"] = season_scope
                return banner
            image_url = flairs.flair_image_url(season)
            if image_url:
                return {"kind": "remote", "image_url": image_url, "scope": season_scope}
        banner = get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE)
        if banner:
            banner["scope"] = PAGE_HEADER_BANNER_SCOPE
            return banner
    return None


def set_page_banner(conn: sqlite3.Connection, page_key: str, banner: dict[str, Any]) -> None:
    set_app_meta(conn, _page_banner_key(page_key), json.dumps(banner))


def clear_page_banner(conn: sqlite3.Connection, page_key: str) -> None:
    set_app_meta(conn, _page_banner_key(page_key), "")
