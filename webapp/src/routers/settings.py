"""Audited every setting this app actually exposes (routers/*.py, db.py's
schema, every template with a form that isn't a create/edit modal) before
deciding on structure, per the redesign brief's own instruction not to
force settings into categories that only look complete. Result: five
categories, each earning its own focused page because each is a distinct
thing a user thinks about, not because five is a tidy number --

  1. General     -- identity + format preferences: display name, week
                     start, time format; plus old/new/confirm
                     password forms for the app's own login and the app's
                     stored Radicale connection credential ("Login &
                     security" -- see change_login_password/
                     change_radicale_password below).
  2. Appearance   -- how the app looks: theme.
  3. Labels       -- the app's one organizing concept (spaces/projects/tags
                     collapsed into "labels", see features/architecture
                     .md); links straight to the existing /labels manage
                     page rather than duplicating it under /settings/*.
  4. Published lists -- subscribable filtered calendars/lists; no tabbar
                     slot of its own (see base.html's nav rework history).
  5. Advanced     -- rarely-touched, real-capability actions: reset Home's
                     widget layout, export & backup, auto-archive
                     completed tasks, and the two destructive purge
                     actions. Not "Danger zone" as its own top-level thing
                     floating off the bottom of the old page -- it's
                     exactly what "Advanced" means in every settings app.

Explicitly NOT created, and why (see the redesign brief's "only create
categories that are actually useful"):
  - Integrations -- Radicale is internal plumbing for Published Lists,
    not a user-facing connection to configure; nothing else calls out.
  - Privacy -- no accounts, no telemetry toggle, nothing to show here;
    a page with zero real content is worse than no page.
  - Calendar/Tasks as their own Settings categories -- Schedule's own
    settings (semester dates/credits/reminder/event label) already moved
    onto /schedule itself as a <details> block specifically so there wouldn't be two paths to the same
    four fields; re-adding a Settings mirror here would recreate exactly
    the "which one is current" drift that move was fixing. Tasks has no
    settings of its own beyond the habit-tracking label, which likewise
    already lives contextually on Tasks > Habits (tasks.py's
    save_habit_settings) for the same reason. Both stay contextual-only,
    not mirrored -- see the redesign brief's own "only mirror a setting
    when the contextual shortcut provides a real usability advantage";
    a settings mirror nobody asked for isn't one.

Every child page shares one back-navigation shape (_settings_breadcrumb
.html): "Settings" (or "Settings / Data") as a link, current page as plain
text -- Back always returns one level up inside Settings, never out to
whatever page was open before Settings was entered (redesign brief item 3).
"""

from __future__ import annotations

import base64
import hmac
import io
import os
import threading
import uuid
import zipfile

from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import log as app_log
from ..log import get_logger
from .. import clock, auth, config, data_health, db, env_file, finance, finance_stats, flairs, offline_sync, push, release, reminders
from ..image_sniff import sniff_image_type
from ..deps import (
    ACCENT_COLOR_KEY,
    ACCENT_PRESETS,
    EDIT_MODE_KEY,
    FOUR_WEEK_POSITION_KEY,
    HABIT_STREAK_TERMINOLOGY_KEY,
    HIDE_SLEEP_HOURS_KEY,
    PAGE_HEADER_BANNER_SCOPE,
    RECURRENCE_TERMINOLOGY_KEY,
    SHOW_LABEL_ICONS_KEY,
    TIME_FORMAT_KEY,
    WEEK_START_KEY,
    _four_week_position_from_value,
    get_db,
    respond,
    templates,
    wants_json,
)
from .dashboard import DISPLAY_NAME_KEY
from .export import _redirect_with_error, _redirect_with_note, export_context
from .tasks import TASK_AUTO_ARCHIVE_DAYS_KEY

router = APIRouter(tags=["settings"])
logger = get_logger(__name__)

HUB_CATEGORIES = [
    {"url": "/settings/general", "icon": "user", "name": "General", "desc": "Week start, time format, and other display preferences"},
    {"url": "/settings/your-profile", "icon": "user-check", "name": "Your Profile", "desc": "Profile picture, nickname, login & security"},
    {"url": "/settings/notifications", "icon": "bell", "name": "Notifications", "desc": "Push notifications, reminder types, morning digest"},
    {"url": "/settings/appearance", "icon": "sun", "name": "Appearance", "desc": "Theme"},
    {"url": "/settings/taxonomy", "icon": "layers", "name": "Taxonomy & Data", "desc": "Labels, groups, projects, frontmatter fields, tags and holidays in one table"},
    {"url": "/settings/notebook", "icon": "file-text", "name": "Notebook", "desc": "Document sidebar layout"},
    {"url": "/settings/finance-accounts", "icon": "credit-card", "name": "Finance accounts", "desc": "Money accounts, currencies and opening balances"},
    {"url": "/settings/time-blocks", "icon": "moon", "name": "Sleep & Leisure Time", "desc": "Weekly hours the Week/Day grid highlights and warns about"},
    {"url": "/settings/logs", "icon": "list", "name": "Logs", "desc": "What the app is doing, live, by level"},
    {"url": "/settings/data-maintenance", "icon": "database", "name": "Data & Maintenance", "desc": "Backups, integrity, sync conflicts, export, purge"},
    {"url": "/published-lists", "icon": "share-2", "name": "Published lists", "desc": "Subscribable filtered calendars/lists"},
]

# Breadcrumb roots shared by every settings_*.html page below.
_ROOT_CRUMB = [{"url": "/settings", "name": "Settings"}]

DAYS_CHOICES = [("0", "Never"), ("7", "After 1 week"), ("30", "After 1 month")]


def _maintenance_status_context(request: Request, conn) -> dict:
    """What the Database / Backup / Sync status cards and the needs-attention
    card read (they live on the main Settings page); the Data & Maintenance
    modal builds its own context on top of the same summary."""
    summary = data_health.health_summary(conn, request.app.state.settings.db_path, _backups_dir(request))
    completed_task_count = len([t for t in db.list_tasks(conn) if t["status"] in ("done", "archived")])
    return {"summary": summary, "conflicts": db.list_sync_conflicts(conn), "completed_task_count": completed_task_count}


@router.get("/settings")
def settings_index(request: Request, conn=Depends(get_db)):
    # conflict_count feeds the Data & Maintenance row's badge
    # (settings_index.html) -- the "visible even without visiting the page"
    # half of SETTINGS_UI_GUIDE.md's sync-conflict recommendation.
    status = _maintenance_status_context(request, conn)
    ctx = {
        "request": request,
        "active_tab": "settings",
        "categories": HUB_CATEGORIES,
        "conflict_count": len(status["conflicts"]),
        "release_version": release.VERSION,
        "release_title": release.TITLE,
    }
    return templates.TemplateResponse("settings_index.html", ctx)


def _current_settings(request: Request):
    """request.app.state.settings, defensively. Most routers can assume
    "app" is always in scope (a real request always has one), but
    settings_general is exercised by several older tests that build a bare
    Request with no "app" key at all (predating this route needing
    app.state -- see test_page_header_narrow.py's _bare_request). None is
    a safe fallback: every caller below already treats it as "nothing
    env-configured" (has_persisted_credentials's own `if not settings`
    early-out, and the getattr-guarded env checks)."""
    try:
        return request.app.state.settings
    except (KeyError, AttributeError):
        return None


@router.get("/settings/general")
def settings_general(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "settings_general.html",
        {
            "request": request,
            "active_tab": "settings_general",
            "crumbs": _ROOT_CRUMB,
            "title": "General",
            "current_week_start": db.get_app_meta(conn, WEEK_START_KEY) or "monday",
            "current_time_format": db.get_app_meta(conn, TIME_FORMAT_KEY) or "24h",
            "current_four_week_position": _four_week_position_from_value(
                db.get_app_meta(conn, FOUR_WEEK_POSITION_KEY) or "1"
            ),
            # 1.6 ("Configurable terminology") -- "standard" or "playful"
            # labels on the recurrence editor's holiday-calendar/weekend
            # controls. See deps.py's RECURRENCE_TERMINOLOGY_KEY comment.
            "current_recurrence_terminology": db.get_app_meta(conn, RECURRENCE_TERMINOLOGY_KEY) or "standard",
            "current_habit_streak_terminology": db.get_app_meta(conn, HABIT_STREAK_TERMINOLOGY_KEY) or "standard",
            "current_hide_sleep_hours": db.get_app_meta(conn, HIDE_SLEEP_HOURS_KEY) == "1",
            "current_flair_languages": db.active_flair_languages(conn),
            "flair_language_options": [
                {"uid": code, "name": label} for code, label in flairs.FLAIR_LANGUAGE_LABELS.items()
            ],
            "current_timezone": db.get_app_meta(conn, config.TIMEZONE_KEY) or "",
            "timezone_options": [{"uid": "", "name": "System default"}]
            + [{"uid": z, "name": z} for z in config.TIMEZONE_CHOICES],
            "current_default_currency": finance.default_currency(conn),
            "currency_options": [{"uid": "", "name": "None"}] + [{"uid": c, "name": c} for c in finance_stats.CURRENCIES],
        },
    )


