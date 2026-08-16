# Deploying Command Center Web (curodav)

Two supported ways to run this app on a real server, both with a one-command
installer and updater:

| Path | How it runs | Good for |
|---|---|---|
| [`systemd/`](systemd/) | A native systemd service from a clone of the repo | A single Linux host you already manage |
| [`docker/`](docker/) | `docker compose` containers (named volumes for all data) | Any host with Docker, easy teardown |

Both install the app **without** Radicale by default — the app is fully
usable standalone (all reads *and* writes live in its own SQLite store).
The optional CalDAV/CardDAV server is added with `--with-radicale` and is
only needed if you want to sync the calendar/tasks/contacts to a phone or
another CalDAV client.

> **Security first:** the app ships with **no authentication** and only
> enforces a login when you configure it (set `CC_AUTH_USERNAME` +
> `CC_AUTH_PASSWORD` in the env file — see the configuration table below and
> [`features/auth.md`](../features/auth.md) for how the single-user login
> works). Until you do, both deploys publish the app on `127.0.0.1:8000`
> and expect you to reach it over a trusted network (e.g. Tailscale) or
> through a reverse proxy that adds auth. Do not expose the port directly
> to the internet — at minimum, set the `CC_AUTH_*` variables.

## Quick start

**systemd** (run as root):

```bash
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/systemd/install.sh)          # app only
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/systemd/install.sh) --with-radicale
```

**Docker** (run as root):

```bash
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/docker/install.sh)
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/docker/install.sh) --with-radicale
```

The installers clone the repo to `/opt/curodav`, install dependencies, write
a config file, and start the service(s). After the first install, update with
`sudo bash /opt/curodav/deploy/systemd/update.sh` (or `.../docker/update.sh`)
— or re-run the same installer, which is idempotent and never overwrites your
config.

Point your browser at `http://<host>:8000`.

## Configuration

Both deploys read an environment file at `/etc/curodav/curodav.env`, created
from the example on first install (your edits are never overwritten by
re-runs). The systemd units pick it up via `EnvironmentFile`; the compose
service reads it via `env_file` (optional — the container has sensible
defaults without it).

The important variables (see `deploy/*/curodav.env.example` for all of them):

| Var | Default | Purpose |
|---|---|---|
| `CC_DB_PATH` | `~/.command_center_web/cache.sqlite` | The SQLite cache. systemd: set to `/var/lib/curodav/data/cache.sqlite`. Docker: the container's home (`/var/lib/curodav`, a named volume) |
| `CC_BACKUP_DIR` | next to the DB | Where Settings > Data health stores backups |
| `CC_SYNC_INTERVAL` | `60` | Background Radicale pull interval, seconds |
| `CC_RADICALE_URL` | `http://127.0.0.1:5232/devuser/` | Radicale principal URL — see below |
| `CC_AUTH_USERNAME` | *(none)* | Single-user login — set **both** with `CC_AUTH_PASSWORD` to require a login on every page |
| `CC_AUTH_PASSWORD` | *(none)* | The one account's password (see above) |
| `CC_AUTH_SECRET` | *(auto-generated)* | Session-cookie signing key; unset = auto-generated and stored in the app DB |

### Enabling phone sync (optional Radicale)

Install with `--with-radicale` and the installer generates a credential and
appends the three `CC_RADICALE_*` lines to `/etc/curodav/curodav.env` for
you. The critical detail is the **URL shape**: it must end with the sync
user's own principal path plus a trailing slash — the username, not just the
server root:

- systemd: `CC_RADICALE_URL=http://127.0.0.1:5232/<user>/`
- Docker: `CC_RADICALE_URL=http://radicale:5232/<user>/` (`radicale` is the
  container's hostname on the compose network)

(`--with-radicale` uses plaintext htpasswd auth for the sync user, matching
the app's own trusted-network model. A hardened config — bcrypt htpasswd,
TLS — is a drop-in replacement for `deploy/*/radicale/config`.)

The app connects to Radicale at startup to create its `tasks` / `calendar` /
`contacts` collections. If the server is unreachable at boot the app simply
starts without the sync bridge (it logs `Radicale unreachable at startup;
running without the sync bridge` and keeps serving) and retries on the next
restart — a Radicale outage never takes the app down.

### Pointing a phone at it

With the calendar app on your phone, add a CalDAV/CardDAV account pointing at
`http://<host>:5232/<user>/` (Docker publishes `127.0.0.1:5232` on the host
by default; change that port mapping or use Tailscale if the phone is off the
LAN).

## What each deploy manages

**systemd**

- `/opt/curodav` — the repo; the venv is the repo-root `.venv` (`uv sync
  --frozen --no-dev` run from `webapp/`).
- `/var/lib/curodav` — app data: SQLite cache, backups, and (with
  `--with-radicale`) Radicale collections. Everything worth keeping lives
  here.
- `/etc/curodav` — `curodav.env` plus `radicale/{config,users}`.
- Units: `curodav.service` (the app), `curodav-radicale.service` (optional),
  both enabled and started. Update re-installs the units, so unit changes
  between releases propagate automatically.
- `update.sh` takes a cheap SQLite snapshot before pulling; the app's own
  Settings > Data health backups are the authoritative backup mechanism.
- Uninstall: `systemctl disable --now curodav.service curodav-radicale.service`
  and remove the three directories (keep `/var/lib/curodav` for your data).

**Docker**

- `/opt/curodav` — the repo, also the image build context.
- `/etc/curodav` — `curodav.env`.
- Named volumes: `curodav-data` (app home: SQLite + backups) and
  `radicale-collections` (with `--with-radicale`). `docker compose down`
  stops containers but keeps both volumes; `down -v` deletes the data.
- The Radicale `users` file lives at `deploy/docker/radicale/users` (copied
  from `users.example` by the installer; gitignored). It is bind-mounted
  read-only into the container.
- Uninstall: `docker compose -f /opt/curodav/deploy/docker/docker-compose.yml
  --profile sync down` (add `-v` to also delete the data volumes).

## Updating

```bash
sudo bash /opt/curodav/deploy/systemd/update.sh   # or
sudo bash /opt/curodav/deploy/docker/update.sh
```

Both pull the latest `main`, re-install dependencies / rebuild the image,
and restart — your `/etc/curodav` config and data are untouched. Updates are
safe to run at any time.

## Layout

```
deploy/
  systemd/
    curodav.service            app unit (uvicorn on 0.0.0.0:8000)
    curodav-radicale.service   optional Radicale unit
    curodav.env.example        config template (installed to /etc/curodav)
    radicale/config.example    Radicale config template
    install.sh                 idempotent installer (sudo)
    update.sh                  updater (sudo)
  docker/
    Dockerfile                 python:3.12-slim + uv image
    docker-compose.yml         app (+ optional radicale, profile "sync")
    curodav.env.example        config template
    radicale/config            Radicale config (mounts to /etc/radicale)
    radicale/users.example     copy to `users` and set the sync password
    install.sh                 idempotent installer (sudo)
    update.sh                  updater (sudo)
```
