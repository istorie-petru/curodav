#!/usr/bin/env bash
# One-command launch: installs deps if needed, starts the dev Radicale
# instance, then the web app, and stops Radicale when the web app exits
# (Ctrl+C). Uses the throwaway dev Radicale config in .dev/radicale/ --
# see README.md's "Deploying for real" section before using this anywhere
# beyond localhost.
set -euo pipefail
cd "$(dirname "$0")"

# `./run.sh skipauth` waives the login for this local run only (loopback
# requests); the saved account and password are untouched.
for arg in "$@"; do
  case "$arg" in
    skipauth|--skipauth|--skip-auth) export CC_SKIP_AUTH=1; echo "==> Login skipped for this run (loopback only)." ;;
    *) echo "Unknown option: $arg (supported: skipauth)" >&2; exit 2 ;;
  esac
done

# A leftover server on :8000 would keep answering (with its old login
# setting) while the new one fails to bind, so refuse to start instead.
if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then
  echo "!!> Port 8000 is already in use (an earlier run still going?). Stop it and retry." >&2
  exit 1
fi

echo "==> Syncing dependencies (uv sync)..."
uv sync
uv run python scripts/build_static_bundle.py

RADICALE_CONFIG=".dev/radicale/config"
RADICALE_STORAGE=".dev/radicale/collections"
RADICALE_HTPASSWD=".dev/radicale/users"
mkdir -p "$RADICALE_STORAGE"

export CC_RADICALE_URL="${CC_RADICALE_URL:-http://127.0.0.1:5232/devuser/}"
export CC_RADICALE_USER="${CC_RADICALE_USER:-devuser}"
export CC_RADICALE_PASSWORD="${CC_RADICALE_PASSWORD:-devpass}"

# The htpasswd file is gitignored (it holds credentials), so a fresh clone
# has none and Radicale refuses to start. Seed it once from the same
# credentials the web app will log in with; never overwrite an existing one.
if [[ ! -f "$RADICALE_HTPASSWD" ]]; then
  echo "==> Creating dev Radicale users file ($RADICALE_HTPASSWD)..."
  (umask 077 && printf '%s:%s\n' "$CC_RADICALE_USER" "$CC_RADICALE_PASSWORD" > "$RADICALE_HTPASSWD")
fi

echo "==> Starting Radicale (CalDAV/CardDAV server) on 127.0.0.1:5232..."
uv run python -m radicale --config "$RADICALE_CONFIG" \
  --storage-filesystem_folder="$RADICALE_STORAGE" \
  --auth-htpasswd_filename="$RADICALE_HTPASSWD" &
RADICALE_PID=$!

cleanup() {
  echo ""
  echo "==> Stopping Radicale..."
  kill "$RADICALE_PID" 2>/dev/null || true
  wait "$RADICALE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Give Radicale a moment to bind before the web app's startup sync hits it.
sleep 2
if ! kill -0 "$RADICALE_PID" 2>/dev/null; then
  echo "!!> Radicale exited during startup (see its log above); the web app" >&2
  echo "    will run standalone, without CalDAV/CardDAV sync." >&2
fi

echo "==> Starting web app on http://127.0.0.1:8000 ..."
uv run python -m src.main
