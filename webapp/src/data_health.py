"""Data health & maintenance (`plans/open.md` § Data health & maintenance,
`plans/roadmap.md`'s 1.1 side work) -- the verified-backups precondition
1.8 (offline-first editing & synchronization) is gated on: "trusted only
once verified backups (data health, 1.1) exist" (`plans/STATE.md`).

Settings > Data health (`routers/settings.py`'s settings_data_health) and
`scripts/data_health.py` (the CLI) are both thin wrappers around the plain
functions in this module -- "GUI and CLI use the same underlying
maintenance services rather than separate logic" (`open.md`), so a backup
made from the command line looks and behaves identically to one made from
the browser, and there is exactly one implementation of each maintenance
operation to keep correct.

What lives here vs. what doesn't, per features/architecture.md §1.4's
local-only-module rule: a *server-side* backup file is genuinely new
persisted state (not derivable from the pool), so it's a real file under
`backup_dir`, timestamped and self-describing -- the *list* of backups and
their sizes/ages is never itself stored, just computed on read by scanning
that directory (the "don't store derived values" rule, §6). A backup's
verification result is likewise recomputed by re-reading the backup file
each time you ask, but the *result of the last check* is cheap to cache so
the Data Health page doesn't have to re-verify a potentially large file on
every page load -- that one exception is written as a small JSON sidecar
next to the backup file it describes (`<file>.verify.json`), not into the
app database, so it needs no schema change and a backup file plus its
sidecar are both portable together (copy the pair anywhere, e.g. off-box).

Payload shape: identical to `routers/export.py`'s `build_backup_payload` --
see that function's own comment for why there is exactly one definition of
"what a full backup contains" shared by the on-demand data.json download
and these server-side backups.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The top-level keys build_backup_payload always produces -- verify_backup
# checks every one of these is present and holds a list (or, for the two
# scalar keys, is present at all). Kept here rather than imported from
# routers/export.py so this module has no dependency on the HTTP layer
# (routers import db_health-ish modules, never the reverse -- see
# features/architecture.md §2's layering rule).
_REQUIRED_LIST_KEYS = (
    "events", "tasks", "contacts", "labels", "object_labels",
    "schedule_holidays", "task_completions", "event_task_relations",
)
# 2026-08-15: "schedule_settings" dropped -- the whole Schedule module (and
# its `schedule_settings` table) is removed, see plans/STATE.md's removal
# entry; `build_backup_payload` no longer produces that key at all.
_REQUIRED_SCALAR_KEYS = ("exported_at",)

# Every collection row that carries its own stable identifier is expected
# to have a non-empty "uid" -- object_labels/task_completions/
# event_task_relations are join-shaped rows with no uid of their own, and
# are excluded on purpose.
_UID_KEYED_COLLECTIONS = ("events", "tasks", "contacts")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_filename(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    # Sortable-by-name timestamp (filesystem listing order == chronological
    # order) plus a "backup-" prefix so a backups directory that also holds
    # stray files (or another app's data) can't be mistaken for one of ours.
    # Microsecond precision matters here, not just cosmetically -- a
    # restore always takes a same-second "safety backup" of the pre-restore
    # state (see restore_backup below); a whole-second-only timestamp would
    # let that safety backup collide with (and silently overwrite) the very
    # backup file being restored from.
    return f"backup-{when.strftime('%Y%m%dT%H%M%S%f')}Z.json"


def _verify_sidecar_path(backup_path: Path) -> Path:
    # Deliberately does NOT end in ".json" -- list_backups' `glob("backup-
    # *.json")` would otherwise pick the sidecar up as a second, bogus
    # "backup" (and, since its longer name sorts after the real file's,
    # `reverse=True` would put that bogus entry first).
    return backup_path.parent / (backup_path.name + ".verify")


# --------------------------------------------------------------------- #
# Backups: create / list / delete
# --------------------------------------------------------------------- #


def create_backup(conn: sqlite3.Connection, backups_dir: Path, payload: dict[str, Any] | None = None) -> Path:
    """Writes a new timestamped full backup to `backups_dir`. `payload`
    lets a caller that already built one (routers/settings.py's restore
    route, which snapshots the pre-restore state) pass it straight through
    instead of re-querying the database a second time; the default path
    (CLI, the plain "Create backup" button) builds it fresh via
    routers/export.py's build_backup_payload -- imported lazily to avoid a
    hard import-time dependency from this module onto the FastAPI router
    layer (routers/export.py imports `fastapi`; scripts/data_health.py has
    no FastAPI installed requirement otherwise)."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    if payload is None:
        from .routers.export import build_backup_payload

        payload = build_backup_payload(conn)
    path = backups_dir / _backup_filename()
    # Belt-and-suspenders on top of the microsecond-precision filename
    # above: if two backups still land in the exact same microsecond (seen
    # in fast back-to-back test runs), don't silently clobber the first
    # one -- keep incrementing a numeric suffix until the name is free.
    n = 2
    while path.exists():
        path = backups_dir / _backup_filename().replace(".json", f"-{n}.json")
        n += 1
    # Atomic-ish write: build the full file in a temp name, then rename --
    # a crash/kill mid-write can never leave a half-written file with the
    # real backup's name that a later verify/restore would trust.
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)
    return path


