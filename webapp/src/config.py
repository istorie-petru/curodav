"""Settings, read from environment variables so the same code runs against
the local dev Radicale (see webapp/.dev/radicale/) and a real deployment
without editing source. No secrets committed here -- see webapp/.dev/README
for the dev-only defaults, which must not be reused for anything reachable
off localhost."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
        radicale_username=os.environ.get("CC_RADICALE_USER", "devuser"),
        radicale_password=os.environ.get("CC_RADICALE_PASSWORD", "devpass"),
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
    )
