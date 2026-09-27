#!/usr/bin/env bash
# One-time (or password-rotation) step: writes the bcrypt htpasswd entry
# Radicale authenticates against, into the same named volume the radicale
# service mounts at /data. Run this once before the first `docker compose
# up`, using the RADICALE_USER/RADICALE_PASSWORD you put in .env.
#
#   cd deploy/docker && ./create-radicale-user.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "!! .env not found -- cp .env.example .env and fill it in first." >&2
  exit 1
fi
set -a
source .env
set +a

: "${RADICALE_USER:?RADICALE_USER not set in .env}"
: "${RADICALE_PASSWORD:?RADICALE_PASSWORD not set in .env}"

docker compose build radicale
docker compose run --rm --entrypoint python \
  -e RADICALE_USER -e RADICALE_PASSWORD \
  radicale -c "
import bcrypt, os, pathlib
user = os.environ['RADICALE_USER']
password = os.environ['RADICALE_PASSWORD']
pathlib.Path('/data').mkdir(parents=True, exist_ok=True)
h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
pathlib.Path('/data/users').write_text(f'{user}:{h}\n')
print(f'Wrote /data/users for user {user!r}')
"
