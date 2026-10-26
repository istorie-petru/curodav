"""The signing secret, password hash and recovery token live in an owner-only file next to the database, not in it.

A backup, a pre-migration copy or an export of the database therefore never carries a way to forge or reset a login.
A database with no file path (in memory) keeps them in app_meta."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from . import db

FILE_NAME = "secrets.json"
KEYS = ("auth_session_secret", "auth_username", "auth_password_hash", "auth_recovery_token")


def _path(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]).parent / FILE_NAME if row and row[2] else None


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(temp, path)


def get(conn: sqlite3.Connection, key: str) -> str | None:
    path = _path(conn)
    if path is None:
        return db.get_app_meta(conn, key)
    return _read(path).get(key) or None


def put(conn: sqlite3.Connection, key: str, value: str) -> None:
    path = _path(conn)
    if path is None:
        db.set_app_meta(conn, key, value)
        return
    data = _read(path)
    data[key] = value
    _write(path, data)


def remove(conn: sqlite3.Connection, key: str) -> None:
    path = _path(conn)
    if path is None:
        conn.execute("DELETE FROM app_meta WHERE key = ?", (key,))
        conn.commit()
        return
    data = _read(path)
    if data.pop(key, None) is not None:
        _write(path, data)


def move_from_database(conn: sqlite3.Connection) -> None:
    """One-time move of the values out of app_meta; a value already in the file wins."""
    path = _path(conn)
    if path is None:
        return
    data = _read(path)
    for key in KEYS:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        if row and row[0]:
            data.setdefault(key, row[0])
    if data:
        _write(path, data)
        conn.execute(f"DELETE FROM app_meta WHERE key IN ({', '.join('?' for _ in KEYS)})", KEYS)
