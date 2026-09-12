"""Settings -- reworked 2026-08-08 into a real hub-and-children area instead
of one long page (see features/settings.md's 2026-08-08 entry for the
full brainstorm/rationale; the 2026-08-07 pass this replaces got Settings
to "four honest groups on one page," which was real progress but still one
scrolling page mixing a dozen unrelated controls together).

Audited every setting this app actually exposes (routers/*.py, db.py's
schema, every template with a form that isn't a create/edit modal) before
deciding on structure, per the redesign brief's own instruction not to
force settings into categories that only look complete. Result: five
categories, each earning its own focused page because each is a distinct
thing a user thinks about, not because five is a tidy number --

  1. General     -- identity + format preferences: display name, week
                     start, time format; plus (2026-08-30) old/new/confirm
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

2026-08-08 follow-up: "Widgets" (its own hub category, holding a "Custom
widgets" builder on/off toggle plus the reset-layout action) is gone --
per direct feedback, the toggle itself was removed outright (see
_modal_widget_customize.html's own comment: it was a boolean whose only
effect was hiding the one way to add a widget, not a real preference).
That left exactly one action in that category (reset layout), not enough
to justify its own top-level page -- folded into Advanced instead, next
to the other rarely-touched, real-capability actions it already
thematically belongs with.

2026-08-08 follow-up #2: "Data & backup" (a sub-hub of Habits/Published
lists/Export) is gone too, per direct feedback -- Export & backup moved
into Advanced (same "real capability" theme as Reset layout/Auto-archive/
Purge), and Published lists became a direct hub category in its own right
rather than nested one level deeper. Habits is NOT a hub category (2026-08-08
follow-up #3): it's reached from Tasks > Habits, its contextual home where
the habit-tracking label setting also lives (tasks.py's save_habit_settings),
so a Settings-hub shortcut would be pure mirroring of something already one
click away. Once Export left, Data & backup had exactly two entries doing
nothing but forwarding to Habits/Published lists -- a layer with no content
of its own, just indirection.

Explicitly NOT created, and why (see the redesign brief's "only create
categories that are actually useful"):
  - Notifications -- the only reminder-adjacent setting (Schedule's
    reminder_minutes) is itself contextual, living on /schedule (see
    below); there's no cross-app notification system to configure.
  - Integrations -- Radicale is internal plumbing for Published Lists,
    not a user-facing connection to configure; nothing else calls out.
  - Privacy -- no accounts, no telemetry toggle, nothing to show here;
    a page with zero real content is worse than no page.
  - Calendar/Tasks as their own Settings categories -- Schedule's own
    settings (semester dates/credits/reminder/event label) already moved
    onto /schedule itself as a <details> block (2026-08-08, before this
    redesign) specifically so there wouldn't be two paths to the same
    four fields; re-adding a Settings mirror here would recreate exactly
    the "which one is current" drift that move was fixing. Tasks has no
    settings of its own beyond the habit-tracking label, which likewise
    already lives contextually on Tasks > Habits (tasks.py's
    save_habit_settings) for the same reason. Both stay contextual-only,
    not mirrored -- see the redesign brief's own "only mirror a setting
    when the contextual shortcut provides a real usability advantage";
    a settings mirror nobody asked for isn't one.

2026-08-14 follow-up: Holidays is the one exception to the "Schedule stays
contextual-only" rule directly above, and deliberately so -- a named
holiday calendar isn't a Schedule *setting* (a single field like semester
dates), it's a reusable, named list of date ranges any recurring event
anywhere in the app can reference (1.6), the same "Labels" shape as the
existing Labels hub category rather than a per-page config field. It moved
from Schedule's Table view into its own `/settings/holidays` hub category,
built as a Tasks-table-style grid. Schedule's own <details> Settings panel
still keeps its `holiday_calendar` field (which named calendar the
semester's classes respect) -- only the calendars' contents moved, not the
picker that chooses among them.

Every child page shares one back-navigation shape (_settings_breadcrumb
.html): "Settings" (or "Settings / Data") as a link, current page as plain
text -- Back always returns one level up inside Settings, never out to
whatever page was open before Settings was entered (redesign brief item 3).
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import threading
import uuid

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import auth, config, data_health, db, env_file, offline_sync
from ..image_sniff import sniff_image_type
from ..deps import (
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
    templates,
)
from .dashboard import DISPLAY_NAME_KEY
from .export import _redirect_with_error, _redirect_with_note, export_context
from .tasks import TASK_AUTO_ARCHIVE_DAYS_KEY

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

# Hub categories (settings_index.html) -- name/desc/icon/url for each of the
# pages above. Labels/Published lists are direct links to their existing
# manage pages (no /settings/* wrapper for either -- see
# labels_manage.html/published_lists.html's own breadcrumbs for how each
# still reads as "inside Settings"). Habits is deliberately NOT a hub
# category: it's reached from Tasks > Habits, its contextual home.
#
# 2026-08-17 settings HTML uniformity pass (SETTINGS_UI_GUIDE.md
# "Proposed reorganization") -- Data health, Sync conflicts and Advanced
# were three pages splitting "everything about your data's safety and
# lifecycle" across them with no priority ordering inside any of them.
# They're one "Data & Maintenance" category now (settings_data_maintenance.
# html, urgent items first): the old /settings/data-health,
# /settings/sync-conflicts and /settings/advanced URLs stay as 303
# redirects for old bookmarks/links. The conflict-count badge that makes an
# unresolved conflict visible from the hub itself lives on this one row
# (settings_index.html reads `conflict_count`).
HUB_CATEGORIES = [
    {"url": "/settings/general", "icon": "user", "name": "General", "desc": "Week start, time format, and other display preferences"},
    {"url": "/settings/your-profile", "icon": "user-check", "name": "Your Profile", "desc": "Profile picture, nickname, login & security"},
    {"url": "/settings/appearance", "icon": "sun", "name": "Appearance", "desc": "Theme"},
    {"url": "/settings/labels", "icon": "tag", "name": "Labels", "desc": "Rename, recolor, organize"},
    {"url": "/settings/holidays", "icon": "calendar", "name": "Holidays", "desc": "Named holiday calendars non-working recurrence respects"},
    {"url": "/settings/time-blocks", "icon": "moon", "name": "Sleep & Leisure Time", "desc": "Weekly hours the Week/Day grid highlights and warns about"},
    {"url": "/settings/data-maintenance", "icon": "database", "name": "Data & Maintenance", "desc": "Backups, integrity, sync conflicts, export, purge"},
    {"url": "/published-lists", "icon": "share-2", "name": "Published lists", "desc": "Subscribable filtered calendars/lists"},
]

# Breadcrumb roots shared by every settings_*.html page below.
_ROOT_CRUMB = [{"url": "/settings", "name": "Settings"}]

# "Auto-archive completed tasks" (settings_data_maintenance.html) -- a
# fixed set of choices, not a free-typed number: a handful of sane presets
# is faster to pick from and impossible to fat-finger into "archive after
# 0.5 days" or a negative number. "0" is Never, this app's original
# behavior (nothing auto-deletes) -- always the default for an existing
# install that's never touched this control. Relabeled 2026-08-26 (page
# redesign): the plain day-counts became the plainer phrases below; the
# stored values are unchanged, so existing settings keep working.
DAYS_CHOICES = [("0", "Never"), ("7", "After 1 week"), ("30", "After 1 month")]


@router.get("/settings")
def settings_index(request: Request, conn=Depends(get_db)):
    # conflict_count feeds the Data & Maintenance row's badge
    # (settings_index.html) -- the "visible even without visiting the page"
    # half of SETTINGS_UI_GUIDE.md's sync-conflict recommendation.
    return templates.TemplateResponse(
        "settings_index.html",
        {
            "request": request,
            "active_tab": "settings",
            "categories": HUB_CATEGORIES,
            "conflict_count": len(db.list_sync_conflicts(conn)),
        },
    )


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
            # 2026-08-08 -- "Week starts on" and "24-hour time" are the
            # same kind of thing (a personal display/format preference, not
            # tied to one specific page) and both affect several pages at
            # once (Calendar Month/Week, Schedule, every dashboard widget
            # that shows a time), so neither earns its own Settings
            # category -- see deps.py's week_start()/time_format() for
            # where these get read back out everywhere else in the app.
            # Named current_week_start/current_time_format, NOT week_start/
            # time_format -- those names are already taken by deps.py's
            # own Jinja globals (week_start(request)/time_format(request),
            # called from base.html on every single page). A same-named
            # context variable shadows a same-named global in Jinja, so
            # passing "time_format" here broke base.html's own
            # `{{ time_format(request) }}` call the instant this page
            # rendered it -- "'str' object is not callable" (found via the
            # test suite, not a hunch).
            "current_week_start": db.get_app_meta(conn, WEEK_START_KEY) or "monday",
            "current_time_format": db.get_app_meta(conn, TIME_FORMAT_KEY) or "24h",
            # 2026-08-11 -- "4-Week view: current week" (see deps.py's
            # FOUR_WEEK_POSITION_KEY): which of the four rows the Calendar
            # 4-Week view's current week occupies. Read back through the
            # same _four_week_position_from_value parse the calendar route
            # itself uses, so "this setting shows 1/2/3/4" and "the view
            # does what the setting says" can't disagree on a bad value.
            "current_four_week_position": _four_week_position_from_value(
                db.get_app_meta(conn, FOUR_WEEK_POSITION_KEY) or "1"
            ),
            # 1.6 ("Configurable terminology") -- "standard" or "playful"
            # labels on the recurrence editor's holiday-calendar/weekend
            # controls. See deps.py's RECURRENCE_TERMINOLOGY_KEY comment.
            "current_recurrence_terminology": db.get_app_meta(conn, RECURRENCE_TERMINOLOGY_KEY) or "standard",
            # 2026-08-28 -- "Habit streak terminology" -- "standard" or
            # "playful" wording for the Habits group's streak readout
            # (Tasks table). See deps.py's HABIT_STREAK_TERMINOLOGY_KEY.
            "current_habit_streak_terminology": db.get_app_meta(conn, HABIT_STREAK_TERMINOLOGY_KEY) or "standard",
            # 2026-09-09 (direct request) -- "Hide sleep hours in Planner":
            # off by default. Read back by routers/calendar.py's
            # _week_view_context via _sleep_collapse_window; see that
            # function's own docstring for what happens when this is on but
            # the configured Sleep-kind time blocks don't agree on one
            # single start/end window.
            "current_hide_sleep_hours": db.get_app_meta(conn, HIDE_SLEEP_HOURS_KEY) == "1",
        },
    )


@router.get("/settings/your-profile")
def settings_your_profile(request: Request, conn=Depends(get_db)):
    """2026-09-11 direct request: "move the password, username, radicale
    url etc, settings from general to a new page named Your Profile. It
    should include the Profile Picture and Nickname (current Your Name,
    used in greeting)." Same context fields settings_general used to build
    for its Profile picture / Your name / Account / Restart app cards --
    moved here verbatim, this page's own template is those same cards'
    markup unchanged (only the page title/crumbs and where the underlying
    routes redirect back to)."""
    settings = _current_settings(request)
    return templates.TemplateResponse(
        "settings_your_profile.html",
        {
            "request": request,
            "active_tab": "settings_your_profile",
            "crumbs": _ROOT_CRUMB,
            "title": "Your Profile",
            "display_name": db.get_app_meta(conn, DISPLAY_NAME_KEY) or "",
            # The user's own profile picture (2026-08-09) -- {photo_b64,
            # photo_type} or None, stored in app_meta (db.py's profile-photo
            # helpers, same store as the display name). Rendered as the
            # avatar on this page.
            "profile_photo": db.get_profile_photo(conn),
            # Account (2026-09-08 -- replaces the old separate "Login &
            # security" app-login card and Data & Maintenance's "CalDAV /
            # Radicale sync" card; see account_settings' own docstring for
            # the merge this reflects: one username/password, used for
            # both). auth_is_env / radicale_env_configured together decide
            # whether this install's credentials currently live in the
            # env file or in app_meta -- env_file_available is whether
            # there's actually a CC_ENV_FILE to rewrite when they do
            # (curodav-ctl deploys always have one; a local/manual run
            # doesn't, and account_settings refuses to silently fall back
            # to app_meta out from under an env-configured install).
            # has_account distinguishes "change your credentials"
            # (current password required) from "set them up for the first
            # time" (no account yet -- common in local/dev, where /setup
            # never runs). getattr-guarded: several test files build a
            # bare SimpleNamespace Settings stand-in predating some of
            # these fields.
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
    """Settings > Your Profile's "Account" card -- 2026-09-08, direct request
    ("merge the concept of radicale username to the app username, and
    merge the app password with the radicale password"). Replaces three
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
    it were a real chosen credential."""
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
        # 2026-09-11 direct request: "Restart app" moved to Data &
        # Maintenance and "should be able to be called after editing
        # important environment data for the app, appearing in the form of
        # a toast" -- redirecting THERE instead of back to Your Profile is
        # what makes that true: this page's note-becomes-a-toast script
        # (data_maintenance.js) turns "Saved..." into a floating toast that
        # lands right next to the Restart app button, not a static banner
        # on a page that no longer has that button at all.
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
    # 2026-09-07 audit fix (carried over from change_login_password): rotate
    # the session-signing secret whenever persisted credentials are
    # (re)established, so a session issued under the old password stops
    # verifying immediately instead of staying valid for the rest of its
    # 30-day life. The in-process cache AuthMiddleware reads is updated
    # here too, same as purge_all, so this response's own freshly-minted
    # cookie doesn't look unauthenticated on the very next request.
    secret = auth.rotate_session_secret(settings, conn)
    if state is not None:
        state._cc_auth_secret = secret
    token = auth.make_session_token(secret, username)
    # 2026-09-11 direct request: same reasoning as the env-managed branch
    # above -- only redirect to Data & Maintenance (where the toast lands
    # next to the Restart app button) when a restart is actually relevant
    # (a new password or Radicale URL was saved); a username-only change
    # already takes effect immediately (the session was just re-minted
    # above), so there's nothing to restart for and the user stays on
    # Your Profile.
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
    """Settings > Data & Maintenance's "Restart app" button -- 2026-09-08,
    direct request ("have a button actually restarting the app so it
    applies"); moved here from Settings > Your Profile 2026-09-11 (direct
    request, same paragraph: "The Restart app should also be moved to the
    Data & Maintenance and should be able to be called after editing
    important environment data for the app, appearing in the form of a
    toast") -- see account_settings' own `restart_relevant`
    redirect-target logic for the toast half of that request.
    Applies an account_settings env-file save (or any other change that
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
    instead of actually exiting."""
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


# --------------------------------------------------------------------- #
# Profile picture (2026-08-09) -- the user's own avatar, editable from
# Settings > General, stored as base64 in app_meta (see db.py's
# get_profile_photo/set_profile_photo/clear_profile_photo -- same store the
# display name lives in). The file input reuses the `.avatar-upload`/
# `.avatar-upload-input` markup from contact_form.html, so static/
# avatar_cropper.js's crop/resize tool wires up automatically and the form
# still posts a plain `name="photo"` file exactly like a contact's.
# --------------------------------------------------------------------- #

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
        # 2026-09-07 fix (flagged in an earlier audit): `image_type` above
        # only reflects the browser's own Content-Type claim -- confirm the
        # bytes actually are a real image before storing them, using
        # whatever the bytes actually are rather than trusting the
        # (possibly spoofed) header any further.
        sniffed = sniff_image_type(data)
        if sniffed is None:
            raise HTTPException(400, "That file doesn't look like a real JPEG, PNG, GIF, or WEBP image.")
        db.set_profile_photo(conn, base64.b64encode(data).decode("ascii"), sniffed)
    return RedirectResponse(url="/settings/your-profile", status_code=303)


@router.post("/settings/profile-photo-remove")
def remove_profile_photo(conn=Depends(get_db)):
    """Clear the profile picture back to the initials fallback. A separate
    POST route (never a GET link) so removing is a real form submission,
    same non-cacheable convention as every other destructive action here."""
    db.clear_profile_photo(conn)
    return RedirectResponse(url="/settings/your-profile", status_code=303)


@router.get("/settings/profile-photo/image")
def profile_photo_image(conn=Depends(get_db)):
    """Serves the profile picture's decoded bytes for `<img src>` (2026-08-29,
    direct request: "better cache these images"). Exact mirror of routers/
    banners.py's banner_image -- same problem (a profile photo used to be
    embedded as an inline `data:` URI, deps.py's avatar() global, riding
    along in the HTML of every page that shows it: contact list rows aside,
    this one specifically rendered on every dashboard/label/Space page via
    the header avatar overlap), same fix (a real, separately cacheable
    request), same immutable Cache-Control safety argument (the URL's own
    `?v=` -- db.get_profile_photo's `version` -- changes whenever the photo
    does, so a stale cached response can never be served under a freshly-
    rendered page's URL)."""
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
    """"4-Week view: current week" (2026-08-11) -- which of the four rows
    of the Calendar 4-Week view the current week occupies. Only ever stores
    one of the settings_ general page's own offered choices ("1".."4",
    validated against the same fixed set deps.py's reader clamps to); an
    unrecognized or tampered value falls back to "1" (first row) rather
    than silently placing the current week somewhere the UI never offered.
    Read back by routers/calendar.py's four_week_view."""
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


@router.post("/settings/hide-sleep-hours")
def set_hide_sleep_hours(enabled: str = Form(""), conn=Depends(get_db)):
    """"Hide sleep hours in Planner" (Settings > General, 2026-09-09, direct
    request: "the time tagged as sleep time is just removed as cells from
    the planner calendar view"). Off by default, same on/off pattern as
    set_edit_mode above. Read back by routers/calendar.py's
    _week_view_context -- Week/Planner only, Day view is unaffected
    regardless of this setting (direct decision)."""
    db.set_app_meta(conn, HIDE_SLEEP_HOURS_KEY, "1" if enabled == "1" else "")
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
            # 2026-08-09 -- named current_show_label_icons, NOT
            # show_label_icons: that name is taken by deps.py's own Jinja
            # global (show_label_icons(request)), and a same-named context
            # variable would shadow it the way current_week_start was
            # forced on the General page for the exact same reason (see
            # settings_general's comment).
            "current_show_label_icons": db.get_app_meta(conn, SHOW_LABEL_ICONS_KEY) == "1",
            # Sidebar redesign item 13d (2026-08-29): edit mode is now a
            # persistent, app-wide toggle here instead of each dashboard/
            # label page's own "Edit mode"/"Done" buttons -- see
            # EDIT_MODE_KEY's own comment in routers/dashboard.py.
            "current_edit_mode": db.get_app_meta(conn, EDIT_MODE_KEY) == "1",
            # 2026-08-29 (sidebar redesign item 13e follow-up) -- the
            # Standard Page Header's own optional banner (deps.py's
            # PAGE_HEADER_BANNER_SCOPE); "Add"/"Change" label + the Remove
            # control inside the editor both key off whether this is set,
            # same convention as dashboard.html/label_detail.html's own
            # Add/Change banner button. Named current_page_header_banner,
            # NOT page_header_banner -- that name is taken by deps.py's own
            # Jinja global (page_header_banner(request), called inside
            # _page_header_narrow.html's own macro on every page, including
            # this one), same "current_X" convention as current_show_label_
            # icons/current_edit_mode above for the exact same shadowing
            # reason.
            "current_page_header_banner": db.get_page_banner(conn, PAGE_HEADER_BANNER_SCOPE),
        },
    )


