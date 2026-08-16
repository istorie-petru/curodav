#!/usr/bin/env bash
# Install Command Center Web (curodav) as a systemd service.
#
#   sudo bash install.sh                   # the app only
#   sudo bash install.sh --with-radicale   # app + optional CalDAV/CardDAV server
#
# What it sets up (paths are overridable via CC_* env vars):
#   /opt/curodav          the repo (git clone), venv created by `uv sync`
#   /var/lib/curodav      data: SQLite cache, backups, radicale collections
#   /etc/curodav          config: curodav.env + radicale/ (0640 root:curodav)
#   curodav.service       the app, enabled + started
#   curodav-radicale.service  optional, only with --with-radicale
#
# Safe to re-run: pulls the latest repo, re-syncs deps, reinstalls the units,
# and never overwrites an existing /etc/curodav/curodav.env.
set -euo pipefail

REPO_URL="https://github.com/istorie-petru/curodav.git"
REPO_DIR="${CC_REPO_DIR:-/opt/curodav}"
SERVICE_USER="${CC_SERVICE_USER:-curodav}"
DATA_DIR="/var/lib/curodav"
CONF_DIR="/etc/curodav"
RADICALE_VENV="/opt/curodav-radicale/.venv"
WITH_RADICALE=0

for arg in "$@"; do
  case "$arg" in
    --with-radicale) WITH_RADICALE=1 ;;
    --repo-dir=*)    REPO_DIR="${arg#*=}" ;;
    --user=*)        SERVICE_USER="${arg#*=}" ;;
    *) echo "install.sh: unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "install.sh: this installer must run as root (sudo)." >&2
  exit 1
fi

# --- prerequisites --------------------------------------------------------
for tool in git curl; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "install.sh: missing prerequisite: $tool" >&2
    exit 1
  fi
done

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  echo "==> Installing uv (Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV_BIN="$HOME/.local/bin/uv"
  [ -x "$UV_BIN" ] || { echo "install.sh: uv install failed" >&2; exit 1; }
fi

# --- service user -----------------------------------------------------------
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  echo "==> Creating system user '$SERVICE_USER'..."
  useradd --system --home-dir "$DATA_DIR" --create-home \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- repo --------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  echo "==> Updating existing repo at $REPO_DIR..."
  git -C "$REPO_DIR" pull --ff-only
else
  echo "==> Cloning $REPO_URL -> $REPO_DIR ..."
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$REPO_DIR"

# --- data + config dirs -------------------------------------------------------
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$DATA_DIR/data" "$DATA_DIR/data/backups"
install -d -o root -g "$SERVICE_USER" -m 0750 "$CONF_DIR"
if [ "$WITH_RADICALE" = 1 ]; then
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR/radicale/collections"
  install -d -o root -g "$SERVICE_USER" -m 0750 "$CONF_DIR/radicale"
fi

# --- env file (never overwrite) -------------------------------------------------
ENV_FILE="$CONF_DIR/curodav.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "==> Writing $ENV_FILE (from the example)..."
  install -o root -g "$SERVICE_USER" -m 0640 \
    "$REPO_DIR/deploy/systemd/curodav.env.example" "$ENV_FILE"
fi

# --- app dependencies -----------------------------------------------------------
# Run uv from webapp/ (the workspace member) -- that is where run.sh already
# syncs from, and it is the invocation that installs the member's runtime
# deps into the repo-root .venv. --no-dev keeps the dev group (pytest, ...)
# out of production. HOME is exported because `su` (without -l) otherwise
# keeps root's HOME=/root, which the service user cannot write to for uv's
# cache/downloads.
echo "==> Installing app dependencies (uv sync, no dev group)..."
su -s /bin/bash "$SERVICE_USER" -c "export HOME='$DATA_DIR'; cd '$REPO_DIR/webapp' && '$UV_BIN' sync --frozen --no-dev"

# --- app unit --------------------------------------------------------------------
echo "==> Installing systemd units..."
install -m 0644 "$REPO_DIR/deploy/systemd/curodav.service" \
  /etc/systemd/system/curodav.service
systemctl daemon-reload
systemctl enable --now curodav.service

# --- optional Radicale companion ----------------------------------------------------
if [ "$WITH_RADICALE" = 1 ]; then
  echo "==> Setting up Radicale (CalDAV/CardDAV server)..."
  install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$(dirname "$RADICALE_VENV")"
  su -s /bin/bash "$SERVICE_USER" -c "export HOME='$DATA_DIR'; '$UV_BIN' venv --python 3.12 '$RADICALE_VENV'"
  su -s /bin/bash "$SERVICE_USER" -c "export HOME='$DATA_DIR'; '$UV_BIN' pip install --python '$RADICALE_VENV/bin/python' 'radicale>=3.3'"

  install -o root -g "$SERVICE_USER" -m 0644 \
    "$REPO_DIR/deploy/systemd/radicale/config.example" \
    "$CONF_DIR/radicale/config"

  RADICALE_USER="${CC_RADICALE_USER:-curodav}"
  if [ ! -f "$CONF_DIR/radicale/users" ]; then
    RADICALE_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 18)"
    printf '%s:%s\n' "$RADICALE_USER" "$RADICALE_PASSWORD" > "$CONF_DIR/radicale/users"
    chmod 0600 "$CONF_DIR/radicale/users"
    if ! grep -q '^CC_RADICALE_URL=' "$ENV_FILE"; then
      printf '\n# Radicale sync credentials (generated by install.sh --with-radicale)\nCC_RADICALE_URL=http://127.0.0.1:5232/%s/\nCC_RADICALE_USER=%s\nCC_RADICALE_PASSWORD=%s\n' \
        "$RADICALE_USER" "$RADICALE_USER" "$RADICALE_PASSWORD" >> "$ENV_FILE"
    fi
    echo ""
    echo "Generated Radicale credentials (also stored in $ENV_FILE):"
    echo "    URL:      http://127.0.0.1:5232/$RADICALE_USER/"
    echo "    user:     $RADICALE_USER"
    echo "    password: $RADICALE_PASSWORD"
    echo ""
  fi

  install -m 0644 "$REPO_DIR/deploy/systemd/curodav-radicale.service" \
    /etc/systemd/system/curodav-radicale.service
  systemctl daemon-reload
  systemctl enable --now curodav-radicale.service
fi

echo "==> Done. Service status:"
systemctl --no-pager --full status curodav.service | head -12
echo ""
echo "    Point your browser at http://<this-host>:8000"
echo "    Update later with: sudo bash $REPO_DIR/deploy/systemd/update.sh"