"""Moves the data folder from ~/.command_center_web to ~/.curodav and renames cache.sqlite to curodav.sqlite.

Stop the app first. The database is copied to a backup beside the old folder before anything moves, and nothing is
deleted: the old folder is renamed, not removed. Run with --dry-run to see what would happen.

    python scripts/move_data_folder.py [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    old, new = config.LEGACY_DATA_DIR, config.DEFAULT_DATA_DIR
    if not (old / "cache.sqlite").exists():
        print(f"Nothing to move: {old / 'cache.sqlite'} does not exist.")
        return 0
    if new.exists():
        print(f"{new} already exists; not touching it.", file=sys.stderr)
        return 1
    print(f"Will move {old} to {new} and rename cache.sqlite to curodav.sqlite.")
    if args.dry_run:
        return 0
    safety = old.with_name(old.name + ".backup-before-move-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copytree(old, safety)
    print(f"Full copy kept at {safety}")
    shutil.move(str(old), str(new))
    for suffix in ("", "-wal", "-shm"):
        source = new / f"cache.sqlite{suffix}"
        if source.exists():
            source.rename(new / f"curodav.sqlite{suffix}")
    print(f"Moved. Start the app again; it now reads {new / 'curodav.sqlite'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
