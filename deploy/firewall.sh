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
#   - 8080 (nginx, ../nginx/) -- also binds 127.0.0.1 only at the
#     application level (its own config.template's `listen` line); same
#     belt-and-suspenders reasoning as radicale above. This is the ONLY
#     port cloudflared's ingress rule actually points at now -- it fans
#     out to :8000/:5232 locally, itself never bound to 0.0.0.0.
#
# Run this BEFORE cloudflared/install-cloudflared.sh / radicale/
# install-radicale.sh, or any time after to confirm/re-apply -- ufw rules
# are idempotent (re-adding an existing rule is a no-op).
#
# SAFETY: this only opens port 22. If sshd is actually configured to
# listen on a different port (a common hardening step, and easy to forget
# about weeks/months later), running this as-is locks you out of the box
# entirely -- there is no inbound port left for you to reconnect on, and
# recovering from that needs your hosting provider's own console/rescue
# access, not SSH. This script now detects the port sshd is ACTUALLY
# configured for and refuses to proceed if it isn't 22, rather than
# silently doing the wrong thing. Override with
# FIREWALL_SSH_PORT=<port> if your SSH really is non-standard.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> firewall.sh must run as root (sudo)." >&2
  exit 1
fi

detect_sshd_port() {
  local port
  # sshd -T dumps the fully-resolved effective config (defaults + all
  # Include'd/overriding files) -- more reliable than grepping
  # sshd_config directly, which might not even set Port explicitly (the
  # implicit default is 22) or might set it inside an included file.
  # Requires host keys to already exist, which they will on any real,
  # already-provisioned host; if sshd -T fails for any reason, fall back
  # to a plain grep, then finally assume the standard default.
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
  echo "    This script only opens the port you tell it to -- proceeding with" >&2
  echo "    the default would open 22 (which nothing is listening on) and" >&2
  echo "    leave ${DETECTED_SSH_PORT} (your ACTUAL ssh port) unreachable," >&2
  echo "    locking you out of this host." >&2
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

echo "==> Allowing ssh (${SSH_PORT}) only -- cloudflared needs no inbound port at all..."
ufw allow "${SSH_PORT}/tcp" comment 'ssh'

echo "==> Explicitly denying direct access to the app + radicale ports"
echo "    (defense in depth -- default-deny already covers these, this"
echo "    just makes the intent unambiguous if the default policy ever"
echo "    changes later)..."
ufw deny 8000/tcp comment 'curodav -- reachable only via nginx + cloudflared tunnel'
ufw deny 5232/tcp comment 'radicale -- reachable only via nginx + cloudflared tunnel'
ufw deny 8080/tcp comment 'nginx path-router -- reachable only via cloudflared tunnel'

echo "==> Enabling ufw..."
ufw --force enable

echo "==> Done. Current rules:"
ufw status verbose
