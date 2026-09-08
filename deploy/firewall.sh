#!/usr/bin/env bash
# Locks the public server down to SSH only. With Cloudflare Tunnel
# (cloudflared/install-cloudflared.sh), nothing needs to be reachable from
# outside at all -- the tunnel is a fully OUTBOUND connection cloudflared
# makes out to Cloudflare's network, so there's no local listening port to
# open for 80/443 the way a Caddy-in-front setup would need. Everything
# except ssh is closed by ufw's default-deny-incoming policy, most
# importantly:
#   - 8000 (curodav) -- uvicorn's own ExecStart binds 0.0.0.0:8000
#     (scripts/curodav-ctl), NOT loopback-only, so without this firewall
#     the app would otherwise be reachable directly from the internet,
#     bypassing Cloudflare's edge (TLS, WAF, everything) entirely.
#   - 5232 (radicale) -- config.template binds 127.0.0.1:5232 (loopback
#     only) at the application level already, so this firewall is belt and
#     suspenders here rather than the only thing stopping external access.
#
# Run this BEFORE cloudflared/install-cloudflared.sh / radicale/
# install-radicale.sh, or any time after to confirm/re-apply -- ufw rules
# are idempotent (re-adding an existing rule is a no-op).
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

echo "==> Allowing ssh (22) only -- cloudflared needs no inbound port at all..."
ufw allow 22/tcp comment 'ssh'

echo "==> Explicitly denying direct access to the app + radicale ports"
echo "    (defense in depth -- default-deny already covers these, this"
echo "    just makes the intent unambiguous if the default policy ever"
echo "    changes later)..."
ufw deny 8000/tcp comment 'curodav -- reachable only via cloudflared tunnel'
ufw deny 5232/tcp comment 'radicale -- reachable only via cloudflared tunnel'

echo "==> Enabling ufw..."
ufw --force enable

echo "==> Done. Current rules:"
ufw status verbose