def list_backups(backups_dir: Path) -> list[dict[str, Any]]:
    """Every `backup-*.json` file in `backups_dir`, newest first, each with
    its cached verification result if one exists (see the module docstring
    for why that's a sidecar file, not stored data). Never raises if the
    directory doesn't exist yet -- an install that has never made a backup
    reads as an empty list, not an error."""
    if not backups_dir.exists():
        return []
    rows = []
    for path in sorted(backups_dir.glob("backup-*.json"), reverse=True):
        stat = path.stat()
        sidecar = _verify_sidecar_path(path)
        verification = None
        if sidecar.exists():
            try:
                verification = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                verification = None
        rows.append(
            {
                "filename": path.name,
                "path": str(path),
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "verification": verification,
            }
        )
    return rows


def latest_backup(backups_dir: Path) -> dict[str, Any] | None:
    backups = list_backups(backups_dir)
    return backups[0] if backups else None


# --------------------------------------------------------------------- #
# Verification -- "actively verified, not merely created" (open.md)
# --------------------------------------------------------------------- #


@dataclass
class VerificationResult:
    ok: bool
    checked_at: str
    filename: str
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "checked_at": self.checked_at, "filename": self.filename,
            "errors": self.errors, "counts": self.counts,
        }


def verify_backup(path: Path) -> VerificationResult:
    """Validates JSON structure, expected top-level data, required entity
    collections, and basic per-row integrity (open.md's own acceptance
    bar for "verified", not just "created") -- does NOT attempt a real
    restore into a scratch database; that would be a much stronger check
    but also a much slower/heavier one to run on every "Verify" click, and
    a structurally-valid, uid-complete payload is exactly what
    restore_backup_payload (routers/export.py) needs to succeed. Writes
    its own sidecar file next to `path` so list_backups can show the
    result without re-running this."""
    checked_at = _now()
    errors: list[str] = []
    counts: dict[str, int] = {}

    if not path.exists():
        result = VerificationResult(ok=False, checked_at=checked_at, filename=path.name, errors=["file does not exist"])
        return result

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return VerificationResult(ok=False, checked_at=checked_at, filename=path.name, errors=[f"could not read file: {e}"])

    if not raw.strip():
        return VerificationResult(ok=False, checked_at=checked_at, filename=path.name, errors=["file is empty"])

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return VerificationResult(ok=False, checked_at=checked_at, filename=path.name, errors=[f"invalid JSON: {e}"])

    if not isinstance(payload, dict):
        return VerificationResult(ok=False, checked_at=checked_at, filename=path.name, errors=["top level is not a JSON object"])

    for key in _REQUIRED_SCALAR_KEYS:
        if key not in payload:
            errors.append(f"missing required key: {key}")

    for key in _REQUIRED_LIST_KEYS:
        if key not in payload:
            errors.append(f"missing required key: {key}")
            continue
        value = payload[key]
        if not isinstance(value, list):
            errors.append(f"'{key}' should be a list, got {type(value).__name__}")
            continue
        counts[key] = len(value)

    for key in _UID_KEYED_COLLECTIONS:
        for i, row in enumerate(payload.get(key) or []):
            if not isinstance(row, dict):
                errors.append(f"{key}[{i}] is not an object")
            elif not row.get("uid"):
                errors.append(f"{key}[{i}] is missing a 'uid'")

    result = VerificationResult(ok=not errors, checked_at=checked_at, filename=path.name, errors=errors, counts=counts)
    try:
        _verify_sidecar_path(path).write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    except OSError:
        pass  # a failed sidecar write shouldn't hide a real verification result
    return result


# --------------------------------------------------------------------- #
# Restore -- always preceded by a safety snapshot, "where practical"
# --------------------------------------------------------------------- #