@router.get("/settings/logs")
def settings_logs(request: Request):
    return templates.TemplateResponse(
        "settings_logs.html",
        {"request": request, "active_tab": "settings_logs", "crumbs": _ROOT_CRUMB, "title": "Logs", "levels": list(app_log.LEVELS)},
    )


@router.get("/settings/logs/entries")
def settings_log_entries(level: str = "important", after: int = 0):
    return JSONResponse(app_log.entries(level, after))


@router.get("/settings/notifications")
def settings_notifications(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "settings_notifications.html",
        {
            "request": request,
            "active_tab": "settings_notifications",
            "crumbs": _ROOT_CRUMB,
            "title": "Notifications",
            "push_types": [(t, reminders.TYPE_LABELS[t]) for t in reminders.TYPES],
            "push_types_on": reminders.enabled_types(conn),
            "push_digest_time": reminders.digest_time_str(conn),
            "push_contact_email": push.contact_email(conn),
        },
    )


@router.get("/settings/your-profile")
def settings_your_profile(request: Request, conn=Depends(get_db)):
    """It
        should include the Profile Picture and Nickname (current Your Name,
        used in greeting)." Same context fields settings_general used to build
        for its Profile picture / Your name / Account / Restart app cards --
        moved here verbatim, this page's own template is those same cards'
        markup unchanged (only the page title/crumbs and where the underlying
        routes redirect back to).
    """
    settings = _current_settings(request)
    return templates.TemplateResponse(
        "settings_your_profile.html",
        {
            "request": request,
            "active_tab": "settings_your_profile",
            "crumbs": _ROOT_CRUMB,
            "title": "Your Profile",
            "display_name": db.get_app_meta(conn, DISPLAY_NAME_KEY) or "",
            "profile_photo": db.get_profile_photo(conn),
            "auth_is_env": bool(
                getattr(settings, "auth_username", None) and getattr(settings, "auth_password", None)
            ),
            "radicale_env_configured": getattr(settings, "radicale_env_configured", False),
            "env_file_available": bool(getattr(settings, "env_file_path", None)),
            "has_account": auth.has_persisted_credentials(settings, conn)
            or bool(getattr(settings, "auth_username", None) and getattr(settings, "auth_password", None)),
            "account_username": (
                getattr(settings, "auth_username", None)
                or (auth.get_persisted_credentials(conn) or (None,))[0]
                or ""
            ),
            "radicale_url": getattr(settings, "radicale_base_url", ""),
        },
    )


@router.post("/settings/account")
def account_settings(
    request: Request,
    username: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
    radicale_url: str = Form(""),
    conn=Depends(get_db),
):
    """Replaces three
        former routes (change_login_password, change_radicale_password, Data
        & Maintenance's settings_radicale) that each managed a separate
        credential -- the app's own login, and the app's stored copy of the
        Radicale connection -- with one form: a single username and password
        govern both, plus the Radicale server URL (not a credential, just
        where to reach it).

        Storage backend is chosen by whether this account is currently
        env-configured (`auth_is_env`: CC_AUTH_USERNAME/PASSWORD both set) OR
        the Radicale side is (`settings.radicale_env_configured`,
        CC_RADICALE_URL set) -- either one puts the WHOLE account on the
        env-file path from here on, converting the other half over too the
        first time this form is saved (e.g. an install that only ever had
        CC_RADICALE_URL set now also gets CC_AUTH_USERNAME/PASSWORD written
        alongside it): the point of merging is one identity, not one still
        living in two different places depending on which half happened to
        be configured first.

        - Env-configured (either half) with `settings.env_file_path` known
          (`CC_ENV_FILE`, set by curodav-ctl's generated unit): writes
          CC_AUTH_USERNAME/CC_RADICALE_USER (always) and CC_AUTH_PASSWORD/
          CC_RADICALE_PASSWORD (only when `new_password` is given) via
          env_file.update_env_file. Takes effect on the next process start --
          Settings > Your Profile's "Restart app" button (restart_app below) is
          how an operator actually applies it without SSHing in.
        - Env-configured but no CC_ENV_FILE known (a non-curodav-ctl deploy
          that still sets these env vars by some other means): refuses to
          edit at all, same "edit curodav.env and restart yourself" fallback
          the three routes this replaces always used -- there's nowhere safe
          to write.
        - Neither env-configured: persisted in app_meta, same as before --
          auth.set_persisted_credentials (hashed) for login, config.
          RADICALE_USERNAME_KEY/RADICALE_PASSWORD_KEY (retrievable, config.
          py's own docstring covers why) mirrored to match. Login takes
          effect immediately (session re-minted below, same as the old
          change_login_password); the Radicale connection still needs a
          restart to reach CalDavBridge (main.py's lifespan builds it once).

        Any existing account (env or persisted) requires `current_password`
        to verify before ANY change here is accepted -- username, password,
        or just the Radicale URL -- since this form now controls both the
        login and the sync credential together; a first-time save (no
        account yet) has nothing to verify against and requires a
        `new_password` to create one. `new_password` left blank on an
        existing account keeps the current password, changing only the
        username and/or URL. The Radicale password key is only ever written
        when `new_password` is actually supplied -- never silently persists
        `settings.radicale_password`'s dev-default fallback ("devpass") as if
        it were a real chosen credential.
    """
    settings = request.app.state.settings
    username = username.strip()
    radicale_url = radicale_url.strip()

    auth_is_env = bool(getattr(settings, "auth_username", None) and getattr(settings, "auth_password", None))
    env_managed = auth_is_env or getattr(settings, "radicale_env_configured", False)
    env_path = getattr(settings, "env_file_path", None)

    if env_managed and not env_path:
        return _redirect_with_error(
            "/settings/your-profile",
            "Login/Radicale are set via environment variables, and this install has no CC_ENV_FILE to edit them through -- edit curodav.env by hand and restart.",
        )

    if not username:
        return _redirect_with_error("/settings/your-profile", "Choose a username.")

    if auth_is_env:
        has_account = True

        def verify(pw: str) -> bool:
            return hmac.compare_digest(pw, settings.auth_password or "")
    else:
        persisted = auth.get_persisted_credentials(conn)
        has_account = persisted is not None
        if has_account:
            _, stored_hash = persisted

            def verify(pw: str) -> bool:
                return auth._verify_password_hash(pw, stored_hash)
        else:
            def verify(pw: str) -> bool:
                return True

    error = None
    if has_account and not verify(current_password):
        error = "Current password is incorrect."
    elif not has_account and not new_password:
        error = "Choose a password."
    elif new_password:
        if len(new_password) < 8:
            error = "New password must be at least 8 characters."
        elif new_password != new_password_confirm:
            error = "New passwords do not match."
    if error:
        return _redirect_with_error("/settings/your-profile", error)

    if env_managed:
        updates = {"CC_AUTH_USERNAME": username, "CC_RADICALE_USER": username}
        if new_password:
            updates["CC_AUTH_PASSWORD"] = new_password
            updates["CC_RADICALE_PASSWORD"] = new_password
        if radicale_url:
            updates["CC_RADICALE_URL"] = radicale_url
        try:
            env_file.update_env_file(env_path, updates)
        except OSError:
            logger.exception("Failed to write env file %s", env_path)
            return _redirect_with_error(
                "/settings/your-profile",
                "Could not save -- the app couldn't write to its env file. Check file permissions.",
            )
        return _redirect_with_note(
            '/settings/data-maintenance', 'Saved. Click "Restart app" below to apply it.'
        )

    # Not env-managed -- app_meta, same storage as before this merge.
    if new_password:
        auth.set_persisted_credentials(conn, username, new_password)
        db.set_app_meta(conn, config.RADICALE_PASSWORD_KEY, new_password)
    else:
        db.set_app_meta(conn, auth.AUTH_USERNAME_KEY, username)
    db.set_app_meta(conn, config.RADICALE_USERNAME_KEY, username)
    db.set_app_meta(conn, config.RADICALE_URL_KEY, radicale_url or settings.radicale_base_url)

    state = getattr(request.app, "state", None)
    if state is not None:
        state._cc_auth_configured = True
    secret = auth.rotate_session_secret(settings, conn)
    if state is not None:
        state._cc_auth_secret = secret
    token = auth.make_session_token(secret, username)
    restart_relevant = bool(new_password or radicale_url)
    response = _redirect_with_note(
        "/settings/data-maintenance" if restart_relevant else "/settings/your-profile",
        "Saved. Restart the app for the Radicale connection to pick up the change."
        if restart_relevant
        else "Saved.",
    )
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=auth.is_secure_request(request),
        path="/",
    )
    return response


