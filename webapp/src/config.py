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


def load_settings() -> Settings:
    return Settings(
        radicale_base_url=os.environ.get(
            "CC_RADICALE_URL", "http://127.0.0.1:5232/devuser/"
        ),
        radicale_username=os.environ.get("CC_RADICALE_USER", "devuser"),
        radicale_password=os.environ.get("CC_RADICALE_PASSWORD", "devpass"),
        calendar_collection=os.environ.get("CC_CALENDAR_COLLECTION", "calendar"),
        tasks_collection=os.environ.get("CC_TASKS_COLLECTION", "tasks"),
        contacts_collection=os.environ.get("CC_CONTACTS_COLLECTION", "contacts"),
        db_path=Path(
            os.environ.get(
                "CC_DB_PATH", str(Path.home() / ".command_center_web" / "cache.sqlite")
            )
        ),
        sync_interval_seconds=int(os.environ.get("CC_SYNC_INTERVAL", "60")),
    )
