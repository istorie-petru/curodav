#!/usr/bin/env python3
"""Scans a Radicale filesystem storage folder for calendar/task/contact
items that can't be parsed -- the root cause behind Radicale's REPORT
handler (used for almost every read: listing a calendar, searching for an
object by UID, etc.) returning a 500 for an *entire* collection the moment
any single item in it is unparseable. See app/report.py in the radicale
package: item filtering is wrapped in a bare `except Exception: raise
RuntimeError(...)` with no per-item recovery, so one broken .ics or .vcf
anywhere in a collection takes down every REPORT against that collection,
not just requests touching the broken item itself.

caldav_bridge.py's create/update/delete paths were changed to fetch a
specific object by its known URL (a plain GET) instead of searching for it
via REPORT, which sidesteps this for single-object operations -- but
*listing* a whole collection (Month/Week/Day views' background sync,
Tasks, Contacts) genuinely needs the server to return everything, so it
can't route around a broken item the same way. The fix for that is finding
and removing/repairing whatever's actually broken, which is what this
script is for.

Usage:
    uv run python scripts/find_corrupt_items.py [path/to/radicale/storage]

If no path is given, defaults to .dev/radicale/collections (the storage
folder run.sh uses) relative to this script's location. Read-only -- it
only reports what it finds; nothing is deleted or modified. For a real
deployment, point it at whatever `filesystem_folder` your Radicale
config uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from icalendar import Calendar as ICalendar
except ImportError:
    print("Missing dependency: pip install icalendar  (or: uv run --with icalendar ...)")
    sys.exit(1)

try:
    import vobject
except ImportError:
    vobject = None  # .vcf checking becomes a no-op if vobject isn't available


def check_ics(path: Path) -> str | None:
    """Returns an error message if `path` fails to parse as iCalendar,
    None if it's fine."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return f"could not read file: {e}"
    if not raw.strip():
        return "file is empty"
    try:
        ICalendar.from_ical(raw)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


def check_vcf(path: Path) -> str | None:
    if vobject is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        return f"could not read file: {e}"
    if not raw.strip():
        return "file is empty"
    try:
        vobject.readOne(raw)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


def main() -> int:
    if len(sys.argv) > 1:
        storage = Path(sys.argv[1]).expanduser().resolve()
    else:
        storage = (Path(__file__).resolve().parent.parent / ".dev/radicale/collections").resolve()

    if not storage.exists():
        print(f"Storage folder not found: {storage}")
        print("Pass the real path as an argument, e.g.:")
        print("  uv run python scripts/find_corrupt_items.py ~/.local/share/radicale/collections")
        return 1

    print(f"Scanning {storage} ...\n")

    checked = 0
    problems: list[tuple[Path, str]] = []
    for path in sorted(storage.rglob("*")):
        if not path.is_file():
            continue
        # Radicale keeps its own cache/index files (.Radicale.cache/, .Radicale.props,
        # .Radicale.lock) alongside the real items -- not user data, skip them.
        if any(part.startswith(".Radicale") for part in path.parts):
            continue
        if path.suffix == ".ics":
            checked += 1
            err = check_ics(path)
            if err:
                problems.append((path, err))
        elif path.suffix == ".vcf":
            checked += 1
            err = check_vcf(path)
            if err:
                problems.append((path, err))

    print(f"Checked {checked} item(s).\n")
    if not problems:
        print("No corrupt items found. If REPORT requests are still 500ing, the storage")
        print("folder passed here may not be the one your running Radicale is actually")
        print("using -- check the [storage] filesystem_folder in its config.")
        return 0

    print(f"Found {len(problems)} unparseable item(s):\n")
    for path, err in problems:
        print(f"  {path}")
        print(f"    -> {err}\n")
    print(
        "Each of these will make every listing/search request against its collection\n"
        "fail with a 500, until it's fixed or removed. To remove one, delete the file\n"
        "directly (Radicale has no admin UI for this) -- do it while Radicale is\n"
        "stopped, then restart it and this app."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
