#!/usr/bin/env bash
# Locks the host down to SSH only via ufw. Everything else (8000 curodav,
# 5232 radicale, 8080 nginx) is reached only through the Cloudflare Tunnel,
# which is outbound-only -- no inbound port needs to be open for it.
#
# SAFETY: if sshd is actually listening on a non-standard port and this
# script opens 22 instead, you lock yourself out with no way back short of
# provider console access. It detects sshd's real port and refuses to
# proceed if it isn't 22 -- override with FIREWALL_SSH_PORT=<port>.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> firewall.sh must run as root (sudo)." >&2
  exit 1
fi

detect_sshd_port() {
  local port
  if command -v sshd >/dev/null 2>&1; then
    port="$(sshd -T 2>/dev/null | awk 'tolower($1)=="port"{print $2; exit}')"
  fi
  if [ -z "${port:-}" ] && [ -f /etc/ssh/sshd_config ]; then
    port="$(awk 'tolower($1)=="port"{print $2; exit}' /etc/ssh/sshd_config 2>/dev/null)"
  fi
  echo "${port:-22}"
}

DETECTED_SSH_PORT="$(detect_sshd_port)"
SSH_PORT="${FIREWALL_SSH_PORT:-$DETECTED_SSH_PORT}"

if [ "$DETECTED_SSH_PORT" != "22" ] && [ -z "${FIREWALL_SSH_PORT:-}" ]; then
  echo "==> sshd appears to be configured on port ${DETECTED_SSH_PORT}, not 22." >&2
  echo "    Proceeding with the default would open 22 (nothing listens there)" >&2
  echo "    and leave ${DETECTED_SSH_PORT} unreachable, locking you out." >&2
  echo "    Re-run as: sudo FIREWALL_SSH_PORT=${DETECTED_SSH_PORT} ./firewall.sh" >&2
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

echo "==> Allowing ssh (${SSH_PORT}) only..."
ufw allow "${SSH_PORT}/tcp" comment 'ssh'

echo "==> Explicitly denying direct access to the app + radicale ports..."
ufw deny 8000/tcp comment 'curodav -- reachable only via nginx + cloudflared tunnel'
ufw deny 5232/tcp comment 'radicale -- reachable only via nginx + cloudflared tunnel'
ufw deny 8080/tcp comment 'nginx path-router -- reachable only via cloudflared tunnel'

echo "==> Enabling ufw..."
ufw --force enable

echo "==> Done. Current rules:"
ufw status verbose
