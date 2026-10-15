"""Settings, read from environment variables so the same code runs against
the local dev Radicale (see webapp/.dev/radicale/) and a real deployment
without editing source. No secrets committed here -- see webapp/.dev/README
for the dev-only defaults, which must not be reused for anything reachable
off localhost."""

from __future__ import annotations

import os
import time
import zoneinfo
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
    photo_cache_dir: Path
    flairs_dir: Path
    auth_username: str | None = None
    auth_password: str | None = None
    auth_session_secret: str | None = None
    deploy_mode: str = "local"
    # Dev-only switch (`./run.sh skipauth`, CC_SKIP_AUTH=1): login is waived for
    # requests that both arrive on and come from loopback in a local-mode run.
    skip_auth: bool = False
    radicale_env_configured: bool = False
    env_file_path: str | None = None
    radicale_public_base_url: str | None = None


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
        photo_cache_dir=Path(
            os.environ.get("CC_PHOTO_CACHE_DIR", str(db_path.parent / "photo_cache"))
        ),
        flairs_dir=Path(
            os.environ.get("CC_FLAIRS_DIR", str(db_path.parent / "flairs"))
        ),
        auth_username=os.environ.get("CC_AUTH_USERNAME") or None,
        auth_password=os.environ.get("CC_AUTH_PASSWORD") or None,
        auth_session_secret=os.environ.get("CC_AUTH_SECRET") or None,
        deploy_mode=os.environ.get("CC_DEPLOY_MODE", "local"),
        skip_auth=os.environ.get("CC_SKIP_AUTH") == "1",
        radicale_env_configured=bool(os.environ.get("CC_RADICALE_URL")),
        env_file_path=os.environ.get("CC_ENV_FILE") or None,
        radicale_public_base_url=os.environ.get("CC_RADICALE_PUBLIC_URL") or None,
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
        by main.py's lifespan only AFTER a
        production deploy's CalDavBridge actually connects -- a standalone
        install with no reachable Radicale at all never exercises these
        credentials against anything, so it must not be forced to change them
        just to boot; see main.py's own comment for why the check is gated on
        a live connection rather than firing unconditionally.
    """
    return (
        settings.radicale_username == _DEV_RADICALE_USERNAME
        and settings.radicale_password == _DEV_RADICALE_PASSWORD
    )


TIMEZONE_KEY = "app_timezone"

# The offered dropdown choices (routers/settings.py's settings_general),
# computed once at import time since the host's own tzdata doesn't change
# while this process is running. Only `Region/City`-style IANA names plus
# `UTC` itself -- zoneinfo.available_timezones() also yields legacy
# top-level aliases (`GMT`, `PRC`, `Navajo`, ...) and sign-inverted `Etc/
# GMT+N` entries that would only confuse a picker meant to answer "which
# city/region am I in".
TIMEZONE_CHOICES: tuple[str, ...] = tuple(
    sorted(
        {
            z
            for z in zoneinfo.available_timezones()
            if "/" in z and not z.startswith(("Etc/", "posix/", "right/", "SystemV/"))
        }
        | {"UTC"}
    )
)


def apply_persisted_timezone(conn) -> None:
    """Applies the Timezone setting (TIMEZONE_KEY, above) to this
    process's own clock. Empty/unset ("System default", the value every
    existing install has -- nothing has ever written this key before)
    leaves `os.environ["TZ"]` untouched, so an upgrade changes nothing
    until the setting is actually used, same as every other preference
    here. An unrecognized value (tampered request, or a zone this host's
    own tzdata build doesn't ship) is likewise ignored rather than handed
    to `time.tzset()`, which would otherwise leave the process on
    whatever partial/garbage TZ state that call produces.

    Called once at startup (main.py's lifespan, before the background
    sync/reminder threads start so their very first tick already sees the
    right clock) and again immediately after a save (routers/settings.py's
    set_timezone) so a change takes effect without a restart --
    `time.tzset()` re-reads `os.environ["TZ"]` and updates every thread in
    this process immediately, there's no per-thread state to also update.

    `time.tzset()` doesn't exist on Windows; guarded the same way this
    app already assumes a Linux/Docker host everywhere else (see
    deploy/docker, deploy/nginx, scripts/curodav-ctl).

    Local import of `db`, same acyclic-import-graph reasoning as
    apply_persisted_radicale_overrides above."""
    from . import db

    value = db.get_app_meta(conn, TIMEZONE_KEY)
    if not value or value not in TIMEZONE_CHOICES or not hasattr(time, "tzset"):
        return
    os.environ["TZ"] = value
    time.tzset()
