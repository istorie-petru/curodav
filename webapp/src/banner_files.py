"""Banner images live as files in a `banners` folder next to the database; app_meta keeps only the file name."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

IMAGE_TYPES = ("jpeg", "png", "gif", "webp")


def banners_dir(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]).parent / "banners" if row and row[2] else None


def store(conn: sqlite3.Connection, data: bytes, image_type: str) -> dict[str, Any]:
    """Writes the image and returns the banner fields to merge into the stored dict."""
    directory = banners_dir(conn)
    if directory is None:
        raise RuntimeError("Banner images need a database file to sit next to")
    directory.mkdir(parents=True, exist_ok=True)
    version = hashlib.md5(data).hexdigest()[:12]
    name = f"{version}.{image_type}"
    (directory / name).write_bytes(data)
    return {"image_file": name, "image_type": image_type, "version": version}


def read(conn: sqlite3.Connection, banner: dict[str, Any]) -> bytes | None:
    """The image bytes of an uploaded banner, from its file or from the legacy inline copy."""
    name = banner.get("image_file")
    if name:
        directory = banners_dir(conn)
        path = directory / Path(str(name)).name if directory else None
        try:
            return path.read_bytes() if path else None
        except OSError:
            return None
    try:
        return base64.b64decode(banner.get("image_b64") or "", validate=True) or None
    except (ValueError, TypeError):
        return None
