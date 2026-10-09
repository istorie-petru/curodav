"""A fake ASGI `app` for tests that render the Settings page, which reads the
database and backup paths from `request.app.state.settings`."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

from src import db


def fake_app() -> SimpleNamespace:
    root = Path(tempfile.mkdtemp())
    db_path = root / "cache.sqlite"
    with db.connect(db_path):
        pass
    settings = SimpleNamespace(
        db_path=db_path, backup_dir=root / "backups", radicale_base_url="http://localhost:5232",
        radicale_public_base_url=None,
    )
    return SimpleNamespace(state=SimpleNamespace(settings=settings))
