#!/usr/bin/env bash
# One-command launch: installs deps if needed, starts the dev Radicale
# instance, then the web app, and stops Radicale when the web app exits
# (Ctrl+C). Uses the throwaway dev Radicale config in .dev/radicale/ --
# see README.md's "Deploying for real" section before using this anywhere
# beyond localhost.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Syncing dependencies (uv sync)..."
uv sync

RADICALE_CONFIG=".dev/radicale/config"
RADICALE_STORAGE=".dev/radicale/collections"
RADICALE_HTPASSWD=".dev/radicale/users"
mkdir -p "$RADICALE_STORAGE"

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

export CC_RADICALE_URL="${CC_RADICALE_URL:-http://127.0.0.1:5232/devuser/}"
export CC_RADICALE_USER="${CC_RADICALE_USER:-devuser}"
export CC_RADICALE_PASSWORD="${CC_RADICALE_PASSWORD:-devpass}"

echo "==> Starting web app on http://127.0.0.1:8000 ..."
uv run python -m src.main
