#!/usr/bin/env python3
"""Reset the app login with the recovery token (Settings > Your Profile shows it).

Usage:
    python scripts/password_reset.py                 ask for the token, a new username and password
    python scripts/password_reset.py --show-token    print the recovery token
    python scripts/password_reset.py --new-token     replace the recovery token and print it
    python scripts/password_reset.py --dev-clear     local dev builds only: delete the stored login

A successful reset sets the new login, logs every session out and prints a new
recovery token (the old one stops working). Restart the app afterwards so the
running process picks up the change. A login set through CC_AUTH_USERNAME and
CC_AUTH_PASSWORD takes precedence over the stored one; change those instead.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent / "src"))
sys.path.insert(0, str(_THIS_DIR.parent))

from src import auth, db, secret_store  # noqa: E402
from src.config import load_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--show-token", action="store_true", help="print the recovery token")
    parser.add_argument("--new-token", action="store_true", help="replace the recovery token and print it")
    parser.add_argument("--dev-clear", action="store_true", help="local dev builds only: delete the stored login")
    parser.add_argument("--db-path", type=Path, help="override the database path")
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = args.db_path or settings.db_path

    if settings.auth_username and settings.auth_password:
        print("Note: CC_AUTH_USERNAME/CC_AUTH_PASSWORD are set and override the stored login; change them instead.")

    with db.connect(db_path) as conn:
        if args.show_token or args.new_token:
            print(auth.regenerate_recovery_token(conn) if args.new_token else auth.ensure_recovery_token(conn))
            return 0
        if args.dev_clear:
            if settings.deploy_mode != "local":
                print("--dev-clear only works on a local dev build (CC_DEPLOY_MODE is not 'local').", file=sys.stderr)
                return 1
            for key in (auth.AUTH_USERNAME_KEY, auth.AUTH_PASSWORD_HASH_KEY):
                secret_store.remove(conn, key)
            auth.rotate_session_secret(settings, conn)
            print("Stored login deleted. Restart the app; it asks for a new account.")
            return 0

        token = input("Recovery token: ").strip()
        username = input("New username: ").strip()
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Repeat password: "):
            print("The passwords do not match.", file=sys.stderr)
            return 1
        try:
            new_token = auth.reset_credentials_with_token(settings, conn, token, username, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print("Login reset. Restart the app to apply it.")
    print(f"Your new recovery token: {new_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
