#!/usr/bin/env bash
# Update Command Center Web (curodav) to the latest commit on GitHub.
#
#   sudo bash update.sh
#
# Pulls the repo and rebuilds the image(s), then recreates changed
# containers. Named volumes keep your data; /etc/curodav/curodav.env is
# untouched.
set -euo pipefail

REPO_DIR="${CC_REPO_DIR:-/opt/curodav}"
COMPOSE=(docker compose -f "$REPO_DIR/deploy/docker/docker-compose.yml")

if [ "$(id -u)" -ne 0 ]; then
  echo "update.sh: this updater must run as root (sudo)." >&2
  exit 1
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "update.sh: no repo at $REPO_DIR -- run install.sh first." >&2
  exit 1
fi

if ! git -C "$REPO_DIR" diff --quiet; then
  echo "WARNING: local changes exist in $REPO_DIR -- leaving them untouched,"
  echo "         but the pull may refuse to fast-forward."
fi

echo "==> Pulling latest code..."
git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" pull --ff-only origin main

echo "==> Rebuilding and restarting..."
"${COMPOSE[@]}" up -d --build

echo "==> Update complete."
"${COMPOSE[@]}" ps