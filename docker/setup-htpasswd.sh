#!/usr/bin/env bash
# One-time setup: creates the Radicale htpasswd file for Docker.
# Run this BEFORE starting docker compose.
# Requires: htpasswd (from apache2-utils) or docker (to generate via container).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HTPASSWD_FILE="$SCRIPT_DIR/radicale/htpasswd"

if [ -f "$HTPASSWD_FILE" ]; then
    echo "htpasswd already exists at $HTPASSWD_FILE"
    echo "Delete it first if you want to recreate it."
    exit 0
fi

echo "Creating Radicale htpasswd file..."
echo "You'll be prompted for a password for the 'curodav' user."

# Try htpasswd first (available on most Linux distros, macOS with Homebrew)
if command -v htpasswd &>/dev/null; then
    htpasswd -bc "$HTPASSWD_FILE" curodav
else
    # Fallback: generate via Docker
    echo "htpasswd not found locally, using Docker to generate..."
    docker run --rm -it -v "$SCRIPT_DIR/radicale:/work" httpd:2 htpasswd -bc /work/htpasswd curodav
fi

chmod 644 "$HTPASSWD_FILE"
echo ""
echo "Done! htpasswd file created at: $HTPASSWD_FILE"
echo ""
echo "Next steps:"
echo "  1. Edit docker-compose.yml and set your CC_RADICALE_PASSWORD to match"
echo "  2. Run: docker compose up -d"
echo "  3. Open http://localhost:8000 in your browser"
