#!/usr/bin/env bash
# Installs nginx as the loopback-only path router in front of curodav +
# radicale (see curodav.nginx.conf.template's own header for the why).
# Idempotent: re-running just re-copies the config and reloads.
#
# Order matters relative to the OTHER deploy/ scripts: run this AFTER
# radicale/install-radicale.sh (so radicale.service exists -- nginx will
# start fine either way, proxy_pass doesn't require the upstream to be up
# at nginx's own startup, but there's no reason to invite a 502 window)
# and BEFORE cloudflared/install-cloudflared.sh (whose ingress rule points
# at nginx's port -- see config.yml.template).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> install-nginx.sh must run as root (sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_FILE="/etc/nginx/sites-available/curodav"

if ! command -v nginx >/dev/null 2>&1; then
  echo "==> Installing nginx..."
  apt-get update -y
  apt-get install -y nginx
else
  echo "==> nginx already installed ($(nginx -v 2>&1))."
fi

echo "==> Installing curodav's path-router site..."
cp "${SCRIPT_DIR}/curodav.nginx.conf.template" "$SITE_FILE"
ln -sf "$SITE_FILE" /etc/nginx/sites-enabled/curodav

# Remove the stock default site if present -- it also tries to bind :80,
# which we don't use at all (nginx here only ever listens on
# 127.0.0.1:8080, see the site config), but leaving an unrelated default
# server around is just noise/a second thing to reason about.
if [ -e /etc/nginx/sites-enabled/default ]; then
  echo "==> Removing the stock default site..."
  rm -f /etc/nginx/sites-enabled/default
fi

echo "==> Validating nginx config..."
nginx -t

echo "==> Restarting nginx..."
systemctl enable nginx
systemctl restart nginx

sleep 1
if systemctl is-active --quiet nginx; then
  echo "==> nginx.service is running (loopback :8080 only)."
else
  echo "==> nginx.service failed to start -- check 'journalctl -u nginx -e'." >&2
  exit 1
fi

echo "==> Done. /radicale/* -> :5232, everything else -> :8000, both loopback-only."
