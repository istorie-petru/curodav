"""Where the Accounts vault lives and who has it open (features/accounts-vault.md).

The vault is `accounts.kdbx` next to the database, owner-only. Unlocking keeps the open database and its composite key in
this process's memory, under the hash of a random token the browser holds in its own cookie; nothing about the key ever
reaches disk, a log or the page. A vault locks on request, at logout, after the idle time, and when the process restarts.
Failed unlocks are throttled per process. This needs one worker process, which is how the app runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from . import db, vault_merge, vault_kdbx as kdbx
from .log import get_logger

logger = get_logger(__name__)

COOKIE = "curodav_vault"
FILE_NAME = "accounts.kdbx"
IDLE_KEY = "accounts_idle_minutes"
DEFAULT_IDLE_MINUTES = 10
FREE_TRIES, WINDOW = 5, 15 * 60


class Unlocked:
    """One open vault: the database, its key (sealed in memory), the file stamp it was read at, and what happened since."""

    def __init__(self, db: kdbx.Database, composite: bytes, stamp: tuple | None):
        self.db = db
        self._composite = kdbx.seal_bytes(composite)
        self.stamp = stamp
        self.touched = time.monotonic()
        self.pending_import: list | None = None
        self.notice = ""

    @property
    def composite(self) -> bytes:
        return kdbx.unseal_bytes(self._composite)

    @composite.setter
    def composite(self, value: bytes) -> None:
        self._composite = kdbx.seal_bytes(value)


_open: dict[str, Unlocked] = {}
_failures: list[float] = []
_failures_loaded: set[str] = set()
_lock = threading.Lock()
SNAPSHOT_GAP, SNAPSHOT_KEEP = 10 * 60, 30
THROTTLE_NAME = "accounts.throttle"


def _stamp(path: Path | None) -> tuple | None:
    try:
        st = path.stat() if path else None
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size) if st else None


def snapshot_dir(conn: sqlite3.Connection) -> Path | None:
    """Where earlier copies of the (still encrypted) vault are kept: the backup folder's `vault` folder."""
    path = vault_path(conn)
    if not path:
        return None
    from . import config

    row = conn.execute("PRAGMA database_list").fetchone()
    if row and row[2] and not os.environ.get("CC_ACCOUNTS_FILE"):
        return Path(config.load_settings().backup_dir) / "vault"
    return path.parent / "vault-backups"


def list_snapshots(conn: sqlite3.Connection) -> list[dict]:
    folder = snapshot_dir(conn)
    if not folder or not folder.is_dir():
        return []
    rows = []
    for f in sorted(folder.glob("accounts-*.kdbx"), reverse=True):
        st = f.stat()
        rows.append({"name": f.name, "size": st.st_size, "at": st.st_mtime})
    return rows


def _snapshot(conn: sqlite3.Connection, path: Path) -> None:
    """Keeps a copy of the file as it was before this save, at most one every ten minutes, the newest thirty."""
    folder = snapshot_dir(conn)
    if not folder or not path.exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    newest = max((f.stat().st_mtime for f in folder.glob("accounts-*.kdbx")), default=0)
    if time.time() - newest < SNAPSHOT_GAP:
        return
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    target = folder / f"accounts-{stamp}.kdbx"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(path.read_bytes())
    for old in sorted(folder.glob("accounts-*.kdbx"), reverse=True)[SNAPSHOT_KEEP:]:
        old.unlink(missing_ok=True)


def snapshot_path(conn: sqlite3.Connection, name: str) -> Path | None:
    folder = snapshot_dir(conn)
    if not folder or "/" in name or "\\" in name or not name.startswith("accounts-") or not name.endswith(".kdbx"):
        return None
    target = folder / name
    return target if target.is_file() else None


def _throttle_file(conn: sqlite3.Connection) -> Path | None:
    path = vault_path(conn)
    return path.parent / THROTTLE_NAME if path else None


