#!/usr/bin/env bash
# One-command launch: installs deps if needed, starts the dev Radicale
# instance and a SearXNG instance (for the banner editor's image search,
# see routers/banners.py), then the web app, and stops both when the web
# app exits (Ctrl+C). Uses the throwaway dev Radicale config in
# .dev/radicale/ -- see README.md's "Deploying for real" section before
# using this anywhere beyond localhost.
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

# SearXNG (banner image search). Run via Docker when available -- the
# official image listens on 8080; the .dev/searxng/settings.yml mounted
# below is what enables the JSON API that src/searxng.py queries (the
# stock image only serves the HTML UI, so format=json gets a 403 without
# it). Not a hard dependency: the banner editor already renders an inline
# "search failed" message when SearXNG is unreachable, so this is a
# convenience for local dev, and "docker not found / image pull failed"
# degrades to "banner search is unavailable", nothing more.
SEARXNG_PORT="${CC_SEARXNG_PORT:-8080}"
SEARXNG_CONTAINER="command-center-searxng"
SEARXNG_SETTINGS=".dev/searxng/settings.yml"
mkdir -p .dev/searxng
STARTED_SEARXNG=""

start_searxng() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "==> Skipping SearXNG: docker not found (banner search will be unavailable)"
    return
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "$SEARXNG_CONTAINER"; then
    echo "==> Restarting SearXNG container ($SEARXNG_CONTAINER) so the dev settings.yml applies..."
    docker rm -f "$SEARXNG_CONTAINER" >/dev/null 2>&1 || true
  fi
  echo "==> Starting SearXNG (Docker) on 127.0.0.1:$SEARXNG_PORT (first run pulls the image)..."
  if docker run -d --rm --name "$SEARXNG_CONTAINER" \
    -p "127.0.0.1:$SEARXNG_PORT:8080" \
    -v "$(pwd)/$SEARXNG_SETTINGS:/etc/searxng/settings.yml:ro" \
    -e "SEARXNG_BASE_URL=http://127.0.0.1:$SEARXNG_PORT" \
    searxng/searxng; then
    STARTED_SEARXNG="1"
    # Give SearXNG a moment to boot before the app (and any banner search)
    # starts. Not a hard wait-for-ready -- the editor handles a not-yet-up
    # instance with an inline error.
    sleep 3
  else
    echo "==> Could not start SearXNG container (banner search will be unavailable)"
  fi
}

cleanup() {
  echo ""
  if [ -n "$STARTED_SEARXNG" ]; then
    echo "==> Stopping SearXNG..."
    docker rm -f "$SEARXNG_CONTAINER" >/dev/null 2>&1 || true
  fi
  echo "==> Stopping Radicale..."
  kill "$RADICALE_PID" 2>/dev/null || true
  wait "$RADICALE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start_searxng

# Give Radicale a moment to bind before the web app's startup sync hits it.
sleep 2

export CC_RADICALE_URL="${CC_RADICALE_URL:-http://127.0.0.1:5232/devuser/}"
export CC_RADICALE_USER="${CC_RADICALE_USER:-devuser}"
export CC_RADICALE_PASSWORD="${CC_RADICALE_PASSWORD:-devpass}"
export CC_SEARXNG_URL="${CC_SEARXNG_URL:-http://127.0.0.1:$SEARXNG_PORT}"

echo "==> Starting web app on http://127.0.0.1:8000 ..."
uv run python -m src.main
