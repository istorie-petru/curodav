#!/usr/bin/env bash
# Update the installed curodav by re-running the installer from your clone.
#
#   sudo bash <your-clone>/deploy/systemd/update.sh
#
# The installer syncs your clone to /opt/curodav, re-syncs dependencies,
# reinstalls the systemd units, and restarts the service(s). Config in
# /etc/curodav and data in /var/lib/curodav are untouched. Pull your clone
# first if you want the latest upstream code.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ ! -d "$SOURCE_DIR/.git" ]; then
  echo "update.sh: $SOURCE_DIR looks like the installed copy, not a clone." >&2
  echo "Update from your clone instead:" >&2
  echo "    git -C <your-clone> pull" >&2
  echo "    sudo bash <your-clone>/deploy/systemd/install.sh" >&2
  exit 1
fi

echo "==> Re-running the installer from $SOURCE_DIR ..."
exec bash "$SOURCE_DIR/deploy/systemd/install.sh" "$@"