@router.post("/settings/restart")
def restart_app(request: Request):
    """Applies an account_settings env-file save (or any other change that
        needs a fresh process, e.g. a Radicale connection saved to app_meta)
        by having THIS process exit cleanly and letting systemd relaunch it
        with the new environment -- not by shelling out to `systemctl`
        itself, which would need granting the service user new privileges it
        deliberately doesn't have (NoNewPrivileges/ProtectSystem in
        scripts/curodav-ctl's generated unit). `Restart=always` on that unit
        (changed from `on-failure` alongside this route) is what makes a
        plain, non-crashing `exit(0)` come back up at all.

        Gated on `deploy_mode == "production"` -- the one signal this app
        already has for "systemd-managed, something is watching to relaunch
        me" (curodav-ctl's generated .env always sets it; local/manual runs
        default to "local"). Without that gate, clicking this on a bare
        `uvicorn` dev run would just kill the process with nothing to bring
        it back.

        The actual exit happens on a background thread half a second after
        this function returns its response -- long enough for uvicorn to
        finish writing the redirect to the socket first, short enough that
        the operator's browser barely notices before the reload. `os._exit`
        (not `sys.exit`, not raising) skips normal interpreter teardown on
        purpose: there's nothing here that needs flushing or rolling back --
        every write that led to this point is already committed (SQLite,
        or env_file.update_env_file's own atomic rename) -- and an ordinary
        shutdown path risks hanging on an in-flight background sync tick
        instead of actually exiting.
    """
    settings = request.app.state.settings
    if getattr(settings, "deploy_mode", "local") != "production":
        return _redirect_with_error(
            "/settings/data-maintenance",
            "Restart isn't available outside a systemd-managed (production) deploy -- stop and restart the process yourself.",
        )
    logger.warning("Restart requested from Settings > Data & Maintenance -- exiting for systemd to relaunch.")
    threading.Timer(0.5, os._exit, args=(0,)).start()
    return _redirect_with_note(
        "/settings/data-maintenance", "Restarting -- this page will reconnect in a few seconds."
    )


@router.post("/settings/display-name")
def set_display_name(display_name: str = Form(""), conn=Depends(get_db)):
    """"Nickname" (formerly "Your name") -- the optional display name
    Home's greeting reads ("Good evening, {name}"), app_meta-backed.
    Empty/whitespace-only clears it, back to the name-less "Good evening"
    alone (routers/dashboard.py's _greeting_for_hour)."""
    db.set_app_meta(conn, DISPLAY_NAME_KEY, display_name.strip())
    return RedirectResponse(url="/settings/your-profile", status_code=303)


# Cap + content-type allowlist -- same reasoning as routers/contacts.py's
# _read_photo comment (untrusted upload into an auth-less app; avatar_cropper
# already downsizes to a small JPEG, so 5MB is a generous ceiling, not a
# substitute for the cropper).
_MAX_PROFILE_PHOTO_BYTES = 5 * 1024 * 1024
_PROFILE_PHOTO_TYPES = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


@router.post("/settings/profile-photo")
def set_profile_photo(
    photo: UploadFile | None = File(None),
    conn=Depends(get_db),
):
    """Upload a new profile picture. Reads the file synchronously via
    UploadFile.file (same as routers/export.py's import routes) so this is
    a plain sync route -- directly callable in tests. An empty file field
    (FastAPI hands back an UploadFile with no filename for an unfilled
    <input type=file>) is a no-op redirect, not an error: the avatar form
    submits it every time alongside nothing else."""
    if photo is not None and photo.filename:
        image_type = _PROFILE_PHOTO_TYPES.get((photo.content_type or "").lower())
        if image_type is None:
            raise HTTPException(400, "Unsupported photo type -- use JPEG, PNG, GIF, or WEBP.")
        data = photo.file.read()
        if len(data) > _MAX_PROFILE_PHOTO_BYTES:
            raise HTTPException(400, "Photo is too large (max 5MB).")
        sniffed = sniff_image_type(data)
        if sniffed is None:
            raise HTTPException(400, "That file doesn't look like a real JPEG, PNG, GIF, or WEBP image.")
        db.set_profile_photo(conn, base64.b64encode(data).decode("ascii"), sniffed)
    return RedirectResponse(url="/settings/your-profile", status_code=303)


@router.get("/settings/profile-photo/upload")
def profile_photo_upload_modal(request: Request, conn=Depends(get_db)):
    """The shared upload modal (upload_modal.html) for the profile picture."""
    return templates.TemplateResponse(
        "upload_modal.html",
        {
            "request": request,
            "title": "Profile picture",
            "form_id": "profile-photo-upload-form",
            "upload_action": "/settings/profile-photo",
            "field_name": "photo",
            "input_class": "avatar-upload-input",
            "zone_label": "Choose or drop a photo",
            "preview_url": ("/settings/profile-photo/image?v=" + str(db.get_profile_photo(conn).get("version"))) if db.get_profile_photo(conn) else "",
            "delete_url": "/settings/profile-photo-remove" if db.get_profile_photo(conn) else "",
            "delete_label": "Remove your profile picture?",
            "back_url": "/settings/your-profile",
        },
    )


@router.post("/settings/profile-photo-remove")
def remove_profile_photo(conn=Depends(get_db)):
    """Clear the profile picture back to the initials fallback. A separate
    POST route (never a GET link) so removing is a real form submission,
    same non-cacheable convention as every other destructive action here."""
    db.clear_profile_photo(conn)
    return RedirectResponse(url="/settings/your-profile", status_code=303)


@router.get("/settings/profile-photo/image")
def profile_photo_image(conn=Depends(get_db)):
    """Serves the profile picture's decoded bytes for `<img src>`. Exact mirror of routers/
        banners.py's banner_image -- same problem (a profile photo used to be
        embedded as an inline `data:` URI, deps.py's avatar() global, riding
        along in the HTML of every page that shows it: contact list rows aside,
        this one specifically rendered on every dashboard/label/Space page via
        the header avatar overlap), same fix (a real, separately cacheable
        request), same immutable Cache-Control safety argument (the URL's own
        `?v=` -- db.get_profile_photo's `version` -- changes whenever the photo
        does, so a stale cached response can never be served under a freshly-
        rendered page's URL).
    """
    photo = db.get_profile_photo(conn)
    if not photo:
        raise HTTPException(404)
    try:
        data = base64.b64decode(photo["photo_b64"], validate=True)
    except (ValueError, TypeError):
        raise HTTPException(404)
    image_type = str(photo.get("photo_type") or "").lower()
    if image_type not in ("jpeg", "png", "gif", "webp"):
        image_type = "jpeg"
    return Response(
        content=data,
        media_type=f"image/{image_type}",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Content-Encoding": "identity",
        },
    )


_FLAIRS_CRUMB = _ROOT_CRUMB

_MAX_ZIP_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB compressed
_MAX_UPLOAD_ENTRIES = 500


def _known_flair_ids() -> list[str]:
    """Every id the app currently recognizes across all three flair
        mechanisms -- keyword-matched (flairs.FLAIR_KEYWORDS) and the two
        date-matched tiers. Sorted for a stable, readable settings_flairs.html
        listing -- ordering has no bearing on the matching logic itself.
    """
    return sorted(set(flairs.FLAIR_KEYWORDS) | set(db.MONTH_BANNER_SCOPES) | set(db.SEASON_BANNER_SCOPES))


@router.get("/settings/flairs")
def settings_flairs(request: Request, conn=Depends(get_db)):
    all_ids = _known_flair_ids()
    configured_ids = {i for i in all_ids if flairs.flair_image_url(i)}
    return templates.TemplateResponse(
        "settings_flairs.html",
        {
            "request": request,
            "active_tab": "settings_flairs",
            "crumbs": _FLAIRS_CRUMB,
            "title": "Flairs",
            "flairs_dir_configured": flairs.get_flairs_dir() is not None,
            "total_count": len(all_ids),
            "configured_count": len(configured_ids),
            "missing_ids": [i for i in all_ids if i not in configured_ids],
        },
    )


