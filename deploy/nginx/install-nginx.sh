#!/usr/bin/env bash
# Installs nginx as the loopback-only path router in front of curodav +
# radicale. Idempotent: re-running just re-copies the config and reloads.
# Run AFTER radicale/install-radicale.sh, BEFORE cloudflared/install-cloudflared.sh.
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

# 2026-09-13 -- Radicale-specific rate limiting (see that file's own
# comment for why). Must land in conf.d/, not sites-available/: the
# limit_req_zone directive it defines is only legal in nginx's http {}
# context, and Debian's stock nginx.conf already includes conf.d/*.conf
# from there (same mechanism it uses for sites-enabled/*).
#
# RATE_LIMIT_IP_SOURCE (2026-09-18, set by curodav-ctl based on --proxy=):
# the nginx variable to key rate limiting on. Defaults to the Cloudflare
# Tunnel header (curodav-ratelimit.conf.template's own comment explains
# why); a manual/non-Cloudflare reverse proxy setup should pass
# $remote_addr instead, since there's no CF-Connecting-IP header to trust
# in that case.
echo "==> Installing Radicale rate-limit zone..."
IP_SOURCE="${RATE_LIMIT_IP_SOURCE:-\$http_cf_connecting_ip}"
sed "s|{{IP_SOURCE}}|${IP_SOURCE}|g" "${SCRIPT_DIR}/curodav-ratelimit.conf.template" > /etc/nginx/conf.d/curodav-ratelimit.conf

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
