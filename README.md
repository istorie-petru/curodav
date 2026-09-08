# Command Center

A self-hosted **personal organizer / PWA dashboard** for one person: a home
dashboard with widgets, a full calendar, tasks, a class timetable, habit
tracking, contacts, and one universal label system that organizes all of it. It
syncs to your phone through open standards (CalDAV/CardDAV) — no cloud account,
no subscription.

## What it is

- **Single-user by design.** Tasks, events, and contacts are the primary
  objects; a *label* is a name they point at, not an entity with a lifecycle.
  Everything else — Spaces, Projects, Schedule, Published Lists — is a behavior
  over that pool, never a new kind of object.
- **Runs entirely from one tree** with no external services beyond the optional
  Radicale sync server. Self-host it where you like.
- **The current version is 2.0.0** — the first full, stable release. The
  app's history (phases 0.1 → 1.9) and the versioning rules are in
  [`plans/abandoned.md`](documentation/plans/abandoned.md).

## Is this for you?

This is a self-hosted app: you run it on your own server (a spare computer,
a Raspberry Pi, a cheap VPS, a Proxmox VM/LXC) rather than signing up for a
hosted service. If you're comfortable running a few terminal commands over
SSH and don't mind occasionally reading a log file, you can run this. If
"self-hosted" and "systemd service" are unfamiliar terms, read the
[Getting started](#getting-started) walkthrough below first — it explains
each one as it comes up — before deciding whether to proceed.

## The stack

| Layer | Technology |
|---|---|
| App framework | **FastAPI** (Python 3.12+) + **Uvicorn** |
| Server-side rendering | **Jinja2** templates; JS adds interactivity on top |
| Database | **SQLite** (a single local file, treated as a rebuildable cache) |
| Sync backend | **Radicale** (self-hosted CalDAV/CardDAV) + `caldav` / `icalendar` / `vobject` |
| Frontend | Vanilla **JavaScript + CSS** (Material 3) — no framework, no build step |
| Testing | **pytest** + httpx |

## Repository layout

```
webapp/      The app — FastAPI client (sole client since 0.7)
  src/       Routers, db layer, pure logic modules, static assets, templates
  tests/     pytest suite (acceptance-oriented, one file per feature)
  run.sh     One-command dev start (uv sync + dev Radicale + the app)
scripts/     Deploy tooling (curodav-ctl)
documentation/   All project docs — see "Where docs live" below
  features/  Outcome documentation — what the current app actually does
  plans/     Planning
pyproject.toml / uv.lock   uv workspace
```

## Getting started

There are two different things people mean by "getting started" here — try
it out on your own laptop first, or install it for real on a server you'll
actually use day to day. Pick one.

### Just trying it out (your own computer, nothing permanent)

Requires [Python 3.12+](https://www.python.org/downloads/) and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) (a
Python package manager) installed first.

```bash
git clone https://github.com/istorie-petru/curodav.git
cd curodav/webapp
./run.sh                 # -> http://127.0.0.1:8000
```

Open `http://127.0.0.1:8000` in your browser. `run.sh` installs the app's
dependencies (`uv sync`), starts a throwaway test sync server (Radicale) in
the background, then the app itself, and shuts the sync server down again
when you press Ctrl+C. Nothing here is written outside this folder, and
there's no login screen — this mode is meant for one person poking around
on their own machine, not for exposing to a network. When you're done
evaluating it, delete the `curodav` folder and nothing is left behind.

Run the test suite (optional, for anyone editing the code):

```bash
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q
```

All tests green or a change isn't done.

### Installing it for real (a server, always-on)

**What you need first:**

- A **Debian 12** machine you have root/`sudo` access to — a spare PC, a
  Raspberry Pi running Debian, a $5/mo VPS, or a VM/LXC container in
  something like Proxmox. Not Windows or macOS. No Docker required (and
  none used) — it installs directly as a system service.
- That machine reachable over SSH from the computer you're typing commands
  on.
- A rough idea of how you'll reach it afterward: over your home network,
  over a VPN like [Tailscale](https://tailscale.com/) (recommended — free,
  easiest to set up, and keeps the app off the public internet entirely),
  or publicly if you want phone sync from anywhere (see
  [Connecting your phone](#connecting-your-phone-caldavcarddav) below).

The app deploys as a systemd service via
[`scripts/curodav-ctl`](scripts/curodav-ctl). Each deploy builds a fresh,
isolated release and atomically swaps a symlink over to it; nothing is ever
edited in place, and a deploy that fails its own health check rolls itself
back automatically — the site never goes down mid-upgrade.

#### First install (fresh host)

SSH into the server, then:

```bash
git clone https://github.com/istorie-petru/curodav.git /tmp/bootstrap
sudo /tmp/bootstrap/scripts/curodav-ctl install
rm -rf /tmp/bootstrap
```

(`curodav-ctl` ships inside this repo rather than a separate infra repo, and
figures out its own repo URL from the clone it's running from — that's why
you clone first and run the script *from inside* that clone, rather than
downloading just the one script file.)

`install` will:

1. Create a dedicated `curodav` system user and the `/srv/curodav` folder
   layout it lives in.
2. Generate `/srv/curodav/shared/.env` — the app's one config file — with a
   random secret key already filled in and everything else left as
   commented-out examples.
3. Install and enable the `curodav.service` systemd unit (systemd is
   Debian's standard "keep this program running, restart it if it crashes
   or the server reboots" mechanism — no separate install step needed, it's
   already on the machine).
4. Build and start the first release.

By the end, the app is running at `http://<the server's IP address>:8000`.
Open that in a browser (over Tailscale, your LAN, or however you chose to
reach it above) and you'll land on a one-time **setup page**: pick a
username and password there, right in the browser — no config file editing
required for this part. That's your login from then on, and the app is now
private to whoever knows that password.

Deploying to a fork, or from a separate infra repo instead of in-tree, works
the same way but with an explicit override: `sudo CURODAV_REPO_URL=<url> -E
curodav-ctl install`.

#### Updating (every deploy after that)

```bash
sudo curodav-ctl update
```

This clones the latest `main`, builds it (`uv sync --frozen --no-dev`) into
a new timestamped release under `/srv/curodav/releases/`, atomically swaps
the `current` symlink to it, restarts the service, and health-checks it
over HTTP. If the health check fails, it swaps `current` back to the
previous release, restarts again, and exits non-zero — the bad release
never stays live. Releases beyond the last 5 are pruned automatically.
Config in `shared/.env` and data in `shared/data/` live outside every
release directory, so neither is touched by a swap.

#### Continuous deployment

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs
`sudo curodav-ctl update` over SSH on every push to `main`, using the
`LXC_IP`, `LXC_USER`, and `SSH_KEY` repo secrets.
[`.github/workflows/rollback.yml`](.github/workflows/rollback.yml) is a
manual (`workflow_dispatch`) escape hatch that swaps `current` back to
`previous` on demand — unlike `update`'s automatic rollback, it doesn't
health-check first, so use it only to undo a deploy that's already known
to be broken.

#### Removing

```bash
sudo curodav-ctl remove
```

Stops and disables the service, deletes the unit file, removes the
`curodav` system user, and wipes `/srv/curodav` (all releases and data) —
after a `type 'yes'` confirmation prompt.

### Security note (read this before exposing the app to a network)

The login screen (from the one-time setup page above) only stops someone
from *using* the app without your password — it does not encrypt the
connection. Browser-to-server traffic is plain HTTP unless something in
front of the app adds TLS. Two supported ways to do that safely:

- **Tailscale (recommended for most people)** — a free VPN that gives your
  server a private address only your own devices can reach. Nothing about
  the app is exposed to the public internet at all; you don't need a
  domain name or a certificate. Install it on the server and on your phone/
  laptop, then reach the app at its Tailscale address instead of a public
  IP.
- **A public domain with TLS** — needed if you want CalDAV/CardDAV sync to
  reach your phone from outside your home network (see
  [Connecting your phone](#connecting-your-phone-caldavcarddav) below,
  which walks through Cloudflare Tunnel — no port-forwarding or manual
  certificates required).

Don't just forward port 8000 on your home router to the open internet
without one of the above — the app has no rate-limit/lockout beyond a
basic 5-attempts-per-15-minutes login throttle, and no TLS of its own.

### Connecting your phone (CalDAV/CardDAV)

Syncing your calendar/tasks/contacts to your phone's native apps needs two
things: **Radicale** (the sync server the app talks to) installed and
running, and a CalDAV/CardDAV client app on the phone — **DAVx5** (Android,
free/open-source) is the one this project is built and tested against;
iOS can connect to the same Radicale server using its built-in
Settings > Calendar/Contacts "Add Account" screen instead.

If you only want sync between the app and *itself* (i.e. you're fine using
the app through a browser and don't need a separate phone calendar app),
you can skip this section — Radicale isn't required for the app to work.

For phone sync reachable from outside your home network, the supported
path is Cloudflare Tunnel (no port-forwarding, no certificates to renew)
plus a real Radicale install with a password — full step-by-step
instructions, including the exact fields to enter into DAVx5, are in
[`deploy/README.md`](deploy/README.md). If your phone is on the same
network/Tailscale as the server, you can point DAVx5 directly at
Radicale's local address instead and skip the tunnel setup entirely.

### Troubleshooting

- **Can't reach the app after install.** Check the service is actually
  running: `sudo systemctl status curodav`. Logs: `sudo journalctl -u
  curodav -f`.
- **Update seemed to fail / site is down after `curodav-ctl update`.** It
  should have already rolled itself back — re-check `sudo systemctl status
  curodav`. If it's still down, `sudo journalctl -u curodav -n 100` shows
  what the last release logged before failing its health check.
- **Forgot the login password.** There's no self-service password reset
  yet, and no admin-only bypass — the only way back in is clearing the
  stored account directly from the database (`sqlite3
  /srv/curodav/shared/data/cache.sqlite "DELETE FROM app_meta WHERE key IN
  ('auth_username','auth_password_hash');"`, then `sudo systemctl restart
  curodav`), which forces the one-time `/setup` page to run again. This
  does not touch your calendar/task/contact data — only the stored login.
  See [`documentation/features/auth.md`](documentation/features/auth.md)
  for the full auth model.
- **Something else.** Check
  [`documentation/webapp.md`](documentation/webapp.md)'s "Known gaps"
  section, or open a GitHub issue.

## Where docs live

All project documentation lives under [`documentation/`](documentation/README.md),
organized by state, not by history:

| Doc | What it is |
|---|---|
| [`documentation/plans/STATE.md`](documentation/plans/STATE.md) | **Start here.** Current position on the roadmap, the next slice, and how to run a low-token session. Read only this at session start |
| [`documentation/features/README.md`](documentation/features/README.md) | Tour of what you can do today; links each area to its technical doc |
| [`documentation/features/architecture.md`](documentation/features/architecture.md) | The rulebook — data model, layering, design system, how a feature gets in. **Read this before touching code** |
| [`documentation/CODE_READING_GUIDE.md`](documentation/CODE_READING_GUIDE.md) | Plain-language guide to how files are structured and named, for editing the code yourself |
| [`documentation/CLEAN_CODE_GUIDE.md`](documentation/CLEAN_CODE_GUIDE.md) | Honest critique of what hurts readability today (giant files, history-as-comments) + rules for writing cleaner code going forward |
| [`documentation/CODING_STANDARDS.md`](documentation/CODING_STANDARDS.md) | Reference for naming files/functions/variables and where comments belong (file/class/function/inline) and how much |
| [`documentation/UI_CONSISTENCY_GUIDE.md`](documentation/UI_CONSISTENCY_GUIDE.md) | One canonical pattern per UI piece — cards, buttons, forms, tables, modals, tags, toolbars, empty states — and the "ask before inventing a new one" rule |
| [`documentation/SETTINGS_UI_GUIDE.md`](documentation/SETTINGS_UI_GUIDE.md) | Settings-specific canon: which layout for preferences vs. managed records vs. logs, and a reorg proposal for Advanced/Data health/Sync conflicts |
| [`documentation/plans/roadmap.md`](documentation/plans/roadmap.md) | The single build order across all open work, phased by release |
| [`documentation/plans/open-priority.md`](documentation/plans/open-priority.md) | Open work that reshapes the architecture/presentation (the rework) |
| [`documentation/plans/open.md`](documentation/plans/open.md) | Open work that is low-priority or app-local |
| [`documentation/plans/abandoned.md`](documentation/plans/abandoned.md) | What was deliberately cut or superseded, and why — plus the versioning/phase history |
| [`documentation/webapp.md`](documentation/webapp.md) | The webapp subproject's own README — dev setup, running the pieces separately, env vars |

The distinction matters: `documentation/features/` describes shipped behavior,
`documentation/plans/` tracks what hasn't shipped yet, and
`documentation/plans/abandoned.md` records why things won't come back without
being re-litigated.

## Versioning

Versions track the phases the app has gone through, not semantic versioning: a
`0.x` version was a development phase, `x.0` is a full release, and minor
releases within a major version are numbered `1.1` … `1.9`. The app is at
**1.9.0**; the next full release, once all roadmap work is implemented, is
**2.0**. The full phase table (0.1 → 1.0) is in
[`documentation/plans/abandoned.md`](documentation/plans/abandoned.md); the
release order is in [`documentation/plans/roadmap.md`](documentation/plans/roadmap.md).
