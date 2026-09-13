#!/usr/bin/env bash
# Sets up Radicale as its own systemd service at /srv/radicale, separate
# from curodav's own /srv/curodav (scripts/curodav-ctl) -- see
# radicale.service's own header comment for why they're independent.
#
# Idempotent for the parts that are safe to be (user/dirs/venv/service
# install) -- NOT idempotent for the htpasswd user, which it will refuse to
# overwrite if RADICALE_USER already has a line in /srv/radicale/users (use
# --reset-password to force a rotation instead).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "==> install-radicale.sh must run as root (sudo)." >&2
  exit 1
fi

RESET_PASSWORD=0
if [ "${1:-}" = "--reset-password" ]; then
  RESET_PASSWORD=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
# DEPLOY_ENV_FILE env var override: scripts/curodav-ctl's `run_dav_setup`
# passes this pointing at the persisted /srv/curodav/shared/deploy.env
# instead of this release's own (gitignored, disposable-on-every-update)
# deploy/deploy.env. Running this script by hand per deploy/README.md's
# manual walkthrough still works unchanged -- the override is unset then,
# so it falls back to the release-local path exactly as before.
ENV_FILE="${DEPLOY_ENV_FILE:-${DEPLOY_DIR}/deploy.env}"
BASE_DIR="/srv/radicale"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> ${ENV_FILE} not found -- copy deploy.env.example to deploy.env and fill it in first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

if [ -z "${RADICALE_USER:-}" ]; then
  echo "==> RADICALE_USER is unset in deploy.env." >&2
  exit 1
fi

echo "==> Creating 'radicale' system user..."
if ! id radicale >/dev/null 2>&1; then
  useradd --system --home-dir "$BASE_DIR" --shell /usr/sbin/nologin --create-home radicale
fi

echo "==> Creating ${BASE_DIR} layout..."
mkdir -p "${BASE_DIR}/collections"

echo "==> Creating venv + installing radicale + bcrypt..."
if [ ! -d "${BASE_DIR}/venv" ]; then
  python3 -m venv "${BASE_DIR}/venv"
fi
"${BASE_DIR}/venv/bin/pip" install --upgrade pip --quiet
"${BASE_DIR}/venv/bin/pip" install --upgrade "radicale>=3.3" bcrypt --quiet

echo "==> Installing config..."
cp "${SCRIPT_DIR}/config.template" "${BASE_DIR}/config"

echo "==> Setting up bcrypt auth for user '${RADICALE_USER}'..."
touch "${BASE_DIR}/users"
if grep -q "^${RADICALE_USER}:" "${BASE_DIR}/users" 2>/dev/null && [ "$RESET_PASSWORD" -eq 0 ]; then
  echo "    ${RADICALE_USER} already has a password set -- leaving it untouched."
  echo "    Re-run with --reset-password to rotate it instead."
else
  if [ -n "${RADICALE_PASSWORD:-}" ] && [ -n "${RADICALE_PASSWORD_CONFIRM:-}" ]; then
    # Pre-set by scripts/curodav-ctl's collect_radicale_password (one prompt
    # there serves both this bcrypt hash and curodav's own CC_RADICALE_PASSWORD).
    # Deliberately NOT a CLI arg (would land in shell history and any other
    # user's `ps` output). It IS, honestly, a slightly larger exposure than a
    # bare interactive prompt though: for as long as THIS process runs, the
    # value sits in its environment block, readable by root via
    # /proc/<this-pid>/environ -- and unsetting it below only prevents further
    # child processes from inheriting it, it does not retroactively scrub
    # /proc/<pid>/environ (which on Linux generally reflects the process's
    # environment at exec time, not later unsetenv() calls). Everything here
    # already runs as root, so this doesn't cross a privilege boundary, and
    # the exposure window is only this script's own runtime -- but it's worth
    # being precise about rather than pretending it's identical to a prompt.
    echo "    Using RADICALE_PASSWORD from the environment (set by curodav-ctl)."
  else
    # Run standalone (deploy/README.md's manual walkthrough): prompt directly,
    # never passed as an arg/env var, never written anywhere but the
    # bcrypt-hashed line in /srv/radicale/users.
    read -r -s -p "    Set a Radicale password for '${RADICALE_USER}': " RADICALE_PASSWORD
    echo
    read -r -s -p "    Confirm: " RADICALE_PASSWORD_CONFIRM
    echo
  fi
  if [ "$RADICALE_PASSWORD" != "$RADICALE_PASSWORD_CONFIRM" ]; then
    echo "==> Passwords didn't match, aborting." >&2
    exit 1
  fi
  HASHED_LINE="$("${BASE_DIR}/venv/bin/python" -c "
