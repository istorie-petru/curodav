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
- **The current version is 1.9.0.** The app's history (phases 0.1 → 1.0)
  and the versioning rules are in [`plans/abandoned.md`](documentation/plans/abandoned.md).

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

```bash
cd webapp
./run.sh                 # -> http://127.0.0.1:8000
```

That's the one-command path: it runs `uv sync`, starts a throwaway dev Radicale
instance, then the app, and stops Radicale on Ctrl+C. See
[`documentation/webapp.md`](documentation/webapp.md) for running the pieces
separately and for deployment notes.

Run the test suite:

```bash
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q
```

All tests green or a change isn't done.

## Deployment

The app deploys to a plain Debian 12 host (a Proxmox LXC, a VM, bare metal —
no Docker) as a systemd service, via [`scripts/curodav-ctl`](scripts/curodav-ctl).
Each deploy builds a fresh, isolated release and swaps a symlink; nothing is
edited in place, and a failed deploy rolls itself back automatically.

### First install (fresh host)

`curodav-ctl` ships inside this repo rather than a separate infra repo, and
it's self-aware of where it came from — it never has a repo URL hardcoded
into it. That's why bootstrapping means cloning the repo first and running
the script *from inside that clone*, not curl-ing the raw file on its own:

```bash
git clone https://github.com/istorie-petru/curodav.git /tmp/bootstrap
sudo /tmp/bootstrap/scripts/curodav-ctl install
rm -rf /tmp/bootstrap
```

`install` reads its own clone's `git remote get-url origin` to learn the
repo URL, then:

1. Creates the `curodav` system user and the `/srv/curodav` layout
   (`releases/`, `shared/`, `shared/data/`).
2. Persists the detected repo URL to `/srv/curodav/shared/repo_url`, and
   copies itself to `/usr/local/bin/curodav-ctl` — from this point on the
   `/tmp/bootstrap` clone is disposable.
3. Generates `/srv/curodav/shared/.env` with a random `CC_AUTH_SECRET`
   (`openssl rand`) and sane defaults; every other setting (Radicale sync,
   a pre-provisioned login, `CC_DB_PATH`, …) is documented inline in that
   file and left commented out.
4. Installs the `curodav.service` systemd unit.
5. Runs a full `update` (below) to produce the first release, then enables
   and starts the service.

Deploying to a fork, or from a separate infra repo instead of in-tree, works
the same way but with an explicit override: `sudo CURODAV_REPO_URL=<url> -E
curodav-ctl install`.

### Updating (every deploy after that)

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

### Continuous deployment

[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) runs
`sudo curodav-ctl update` over SSH on every push to `main`, using the
`LXC_IP`, `LXC_USER`, and `SSH_KEY` repo secrets.
[`.github/workflows/rollback.yml`](.github/workflows/rollback.yml) is a
manual (`workflow_dispatch`) escape hatch that swaps `current` back to
`previous` on demand — unlike `update`'s automatic rollback, it doesn't
health-check first, so use it only to undo a deploy that's already known
to be broken.

### Removing

```bash
sudo curodav-ctl remove
```

Stops and disables the service, deletes the unit file, removes the
`curodav` system user, and wipes `/srv/curodav` (all releases and data) —
after a `type 'yes'` confirmation prompt.

Note: the app has no authentication of its own beyond the optional
`CC_AUTH_USERNAME`/`CC_AUTH_PASSWORD` pair — reach it over a trusted
network (Tailscale) or behind an authenticated reverse proxy.

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
