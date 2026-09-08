# Command Center — Architecture & Feature Rulebook

Authoritative "how this codebase works" + "how a feature gets in". Read this before
touching any of the code in `webapp/` — the sole client. If a decision here
conflicts with something you remember from an older build, this document wins;
earlier reasoning that's since been superseded lives in `plans/abandoned.md` (the
now-deleted `desktop/` app's history and everything deliberately cut) and
`plans/open.md` (known open risks). This folder (`features/`) is the description
of what the current webapp actually does.

The guiding mandate, restated everywhere: **Tasks / Events / Contacts are the
primary objects. A label is a name they point at, not an entity with a lifecycle.
Everything else — Spaces, Projects, Schedule modules, Published Lists — is a
behavior over that pool, not a new kind of object.** And: *prefer deleting over
extending; never grow a compatibility layer.*

---

## 1. The data model

### 1.1 The universal pool — plain SQL, no Radicale relationship

`tasks`, `events`, `contacts` are the primary objects, one universal pool per
type (not partitioned by "which calendar/list/addressbook it lives in" — creating
a task never requires picking a list). These are **plain SQL rows, full stop** —
no `href`/`etag`/`calendar_path` against any Radicale collection, no invisible
default collection. The app is a single central server that the web UI is the
only access path to; there's no multi-device-via-Radicale problem to solve for
the base pool. Every row still keeps enough shape (title/dates/location/raw
fields) to serialize to a valid VEVENT/VTODO/VCARD on demand
(`src/ical_rows.py`, `src/vcard_rows.py`) — for export, and for §1.3's Published
Lists — but nothing about base storage reads from or writes to Radicale.

- **`habits`/`habit_entries`** stay their own local-only pair (unaffected by the
  pool/label model beyond gaining `object_labels` rows the same way tasks do).
- **`schedule_classes`/`schedule_holidays`/`schedule_settings`** are local-only
  modules, not synced objects — see §1.4.

### 1.2 Labels — the one organizing mechanism, not an entity

Everything that used to be "which calendar/list/tag/project/space is this in" is
now one mechanism:

- **`object_labels(object_type, object_id, label_name)`** — the only join table.
  `label_name` is a natural key (globally unique text), not a surrogate id a row
  holds a hard FK into. A label isn't created or deleted as its own workflow;
  "deleting" a label just means nothing points at it anymore.
- **`label_config(label_name, color, icon, description, parent_name,
  generate_space, enabled_modules_json, dashboard_preset_json)`** — optional,
  sparse config keyed by name. A label with zero rows here still fully works
  (default color, no generated page, shows up in "manage labels" purely because
  `object_labels` mentions it). No delete-cascade relationship to anything.
- Labels nest via `parent_name` for organization; a label with `generate_space=true`
  gets a generated page at `/labels/{name}` (`routers/labels.py`), aggregating by
  **direct** `object_labels` membership only — never transitive through
  `parent_name`.
