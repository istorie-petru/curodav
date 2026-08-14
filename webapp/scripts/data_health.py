#!/usr/bin/env python3
"""Data health & maintenance CLI -- the command-line half of `plans/open.md`
§ Data health & maintenance's "provide both GUI and CLI workflows" ask. Every
subcommand here calls straight into `src/data_health.py`, the exact same
functions Settings > Data health (`routers/settings.py`) uses -- there is
one implementation of "create a backup" / "verify a backup" / etc., not a
GUI copy and a CLI copy that could quietly disagree.

Usage:
    python scripts/data_health.py status
    python scripts/data_health.py backup
    python scripts/data_health.py list
    python scripts/data_health.py verify [filename]        # defaults to latest
    python scripts/data_health.py restore <filename> [--no-safety-backup]
    python scripts/data_health.py integrity-check
    python scripts/data_health.py repair

All subcommands accept --db-path and --backup-dir to override the app's
configured locations (same CC_DB_PATH / CC_BACKUP_DIR env vars
src/config.py reads, or ~/.command_center_web/{cache.sqlite,backups}/ by
default).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent / "src"))
sys.path.insert(0, str(_THIS_DIR.parent))

from src import data_health, db  # noqa: E402


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    from src.config import load_settings

    settings = load_settings()
    db_path = args.db_path or settings.db_path
    backup_dir = args.backup_dir or settings.backup_dir
    return db_path, backup_dir


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}GB"


def cmd_status(args: argparse.Namespace) -> int:
    db_path, backup_dir = _resolve_paths(args)
    if not db_path.exists():
        print(f"No database at {db_path} yet.")
        return 0
    with db.connect(db_path) as conn:
        summary = data_health.health_summary(conn, db_path, backup_dir)
    integ = summary["integrity"]
    print(f"Database integrity : {'OK' if integ['ok'] else 'PROBLEM: ' + integ['detail']}")
    lb = summary["latest_backup"]
    print(f"Last backup        : {lb['filename'] + ' (' + lb['created_at'] + ')' if lb else 'none yet'}")
    lv = summary["latest_verified_backup"]
    if lv:
        v = lv["verification"]
        print(f"Last verification  : {lv['filename']} -- {'OK' if v['ok'] else str(len(v['errors'])) + ' problem(s)'} ({v['checked_at']})")
    else:
        print("Last verification  : none yet")
    print(f"Sync               : {summary['sync']['detail']}")
    st = summary["storage"]
    print(f"Database size      : {_fmt_bytes(st['db_size_bytes'])}")
    print(f"Backups            : {st['backup_count']} ({_fmt_bytes(st['backups_dir_size_bytes'])})")
    ent = summary["entities"]
    print(f"Entities           : {ent['task_count']} tasks, {ent['event_count']} events, {ent['contact_count']} contacts")
    return 0 if integ["ok"] else 1


def cmd_backup(args: argparse.Namespace) -> int:
    db_path, backup_dir = _resolve_paths(args)
    with db.connect(db_path) as conn:
        path = data_health.create_backup(conn, backup_dir)
    print(f"Backup written: {path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    _, backup_dir = _resolve_paths(args)
    backups = data_health.list_backups(backup_dir)
    if not backups:
        print("No backups yet.")
        return 0
    for b in backups:
        verified = "unverified"
        if b["verification"]:
            verified = "OK" if b["verification"]["ok"] else f"{len(b['verification']['errors'])} problem(s)"
        print(f"{b['filename']}  {_fmt_bytes(b['size_bytes']):>8}  {b['created_at']}  [{verified}]")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    _, backup_dir = _resolve_paths(args)
    if args.filename:
        target = backup_dir / args.filename
    else:
        latest = data_health.latest_backup(backup_dir)
        if latest is None:
            print("No backup to verify -- run `backup` first.")
            return 1
        target = Path(latest["path"])
    result = data_health.verify_backup(target)
    if result.ok:
        print(f"OK: {target.name} -- {result.counts}")
        return 0
    print(f"FAILED: {target.name}")
    for e in result.errors:
        print(f"  - {e}")
    return 1


def cmd_restore(args: argparse.Namespace) -> int:
    db_path, backup_dir = _resolve_paths(args)
    target = backup_dir / args.filename if not Path(args.filename).is_absolute() else Path(args.filename)
    if not target.exists():
        print(f"No such backup: {target}")
        return 1
    safety_dir = None if args.no_safety_backup else backup_dir
    with db.connect(db_path) as conn:
        result = data_health.restore_backup(conn, target, backups_dir=safety_dir)
    if not result["ok"]:
        print("Restore aborted -- backup failed verification:")
        for e in result["errors"]:
            print(f"  - {e}")
        return 1
    print(f"Restored {result['restored']} row(s) from {target.name}.")
    if result["safety_backup"]:
        print(f"Safety backup of the prior state: {result['safety_backup']}")
    return 0


def cmd_integrity_check(args: argparse.Namespace) -> int:
    db_path, _ = _resolve_paths(args)
    with db.connect(db_path) as conn:
        result = data_health.check_integrity(conn)
    print(result["detail"])
    return 0 if result["ok"] else 1


def cmd_repair(args: argparse.Namespace) -> int:
    db_path, _ = _resolve_paths(args)
    with db.connect(db_path) as conn:
        result = data_health.compact_and_reindex(conn, db_path)
    print(f"Compacted & reindexed. Size: {_fmt_bytes(result['size_before_bytes'])} -> {_fmt_bytes(result['size_after_bytes'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("backup").set_defaults(func=cmd_backup)
    sub.add_parser("list").set_defaults(func=cmd_list)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("filename", nargs="?", default=None)
    p_verify.set_defaults(func=cmd_verify)

    p_restore = sub.add_parser("restore")
    p_restore.add_argument("filename")
    p_restore.add_argument("--no-safety-backup", action="store_true")
    p_restore.set_defaults(func=cmd_restore)

    sub.add_parser("integrity-check").set_defaults(func=cmd_integrity_check)
    sub.add_parser("repair").set_defaults(func=cmd_repair)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