@router.post("/settings/flairs/upload")
def upload_flairs(
    files: list[UploadFile] = File(default=[]),
    zip_file: UploadFile | None = File(None),
    conn=Depends(get_db),
):
    """Bulk version of an operator manually copying files into flairs_dir
        over SSH -- accepts any combination of a .zip
        (any file at any depth, smart-filtered by basename -- see flairs.
        ingest_uploaded_photos's own docstring) and/or multiple individual
        files (one `<input multiple>` or `webkitdirectory` folder picker,
        same form field either way -- the browser sends N files under one
        field name, FastAPI hands them back as a list already). Both sources
        feed the SAME ingest call so one submission gets one summary message
        covering everything dropped in at once, not one message per source.

        Zip entries are read through `ZipFile.open(...).read(cap)` rather
        than trusting `ZipInfo.file_size` -- that header is attacker-supplied
        and a crafted zip can under-report it while the real deflate stream
        decompresses to far more, the classic zip-bomb shape; bounding the
        READ itself (not the size a lying header claims) means this can never
        decompress more than `MAX_UPLOAD_BYTES + 1` for any single entry
        regardless of what the header says. An entry that hits that cap is
        reported as "too large" (same message ingest_uploaded_photos would
        give it) without ever holding the full decompressed bytes in memory.

        Confirmed via AskUserQuestion: overwrites an existing photo for an id
        silently (flair_image_url's own mtime cache-bust means the new photo
        shows up immediately everywhere, same as replacing the file by hand
        already did), and non-matching zip contents (icons/*.svg, unmatched/*,
        mapping.csv, a nested folder structure, ...) are smart-filtered by
        basename regardless of depth rather than requiring a flat top-level
        zip.
    """
    if flairs.get_flairs_dir() is None:
        return _redirect_with_error(
            "/settings/flairs",
            "No flairs folder is configured (CC_FLAIRS_DIR) -- there's nowhere to save these to.",
        )
    entries: list[tuple[str, bytes]] = []
    pre_skipped: list[tuple[str, str]] = []
    if zip_file is not None and zip_file.filename:
        zip_bytes = zip_file.file.read(_MAX_ZIP_UPLOAD_BYTES + 1)
        if len(zip_bytes) > _MAX_ZIP_UPLOAD_BYTES:
            return _redirect_with_error("/settings/flairs", "That zip file is too large (max 50MB).")
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                for info in archive.infolist()[:_MAX_UPLOAD_ENTRIES]:
                    if info.is_dir():
                        continue
                    with archive.open(info) as member:
                        data = member.read(flairs.MAX_UPLOAD_BYTES + 1)
                    if len(data) > flairs.MAX_UPLOAD_BYTES:
                        pre_skipped.append((info.filename, "file too large (max 8MB)"))
                        continue
                    entries.append((info.filename, data))
        except zipfile.BadZipFile:
            return _redirect_with_error("/settings/flairs", "That file isn't a valid zip archive.")
    for upload in (files or [])[:_MAX_UPLOAD_ENTRIES]:
        if upload.filename:
            entries.append((upload.filename, upload.file.read()))
    result = flairs.ingest_uploaded_photos(entries)
    result.skipped = pre_skipped + result.skipped
    message = result.summary()
    if result.saved or not result.skipped:
        return _redirect_with_note("/settings/flairs", message)
    return _redirect_with_error("/settings/flairs", message)


@router.post("/settings/week-start")
def set_week_start(week_start: str = Form("monday"), conn=Depends(get_db)):
    """"Week starts on" -- affects Calendar's Month/Week grids
    (routers/calendar.py's _week_bounds/_month_grid, both read via
    deps.py's week_start()). Only "sunday" is ever stored as the
    non-default explicit choice; anything else (including a tampered or
    unrecognized value) falls back to "monday", this app's original
    hardcoded behavior before this preference existed."""
    db.set_app_meta(conn, WEEK_START_KEY, "sunday" if week_start == "sunday" else "monday")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/four-week-position")
def set_four_week_position(position: str = Form("1"), conn=Depends(get_db)):
    """"4-Week view: current week" -- which of the four rows
        of the Calendar 4-Week view the current week occupies. Only ever stores
        one of the settings_ general page's own offered choices ("1".."4",
        validated against the same fixed set deps.py's reader clamps to); an
        unrecognized or tampered value falls back to "1" (first row) rather
        than silently placing the current week somewhere the UI never offered.
        Read back by routers/calendar.py's four_week_view.
    """
    db.set_app_meta(conn, FOUR_WEEK_POSITION_KEY, position if position in ("1", "2", "3", "4") else "1")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/recurrence-terminology")
def set_recurrence_terminology(terminology: str = Form("standard"), conn=Depends(get_db)):
    """1.6 ("Configurable terminology") -- "standard" or "playful" labels
    on the recurrence editor's holiday-calendar/weekend controls. Only
    ever stores one of the two offered choices; anything else falls back
    to "standard", same "unrecognized value -> the default, not silently
    picking something the UI never offered" convention as set_week_start/
    set_four_week_position above. Presentation-layer only -- the
    underlying holiday_calendar/exclude_saturday/exclude_sunday fields on
    events and schedule_settings never change name or meaning."""
    db.set_app_meta(conn, RECURRENCE_TERMINOLOGY_KEY, "playful" if terminology == "playful" else "standard")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/habit-streak-terminology")
def set_habit_streak_terminology(terminology: str = Form("standard"), conn=Depends(get_db)):
    """"Habit streak terminology" -- "standard" or "playful" wording for
    the Habits group's streak readout (Tasks table, _habit_row.html via
    deps.py's habit_streak_text() global). Only ever stores one of the two
    offered choices; anything else falls back to "standard", same
    convention as set_recurrence_terminology above. Presentation-layer
    only -- the underlying current_streak integer never changes."""
    db.set_app_meta(conn, HABIT_STREAK_TERMINOLOGY_KEY, "playful" if terminology == "playful" else "standard")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/time-format")
def set_time_format(time_format: str = Form("24h"), conn=Depends(get_db)):
    """"24-hour time" -- affects every server-rendered time in the app
    (deps.py's fmt_time/fmt_hour Jinja filters) and the Calendar/Schedule
    drag-preview labels (static/calendar.js's/schedule_grid.js's
    minutesToDisplayTime(), which reads this via base.html's
    `data-time-format` body attribute)."""
    db.set_app_meta(conn, TIME_FORMAT_KEY, "12h" if time_format == "12h" else "24h")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/timezone")
def set_timezone(timezone: str = Form(""), conn=Depends(get_db)):
    """Timezone. Empty ("System default") clears the override; anything
        else must be one of the exact zone names settings_general.html's
        dropdown offered (config.TIMEZONE_CHOICES) -- a tampered or
        unrecognized value is dropped rather than stored, same "never store
        what the UI didn't actually offer" convention as set_week_start above.
        apply_persisted_timezone applies the change to this process's own
        clock immediately, so it takes effect without a restart.
    """
    value = timezone if timezone in config.TIMEZONE_CHOICES else ""
    db.set_app_meta(conn, config.TIMEZONE_KEY, value)
    config.apply_persisted_timezone(conn)
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/default-currency")
def set_default_currency(currency: str = Form(""), conn=Depends(get_db)):
    db.set_app_meta(conn, finance.DEFAULT_CURRENCY_KEY, currency if currency in finance_stats.CURRENCIES else "")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/notifications")