@router.post("/settings/label-icons")
def set_label_icons(show: str = Form(""), conn=Depends(get_db)):
    """"Show icons next to labels" (Settings > Appearance, 2026-08-09) --
    renders every label's assigned icon before its name wherever the app
    shows a label (task/event label pills, Tasks table/board, calendar
    chips). Reads via deps.py's show_label_icons()/label_icon() globals.
    Default off -- an install that's never touched this stores nothing,
    which reads as "" (off), so labels stay plain text until explicitly
    turned on."""
    db.set_app_meta(conn, SHOW_LABEL_ICONS_KEY, "1" if show == "1" else "")
    return RedirectResponse(url="/settings/appearance", status_code=303)


@router.post("/settings/edit-mode")
def set_edit_mode(enabled: str = Form(""), conn=Depends(get_db)):
    """"Edit mode" (Settings > Appearance, 2026-08-29, sidebar redesign
    item 13d) -- shows the widget grid's editing controls (move/resize/
    reorder/delete a widget, New widget, Reset layout, Add/Change banner)
    on every dashboard/label/Space page until turned off here, replacing
    the old per-page "Edit mode"/"Done" buttons and their `?edit=1` query
    param (routers/dashboard.py's widget_page_context reads this flag
    directly now). Same on/off pattern as set_label_icons above."""
    db.set_app_meta(conn, EDIT_MODE_KEY, "1" if enabled == "1" else "")
    return RedirectResponse(url="/settings/appearance", status_code=303)


