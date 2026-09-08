#!/usr/bin/env bash
# Installs cloudflared, creates (or reuses) a named Cloudflare Tunnel,
# routes DOMAIN_APP/DOMAIN_DAV's DNS at it, and runs it as a systemd
# service. Replaces what a Caddy + Let's Encrypt setup would otherwise do
# -- no local reverse proxy, no cert renewal, no inbound port opened at
# all (see ../firewall.sh).
#
# Idempotent for everything except the interactive login: if
# /root/.cloudflared/cert.pem already exists (this host is already
# authorized against your Cloudflare account), it's reused as-is. If a
# tunnel named TUNNEL_NAME already exists, it's reused rather than
# recreated. DNS routes are safe to re-run (cloudflared no-ops or warns if
# a route already points at this tunnel).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> install-cloudflared.sh must run as root (sudo)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${DEPLOY_DIR}/deploy.env"
CF_DIR="/etc/cloudflared"
ROOT_CF_DIR="/root/.cloudflared"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> ${ENV_FILE} not found -- copy deploy.env.example to deploy.env and fill it in first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

for var in DOMAIN_APP DOMAIN_DAV TUNNEL_NAME; do
  if [ -z "${!var:-}" ] || [[ "${!var}" == *example.com* ]]; then
    echo "==> ${var} is unset or still a placeholder in deploy.env -- edit it first." >&2
    exit 1
  fi
done

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "==> Installing cloudflared from Cloudflare's official apt repo..."
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs 2>/dev/null || echo bookworm) main" \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y
  apt-get install -y cloudflared
else
  echo "==> cloudflared already installed ($(cloudflared --version))."
fi

if [ ! -f "${ROOT_CF_DIR}/cert.pem" ]; then
  echo "==> Not yet authorized against your Cloudflare account."
  echo "    Running 'cloudflared tunnel login' -- this prints a URL below;"
  echo "    open it in a browser on ANY device, log in, and pick the"
  echo "    domain/zone that owns DOMAIN_APP/DOMAIN_DAV. Waiting..."
  cloudflared tunnel login
  if [ ! -f "${ROOT_CF_DIR}/cert.pem" ]; then
    echo "==> Login didn't complete (no ${ROOT_CF_DIR}/cert.pem) -- re-run this script after authorizing." >&2
    exit 1
  fi
else
  echo "==> Already authorized (${ROOT_CF_DIR}/cert.pem exists)."
fi

# --- find-or-create the tunnel, then read its UUID back out -----------------
tunnel_id() {
  cloudflared tunnel list -o json 2>/dev/null | python3 -c "
import json, sys
name = sys.argv[1]
try:
    tunnels = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)
for t in tunnels:
    if t.get('name') == name and not t.get('deleted_at'):
        print(t['id'])
        break
" "$TUNNEL_NAME"
}

TUNNEL_ID="$(tunnel_id)"
if [ -z "$TUNNEL_ID" ]; then
  echo "==> Creating tunnel '${TUNNEL_NAME}'..."
  cloudflared tunnel create "$TUNNEL_NAME"
  TUNNEL_ID="$(tunnel_id)"
  if [ -z "$TUNNEL_ID" ]; then
    echo "==> Tunnel creation didn't leave a matching entry in 'cloudflared tunnel list' -- aborting." >&2
    exit 1
  fi
else
  echo "==> Reusing existing tunnel '${TUNNEL_NAME}' (${TUNNEL_ID})."
fi

CRED_FILE="${ROOT_CF_DIR}/${TUNNEL_ID}.json"
if [ ! -f "$CRED_FILE" ]; then
  echo "==> Expected credentials file ${CRED_FILE} not found -- was this tunnel created on a different machine? Delete it from the Cloudflare dashboard and re-run to create a fresh one on THIS host." >&2
  exit 1
fi

echo "==> Routing DNS for ${DOMAIN_APP} and ${DOMAIN_DAV} at this tunnel..."
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN_APP" || echo "    (already routed, or needs manual attention -- see output above)"
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN_DAV" || echo "    (already routed, or needs manual attention -- see output above)"

echo "==> Creating 'cloudflared' system user..."
if ! id cloudflared >/dev/null 2>&1; then
  useradd --system --home-dir "$CF_DIR" --shell /usr/sbin/nologin cloudflared
fi

echo "==> Installing config + credentials to ${CF_DIR}..."
mkdir -p "$CF_DIR"
cp "$CRED_FILE" "${CF_DIR}/${TUNNEL_ID}.json"
sed -e "s/{{TUNNEL_ID}}/${TUNNEL_ID}/g" \
    -e "s/{{DOMAIN_APP}}/${DOMAIN_APP}/g" \
    -e "s/{{DOMAIN_DAV}}/${DOMAIN_DAV}/g" \
    "${SCRIPT_DIR}/config.yml.template" > "${CF_DIR}/config.yml"

cloudflared tunnel --config "${CF_DIR}/config.yml" ingress validate

chown -R cloudflared:cloudflared "$CF_DIR"
chmod 700 "$CF_DIR"
chmod 600 "${CF_DIR}/config.yml" "${CF_DIR}/${TUNNEL_ID}.json"

echo "==> Installing systemd unit..."
cp "${SCRIPT_DIR}/cloudflared.service" /etc/systemd/system/cloudflared.service
systemctl daemon-reload
systemctl enable cloudflared
systemctl restart cloudflared

sleep 2
if systemctl is-active --quiet cloudflared; then
  echo "==> cloudflared.service is running."
else
  echo "==> cloudflared.service failed to start -- check 'journalctl -u cloudflared -e'." >&2
  exit 1
fi

echo "==> Done. Once DNS has propagated (usually near-instant on Cloudflare):"
echo "      https://${DOMAIN_APP} -> localhost:8000 (curodav)"
echo "      https://${DOMAIN_DAV} -> localhost:5232 (radicale, once installed)"