def set_notifications(
    types: list[str] = Form([]),
    digest_time: str = Form("08:00"),
    email: str | None = Form(None),
    x_requested_with: str | None = Header(default=None),
    conn=Depends(get_db),
):
    """Web Push P3: which reminder types are on (app-wide --
        every subscribed device gets the same ones) and the morning digest
        time for tasks/habits due today. A malformed time keeps the old one.
    """
    fetch = isinstance(x_requested_with, str) and wants_json(x_requested_with)
    normalized_email = None
    if isinstance(email, str) and email.strip():
        normalized_email = push.normalize_email(email)
        if normalized_email is None:
            message = "That doesn't look like an email address. Nothing was saved."
            if fetch:
                return JSONResponse({"error": message}, status_code=400)
            return _redirect_with_error("/settings/notifications", message)
    chosen = [t for t in reminders.TYPES if isinstance(types, list) and t in types]
    db.set_app_meta(conn, reminders.TYPES_KEY, ",".join(chosen))
    try:
        h, m = (int(x) for x in (digest_time or "").split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            db.set_app_meta(conn, reminders.DIGEST_TIME_KEY, f"{h:02d}:{m:02d}")
    except (ValueError, TypeError):
        pass
    if isinstance(email, str):
        db.set_app_meta(conn, push.CONTACT_KEY, normalized_email or "")
    if fetch:
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/settings/notifications#push-settings", status_code=303)


@router.post("/settings/push-contact")
def set_push_contact(email: str = Form(""), conn=Depends(get_db)):
    """The contact email sent to push services with every notification
    (the VAPID `sub` claim, src/push.py) -- who they reach about abusive
    traffic. Blank clears it (falls back to CC_PUSH_CONTACT, then the
    default); an invalid address keeps the old one and says so."""
    if not (email or "").strip():
        db.set_app_meta(conn, push.CONTACT_KEY, "")
        return RedirectResponse(url="/settings/notifications#push-settings", status_code=303)
    normalized = push.normalize_email(email)
    if normalized is None:
        return _redirect_with_error(
            "/settings/notifications", "That doesn't look like an email address -- the notification contact wasn't changed."
        )
    db.set_app_meta(conn, push.CONTACT_KEY, normalized)
    return RedirectResponse(url="/settings/notifications#push-settings", status_code=303)


@router.post("/settings/hide-sleep-hours")
def set_hide_sleep_hours(enabled: str = Form(""), conn=Depends(get_db)):
    """"Hide sleep hours in Planner". Off by default, same on/off pattern as
        set_edit_mode above. Read back by routers/calendar.py's
        _week_view_context -- Week/Planner only, Day view is unaffected
        regardless of this setting (direct decision).
    """
    db.set_app_meta(conn, HIDE_SLEEP_HOURS_KEY, "1" if enabled == "1" else "")
    return RedirectResponse(url="/settings/general", status_code=303)


@router.post("/settings/flair-languages")
def set_flair_languages(languages: list[str] = Form([]), conn=Depends(get_db)):
    """"Flair languages" -- which of `flairs.
        FLAIR_KEYWORDS_BY_LANG`'s keyword tables `flairs.match_flair` searches
        when guessing a flair from an event/task/label/group/project's own
        name (db.active_flair_languages reads this back). Same checkbox-
        dropdown shape as General's other multi-value settings (ms_mode=
        "select"), autosubmitting like every other row on that page. Only
        ever stores a subset of `flairs.FLAIR_LANGUAGES` -- an unrecognized
        value can't reach app_meta from this route even if the submitted form
        were hand-crafted, same allowlist-not-blocklist discipline set_
        accent_color already applies to its own fixed choice set. Unticking
        every option stores an explicit empty string rather than refusing the
        submission -- db.active_flair_languages's own comment is what turns
        that back into "English only" on read, not a "zero languages" crash
        state anywhere downstream.
    """
    valid = [lang for lang in languages if lang in flairs.FLAIR_LANGUAGES]
    db.set_app_meta(conn, flairs.FLAIR_LANGUAGES_KEY, ",".join(valid))
    return RedirectResponse(url="/settings/general", status_code=303)


@router.get("/settings/appearance")
def settings_appearance(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "settings_appearance.html",
        {
            "request": request,
            "active_tab": "settings_appearance",
            "crumbs": _ROOT_CRUMB,
            "title": "Appearance",
            "current_show_label_icons": db.get_app_meta(conn, SHOW_LABEL_ICONS_KEY) == "1",
            "current_edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
            "current_accent_color": db.get_app_meta(conn, ACCENT_COLOR_KEY) or "blue",
            "accent_presets": ACCENT_PRESETS,
            "current_page_header_banner": db.get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE),
            "flairs_configured_count": len({i for i in _known_flair_ids() if flairs.flair_image_url(i)}),
            "flairs_total_count": len(_known_flair_ids()),
        },
    )


@router.post("/settings/label-icons")
def set_label_icons(show: str = Form(""), conn=Depends(get_db)):
    """"Show icons next to labels" --
        renders every label's assigned icon before its name wherever the app
        shows a label (task/event label pills, Tasks table/board, calendar
        chips). Reads via deps.py's show_label_icons()/label_icon() globals.
        Default off -- an install that's never touched this stores nothing,
        which reads as "" (off), so labels stay plain text until explicitly
        turned on.
    """
    db.set_app_meta(conn, SHOW_LABEL_ICONS_KEY, "1" if show == "1" else "")
    return RedirectResponse(url="/settings/appearance", status_code=303)


@router.post("/settings/edit-mode")
def set_edit_mode(enabled: str = Form(""), x_requested_with: str | None = Header(None), conn=Depends(get_db)):
    """"Edit mode" -- shows the widget grid's editing controls (move/resize/
        reorder/delete a widget, New widget, Reset layout, Add/Change banner)
        on every dashboard/label/Space page until turned off here, replacing
        the old per-page "Edit mode"/"Done" buttons and their `?edit=1` query
        param (routers/dashboard.py's widget_page_context reads this flag
        directly now). Same on/off pattern as set_label_icons above.
    """
    new_value = enabled == "1"
    db.set_app_meta(conn, EDIT_MODE_KEY, "1" if new_value else "")
    return respond(x_requested_with, "/settings/appearance", edit_mode=new_value)


@router.post("/settings/appearance/accent")
def set_accent_color(color: str = Form(...), conn=Depends(get_db)):
    """"Accent color" -- one of the 8 fixed presets in deps.py's
        ACCENT_PRESETS, never a raw hex (a free color picker was deliberately
        rejected -- see ACCENT_COLOR_KEY's own comment). Rejects anything
        outside that set instead of silently falling back, same as any other
        allowlisted Form value elsewhere in this router -- a request that
        isn't the settings page's own swatch grid (hand-crafted, a stale
        client) shouldn't be able to wedge an unsupported key into app_meta
        that accent_color_hex() would then have to paper over.
    """
    if color not in {p["key"] for p in ACCENT_PRESETS}:
        raise HTTPException(status_code=422, detail=f"Unknown accent color: {color!r}")
    db.set_app_meta(conn, ACCENT_COLOR_KEY, color)
    return RedirectResponse(url="/settings/appearance", status_code=303)


_HOLIDAYS_CRUMB = _ROOT_CRUMB


def _resolve_calendar_name(calendar_name: str, calendar_name_new: str) -> str:
    """A non-blank typed name is always a deliberate override -- it wins
        regardless of which radio happens to be checked/defaulted; otherwise
        the picked radio's value applies; blank calendar_name (no radios
        existed yet, or somehow neither was set) falls back to 'Default'.
    """
    new = (calendar_name_new or "").strip()
    if new:
        return new
    return (calendar_name or "").strip() or "Default"


def _parse_holiday_date_field(value: str, year_agnostic: bool) -> str:
    """create_holiday/update_holiday's form-validation wrapper around
    db.parse_holiday_date -- same "reject with a clear 400 rather than
    silently storing garbage" convention as contacts.py's
    `_parse_birthday_field` for the analogous year-less-date case."""
    try:
        return db.parse_holiday_date(value, year_agnostic)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/settings/holidays")
def settings_holidays(request: Request, conn=Depends(get_db)):
    from .taxonomy import page_response

    return page_response(conn, request, "holidays")


@router.get("/settings/holidays/new")
def new_holiday_modal(request: Request, conn=Depends(get_db)):
    """The "+ Add holiday" entry point -- the same
        holiday_edit_modal.html the Edit buttons open, empty. Opens via
        data-modal, posts to create_holiday below.
    """
    return templates.TemplateResponse(
        "holiday_edit_modal.html",
        {
            "request": request,
            "h": None,
            "form_title": "Add holiday",
            "form_action": "/settings/holidays",
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
            "date_from_value": "",
            "date_to_value": "",
            "year_agnostic": False,
        },
    )