# --------------------------------------------------------------------- #
# Holidays -- moved here from Schedule's own Table view (2026-08-14), per
# direct feedback: a holiday calendar is a reusable, named resource that
# any recurring event can reference (1.6, "Generalized non-working-day
# policy + named holiday calendars"), not something specific to Schedule
# blocks -- the same "Labels get their own page, not a Tasks-only widget"
# reasoning that already applies elsewhere in this Settings hub. The page
# is a grouped list plus a modal (2026-08-17 settings HTML uniformity
# pass, SETTINGS_UI_GUIDE.md pattern B -- holiday_edit_modal.html) rather
# than the old inline-editable grid, so editing an existing holiday's dates
# is one whole-form Save instead of per-cell PATCH calls.
# --------------------------------------------------------------------- #

_HOLIDAYS_CRUMB = _ROOT_CRUMB


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
    return templates.TemplateResponse(
        "settings_holidays.html",
        {
            "request": request,
            "active_tab": "settings_holidays",
            "crumbs": _HOLIDAYS_CRUMB,
            "title": "Holidays",
            "holidays": db.list_holidays(conn),
        },
    )


@router.get("/settings/holidays/new")
def new_holiday_modal(request: Request, conn=Depends(get_db)):
    """The "+ Add holiday" entry point (2026-08-17 settings HTML
    uniformity pass, SETTINGS_UI_GUIDE.md pattern B) -- the same
    holiday_edit_modal.html the Edit buttons open, empty. Opens via
    data-modal, posts to create_holiday below."""
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

    audit-fixes-2.1.md ("only day holidays, without the year"): a
    year-agnostic holiday is stored as "--MM-DD" (db.py's
    is_year_agnostic_holiday_date), but the shared date picker only
    understands real calendar dates -- `date_from_value`/`date_to_value`
    feed it a placeholder-year stand-in (db.holiday_date_picker_value) so
    the right month/day still highlights, while `year_agnostic` drives the
    modal's "Repeats every year" checkbox that's what actually makes the
    year get discarded again on save."""
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
            "uid": str(uuid.uuid4()), "calendar_name": calendar_name.strip() or "Default",
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
            "calendar_name": calendar_name.strip() or "Default",
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
    """2026-08-29 (STATE.md backlog item 1, direct request: "bulk actions
    on tables"). JSON endpoint for `static/bulk_select.js`'s Holidays
    instance -- a plain loop over the same `db.delete_holiday` each row's
    own single-delete button already calls, same "no all-or-nothing
    rollback" shape as `routers/tasks.py::bulk_action`'s delete branch."""
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no holidays selected"}, status_code=400)
    for uid in uids:
        db.delete_holiday(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


# --------------------------------------------------------------------- #
# Sleep Time / Leisure Time (1.9 side work, direct feedback: "Add an
# option in the settings to set-up Leisure Time and Sleep Time... similar
# to the holiday settings, but just adding the hours... and days"). Same
# grouped-list-plus-modal shape as Holidays directly above (2026-08-17
# settings HTML uniformity pass, SETTINGS_UI_GUIDE.md pattern B) -- a
# read-only row per block, Edit button opening time_block_edit_modal.html.
# There's no date range, just a time-of-day start/end plus a day-of-week
# set (`_widget_list_multiselect.html`, filter mode -- see
# db.TIME_BLOCK_DAYS). See routers/calendar.py's `_time_block_overlays`
# for where these rows turn into the Week/Day grid's soft hatching +
# scheduling warning.
#
# 2026-09-08 follow-up (direct request): Sleep and Leisure used to be two
# separate tables (own bulk-select instance, own "+ Add" row, `kind`
# fixed by which table a row's Edit button lived in). They're one merged
# table now -- `kind` is a per-row "Type" column (a pill, red for Sleep/
# green for Leisure, matching the Week/Day grid's own hatching colors)
# instead of which table a row happens to sit in, and the add/edit modal
# grew a real Sleep/Leisure chooser (time_block_edit_modal.html's own
# comment) so a row's type is just another editable field now, not fixed
# at creation. `db.list_time_blocks` already stored both kinds in one
# `time_blocks` table with a `kind` column -- this was a template/route
# change, not a schema change.
# --------------------------------------------------------------------- #

_TIME_BLOCKS_CRUMB = _ROOT_CRUMB

_DAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def _time_block_days_label(days_csv: str) -> str:
    """Human summary of a time block's day set (2026-08-17 direct
    feedback) -- abbreviations ("Mon Tue Fri"), not the full stored day
    names, with the two named sets spelled out: every day is "All week",
    exactly Monday-Friday is "All work week". `days_csv` is comma-separated
    in db.TIME_BLOCK_DAYS order (the form's checkbox order), so both the
    len==7 test and the Mon-Fri slice comparison are order-safe."""
    days = days_csv.split(",") if days_csv else []
    if len(days) == len(db.TIME_BLOCK_DAYS):
        return "All week"
    if days == db.TIME_BLOCK_DAYS[:5]:
        return "All work week"
    return " ".join(_DAY_ABBR.get(d, d) for d in days)


@router.get("/settings/time-blocks")
def settings_time_blocks(request: Request, conn=Depends(get_db)):
    # 2026-09-08 (direct request): one merged, chronologically-sorted list
    # instead of two separate per-kind tables -- sleep_blocks/leisure_blocks
    # are still fetched separately (each already ordered by start_time) so
    # the merge is a simple concatenation, Sleep rows first then Leisure,
    # rather than an alphabetical-by-kind sort that would otherwise
    # interleave/reorder them in a less predictable way.
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
    """The "+ Add time block" entry point (2026-08-17 settings HTML
    uniformity pass, SETTINGS_UI_GUIDE.md pattern B) -- the same
    time_block_edit_modal.html the Edit buttons open, empty. Opens via
    data-modal from the list toolbar and posts to create_time_block below.
    `kind` is just this modal's initial chooser selection now (2026-09-08,
    direct request) -- Sleep/Leisure is a real field in the form
    (time_block_edit_modal.html's own comment), not fixed by the entry
    point; the `?kind=` query param survives only as a convenience default,
    unused by the current single "+ Add time block" row (always opens to
    the "sleep" default) but left in place in case a future caller wants
    to pre-select Leisure."""
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
    selection, same as new_time_block_modal -- it's an editable field now
    (2026-09-08, direct request), not fixed by which row this is."""
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
    endpoint for every field the inline edit used to PATCH separately.
    2026-09-08 (direct request): `kind` now DOES come from the form -- the
    Sleep/Leisure tables merged into one, so a row's type is just another
    editable field (the modal's chooser, time_block_edit_modal.html's own
    comment), not fixed by which table it used to live in. An unrecognized
    `kind` (a crafted/stale request) falls back to the block's existing
    kind rather than storing garbage -- same "drop the malformed edit,
    keep what's on screen" reasoning the end-time-after-start-time guard
    below already uses, just applied to this field too."""
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
    """2026-08-29 (STATE.md backlog item 1) -- same shape as
    bulk_delete_holidays above. Sleep and Leisure share one merged table
    (and one `CCBulkSelect` instance) since 2026-09-08, but this endpoint
    never needed to know which kind a uid belonged to in the first place --
    a time block's uid alone is all `db.delete_time_block` needs -- so it's
    unchanged by that merge."""
    payload = await request.json()
    uids = payload.get("uids") or []
    if not uids:
        return JSONResponse({"error": "no time blocks selected"}, status_code=400)
    for uid in uids:
        db.delete_time_block(conn, uid)
    return JSONResponse({"ok": True, "count": len(uids)})


# --------------------------------------------------------------------- #
# Data & Maintenance (`plans/open.md` § Data health & maintenance) --
# the merged page for everything about your data's safety and lifecycle,
# reorganized 2026-08-17 (SETTINGS_UI_GUIDE.md "Proposed reorganization:
# Advanced + Data health + Sync conflicts") into one priority-ordered page:
# needs-attention first, then health status, primary actions, export &
# import, danger zone, backups last. It folds together three former pages
# -- Data health (server-side, actively-verified backups plus database
# integrity/repair, the 1.8 "trusted only once verified backups exist"
# precondition; every route here is a thin wrapper around src/data_health.
# py's plain functions, the same functions scripts/data_health.py calls),
# Advanced (export & backup, reset Home's widget layout, auto-archive
# completed tasks by age, plus two explicit confirmed-destructive purge
# actions), and Sync conflicts (1.8 slice 2, §7b/c -- a conflict is never
# auto-resolved, restore/dismiss are the only two things a person can do
# with one). The old three URLs redirect here for old bookmarks/links.
# --------------------------------------------------------------------- #

# Fixed preset choices, not a free-typed number -- same reasoning as
# settings_data_maintenance.html's own auto-archive field (this module's
# own DAYS_CHOICES): a select autosubmits on pick, matching this page's
# other direct controls, and a validated preset can never end up storing
# something typo'd/out-of-range. This app's sync design documents 90 days
# as the retention horizon's own default (offline_sync.RETENTION_DAYS),
# so this field's default selection is 90 -- see
# data_health.sync_gc_retention_days's docstring. "0" disables the GC
# outright -- tombstones are then kept forever, which is exactly what the
# redesigned control's "Keep forever" label says (relabeled 2026-08-26,
# stored values unchanged).
SYNC_GC_DAYS_CHOICES = [("30", "Keep 30 days"), ("90", "Keep 90 days"), ("0", "Keep forever")]


def _backups_dir(request: Request) -> Path:
    return request.app.state.settings.backup_dir


def _choices_with_stored_value(
    choices: list[tuple[str, str]], stored: str
) -> list[tuple[str, str]]:
    """The rendered select's options, with one honest extra entry appended
    when the currently-stored value isn't among the presets (2026-08-26:
    the redesigned controls offer three presets each, but an install that
    picked "14"/"90"/"180 days" before the relabel still stores one of
    those). Without this, the browser would silently display the first
    preset while the stored value stayed something else -- a lie. The
    extra entry autosubmits like any other, so picking anything real
    replaces it; it's never itself written back (the POST routes validate
    against the preset lists only)."""
    if any(value == stored for value, _ in choices):
        return choices
    return [*choices, (stored, f"{stored} days (current)")]


@router.get("/settings/data-maintenance")
def settings_data_maintenance(request: Request, conn=Depends(get_db)):
    """The merged Data & Maintenance page (2026-08-17 reorg). Context is
    everything the three former pages used to gather separately: the data
    health summary (health_summary's `integrity`/`latest_backup`/
    `latest_verified_backup`/`sync`/`sync_gc`/`storage`/`entities`/
    `backups`), the unresolved sync conflicts, and Advanced's export/
    import + purge/auto-archive context (export_context() plus the counts
    and choices settings_data_maintenance.html renders).

    2026-08-26 page redesign: the two Maintenance selects' choice lists go
    through _choices_with_stored_value so a legacy stored value stays
    visible; everything else about the context shape is unchanged."""
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
        # Export & backup (was settings_advanced.html's, itself moved off
        # its own /export page -- direct feedback: "export and backup
        # should be fully with all buttons... in the advanced page").
        # export_context() is the same data /export's own page used to
        # gather; radicale_url is fetched here directly since
        # export_context() takes no `request`.
        "radicale_url": request.app.state.settings.radicale_base_url,
        # 2026-09-08 -- this card is read-only display now (the URL only;
        # credentials moved to Settings > General's merged Account card,
        # account_settings' own docstring covers why). radicale_env_
        # configured still distinguishes "set via curodav.env" wording
        # from "set through Settings" in the card's copy. getattr-guarded:
        # several test files build their own minimal SimpleNamespace
        # stand-in for Settings (not the real dataclass) predating this
        # field.
        "radicale_env_configured": getattr(request.app.state.settings, "radicale_env_configured", False),
        # Restart app (2026-09-08, moved here 2026-09-11 direct request) --
        # only meaningful when this process is under systemd with
        # Restart=always (curodav-ctl's generated unit); see restart_app's
        # own docstring for why deploy_mode == "production" is the signal
        # used. getattr-guarded: several test files build a bare
        # SimpleNamespace Settings stand-in predating this field.
        "restart_available": getattr(request.app.state.settings, "deploy_mode", "local") == "production",
    }
    ctx.update(summary)
    ctx.update(export_context(conn))
    return templates.TemplateResponse("settings_data_maintenance.html", ctx)


# /settings/radicale (the old plain URL/username/password form) is gone
# (2026-09-08, superseded by /settings/account -- account_settings' own
# docstring covers the merge) -- Data & Maintenance's "CalDAV / Radicale
# sync" card is now a read-only display of the current URL, pointing at
# Settings > General to actually change the connection, since the
# credentials it used to collect independently are now the same
# username/password as the app's own login.


@router.get("/settings/data-health")
def settings_data_health(request: Request, conn=Depends(get_db)):
    """Old Data health page URL -- kept as a redirect to the merged
    Data & Maintenance page (2026-08-17 reorg) so old bookmarks/links
    (and the many action endpoints' redirect targets) land somewhere real."""
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
        url=f"/settings/data-maintenance?note=Restored+{result['restored']}+row(s).+A+safety+backup+of+the+prior+state+was+made+first.",
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
    """1.8 slice 7 -- Settings' side of the tombstone/idempotency-ledger
    retention horizon (§4). `0` disables automatic (lazy, on-pull) GC --
    same "0 = Never" idiom `routers/tasks.py`'s auto-archive field already
    uses -- without touching `pull()`'s own stale-cursor-forces-full-resync
    safety check, which isn't gated by this setting at all. Only ever
    stores one of the offered presets, same validation-against-the-select's-
    -own-options convention as `set_task_auto_archive`."""
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


# --------------------------------------------------------------------- #
# Advanced -- export & backup, reset Home's widget layout, auto-archive
# completed tasks by age, plus two explicit, confirmed-destructive purge
# actions. 2026-08-17: this whole page is now the "Export & import",
# "Maintenance & upkeep" and "Danger zone" sections of the merged Data &
# Maintenance page (settings_data_maintenance.html); /settings/advanced is
# a redirect there for old bookmarks/links. Scope confirmed directly with
# the user before building the purge actions (2026-08-07): "Purge
# completed" is tasks-only (every done/archived task); "Purge all" is a
# full data wipe across the whole app (not just tasks) -- see db.py's
# purge_all_data/delete_completed_tasks docstrings for exactly what each
# touches and, for purge-all, its one known limitation (Published Lists'
# already-materialized Radicale collections aren't torn down, only this
# app's own tracking of them). Reset layout itself lives in routers/
# dashboard.py (POST /dashboard/reset) -- this page just links to it, same
# as it always has from label_detail.html's own edit-mode toolbar. Export
# & backup itself lives in routers/export.py (/export) -- this page links
# to it (2026-08-08, moved here from the now-deleted "Data & backup"
# category, see this module's own docstring).
# --------------------------------------------------------------------- #


@router.get("/settings/advanced")
def settings_advanced(request: Request, conn=Depends(get_db)):
    """Old Advanced page URL -- kept as a redirect to the merged
    Data & Maintenance page (2026-08-17 reorg) so old bookmarks/links
    (and the export/import redirect from routers/export.py) land
    somewhere real."""
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
    # A purge is a fresh install, and the auto-generated session signing
    # secret lives in the just-wiped app_meta (see src/auth.py's
    # session_secret). Drop the in-process memoized secret (AuthMiddleware
    # caches it on app.state._cc_auth_secret) and clear the session cookie
    # so the very next request re-mints a fresh secret and the old cookie
    # no longer verifies -- with auth enabled that lands the user back on
    # /login, the same state a brand-new install would be in. When a stable
    # CC_AUTH_SECRET is configured instead, the secret isn't in the DB so
    # it's unaffected, but clearing the cookie forces the re-login there
    # too.
    #
    # 2026-08-29: a purge also wipes any /setup-created account (it lives
    # in app_meta too, see auth.py's AUTH_USERNAME_KEY/AUTH_PASSWORD_HASH_
    # KEY), so the "is this install configured" cache AuthMiddleware keeps
    # on app.state._cc_auth_configured must be dropped as well -- otherwise
    # a purged production install would still look configured and skip
    # the forced /setup flow a fresh database should trigger.
    state = getattr(request.app, "state", None)
    if state is not None:
        state._cc_auth_secret = None
        state._cc_auth_configured = False
    response = RedirectResponse(url="/settings/data-maintenance", status_code=303)
    response.delete_cookie(
        auth.SESSION_COOKIE, path="/", samesite="lax", secure=auth.is_secure_request(request)
    )
    return response


# --------------------------------------------------------------------- #
# Sync conflicts (1.8 slice 2, plans/open-priority.md § Offline-first
# editing & synchronization §§7b/c, 9, 11 slice 2) -- the "Sync conflicts
# list" §7b's own text places "adjacent to Settings > Data health". A
# conflict here is never auto-resolved or silently dropped (src/
# offline_sync.py's apply_op/apply_batch record one whenever a genuinely
# concurrent event-time edit or a same-batch project-label clash picks a
# winner) -- restore or dismiss are the only two things a person can do
# with one. 2026-08-17: the list itself renders at the top of the merged
# Data & Maintenance page ("Needs attention" section, settings_data_
# maintenance.html); /settings/sync-conflicts is a redirect there.
# --------------------------------------------------------------------- #


@router.get("/settings/sync-conflicts")
def settings_sync_conflicts(request: Request, conn=Depends(get_db)):
    """Old Sync conflicts page URL -- kept as a redirect to the merged
    Data & Maintenance page (2026-08-17 reorg) so old bookmarks/links
    (and the restore/dismiss redirects below) land somewhere real."""
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
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
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
