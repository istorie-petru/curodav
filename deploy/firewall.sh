#!/usr/bin/env bash
# Locks down the public server to only the ports that need to be reachable
# from outside: 22 (ssh), 80 + 443 (Caddy). Everything else is closed by
# ufw's default-deny-incoming policy, most importantly:
#   - 8000 (curodav) -- uvicorn's own ExecStart binds 0.0.0.0:8000
#     (scripts/curodav-ctl), NOT loopback-only, so without this firewall
#     the app would otherwise be reachable directly, bypassing Caddy's TLS
#     and security headers entirely.
#   - 5232 (radicale) -- config.template binds 127.0.0.1:5232 (loopback
#     only) at the application level already, so this firewall is belt and
#     suspenders here rather than the only thing stopping external access.
#
# Run this BEFORE install-caddy.sh / radicale/install-radicale.sh, or any
# time after to confirm/re-apply -- ufw rules are idempotent (re-adding an
# existing rule is a no-op).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> firewall.sh must run as root (sudo)." >&2
  exit 1
fi

if ! command -v ufw >/dev/null 2>&1; then
  echo "==> Installing ufw..."
  apt-get update -y
  apt-get install -y ufw
fi

echo "==> Setting default policy (deny incoming, allow outgoing)..."
ufw default deny incoming
ufw default allow outgoing

echo "==> Allowing ssh (22), http (80), https (443)..."
ufw allow 22/tcp comment 'ssh'
ufw allow 80/tcp comment 'caddy: ACME + http->https redirect'
ufw allow 443/tcp comment 'caddy: https'

echo "==> Explicitly denying direct access to the app + radicale ports"
echo "    (defense in depth -- default-deny already covers these, this"
echo "    just makes the intent unambiguous if the default policy ever"
echo "    changes later)..."
ufw deny 8000/tcp comment 'curodav -- via caddy only'
ufw deny 5232/tcp comment 'radicale -- via caddy only'

echo "==> Enabling ufw..."
ufw --force enable

echo "==> Done. Current rules:"
ufw status verbose