def restore_backup(conn: sqlite3.Connection, path: Path, backups_dir: Path | None = None) -> dict[str, Any]:
    """Restores `path` into the live database. When `backups_dir` is given,
    takes a fresh safety-snapshot backup of the *current* state first --
    "restore operations ... preserve a recoverable backup of the current
    state where practical" (open.md) -- so a restore that turns out to be
    a mistake is itself one Restore away from being undone. The safety
    snapshot is skipped only when the caller has no backups_dir to put it
    in (e.g. a CLI restore with --no-safety-backup for a throwaway/test
    database); production callers (the Settings route, the default CLI
    behavior) always pass one."""
    from .routers.export import restore_backup_payload

    verification = verify_backup(path)
    if not verification.ok:
        return {
            "ok": False, "restored": 0, "safety_backup": None,
            "errors": verification.errors,
        }

    safety_backup = None
    if backups_dir is not None:
        safety_backup = str(create_backup(conn, backups_dir))

    payload = json.loads(path.read_text(encoding="utf-8"))
    count = restore_backup_payload(conn, payload)
    return {"ok": True, "restored": count, "safety_backup": safety_backup, "errors": []}


# --------------------------------------------------------------------- #
# Database integrity + repair
# --------------------------------------------------------------------- #


def check_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    """SQLite's own `PRAGMA integrity_check` -- a full scan for structural
    corruption (not application-level validation; that's verify_backup's
    job for backup files). Returns the single "ok" row's text verbatim as
    `detail` when it isn't literally "ok", since that's the most useful
    diagnostic SQLite can hand back."""
    rows = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    ok = rows == ["ok"]
    return {"ok": ok, "checked_at": _now(), "detail": "ok" if ok else "; ".join(rows)}