- `label_modules.py`'s flat `enabled_modules` set (`schedule`/`grades`/`homework`/
  `tasks`/`events`/`contacts`) lets a label's generated page gate which sections
  render (e.g. a course label shows Course info/Homework; a plain label doesn't) —
  not a plugin registry, just a checklist a template branches on. The widget grid
  is deliberately never gated by it (widgets already have their own per-widget
  filters).
- One known open risk worth knowing before relying on it further: `project_label_for`
  picks "the" project label for a schedule class/habit heuristically
  (alphabetically, if more than one non-Space label is attached) — see
  `plans/open.md`.

### 1.3 Radicale's role — narrowed to one thing: Published Lists

Radicale (CalDAV/CardDAV) is **not** the source of truth for the base pool — see
§1.1. It's used for exactly one feature: **Published Lists**
(`published_lists` table, `src/published_lists.py`, `routers/published_lists.py`,
under Settings). A List is a Settings-created, named, saved label filter
(`{"all": [...], "any": [...], "none": [...]}` over label names) that the app
materializes into a real Radicale collection and serves a syncable URL for — e.g.
so a phone calendar app can subscribe to just `University` events without seeing
everything. `sync_direction` is `read_only` today (the column exists for a future
two-way mode, unimplemented); materialization is diff-based
(`materialize(conn, bridge, list_row)`) and runs on a periodic background tick
(`sync.py`'s `full_refresh`), not on every write. Deleting a List tears down both
the DB row and the real Radicale collection — the one genuine "delete" action
anywhere in this data model, since a List is a derived collection, not a label.
`src/caldav_bridge.py` is the only thing that ever talks to Radicale, and only
for this.

### 1.4 Local-only modules

Everything that isn't a synced-shape object or a label is a plain local table,
keyed into the pool only via `object_labels`:

- **Schedule** (`schedule_classes`/`schedule_holidays`/`schedule_settings`) — a
  schedule-generated class event lands directly in the universal `events` pool,
  tagged with the course's label (and `University` if it should also appear there
  — applied explicitly, never inherited).
- **`task_checklist_items`**, **`task_completions`** — behavior records local to
  one task, never their own graph.

**Rule:** if a new feature's data can be derived from the pool, or is a
preference/annotation/config, it's local-only. If it genuinely needs a new synced
object type, it must be shaped to round-trip through a real VEVENT/VTODO/VCARD
property (no made-up `X-` properties) — extend `tasks`/`events`/`contacts`, don't
invent a parallel synced store.

### 1.5 What's deliberately not here

Several capabilities the previous (`desktop/`) client had were consciously not
carried over when it was deleted, not silent gaps: **file attachments** (a
content-addressed blob store) and **associative links/backlinks** (a
`blocks`/`references`/`mentions`/`related` graph beyond structural parent/child;
webapp only has the curated event↔task relations feature). WebDAV is opt-in
Published Lists only (§1.3), not a mounted file tree; there's no global
search/command palette (never worked in either app). Generic Databases and the
Grades tracker were also removed. See `plans/abandoned.md` for the full audit and
the decisions — don't rebuild these without re-reading that first.

---

## 2. Layering / how a feature is wired

A feature is a vertical slice. Build it in this order and it fits the rest:

1. **`db.py`** — schema + accessor functions only. No HTTP, no templates, no
   rendering. Functions take `(conn, ...)`, name the operation they perform,
   `commit()` internally, and read/write rows as plain dicts.
2. **`src/<feature>.py`** (optional) — pure logic with no I/O (e.g.
   `published_lists.py::evaluate_label_filter`, `habit_heatmap.py::streaks`,
   grid/calendar/recurrence math). Unit-test these in isolation; never put this
   logic inline in a router where a test can't reach it without a request.
3. **`routers/<feature>.py`** — the HTTP surface. A module-level `APIRouter` with a
   `prefix`, `Depends(get_db)` for reads/most writes and `Depends(get_bridge)` only
   where a Published List is materialized (§1.3) — everything else never touches
   the bridge. Renders via `TemplateResponse`; every write returns a `303` redirect
   back to the page the user came from.
4. **`templates/<feature>.html`** — server-rendered Jinja extending `base.html`.
   Use the `icon()`/`avatar()` globals, the `.card`/`.btn`/`.field`/`.table`
   primitives, and M3 tokens (never hard-coded colors — see §3). Make it
   **modal-capable** when it's a create/edit surface: wrap the fragment in
   `#modal-target` so the same template works as a full page and as the in-place
   dialog `modal.js` fetches.
5. **`static/<feature>.js`** (optional) — progressive enhancement only. The page
   must be fully usable without JS; JS adds drag/resize/preview/toast behavior.

**Rule:** a feature is one folder slice: `db.py` accessor + optional pure module +
router + template + optional JS + its own `tests/test_<feature>.py`. Don't spread
a feature across unrelated files; don't bolt a behavior onto an unrelated screen's
template.

---

## 3. Look & feel — the Material You (M3) contract

The app is styled from one token file, `webapp/src/static/style.css` (reworked
2026-08-04 into a full MD3 pass: elevation system, tonal surfaces, MD3 shape
tokens, ripple feedback, FAB, mobile bottom nav — see that file's own header
comment for the full file organization). The contract:

- **Colors come from M3 role tokens.** Components read `--md-*` roles directly or
  the legacy aliases (`--accent`, `--bg-base`, `--fg-*`, `--control-*`, ...) that
  resolve to them. A template/selector must **never** hard-code a hex/`rgb()`
  color, except:
  - the fixed `.cal-*` calendar palette and `.tag-*`/`.pill-*` label palette —
    these are *user-chosen identity colors* that must look identical in light and
    dark. Everything that reads them reads the *variable*, not the hex.
  - The current M3 palette is a static baseline seeded `#6750A4` (light/dark pair
    in `:root`/`[data-theme="dark"]`). Dynamic wallpaper-sourced color is
    deliberately deferred.
- **Shape:** buttons and the segmented control are full-shape (pill); cards are
  the large-surface (~12–16px) radius; dialogs are 28px.
- **Theming is a `data-theme` attribute** toggled by the shell button; every
  component must provide both light and dark values via the pair of token blocks.
- **Density wins.** This is a data-dense personal hub: body copy ~13px, compact
  tables, a 4pt spacing scale (`--space-*`). Don't sprinkle generous spacing "to
  look prettier" — keep rhythm.
- **One canonical pattern per UI piece, app-wide** — cards, buttons, forms,
  tables/lists, modals, tags/pills, toolbars, empty states, icons. Settings
  gets the plainest version of every one of them, zero exceptions. See
  [`UI_CONSISTENCY_GUIDE.md`](../UI_CONSISTENCY_GUIDE.md) — a new variant of
  any of these is a rare exception that must be asked about before being
  built, not after.

---

## 4. Navigation & shell

Six destinations in the tabbar (`webapp/src/templates/base.html`): **Home**,
**Calendar**, **Tasks**, **Schedule**, **Contacts**, **Settings**. On desktop the
shell is a sticky top app bar + a horizontal tab bar; on ≤720px the tab bar
becomes a fixed bottom bar (MD3 bottom navigation). Settings is a hub that
organizes the manage pages (Labels, Schedule, Published Lists, Contacts, Habits)
rather than duplicating any of their forms. A generated label page
(`/labels/{name}`, §1.2) is reached from wherever it's linked, not from the tab
bar.

**Rule:** a new screen hangs off an existing tab, not a new one. To reach it from
Settings, add a row to `routers/settings.py`'s group list, not a new nav
destination.

---

## 5. Feature lifecycle & testing

1. Write the plan change first as a phase with an acceptance line ("what must be
   true → tested") — see the workflow in `plans/open.md`. Implement in that
   phase's slice. Mark it done with a note of what shipped and the test count.
2. Add tests as `webapp/tests/test_phaseN_<feature>.py` (a `conn` fixture from
   `tmp_path`, a `FakeBridge` only for the Published-List-materialization path,
   router functions called directly with `conn=conn`). Test the *acceptance*, not
   the plumbing: seed → act → assert the user-observable result and the DB
   round-trip.
3. Run the full suite:
   `cd webapp && PYTHONPATH=src /home/peter/Claude/Projects/Dashboard/.venv/bin/python -m pytest -q`.
   All green or the change isn't done. Test cleanup is part of every phase, not a
   separate pass — deleting a table/router/feature deletes or rewrites the tests
   that exercised it in the same phase, no orphaned test files.
4. Once shipped, describe the outcome here in `features/` (this folder is the
   webapp's outcome documentation).

**Admission bar:** if the feature can't state in one line what it makes *true* for
the user, and whether its data is pool (tasks/events/contacts), label, or local-
module, it isn't ready. If it wants a new synced object type, it must justify why
it can't be a label or a field on an existing pool row.

---

## 6. Don't / never

- **No compatibility layer.** Migrate and delete the superseded path; don't keep
  old code paths alive alongside new ones. This is how the label-space rework
  itself proceeded and how `desktop/` was ultimately deleted outright rather than
  kept as a parallel client (see `plans/abandoned.md`).
- **Don't reintroduce collection partitioning.** No `calendar_path`/`list_path`/
  `addressbook_path`-shaped column on `tasks`/`events`/`contacts` — organization
  is 100% by label.
- **Don't give a label a delete endpoint or a lifecycle.** A label empties itself
  naturally once nothing points at it; don't build "delete label" as its own
  workflow (`routers/labels.py` deliberately has no delete route).
- **Don't grow the nav.** New screens attach to an existing tab or Settings' hub.
- **Don't store derived values** (e.g. a computed grade average) — compute on read.
- **Don't hard-code colors** where M3 tokens already exist.
- **Never commit secrets** (Radicale creds come from env/`.env`, `src/config.py`).

---

## 7. The rules, condensed (a checklist)

- [ ] Data: pool object (task/event/contact), label (`object_labels`/
      `label_config`), or local module? Never invent a fourth kind without
      justifying it against §1.4's rule.
- [ ] One folder slice: db + optional pure module + router + template + static JS
      + its own test file.
- [ ] Router returns 303 redirects on writes; renders data-capable templates;
      only touches `Depends(get_bridge)` for Published-List materialization.
- [ ] Template: extends `base.html`, uses `icon()`/`avatar()`, M3 tokens only
      (or `.cal-*`/`.tag-*`), full-page + `#modal-target` when it's a form.
- [ ] JS is progressive enhancement.
- [ ] No new top-level nav destination; reaches through Settings' hub instead.
- [ ] Tests assert the acceptance, and all pass via the single pytest command.
- [ ] Work-in-progress phases tracked in `plans/open.md`; no orphaned imports,
      no hard-coded colors.