@router.get("/settings/holidays/{uid}/edit")
def edit_holiday_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The Holiday Edit button's modal (pattern B) -- one form for every
        field, replacing the old inline-editable table cells
        (static/settings_holidays.js's per-field PATCH). Opens via data-modal
        from the Holidays list row; posts to update_holiday below.
    """
    holiday = db.get_holiday(conn, uid)
    if holiday is None:
        raise HTTPException(404, "Holiday not found")
    return templates.TemplateResponse(
        "holiday_edit_modal.html",
        {
            "request": request,
            "h": holiday,
            "form_title": "Edit holiday",
            "form_action": f"/settings/holidays/{uid}/update",
            "holiday_calendar_names": db.list_holiday_calendar_names(conn),
            "date_from_value": db.holiday_date_picker_value(holiday["date_from"]),
            "date_to_value": db.holiday_date_picker_value(holiday["date_to"]),
            "year_agnostic": db.is_year_agnostic_holiday_date(holiday["date_from"]),
        },
    )


@router.post("/settings/holidays")
def create_holiday(
    calendar_name: str = Form("Default"),
    calendar_name_new: str = Form(""),
    label: str = Form(""),
    date_from: str = Form(...),
    date_to: str = Form(...),
    year_agnostic: str = Form(""),
    conn=Depends(get_db),
):
    # No _regenerate_all(conn) call needed -- a recurring event only ever
    # stores *which* holiday calendar it references (holiday_calendar),
    # never the dates themselves; those are looked up fresh on every read
    # (recurrence_expand.expand_events), so adding a holiday takes effect
    # immediately without touching any event row. Same behavior as the old
    # /schedule/holidays route this replaces.
    db.upsert_holiday(
        conn,
        {
            "uid": str(uuid.uuid4()), "calendar_name": _resolve_calendar_name(calendar_name, calendar_name_new),
            "label": label,
            "date_from": _parse_holiday_date_field(date_from, bool(year_agnostic)),
            "date_to": _parse_holiday_date_field(date_to, bool(year_agnostic)),
        },
    )
    return RedirectResponse(url="/settings/holidays", status_code=303)


@router.post("/settings/holidays/{uid}/update")
def update_holiday(
    uid: str,
    calendar_name: str = Form("Default"),
    calendar_name_new: str = Form(""),
    label: str = Form(""),
    date_from: str = Form(...),
    date_to: str = Form(...),
    year_agnostic: str = Form(""),
    conn=Depends(get_db),
):
    """The Holiday edit modal's single Save button (pattern B) -- one
    endpoint for every field the inline edit used to PATCH separately.
    There's no separate "update" helper in db.py -- a holiday's uid never
    changes, so upsert-by-uid already is the update."""
    holiday = db.get_holiday(conn, uid)
    if holiday is None:
        raise HTTPException(404, "Holiday not found")
    db.upsert_holiday(
        conn,
        {
            **holiday,
            "calendar_name": _resolve_calendar_name(calendar_name, calendar_name_new),
            "label": label,
            "date_from": _parse_holiday_date_field(date_from, bool(year_agnostic)),
            "date_to": _parse_holiday_date_field(date_to, bool(year_agnostic)),
        },
    )
    return RedirectResponse(url="/settings/holidays", status_code=303)


@router.post("/settings/holidays/{uid}/delete")
def delete_holiday(uid: str, conn=Depends(get_db)):
    db.delete_holiday(conn, uid)
    return RedirectResponse(url="/settings/holidays", status_code=303)


@router.post("/settings/holidays/bulk-delete")
async def bulk_delete_holidays(request: Request, conn=Depends(get_db)):
    """JSON endpoint for `static/bulk_select.js`'s Holidays
        instance -- a plain loop over the same `db.delete_holiday` each row's
        own single-delete button already calls, same "no all-or-nothing
        rollback" shape as `routers/tasks.py::bulk_action`'s delete branch.
    """
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no holidays selected"}, status_code=400)
    for uid in uids:
        db.delete_holiday(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


_TIME_BLOCKS_CRUMB = _ROOT_CRUMB

_DAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def _time_block_days_label(days_csv: str) -> str:
    """Human summary of a time block's day set -- abbreviations ("Mon Tue Fri"), not the full stored day
        names, with the two named sets spelled out: every day is "All week",
        exactly Monday-Friday is "All work week". `days_csv` is comma-separated
        in db.TIME_BLOCK_DAYS order (the form's checkbox order), so both the
        len==7 test and the Mon-Fri slice comparison are order-safe.
    """
    days = days_csv.split(",") if days_csv else []
    if len(days) == len(db.TIME_BLOCK_DAYS):
        return "All week"
    if days == db.TIME_BLOCK_DAYS[:5]:
        return "All work week"
    return " ".join(_DAY_ABBR.get(d, d) for d in days)


@router.get("/settings/time-blocks")
def settings_time_blocks(request: Request, conn=Depends(get_db)):
    sleep_blocks = db.list_time_blocks(conn, "sleep")
    leisure_blocks = db.list_time_blocks(conn, "leisure")
    time_blocks = sleep_blocks + leisure_blocks
    for block in time_blocks:
        block["days_label"] = _time_block_days_label(block.get("days") or "")
    return templates.TemplateResponse(
        "settings_time_blocks.html",
        {
            "request": request,
            "active_tab": "settings_time_blocks",
            "crumbs": _TIME_BLOCKS_CRUMB,
            "title": "Sleep & Leisure Time",
            "time_blocks": time_blocks,
            "time_block_days": db.TIME_BLOCK_DAYS,
        },
    )


@router.get("/settings/time-blocks/new")
def new_time_block_modal(request: Request, kind: str = Query("sleep"), conn=Depends(get_db)):
    """The "+ Add time block" entry point -- the same
        time_block_edit_modal.html the Edit buttons open, empty. Opens via
        data-modal from the list toolbar and posts to create_time_block below.
        `kind` is just this modal's initial chooser selection now -- Sleep/Leisure is a real field in the form
        (time_block_edit_modal.html's own comment), not fixed by the entry
        point; the `?kind=` query param survives only as a convenience default,
        unused by the current single "+ Add time block" row (always opens to
        the "sleep" default) but left in place in case a future caller wants
        to pre-select Leisure.
    """
    return templates.TemplateResponse(
        "time_block_edit_modal.html",
        {
            "request": request,
            "b": None,
            "form_title": "Add time block",
            "form_action": "/settings/time-blocks",
            "kind": kind,
            "time_block_days": db.TIME_BLOCK_DAYS,
        },
    )


@router.get("/settings/time-blocks/{uid}/edit")
def edit_time_block_modal(uid: str, request: Request, conn=Depends(get_db)):
    """The time-blocks table's Edit button modal (pattern B) -- one form
        for every field, replacing the old inline-editable table cells
        (static/settings_time_blocks.js's per-field PATCH). Opens via
        data-modal from the list row; posts to update_time_block below. `kind`
        (the row's current Sleep/Leisure) flows in as the chooser's initial
        selection, same as new_time_block_modal -- it's an editable field now, not fixed by which row this is.
    """
    block = db.get_time_block(conn, uid)
    if block is None:
        raise HTTPException(404, "Time block not found")
    return templates.TemplateResponse(
        "time_block_edit_modal.html",
        {
            "request": request,
            "b": block,
            "form_title": "Edit time block",
            "form_action": f"/settings/time-blocks/{uid}/update",
            "kind": block["kind"],
            "time_block_days": db.TIME_BLOCK_DAYS,
        },
    )


@router.post("/settings/time-blocks")
def create_time_block(
    kind: str = Form(...),
    label: str = Form(""),
    start_time: str = Form(...),
    end_time: str = Form(...),
    days: list[str] = Form([]),
    conn=Depends(get_db),
):
    if kind in db.TIME_BLOCK_KINDS and start_time and end_time and end_time > start_time:
        valid_days = [d for d in days if d in db.TIME_BLOCK_DAYS]
        db.upsert_time_block(
            conn,
            {
                "uid": str(uuid.uuid4()), "kind": kind, "label": label,
                "start_time": start_time, "end_time": end_time, "days": ",".join(valid_days),
            },
        )
    return RedirectResponse(url="/settings/time-blocks", status_code=303)


@router.post("/settings/time-blocks/{uid}/update")
def update_time_block(
    uid: str,
    kind: str = Form(""),
    label: str = Form(""),
    start_time: str = Form(...),
    end_time: str = Form(...),
    days: list[str] = Form([]),
    conn=Depends(get_db),
):
    """The time block edit modal's single Save button (pattern B) -- one
        endpoint for every field the inline edit used to PATCH separately. An unrecognized
        `kind` (a crafted/stale request) falls back to the block's existing
        kind rather than storing garbage -- same "drop the malformed edit,
        keep what's on screen" reasoning the end-time-after-start-time guard
        below already uses, just applied to this field too.
    """
    block = db.get_time_block(conn, uid)
    if block is None:
        raise HTTPException(404, "Time block not found")
    valid_days = [d for d in days if d in db.TIME_BLOCK_DAYS]
    valid_kind = kind if kind in db.TIME_BLOCK_KINDS else block["kind"]
    if start_time and end_time and end_time > start_time:
        db.upsert_time_block(
            conn,
            {
                **block,
                "kind": valid_kind,
                "label": label,
                "start_time": start_time,
                "end_time": end_time,
                "days": ",".join(valid_days),
            },
        )
    return RedirectResponse(url="/settings/time-blocks", status_code=303)


@router.post("/settings/time-blocks/{uid}/delete")
def delete_time_block(uid: str, conn=Depends(get_db)):
    db.delete_time_block(conn, uid)
    return RedirectResponse(url="/settings/time-blocks", status_code=303)


@router.post("/settings/time-blocks/bulk-delete")
async def bulk_delete_time_blocks(request: Request, conn=Depends(get_db)):
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no time blocks selected"}, status_code=400)
    for uid in uids:
        db.delete_time_block(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


SYNC_GC_DAYS_CHOICES = [("30", "Keep 30 days"), ("90", "Keep 90 days"), ("0", "Keep forever")]


def _backups_dir(request: Request) -> Path:
    return request.app.state.settings.backup_dir


def _radicale_config_source(settings, conn) -> str:
    """Which of the three places (see block comment above)
    `settings.radicale_base_url`/`username`/`password` actually came from,
    for right now -- not a guess, a direct readout of the same fields
    config.py's own load_settings/apply_persisted_radicale_overrides
    already computed. `radicale_env_configured` is authoritative for "env"
    (config.py sets it True iff CC_RADICALE_URL was present in the process
    environment at startup, whatever supplied it); app_meta's
    RADICALE_URL_KEY is only ever populated by the Account form's
    not-env-managed branch, so its presence alone means "database" without
    needing to also check username/password."""
    if getattr(settings, "radicale_env_configured", False):
        return "environment file (CC_RADICALE_URL)" if getattr(settings, "env_file_path", None) else "an environment variable (CC_RADICALE_URL) with no known file to edit"
    if db.get_app_meta(conn, config.RADICALE_URL_KEY):
        return "the database (set via Settings › Your Profile)"
    return "nothing -- using the built-in dev default (devuser/devpass)"


def _env_file_drift(settings) -> str | None:
    """None unless the on-disk env file's CC_RADICALE_* values disagree
    with what THIS running process actually has loaded (which only ever
    changes at startup -- main.py's lifespan builds the CalDavBridge once,
    no live reload). A disagreement means someone edited curodav.env (by
    hand, or via curodav-ctl install --dav) after this process last
    started, and hasn't restarted since -- exactly the "did my env change
    actually take effect" question with no other visible answer. Only
    checked when env-configured; app_meta-backed installs have no file to
    drift from."""
    env_path = getattr(settings, "env_file_path", None)
    if not env_path or not getattr(settings, "radicale_env_configured", False):
        return None
    file_values = env_file.read_env_file(env_path)
    live = {
        "CC_RADICALE_URL": getattr(settings, "radicale_base_url", None),
        "CC_RADICALE_USER": getattr(settings, "radicale_username", None),
        "CC_RADICALE_PASSWORD": getattr(settings, "radicale_password", None),
    }
    drifted = sorted(key for key, value in live.items() if key in file_values and file_values[key] != value)
    if not drifted:
        return None
    return (
        f"curodav.env has changed ({', '.join(drifted)}) since this process last started -- "
        "restart the app (below) to pick up the new value."
    )


def _radicale_public_url_mismatch(settings) -> str | None:
    """None unless `CC_RADICALE_PUBLIC_URL` (display-only, Published
    Lists' subscribe_url) and `CC_RADICALE_URL` (what the app actually
    syncs against) disagree about which Radicale *user* they point at --
    e.g. CC_RADICALE_URL was hand-edited or RADICALE_USER rotated via
    `curodav-ctl install --dav` without the public URL being updated to
    match. Compares only the last non-empty path segment (the username --
    both URLs' documented shape is `.../<user>/`), not the whole URL,
    since scheme/host legitimately differ (loopback vs. the public
    hostname) by design."""
    base = (getattr(settings, "radicale_base_url", None) or "").rstrip("/")
    public = (getattr(settings, "radicale_public_base_url", None) or "").rstrip("/")
    if not base or not public:
        return None
    base_user = base.rsplit("/", 1)[-1]
    public_user = public.rsplit("/", 1)[-1]
    if base_user and public_user and base_user != public_user:
        return (
            f'The public URL\'s user ("{public_user}") doesn\'t match the sync URL\'s '
            f'("{base_user}") -- CC_RADICALE_PUBLIC_URL and CC_RADICALE_URL look out of sync.'
        )
    return None


def _check_radicale_connection(settings) -> tuple[bool, str]:
    """A live, authenticated PROPFIND against whatever Radicale connection
    THIS running process currently has loaded -- the only way to answer
    "is this actually working right now" without watching journalctl
    during a real phone sync. Deliberately bypasses app.state.bridge: that
    CalDavBridge was built once at startup (main.py's lifespan) and is
    `None` forever if Radicale was unreachable at that moment, so reading
    it here would just repeat one stale verdict on every click instead of
    a fresh check -- the whole point of a "Test connection" button. Depth
    0 PROPFIND on the base collection URL is the cheapest real request
    that exercises both the network path and the credentials (a bare GET
    can 200 on an unauthenticated reverse proxy without ever reaching
    Radicale's own auth check)."""
    url = getattr(settings, "radicale_base_url", "") or ""
    user = getattr(settings, "radicale_username", "") or ""
    password = getattr(settings, "radicale_password", "") or ""
    try:
        resp = httpx.request(
            "PROPFIND",
            url,
            auth=(user, password),
            headers={"Depth": "0", "Content-Type": "application/xml"},
            content='<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:"><D:prop><D:displayname/></D:prop></D:propfind>',
            timeout=5.0,
        )
    except httpx.RequestError as exc:
        return False, f"Could not reach Radicale at {url} -- {exc}"
    if resp.status_code in (200, 207):
        return True, f"Connected -- HTTP {resp.status_code} from {url}."
    if resp.status_code in (401, 403):
        return False, f"Radicale rejected the credentials (HTTP {resp.status_code}) -- check the username/password."
    return False, f"Unexpected response from Radicale: HTTP {resp.status_code}."


@router.post("/settings/radicale/test-connection")
def test_radicale_connection(request: Request):
    """"Test connection" button (Data & Maintenance's CalDAV/Radicale
    card) -- see _check_radicale_connection's own docstring for why this
    always does a fresh live request rather than reusing app.state.bridge.
    Reuses the page's existing toast mechanism (data_maintenance.js reads
    ?note=/?error=), same as every other action on this page, so the
    result shows up as a floating toast right next to the button that
    triggered it instead of a full page reload changing anything else."""
    ok, message = _check_radicale_connection(request.app.state.settings)
    target = "/settings/data-maintenance"
    return _redirect_with_note(target, message) if ok else _redirect_with_error(target, message)


def _choices_with_stored_value(
    choices: list[tuple[str, str]], stored: str
) -> list[tuple[str, str]]:
    """The rendered select's options, with one honest extra entry appended
        when the currently-stored value isn't among the presets. Without this, the browser would silently display the first
        preset while the stored value stayed something else -- a lie. The
        extra entry autosubmits like any other, so picking anything real
        replaces it; it's never itself written back (the POST routes validate
        against the preset lists only).
    """
    if any(value == stored for value, _ in choices):
        return choices
    return [*choices, (stored, f"{stored} days (current)")]


@router.get("/settings/data-maintenance")
def settings_data_maintenance(request: Request, conn=Depends(get_db)):
    """The merged Data & Maintenance page. Context is
        everything the three former pages used to gather separately: the data
        health summary (health_summary's `integrity`/`latest_backup`/
        `latest_verified_backup`/`sync`/`sync_gc`/`storage`/`entities`/
        `backups`), the unresolved sync conflicts, and Advanced's export/
        import + purge/auto-archive context (export_context() plus the counts
        and choices settings_data_maintenance.html renders).
    """
    backups_dir = _backups_dir(request)
    summary = data_health.health_summary(conn, request.app.state.settings.db_path, backups_dir)
    completed_task_count = len([t for t in db.list_tasks(conn) if t["status"] in ("done", "archived")])
    auto_archive_days = db.get_app_meta(conn, TASK_AUTO_ARCHIVE_DAYS_KEY) or "0"
    sync_gc_days = str(summary["sync_gc"]["retention_days"])
    ctx = {
        "request": request,
        "active_tab": "settings_data_maintenance",
        "crumbs": _ROOT_CRUMB,
        "title": "Data & Maintenance",
        "conflicts": db.list_sync_conflicts(conn),
        "sync_gc_days_choices": _choices_with_stored_value(SYNC_GC_DAYS_CHOICES, sync_gc_days),
        "completed_task_count": completed_task_count,
        "task_auto_archive_days": auto_archive_days,
        "days_choices": _choices_with_stored_value(DAYS_CHOICES, auto_archive_days),
        "radicale_url": request.app.state.settings.radicale_base_url,
        "radicale_env_configured": getattr(request.app.state.settings, "radicale_env_configured", False),
        "radicale_source": _radicale_config_source(request.app.state.settings, conn),
        "radicale_public_url": getattr(request.app.state.settings, "radicale_public_base_url", None),
        "radicale_public_url_warning": _radicale_public_url_mismatch(request.app.state.settings),
        "radicale_env_drift": _env_file_drift(request.app.state.settings),
        "restart_available": getattr(request.app.state.settings, "deploy_mode", "local") == "production",
    }
    ctx.update(summary)
    ctx.update(export_context(conn))
    return templates.TemplateResponse("settings_data_maintenance.html", ctx)


@router.get("/settings/data-health")
def settings_data_health(request: Request, conn=Depends(get_db)):
    """Old Data health page URL -- kept as a redirect to the merged
        Data & Maintenance page so old bookmarks/links
        (and the many action endpoints' redirect targets) land somewhere real.
    """
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/data-health/backup")
def data_health_backup(request: Request, conn=Depends(get_db)):
    path = data_health.create_backup(conn, _backups_dir(request))
    return RedirectResponse(url=f"/settings/data-maintenance?note=Backup+created+({path.name}).", status_code=303)


@router.post("/settings/data-health/verify")
def data_health_verify(request: Request, filename: str = Form(""), conn=Depends(get_db)):
    backups_dir = _backups_dir(request)
    target = backups_dir / filename if filename else None
    if target is None or not target.exists():
        latest = data_health.latest_backup(backups_dir)
        target = Path(latest["path"]) if latest else None
    if target is None:
        return RedirectResponse(url="/settings/data-maintenance?error=No+backup+to+verify+yet.", status_code=303)
    result = data_health.verify_backup(target)
    note = "Backup+verified+OK." if result.ok else f"Verification+found+{len(result.errors)}+problem(s)."
    return RedirectResponse(url=f"/settings/data-maintenance?{'note' if result.ok else 'error'}={note}", status_code=303)


@router.post("/settings/data-health/restore")
def data_health_restore(request: Request, filename: str = Form(...), conn=Depends(get_db)):
    """Restores one of the server-stored backups listed on the page (by
    filename, never a client-supplied path) -- restoring an *uploaded*
    file is the existing /export/import/json flow (Settings > Advanced),
    unchanged. Always takes a pre-restore safety snapshot first (see
    data_health.restore_backup's own docstring)."""
    backups_dir = _backups_dir(request)
    target = backups_dir / filename
    if ".." in filename or "/" in filename or not target.resolve().is_relative_to(backups_dir.resolve()):
        raise HTTPException(400, "Invalid backup filename.")
    result = data_health.restore_backup(conn, target, backups_dir=backups_dir)
    if not result["ok"]:
        return RedirectResponse(url="/settings/data-maintenance?error=Restore+aborted%3A+backup+failed+verification.", status_code=303)
    return RedirectResponse(
        url=f"/settings?note=Restored+{result['restored']}+row(s).+A+safety+backup+of+the+prior+state+was+made+first.",
        status_code=303,
    )


@router.post("/settings/data-health/integrity-check")
def data_health_integrity_check(conn=Depends(get_db)):
    result = data_health.check_integrity(conn)
    note = "Database+integrity%3A+OK." if result["ok"] else "Database+integrity+check+found+problems+-+see+detail."
    return RedirectResponse(url=f"/settings/data-maintenance?{'note' if result['ok'] else 'error'}={note}", status_code=303)


@router.post("/settings/data-health/repair")
def data_health_repair(request: Request, conn=Depends(get_db)):
    result = data_health.compact_and_reindex(conn, request.app.state.settings.db_path)
    return RedirectResponse(url="/settings/data-maintenance?note=Compacted+and+reindexed+the+database.", status_code=303)


@router.post("/settings/data-health/sync-retention")
def data_health_set_sync_retention(days: str = Form("90"), conn=Depends(get_db)):
    """`0` disables automatic (lazy, on-pull) GC --
        same "0 = Never" idiom `routers/tasks.py`'s auto-archive field already
        uses -- without touching `pull()`'s own stale-cursor-forces-full-resync
        safety check, which isn't gated by this setting at all. Only ever
        stores one of the offered presets, same validation-against-the-select's-
        -own-options convention as `set_task_auto_archive`.
    """
    valid = {choice for choice, _ in SYNC_GC_DAYS_CHOICES}
    data_health.set_sync_gc_retention_days(conn, int(days) if days in valid else 90)
    return RedirectResponse(url="/settings/data-maintenance?note=Sync+cleanup+retention+updated.", status_code=303)


@router.post("/settings/data-health/sync-gc")
def data_health_run_sync_gc(conn=Depends(get_db)):
    """The manual "Run cleanup now" action -- always runs (force=True),
    even if the lazy automatic trigger is set to Never, same as this
    page's other maintenance actions (Backup now, Verify, Repair) always
    being available regardless of any automatic counterpart's own
    setting."""
    result = data_health.run_sync_gc(conn, force=True)
    purged_entities = result["purged_entities"]
    purged_total = sum(purged_entities.values()) + result["purged_applied_ops"]
    note = f"Sync+cleanup+ran%3A+{purged_total}+row(s)+purged." if purged_total else "Sync+cleanup+ran%3A+nothing+to+purge."
    return RedirectResponse(url=f"/settings/data-maintenance?note={note}", status_code=303)


@router.get("/settings/advanced")
def settings_advanced(request: Request, conn=Depends(get_db)):
    """Old Advanced page URL -- kept as a redirect to the merged
        Data & Maintenance page so old bookmarks/links
        (and the export/import redirect from routers/export.py) land
        somewhere real.
    """
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/task-auto-archive")
def set_task_auto_archive(days: str = Form("0"), conn=Depends(get_db)):
    """"Auto-archive completed tasks" -- a plain string count of days
    ("0" = Never, the default) read back by routers/tasks.py's
    _auto_archive_if_configured on every visit to the Tasks table view.
    Only ever stores one of settings_data_maintenance.html's own offered
    options (validated against DAYS_CHOICES rather than trusting the raw
    POST body) -- an unrecognized value falls back to "0"/Never rather
    than silently deleting tasks on some unintended schedule."""
    valid = {choice for choice, _ in DAYS_CHOICES}
    db.set_app_meta(conn, TASK_AUTO_ARCHIVE_DAYS_KEY, days if days in valid else "0")
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/purge-completed")
def purge_completed(conn=Depends(get_db)):
    db.delete_completed_tasks(conn)
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/purge-all")
def purge_all(request: Request, conn=Depends(get_db)):
    db.purge_all_data(conn)
    state = getattr(request.app, "state", None)
    if state is not None:
        state._cc_auth_secret = None
        state._cc_auth_configured = False
    response = RedirectResponse(url="/settings/data-maintenance", status_code=303)
    response.delete_cookie(
        auth.SESSION_COOKIE, path="/", samesite="lax", secure=auth.is_secure_request(request)
    )
    return response


@router.get("/settings/sync-conflicts")
def settings_sync_conflicts(request: Request, conn=Depends(get_db)):
    """Old Sync conflicts page URL -- kept as a redirect to the merged
        Data & Maintenance page so old bookmarks/links
        (and the restore/dismiss redirects below) land somewhere real.
    """
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/sync-conflicts/{conflict_id}/restore")
def restore_sync_conflict(conflict_id: str, conn=Depends(get_db)):
    """Restoring the losing value is not a special sync-only code path --
    it's a normal new `field_set`/`label_add` op, given a fresh HLC (`now`,
    logical 0, a synthetic "settings-restore" device id, always sorting
    after every real device's own last write), applied through the exact
    same offline_sync.apply_op every push already goes through. The
    conflict is then dismissed -- the restore itself is the resolution."""
    conflict = db.get_sync_conflict(conn, conflict_id)
    if conflict is None:
        return RedirectResponse(url="/settings/data-maintenance", status_code=303)
    now_ms = int(clock.now().timestamp() * 1000)
    restore_hlc = {"physical": now_ms, "logical": 0, "device_id": "settings-restore"}
    if conflict["field_name"] == "project_label":
        offline_sync.apply_op(conn, {
            "op_id": f"restore-{conflict_id}",
            "entity_type": "object_label",
            "entity_uid": conflict["entity_uid"],
            "op_type": "label_add",
            "device_id": "settings-restore",
            "hlc": restore_hlc,
            "target": {
                "object_type": conflict["entity_type"],
                "object_id": conflict["entity_uid"],
                "label_name": conflict["losing_value"],
            },
        })
    else:
        offline_sync.apply_op(conn, {
            "op_id": f"restore-{conflict_id}",
            "entity_type": conflict["entity_type"],
            "entity_uid": conflict["entity_uid"],
            "op_type": "field_set",
            "device_id": "settings-restore",
            "fields": {conflict["field_name"]: {"value": conflict["losing_value"], "hlc": restore_hlc}},
        })
    db.resolve_sync_conflict(conn, conflict_id)
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)


@router.post("/settings/sync-conflicts/{conflict_id}/dismiss")
def dismiss_sync_conflict(conflict_id: str, conn=Depends(get_db)):
    db.resolve_sync_conflict(conn, conflict_id)
    return RedirectResponse(url="/settings/data-maintenance", status_code=303)