def compact_and_reindex(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    """The "supported repair operations" open.md asks for -- deliberately
    modest and safe for a SQLite *cache* (see features/architecture.md
    §1.1: this database is a disposable, rebuildable query cache, not the
    system of record even pre-1.8), not an attempt to un-corrupt anything
    PRAGMA integrity_check already flagged as broken (that needs a real
    restore from backup, not a repair tool). REINDEX rebuilds every index
    from the table data (clears index-only corruption/staleness); VACUUM
    rebuilds the whole file, reclaiming space from deleted rows and
    defragmenting -- reports the size delta since that's the
    user-observable effect of running it."""
    before = db_path.stat().st_size if db_path.exists() else 0
    conn.execute("REINDEX")
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()
    after = db_path.stat().st_size if db_path.exists() else 0
    return {
        "ok": True, "checked_at": _now(),
        "size_before_bytes": before, "size_after_bytes": after,
    }


# --------------------------------------------------------------------- #
# Storage + entity stats (Data Health page's "at a glance" numbers)
# --------------------------------------------------------------------- #


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def storage_stats(db_path: Path, backups_dir: Path) -> dict[str, Any]:
    backups = list_backups(backups_dir)
    return {
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "backups_dir_size_bytes": _dir_size_bytes(backups_dir),
        "backup_count": len(backups),
    }


def entity_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Same counts Settings > Advanced's Export section already shows
    (routers/export.py's export_context) -- reused rather than
    re-queried, so the two pages can never disagree on "how many tasks do
    I have."""
    from .routers.export import export_context

    return export_context(conn)


# --------------------------------------------------------------------- #
# 1.8 slice 7 -- Tombstone GC's own maintenance-service wrapper, same
# "GUI and CLI share one implementation" shape as every backup action
# above. `offline_sync.purge_expired` (src/offline_sync.py) does the
# actual deletion; everything here is bookkeeping around *when* to call
# it and remembering that it ran, for Settings > Data health's benefit.
# --------------------------------------------------------------------- #

SYNC_GC_RETENTION_DAYS_KEY = "sync_gc_retention_days"
SYNC_GC_LAST_RUN_KEY = "sync_gc_last_run"


def sync_gc_retention_days(conn: sqlite3.Connection) -> int:
    """The configured tombstone/idempotency-ledger retention horizon (§4)
    -- "alongside the existing auto-archive-style app_meta presets," per
    §4's own line. Unset means the sync design's own documented default
    (`offline_sync.RETENTION_DAYS`, 90 days -- already what `pull()`'s
    staleness check has used since slice 1); an explicit `"0"` disables
    physical purging specifically (the staleness-forces-full-resync
    safety check is a correctness guarantee, not a storage-management
    knob, and stays in effect either way)."""
    from . import db, offline_sync

    raw = db.get_app_meta(conn, SYNC_GC_RETENTION_DAYS_KEY)
    if not raw:
        return offline_sync.RETENTION_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        return offline_sync.RETENTION_DAYS


def set_sync_gc_retention_days(conn: sqlite3.Connection, days: int) -> None:
    from . import db

    db.set_app_meta(conn, SYNC_GC_RETENTION_DAYS_KEY, str(max(0, days)))


def sync_gc_last_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    from . import db

    raw = db.get_app_meta(conn, SYNC_GC_LAST_RUN_KEY)
    return json.loads(raw) if raw else None


def run_sync_gc(conn: sqlite3.Connection, *, force: bool = False) -> dict[str, Any] | None:
    """The one entry point every caller goes through: routers/sync_api.py's
    lazy "check on every pull" trigger (`force=False` -- a no-op when
    retention is configured to 0/Never, the same "check lazily on a
    request path, no cron" idiom `routers/tasks.py`'s auto-archive check
    already established for this app), Settings' "Run cleanup now" button,
    and `scripts/data_health.py`'s CLI (both `force=True` -- a manual
    action should still work even with the automatic version turned off,
    same as this page's other maintenance actions). Records what happened
    as `SYNC_GC_LAST_RUN_KEY` regardless of whether anything was actually
    purged, so Data health can show "last checked," not just "last found
    something to delete." Returns `None` only for the force=False/disabled
    case -- nothing ran, nothing to record."""
    from . import db, offline_sync

    days = sync_gc_retention_days(conn)
    if days <= 0 and not force:
        return None
    result = offline_sync.purge_expired(conn, retention_days=days if days > 0 else offline_sync.RETENTION_DAYS)
    record = {"at": datetime.now(timezone.utc).isoformat(), **result}
    db.set_app_meta(conn, SYNC_GC_LAST_RUN_KEY, json.dumps(record))
    return record


def _sync_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """1.8 slice 6 -- the sync engine (routers/sync_api.py, driven client-
    side by static/offline_sync_client.js) is now real, so this is no
    longer the fixed `{"configured": False}` placeholder slices 1-5 left
    here. "Configured" means at least one device has ever pushed or
    pulled -- a fresh install with no PWA client installed anywhere still
    correctly reports unconfigured, since `sync_devices` stays empty until
    that happens."""
    from . import db

    devices = db.list_sync_devices(conn)
    if not devices:
        return {"configured": False, "detail": "No device has synced yet.", "device_count": 0, "last_seen_at": None}
    return {
        "configured": True,
        "detail": f"{len(devices)} device{'s' if len(devices) != 1 else ''} synced, most recently {devices[0]['last_seen_at']}.",
        "device_count": len(devices),
        "last_seen_at": devices[0]["last_seen_at"],
    }


def _sync_gc_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """1.8 slice 7 -- retention configuration + the last GC run, for
    Settings > Data health's own Maintenance section. Separate from
    `_sync_summary` (device push/pull state) since retention/purge is a
    distinct concern -- a fresh install with no devices yet still has a
    perfectly real (default) retention horizon to report."""
    last_run = sync_gc_last_run(conn)
    return {
        "retention_days": sync_gc_retention_days(conn),
        "last_run": last_run,
    }


def health_summary(conn: sqlite3.Connection, db_path: Path, backups_dir: Path) -> dict[str, Any]:
    """Everything Settings > Data health's page needs in one call --
    open.md's own list: "database integrity/status; last successful
    backup; last backup verification; synchronization status ...; storage
    usage; relevant entity statistics." Sync status reflects `sync_devices`
    directly (see `_sync_summary`) now that 1.8 slice 6 has shipped a real
    sync engine -- slices 1-5 left this as a fixed not-yet-available
    placeholder so this function's own shape wouldn't need to change once
    it did. `sync_gc` (slice 7) is the retention/purge counterpart."""
    backups = list_backups(backups_dir)
    latest = backups[0] if backups else None
    latest_verified = next((b for b in backups if b["verification"] is not None), None)
    return {
        "integrity": check_integrity(conn),
        "latest_backup": latest,
        "latest_verified_backup": latest_verified,
        "sync": _sync_summary(conn),
        "sync_gc": _sync_gc_summary(conn),
        "storage": storage_stats(db_path, backups_dir),
        "entities": entity_stats(conn),
        "backups": backups,
    }
