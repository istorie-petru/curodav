#!/usr/bin/env bash
# Uninstall Command Center Web (curodav) systemd services.
#
#   sudo bash uninstall.sh                    # the app only
#   sudo bash uninstall.sh --with-radicale    # app + optional CalDAV/CardDAV server
#   sudo bash uninstall.sh --purge            # also delete your data in /var/lib/curodav
#
# Mirror of install.sh: stops and disables the service(s), removes the systemd
# units, and deletes the code and config:
#   /opt/curodav                        the app code (a copy of your clone)
#   /etc/curodav                        config: curodav.env + radicale/
#   /opt/curodav-radicale               optional, only with --with-radicale
#   curodav.service                     the app unit
#   curodav-radicale.service            optional, only with --with-radicale
#
# Your data in /var/lib/curodav (SQLite cache, backups, radicale collections)
# and the 'curodav' service user that owns it are KEPT by default -- pass
# --purge to delete those too.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_DIR="${CC_REPO_DIR:-/opt/curodav}"
SERVICE_USER="${CC_SERVICE_USER:-curodav}"
DATA_DIR="/var/lib/curodav"
CONF_DIR="/etc/curodav"
RADICALE_VENV="/opt/curodav-radicale/.venv"
WITH_RADICALE=0
PURGE=0

for arg in "$@"; do
  case "$arg" in
    --with-radicale) WITH_RADICALE=1 ;;
    --purge)         PURGE=1 ;;
    --repo-dir=*)    REPO_DIR="${arg#*=}" ;;
    --user=*)        SERVICE_USER="${arg#*=}" ;;
    *) echo "uninstall.sh: unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "uninstall.sh: this uninstaller must run as root (sudo)." >&2
  exit 1
fi

# --- services ---------------------------------------------------------------
# Stop and disable before touching any file, so a running app cannot keep
# /opt/curodav or the SQLite cache open while we delete them. Each unit may or
# may not be installed; the loop is per-file so one missing unit is fine.
UNITS="curodav.service"
[ "$WITH_RADICALE" = 1 ] && UNITS="$UNITS curodav-radicale.service"
for unit in $UNITS; do
  if [ -f "/etc/systemd/system/$unit" ]; then
    echo "==> Stopping and disabling $unit ..."
    systemctl stop "$unit" || true
    systemctl disable "$unit" || true
  fi
done

echo "==> Removing systemd units..."
rm -f /etc/systemd/system/curodav.service
rm -rf /etc/systemd/system/curodav.service.d
rm -f /etc/systemd/system/curodav-radicale.service
rm -rf /etc/systemd/system/curodav-radicale.service.d
systemctl daemon-reload

# --- app code ------------------------------------------------------------------
if [ "$SOURCE_DIR" = "$REPO_DIR" ]; then
  echo "==> Keeping $REPO_DIR -- the uninstaller is running from inside it."
  echo "    Remove the installed copy manually once this script has finished."
else
  echo "==> Removing app code at $REPO_DIR ..."
  rm -rf "$REPO_DIR"
fi

# --- config ---------------------------------------------------------------------
echo "==> Removing config at $CONF_DIR ..."
rm -rf "$CONF_DIR"

# --- optional Radicale companion ----------------------------------------------------
if [ "$WITH_RADICALE" = 1 ]; then
  echo "==> Removing Radicale venv at $RADICALE_VENV ..."
  rm -rf "$(dirname "$RADICALE_VENV")"
fi

# --- data + service user ------------------------------------------------------------
if [ "$PURGE" = 1 ]; then
  echo "==> Purging data at $DATA_DIR ..."
  rm -rf "$DATA_DIR"
  if id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "==> Removing service user '$SERVICE_USER' ..."
    userdel "$SERVICE_USER"
  fi
else
  echo "==> Keeping your data at $DATA_DIR (pass --purge to delete it)."
fi

echo "==> Done."
if [ "$PURGE" = 1 ]; then
  echo "    curodav removed, including all data and the '$SERVICE_USER' user."
else
  echo "    curodav removed. Your data is still in $DATA_DIR; the '$SERVICE_USER'"
  echo "    service user still owns it. To delete it as well, re-run with --purge."
fi