def _load_failures(conn: sqlite3.Connection) -> None:
    """The wrong tries are kept in a file, so restarting the server does not give a fresh set of free tries."""
    file = _throttle_file(conn)
    if not file or str(file) in _failures_loaded:
        return
    _failures_loaded.add(str(file))
    try:
        _failures[:] = [float(t) for t in json.loads(file.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        pass


def _store_failures(conn: sqlite3.Connection) -> None:
    file = _throttle_file(conn)
    if not file:
        return
    try:
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_failures, handle)
    except OSError:
        logger.warning("accounts: could not keep the wrong tries")


def check_single_process() -> None:
    """The open vaults live in one process's memory, so a second worker would not see them."""
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS") or "1"
    if workers.isdigit() and int(workers) > 1:
        raise kdbx.VaultError("The vault needs a single server process; set WEB_CONCURRENCY to 1")


def vault_path(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    override = os.environ.get("CC_ACCOUNTS_FILE")
    if override:
        return Path(override)
    return Path(row[2]).parent / FILE_NAME if row and row[2] else None


def exists(conn: sqlite3.Connection) -> bool:
    path = vault_path(conn)
    return bool(path and path.exists())


def idle_minutes(conn: sqlite3.Connection) -> int:
    try:
        return max(0, int(db.get_app_meta(conn, IDLE_KEY) or DEFAULT_IDLE_MINUTES))
    except ValueError:
        return DEFAULT_IDLE_MINUTES


def _key(token: str | None) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def current(conn: sqlite3.Connection, token: str | None) -> Unlocked | None:
    """The open vault for this browser, or None; an idle one is locked first."""
    if not token:
        return None
    with _lock:
        state = _open.get(_key(token))
        if state is None:
            return None
        limit = idle_minutes(conn)
        if limit and time.monotonic() - state.touched > limit * 60:
            del _open[_key(token)]
            logger.info("accounts: vault locked after %s idle minutes", limit)
            return None
        state.touched = time.monotonic()
    refresh(conn, state)
    return state


def wait_seconds(conn: sqlite3.Connection | None = None) -> int:
    """How long the next unlock must wait because of recent failures (0 when it may go ahead)."""
    if conn is not None:
        _load_failures(conn)
    now = time.time()
    with _lock:
        _failures[:] = [t for t in _failures if now - t < WINDOW]
        extra = len(_failures) - FREE_TRIES
        if extra < 0:
            return 0
        return max(0, int(_failures[-1] + min(5 * 2 ** extra, WINDOW) - now))


def _failed(conn: sqlite3.Connection) -> None:
    with _lock:
        _failures.append(time.time())
    _store_failures(conn)


def unlock(conn: sqlite3.Connection, password: str, key_file: bytes | None) -> str:
    """Opens the vault and returns the browser's new token. Raises kdbx.WrongKey, kdbx.VaultError or PermissionError (throttled)."""
    check_single_process()
    wait = wait_seconds(conn)
    if wait:
        raise PermissionError(f"Too many wrong tries; wait {wait} seconds")
    path = vault_path(conn)
    if not path or not path.exists():
        raise kdbx.VaultError("There is no vault yet")
    composite = kdbx.composite_key(password or None, key_file or None)
    try:
        database = kdbx.load(path.read_bytes(), composite)
    except kdbx.WrongKey:
        _failed(conn)
        logger.warning("accounts: failed unlock")
        raise
    token = secrets.token_urlsafe(32)
    with _lock:
        _open[_key(token)] = Unlocked(database, composite, _stamp(path))
        _failures.clear()
    _store_failures(conn)
    logger.info("accounts: vault unlocked")
    return token


def create(conn: sqlite3.Connection, password: str, key_file: bytes | None, name: str = "Accounts") -> str:
    check_single_process()
    path = vault_path(conn)
    if not path:
        raise kdbx.VaultError("This install has no data folder for a vault")
    if path.exists():
        raise kdbx.VaultError("A vault already exists")
    composite = kdbx.composite_key(password or None, key_file or None)
    database = kdbx.new_database(name)
    _write(conn, path, database, composite)
    token = secrets.token_urlsafe(32)
    with _lock:
        _open[_key(token)] = Unlocked(database, composite, _stamp(path))
    logger.info("accounts: vault created")
    return token


def _write(conn: sqlite3.Connection, path: Path, database: kdbx.Database, composite: bytes) -> tuple:
    """Writes a new file beside the old one, checks it opens, keeps the old one as .bak and as a snapshot, and swaps them in one
    rename. Returns the new file's stamp."""
    data = kdbx.dump(database, composite)
    kdbx.load(data, composite)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        _snapshot(conn, path)
        os.replace(path, path.with_name(path.name + ".bak"))
    os.replace(temp, path)
    return _stamp(path)


def _remote(path: Path, composite: bytes) -> kdbx.Database | None:
    try:
        return kdbx.load(path.read_bytes(), composite)
    except (kdbx.VaultError, OSError):
        return None


def save(conn: sqlite3.Connection, state: Unlocked) -> None:
    """Saves the open vault. When the file changed outside Curodav since it was read, that copy is merged in first."""
    path = vault_path(conn)
    if state.stamp is not None and _stamp(path) != state.stamp:
        remote = _remote(path, state.composite)
        if remote is None:
            raise kdbx.VaultError("The vault file was changed outside Curodav and cannot be read with this key; nothing was saved")
        counts = vault_merge.merge(state.db, remote)
        total = counts["added"] + counts["updated"] + counts["removed"]
        state.notice = f"Merged {total} change{'s' if total != 1 else ''} made to the vault file outside Curodav" if total else ""
        logger.warning("accounts: the vault file changed outside Curodav; merged %s", counts)
    state.stamp = _write(conn, path, state.db, state.composite)


def refresh(conn: sqlite3.Connection, state: Unlocked) -> bool:
    """Picks up changes made to the file outside Curodav (every save of ours updates the stamp, so a differing one is foreign)."""
    path = vault_path(conn)
    if path is None or state.stamp is None or _stamp(path) == state.stamp:
        return False
    remote = _remote(path, state.composite)
    if remote is None:
        return False
    state.db = remote
    state.stamp = _stamp(path)
    state.notice = "The vault file was changed outside Curodav; it is shown as it is now"
    logger.info("accounts: reloaded the vault file changed outside Curodav")
    return True


def change_key(conn: sqlite3.Connection, state: Unlocked, password: str, key_file: bytes | None) -> None:
    state.composite = kdbx.composite_key(password or None, key_file or None)
    save(conn, state)
    logger.info("accounts: master key changed")


def check_key(state: Unlocked, password: str, key_file: bytes | None) -> bool:
    """Whether a password and key file are the vault's own, for actions that ask for them again."""
    try:
        return secrets.compare_digest(kdbx.composite_key(password or None, key_file or None), state.composite)
    except kdbx.VaultError:
        return False


def lock(token: str | None) -> None:
    with _lock:
        if _open.pop(_key(token), None) is not None:
            logger.info("accounts: vault locked")


def lock_all() -> None:
    with _lock:
        _open.clear()
