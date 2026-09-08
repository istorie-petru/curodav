"""Settings, read from environment variables so the same code runs against
the local dev Radicale (see webapp/.dev/radicale/) and a real deployment
without editing source. No secrets committed here -- see webapp/.dev/README
for the dev-only defaults, which must not be reused for anything reachable
off localhost."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# The dev-only Radicale fallback credentials (webapp/.dev/radicale/) --
# never meant to protect anything reachable off localhost. Named as
# constants (not just inline literals in load_settings' os.environ.get
# calls) so `uses_default_radicale_credentials` below can compare against
# the exact same values without the two ever drifting apart.
_DEV_RADICALE_USERNAME = "devuser"
_DEV_RADICALE_PASSWORD = "devpass"


@dataclass(frozen=True)
class Settings:
    radicale_base_url: str  # e.g. "http://127.0.0.1:5232/devuser/"
    radicale_username: str
    radicale_password: str
    calendar_collection: str
    tasks_collection: str
    contacts_collection: str
    db_path: Path
    sync_interval_seconds: int
    backup_dir: Path
    # Single-user authentication (2026-08-16, src/auth.py). Both
    # auth_username AND auth_password must be non-empty for login to be
    # enforced -- an unset pair keeps the app open exactly as it always
    # was (local dev, trusted networks). auth_session_secret is optional:
    # when unset, the session-signing secret is auto-generated once and
    # persisted in app_meta, surviving restarts.
    auth_username: str | None = None
    auth_password: str | None = None
    auth_session_secret: str | None = None
    # Deploy-mode default posture (2026-08-29, src/auth.py's setup_required).
    # "local" (default -- covers local dev and any manual/unrecognized run)
    # keeps today's behavior: open unless CC_AUTH_USERNAME/PASSWORD are both
    # set. The systemd unit and the Docker image both set
    # CC_DEPLOY_MODE=production, which forces a first-run GET/POST /setup
    # flow (credentials persisted hashed in app_meta) whenever neither the
    # env pair nor a persisted account exists yet -- those are the two
    # deploy paths an operator is likely to expose beyond localhost, so
    # "fully open by default" is no longer an acceptable default there.
    deploy_mode: str = "local"
    # 2026-08-29 -- true when CC_RADICALE_URL was actually present in the
    # environment (the installer's --with-radicale writes all three
    # CC_RADICALE_* vars together, see deploy/*/install.sh, so URL's
    # presence is treated as "the trio is env-configured" rather than
    # checking each var separately). Distinguishes "explicitly configured
    # via env" from "sitting at the devuser/devpass dev default because
    # nothing else was ever set" -- apply_persisted_radicale_overrides
    # below only touches the latter, and /setup and Settings' Radicale
    # form (routers/auth.py, routers/settings.py) only offer to edit it
    # when this is False, since an env-configured install should keep
    # being managed the way it always was (edit curodav.env, restart).
    radicale_env_configured: bool = False
    # `CC_ENV_FILE` (2026-09-08, src/env_file.py) -- the path to this
    # process's own systemd `EnvironmentFile`, if it's running under one.
    # `scripts/curodav-ctl`'s generated unit sets this to the exact same
    # path as its `EnvironmentFile=` line (a real, fixed path known at
    # install time -- EnvironmentFile itself only injects the file's
    # *contents* as env vars, never its own path). None for local dev/any
    # non-curodav-ctl deploy: Settings > General's Account card
    # (routers/settings.py::account_settings) falls back to persisting in
    # app_meta instead when this is unset, same as it always has.
    env_file_path: str | None = None


def load_settings() -> Settings:
    db_path = Path(
        os.environ.get(
            "CC_DB_PATH", str(Path.home() / ".command_center_web" / "cache.sqlite")
        )
    )
    return Settings(
        radicale_base_url=os.environ.get(
            "CC_RADICALE_URL", "http://127.0.0.1:5232/devuser/"
        ),
        radicale_username=os.environ.get("CC_RADICALE_USER", _DEV_RADICALE_USERNAME),
        radicale_password=os.environ.get("CC_RADICALE_PASSWORD", _DEV_RADICALE_PASSWORD),
        calendar_collection=os.environ.get("CC_CALENDAR_COLLECTION", "calendar"),
        tasks_collection=os.environ.get("CC_TASKS_COLLECTION", "tasks"),
        contacts_collection=os.environ.get("CC_CONTACTS_COLLECTION", "contacts"),
        db_path=db_path,
        sync_interval_seconds=int(os.environ.get("CC_SYNC_INTERVAL", "60")),
        # Data health (1.8 precondition): server-side, actively-verified
        # backups, separate from the on-demand data.json *download* export
        # (routers/export.py) -- these live next to the DB by default so a
        # single-machine deployment's backups travel with it, but are
        # relocatable (e.g. onto a different disk/mount) via CC_BACKUP_DIR.
        backup_dir=Path(
            os.environ.get("CC_BACKUP_DIR", str(db_path.parent / "backups"))
        ),
        auth_username=os.environ.get("CC_AUTH_USERNAME") or None,
        auth_password=os.environ.get("CC_AUTH_PASSWORD") or None,
        auth_session_secret=os.environ.get("CC_AUTH_SECRET") or None,
        deploy_mode=os.environ.get("CC_DEPLOY_MODE", "local"),
        radicale_env_configured=bool(os.environ.get("CC_RADICALE_URL")),
        env_file_path=os.environ.get("CC_ENV_FILE") or None,
    )


# app_meta keys a Radicale connection entered through /setup or Settings
# (routers/auth.py::setup_submit, routers/settings.py) is persisted under
# -- same "runtime-entered secret lives in the DB, not disk config"
# convention as auth.py's AUTH_USERNAME_KEY/AUTH_PASSWORD_HASH_KEY, except
# this password IS stored retrievable (not hashed): the app has to send it
# back to Radicale as an HTTP Basic Auth credential on every sync request,
# unlike the app's own login password, which only ever needs to be
# *verified*, never replayed anywhere.
RADICALE_URL_KEY = "radicale_base_url"
RADICALE_USERNAME_KEY = "radicale_username"
RADICALE_PASSWORD_KEY = "radicale_password"


def apply_persisted_radicale_overrides(settings: "Settings", conn) -> "Settings":
    """Overrides `settings`' Radicale fields from app_meta, if a
    connection was ever saved through /setup or Settings AND the
    environment didn't already configure one explicitly (env always wins
    -- an operator who put CC_RADICALE_* in curodav.env is managing it
    there, this never second-guesses that). Called once, early in
    main.py's lifespan, before the CalDavBridge is constructed -- the
    bridge is only ever built once at process start (no live reload), so
    a Radicale connection entered while the app is already running takes
    effect on the next restart, same as an env-file edit always has.

    Local import of `db` avoided at module level to keep config.py's own
    import graph acyclic-by-convention (db.py doesn't import config.py,
    but nothing stops it from growing a reason to later; this function is
    the only place in this module that needs a live connection)."""
    if settings.radicale_env_configured:
        return settings
    from dataclasses import replace

    from . import db

    url = db.get_app_meta(conn, RADICALE_URL_KEY)
    username = db.get_app_meta(conn, RADICALE_USERNAME_KEY)
    password = db.get_app_meta(conn, RADICALE_PASSWORD_KEY)
    if not (url and username and password):
        return settings
    return replace(
        settings,
        radicale_base_url=url,
        radicale_username=username,
        radicale_password=password,
    )


def uses_default_radicale_credentials(settings: "Settings") -> bool:
    """True when `settings` would authenticate to Radicale with the
    dev-only devuser/devpass fallback (load_settings' defaults) -- true
    whether that's because CC_RADICALE_USER/PASSWORD were never set, or
    because a /setup-persisted override (apply_persisted_radicale_overrides,
    called before this) happens to match the same values verbatim. Checked
    by main.py's lifespan (2026-09-07 audit fix,
    `documentation/reports/full-app-audit-2026-09-07.md`) only AFTER a
    production deploy's CalDavBridge actually connects -- a standalone
    install with no reachable Radicale at all never exercises these
    credentials against anything, so it must not be forced to change them
    just to boot; see main.py's own comment for why the check is gated on
    a live connection rather than firing unconditionally."""
    return (
        settings.radicale_username == _DEV_RADICALE_USERNAME
        and settings.radicale_password == _DEV_RADICALE_PASSWORD
    )
