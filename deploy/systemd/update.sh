#!/usr/bin/env bash
# Update Command Center Web (curodav) to the latest commit on GitHub.
#
#   sudo bash update.sh
#
# Pulls the repo, re-syncs dependencies, reinstalls the (possibly changed)
# systemd units, and restarts the service(s). Your config in /etc/curodav and
# your data in /var/lib/curodav are untouched. A defensive SQLite snapshot
# is taken first -- the app's Settings > Data health backups are the
# authoritative mechanism; this is just a cheap last-resort safety net.
set -euo pipefail

REPO_DIR="${CC_REPO_DIR:-/opt/curodav}"
SERVICE_USER="${CC_SERVICE_USER:-curodav}"
DATA_DIR="/var/lib/curodav"
DB_FILE="${CC_DB_FILE:-$DATA_DIR/data/cache.sqlite}"

if [ "$(id -u)" -ne 0 ]; then
  echo "update.sh: this updater must run as root (sudo)." >&2
  exit 1
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "update.sh: no repo at $REPO_DIR -- run install.sh first." >&2
  exit 1
fi

# --- defensive snapshot -----------------------------------------------------
if [ -f "$DB_FILE" ]; then
  SNAP_DIR="$DATA_DIR/data/backups"
  mkdir -p "$SNAP_DIR"
  SNAP="$SNAP_DIR/pre-update-$(date +%Y%m%d-%H%M%S).sqlite"
  cp -a "$DB_FILE" "$SNAP"
  chown "$SERVICE_USER":"$SERVICE_USER" "$SNAP" 2>/dev/null || true
  echo "==> SQLite snapshot before update: $SNAP"
fi

# --- pull + sync --------------------------------------------------------------
if ! git -C "$REPO_DIR" diff --quiet; then
  echo "WARNING: local changes exist in $REPO_DIR -- leaving them untouched,"
  echo "         but the pull may refuse to fast-forward."
fi
echo "==> Pulling latest code..."
git -C "$REPO_DIR" fetch origin
git -C "$REPO_DIR" pull --ff-only origin main

chown -R "$SERVICE_USER":"$SERVICE_USER" "$REPO_DIR"

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
else
  UV_BIN="$HOME/.local/bin/uv"
  [ -x "$UV_BIN" ] || { echo "update.sh: uv not found" >&2; exit 1; }
fi

echo "==> Re-syncing dependencies..."
su -s /bin/bash "$SERVICE_USER" -c "export HOME='$DATA_DIR'; cd '$REPO_DIR/webapp' && '$UV_BIN' sync --frozen --no-dev"

# --- reinstall units (they can change between releases) -------------------------
install -m 0644 "$REPO_DIR/deploy/systemd/curodav.service" \
  /etc/systemd/system/curodav.service
if [ -f /etc/systemd/system/curodav-radicale.service ]; then
  install -m 0644 "$REPO_DIR/deploy/systemd/curodav-radicale.service" \
    /etc/systemd/system/curodav-radicale.service
fi
systemctl daemon-reload

echo "==> Restarting services..."
systemctl restart curodav.service
if systemctl is-enabled --quiet curodav-radicale.service 2>/dev/null; then
  systemctl restart curodav-radicale.service
fi

echo "==> Update complete."
systemctl --no-pager --full status curodav.service | head -10