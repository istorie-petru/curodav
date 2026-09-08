#!/usr/bin/env bash
# Installs Caddy (official apt repo) and renders Caddyfile.template into
# /etc/caddy/Caddyfile using deploy.env's DOMAIN_APP/DOMAIN_DAV/LE_EMAIL.
# Idempotent -- re-run any time deploy.env changes to re-render and reload.
#
# Prerequisite: DOMAIN_APP and DOMAIN_DAV must already resolve (A/AAAA) to
# this server's public IP before running this -- Caddy's automatic HTTPS
# requests real Let's Encrypt certs for both domains as soon as it starts,
# and will fail the ACME HTTP-01 challenge (needs port 80 reachable and
# DNS pointing here) against a domain that doesn't resolve yet.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> install-caddy.sh must run as root (sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/deploy.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> ${ENV_FILE} not found -- copy deploy.env.example to deploy.env and fill it in first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

for var in DOMAIN_APP DOMAIN_DAV LE_EMAIL; do
  if [ -z "${!var:-}" ] || [[ "${!var}" == *example.com* ]]; then
    echo "==> ${var} is unset or still a placeholder (*.example.com) in deploy.env -- edit it first." >&2
    exit 1
  fi
done

if ! command -v caddy >/dev/null 2>&1; then
  echo "==> Installing Caddy from the official apt repo..."
  apt-get update -y
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
else
  echo "==> Caddy already installed ($(caddy version))."
fi

echo "==> Rendering Caddyfile.template -> /etc/caddy/Caddyfile..."
sed -e "s/{{DOMAIN_APP}}/${DOMAIN_APP}/g" \
    -e "s/{{DOMAIN_DAV}}/${DOMAIN_DAV}/g" \
    -e "s/{{LE_EMAIL}}/${LE_EMAIL}/g" \
    "${SCRIPT_DIR}/Caddyfile.template" > /etc/caddy/Caddyfile

echo "==> Validating config..."
caddy validate --config /etc/caddy/Caddyfile

echo "==> Enabling and (re)starting caddy..."
systemctl enable caddy
systemctl restart caddy

echo "==> Done. Caddy is now reverse-proxying:"
echo "      https://${DOMAIN_APP} -> 127.0.0.1:8000 (curodav)"
echo "      https://${DOMAIN_DAV} -> 127.0.0.1:5232 (radicale, once installed)"
echo "    Caddy requests both certs from Let's Encrypt automatically on startup --"
echo "    check 'journalctl -u caddy -f' if either doesn't come up over HTTPS."