import bcrypt, sys
pw = sys.stdin.readline().rstrip('\n').encode()
print(bcrypt.hashpw(pw, bcrypt.gensalt()).decode())
" <<< "$RADICALE_PASSWORD")"
  # Replace any existing line for this user (covers --reset-password), else append.
  grep -v "^${RADICALE_USER}:" "${BASE_DIR}/users" > "${BASE_DIR}/users.tmp" 2>/dev/null || true
  echo "${RADICALE_USER}:${HASHED_LINE}" >> "${BASE_DIR}/users.tmp"
  mv "${BASE_DIR}/users.tmp" "${BASE_DIR}/users"
  unset RADICALE_PASSWORD RADICALE_PASSWORD_CONFIRM HASHED_LINE
fi

echo "==> Fixing ownership + permissions..."
chown -R radicale:radicale "$BASE_DIR"
chmod 700 "$BASE_DIR"
chmod 600 "${BASE_DIR}/users" "${BASE_DIR}/config"

echo "==> Installing systemd unit..."
cp "${SCRIPT_DIR}/radicale.service" /etc/systemd/system/radicale.service
systemctl daemon-reload
systemctl enable radicale
systemctl restart radicale

sleep 1
if systemctl is-active --quiet radicale; then
  echo "==> radicale.service is running (loopback :5232 only)."
else
  echo "==> radicale.service failed to start -- check 'journalctl -u radicale -e'." >&2
  exit 1
fi

if [ -n "${DEPLOY_ENV_FILE:-}" ]; then
  # Called from scripts/curodav-ctl's run_dav_setup, which wires
  # CC_RADICALE_URL/USER/PASSWORD into /srv/curodav/shared/.env and restarts
  # curodav itself right after this script returns -- printing the manual
  # "add these lines" instructions here would be stale/confusing.
  echo "==> Done. curodav-ctl will wire this into /srv/curodav/shared/.env next."
else
  echo "==> Done. Next:"
  echo "    1. Set in /srv/curodav/shared/.env:"
  echo "         CC_RADICALE_URL=http://127.0.0.1:5232/${RADICALE_USER}/"
  echo "         CC_RADICALE_USER=${RADICALE_USER}"
  echo "         CC_RADICALE_PASSWORD=<the password you just set>"
  echo "         CC_RADICALE_PUBLIC_URL=https://${DOMAIN_APP:-<your DOMAIN_APP>}/radicale/${RADICALE_USER}/"
  echo "       then: systemctl restart curodav"
  echo "    2. Set up ../nginx/install-nginx.sh and ../cloudflared/install-cloudflared.sh"
  echo "       if you haven't already -- Radicale is only reachable from outside"
  echo "       through both of those, at a /radicale/ path under DOMAIN_APP, not"
  echo "       a separate hostname."
  echo "    3. On the phone, add a DAVx5 account with:"
  echo "         URL:      https://${DOMAIN_APP:-<your DOMAIN_APP>}/radicale/${RADICALE_USER}/"
  echo "         Username: ${RADICALE_USER}"
  echo "         Password: <the password you just set>"
fi
