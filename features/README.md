# Features

This folder is the **outcome documentation for the current webapp** (`webapp/`).
Each doc describes one feature area as it actually works today — not
aspirations, not history. For how the code is structured and the rules for
adding features, read [`architecture.md`](architecture.md) first. For what's
been abandoned and what's still open, see `plans/abandoned.md` and
`plans/open.md`.

## What this app is

A **personal organizer / PWA dashboard** for one person (single-user by
design): a home dashboard with widgets, a full calendar, tasks, a class
timetable, habit tracking, contacts, and a universal label system that
organizes all of it. It runs self-hosted and can sync your data to your phone
through an open standard (CalDAV/CardDAV) — no cloud account, no subscription.

## The stack

| Layer | Technology |
|---|---|
| App framework | **FastAPI** (Python 3.12+) + **Uvicorn** |
| Server-side rendering | **Jinja2** templates (pages render as HTML; JS adds interactivity on top) |
| Database | **SQLite** (a single local file) |
| Sync backend | **Radicale** (self-hosted CalDAV/CardDAV server) + the `caldav` / `icalendar` / `vobject` libraries |
| Frontend | Vanilla **JavaScript + CSS** (Material 3 design system) — no framework, no build step |
| Testing | **pytest** + httpx |

All of it runs from one `webapp/` tree with no external services beyond the
optional Radicale sync server. See [`architecture.md`](architecture.md) for how
these pieces fit together.

## What you can do here (plain-language tour)

- **Dashboard** — your home page: widgets you can add, remove, move, stack,
  and configure (today's agenda, the week ahead, overdue tasks, mini calendar,
  habit check-ins, project progress, contacts, and more), plus a greeting, a
  per-page cover banner, and a quick-add box for tasks and events.
- **Calendar** — your events in month, 4-week, week, or day views; drag to
  move/resize, repeat on a schedule, set reminders, and link events to related
  tasks.
- **Tasks** — to-dos as a sortable table, a kanban board, or a timeline/Gantt;
  statuses, priorities, bulk edits, recurring to-dos with streaks, subtasks,
  and links to related events.
- **Contacts** — people you know with photos, phones, emails, addresses, and
  notes; one click to call or email.
- **Labels & Spaces** — one consistent way to organize everything: tag any
  task, event, or contact; labels become filterable pages, and "Spaces" group
  labels into projects with their own dashboard, course info, and homework
  table.
- **Schedule** — your class timetable by day of week and week parity; it
  turns into real calendar events automatically, flags conflicts, counts
  credits, and links each class to its professor contact.
- **Habits** — simple daily check-ins with heatmaps and streaks, tracked
  locally and also usable as a special task view.
- **Published lists** — pick a label filter (say, "University, not archived")
  and get a real calendar/contacts URL your phone can subscribe to.
- **Settings** — appearance, time formats, profile, backup & restore, data
  purge, and more.
- **Export & backup** — your data out as standard ICS/CSV/VCF, a full JSON
  backup, or back in via import/restore.

## Per-feature docs

The table below maps each area to its detailed doc. The docs are written
deliberately technical (endpoints, models, edge cases) so they stay an accurate
reference for development; the tour above is the plain-language version.

| Doc | Covers |
|---|---|
| [`architecture.md`](architecture.md) | The "how it works" + rulebook — data model, layering, M3, nav, lifecycle |
| [`dashboard.md`](dashboard.md) | Widget grid, 11 widget types, Customize/Widget Builder, quick-add, greeting, banner |
| [`calendar.md`](calendar.md) | Month/4-week/week/day views, recurrence, drag interactions, event CRUD, relations |
| [`tasks.md`](tasks.md) | Table/board/timeline views, statuses/priorities, bulk actions, recurring tasks, relations |
| [`contacts.md`](contacts.md) | Contact list/detail/form, fields, photo upload, professor linking |
| [`labels.md`](labels.md) | The one organizing mechanism — manage page, generated Space/project pages, modules |
| [`schedule.md`](schedule.md) | Class timetable → real events, table/weekly-grid views, holidays, settings |
| [`habits.md`](habits.md) | Local habit tracking, heatmaps, streaks, habits-as-tasks view |
| [`published-lists.md`](published-lists.md) | Radicale's only role — label-filtered CalDAV/CardDAV collections |
| [`settings.md`](settings.md) | Hub + General/Appearance/Labels/Published lists/Advanced |
| [`export.md`](export.md) | ICS/CSV/VCF exports, JSON backup, import/restore |
| [`banners.md`](banners.md) | Per-page cover images |
| [`design-system.md`](design-system.md) | M3 tokens, theming, shared input patterns, favicon |

## Workflow

These docs are written or updated once a phase in `plans/` is finished — they
describe outcomes, not intentions. If you're about to start work, check
`plans/open.md` first for whether it's already scoped there.

## Known gaps

Noted for honesty, not as a promise to fix: **no global search / command
palette** (per-view search only); **no file attachments** (beyond contact
photos); **no generic links/backlinks graph** (only curated event↔task
relations); Published Lists are **read-only** sync today. All four were
deliberate decisions — see `plans/abandoned.md`. (Global search across tasks,
events, and contacts is now scoped in `plans/open.md`.)
