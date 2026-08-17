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
  and the versioning rules are in [`plans/abandoned.md`](plans/abandoned.md).

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
features/    Outcome documentation — what the current app actually does
plans/       Planning — see "Where docs live" below
pyproject.toml / uv.lock   uv workspace
```

## Getting started

```bash
cd webapp
./run.sh                 # -> http://127.0.0.1:8000
```

That's the one-command path: it runs `uv sync`, starts a throwaway dev Radicale
instance, then the app, and stops Radicale on Ctrl+C. See
[`webapp/README.md`](webapp/README.md) for running the pieces separately and for
deployment notes.

Run the test suite:

```bash
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q
```

All tests green or a change isn't done.

## Deployment

Two one-command installers run the app on a real server — a native systemd
service or Docker Compose — with an optional Radicale (CalDAV/CardDAV) server
for phone sync:

```bash
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/systemd/install.sh)
sudo bash <(curl -LsSf https://github.com/istorie-petru/curodav/raw/main/deploy/docker/install.sh) --with-radicale
```

See [`deploy/README.md`](deploy/README.md) for both deploy paths, the
`/etc/curodav` config, and the update/uninstall commands. Note: the app has
no authentication of its own — reach it over a trusted network (Tailscale)
or behind an authenticated reverse proxy.

## Where docs live

The repo's documentation is organized by state, not by history:

| Doc | What it is |
|---|---|
| [`plans/STATE.md`](plans/STATE.md) | **Start here.** Current position on the roadmap, the next slice, and how to run a low-token session. Read only this at session start |
| [`features/README.md`](features/README.md) | Tour of what you can do today; links each area to its technical doc |
| [`features/architecture.md`](features/architecture.md) | The rulebook — data model, layering, design system, how a feature gets in. **Read this before touching code** |
| [`CODE_READING_GUIDE.md`](CODE_READING_GUIDE.md) | Plain-language guide to how files are structured and named, for editing the code yourself |
| [`CLEAN_CODE_GUIDE.md`](CLEAN_CODE_GUIDE.md) | Honest critique of what hurts readability today (giant files, history-as-comments) + rules for writing cleaner code going forward |
| [`CODING_STANDARDS.md`](CODING_STANDARDS.md) | Reference for naming files/functions/variables and where comments belong (file/class/function/inline) and how much |
| [`UI_CONSISTENCY_GUIDE.md`](UI_CONSISTENCY_GUIDE.md) | One canonical pattern per UI piece — cards, buttons, forms, tables, modals, tags, toolbars, empty states — and the "ask before inventing a new one" rule |
| [`SETTINGS_UI_GUIDE.md`](SETTINGS_UI_GUIDE.md) | Settings-specific canon: which layout for preferences vs. managed records vs. logs, and a reorg proposal for Advanced/Data health/Sync conflicts |
| [`plans/roadmap.md`](plans/roadmap.md) | The single build order across all open work, phased by release |
| [`plans/open-priority.md`](plans/open-priority.md) | Open work that reshapes the architecture/presentation (the rework) |
| [`plans/open.md`](plans/open.md) | Open work that is low-priority or app-local |
| [`plans/abandoned.md`](plans/abandoned.md) | What was deliberately cut or superseded, and why — plus the versioning/phase history |

The distinction matters: `features/` describes shipped behavior, `plans/` tracks
what hasn't shipped yet, and `plans/abandoned.md` records why things won't come
back without being re-litigated.

## Versioning

Versions track the phases the app has gone through, not semantic versioning: a
`0.x` version was a development phase, `x.0` is a full release, and minor
releases within a major version are numbered `1.1` … `1.9`. The app is at
**1.9.0**; the next full release, once all roadmap work is implemented, is
**2.0**. The full phase table (0.1 → 1.0) is in
[`plans/abandoned.md`](plans/abandoned.md); the release order is in
[`plans/roadmap.md`](plans/roadmap.md).
