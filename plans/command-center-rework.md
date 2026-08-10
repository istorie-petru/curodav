# Command Center Rework — Space & Project-centric redesign

**Status:** Authoritative plan for the webapp rework · logged 2026-08-03
**Scope:** The **webapp** (`webapp/`) only. The desktop client (`desktop/`) is out of
scope and its docs are no longer tracked here.
**Supersedes (all deleted 2026-08-03):** `spaces-home-pipeline.md`,
`spaces-v2-university-material.md`, `webapp-action-pipelines-audit.md`,
`webapp-usability-and-davx5-rollout.md`, `tasks-ux-rework.md`,
`calendar-and-tasks-rework.md`, `design-alignment.md`,
`apple-vs-google-calendar-plan.md`, `expansion-deferred.md`, and the entire
desktop-focused `systems/` folder (`architecture.md`, `decisions-log.md`).
Durable threads from those docs (mobile hosting, contact archiving, schedule
parity) are folded into the relevant sections below; everything else is
superseded by this document.

This document is written to hash out the endpoint: what the app is *going to
be*, what gets deleted, and the concrete phases to get there. It is intentionally
opinionated. When a phase is implemented, the step-by-step agent prompt should
be derived from the phase's section here, and the outcome folded into
`webapp/README.md` / `features/` per the `plans/README.md` workflow.

---

## 0. The mandate

Stop improving the current app. Rebuild it around one idea:

> **Spaces organize life. Projects organize work inside Spaces. Tasks, Events,
> and Contacts are the primary data objects. Everything else is a behavior
> built on top of those.**

For every feature that exists today, ask: does it fit this philosophy? If not,
remove it. Never grow a compatibility layer to preserve an old assumption. Prefer
deleting code over extending it. Opinionated workflows over endless
customization. A significantly better small app over a sprawling generic one.

---

## 1. Critical evaluation of the current webapp

The webapp today (`webapp/`) is a FastAPI, server-rendered HTML app with a
SQLite cache over a Radicale (CalDAV/CardDAV) source of truth. That foundation is
right and stays. Since 2026-07-31 it accreted eleven "phases" of unrelated
generic machinery. Assessment:

| Current system | Files/tables | Verdict | Why |
|---|---|---|---|
| **Radicale source of truth + SQLite cache** | `caldav_bridge.py`, `sync.py`, `db.py` core | **Keep** | Correct data philosophy — portable, no vendor lock-in. |
| Tasks, Events, Contacts (CalDAV/CardDAV rows) | `tasks`, `events`, `contacts` | **Keep** | Core objects. |
| Calendars, task lists, addressbooks (collections) | `calendars`, `task_lists`, `addressbooks` | **Keep, reframe** | These are the CalDAV collections projects/spaces organize. |
| Schedule (university timetable) | `schedule_classes/holidays/settings`, `schedule.py` | **Keep, re-scope** | Becomes the Education space's scheduling engine. |
| **Projects + project groups ("Spaces")** | `projects`, `project_groups`, `routers/projects.py` | **Rework** | Right instinct, wrong naming/depth. `project_groups` is already 90% of a Space but has no module config, no template, and is wedged under "Projects" in settings instead of being first-class. |
| **Dashboard widget system** | `dashboard_widgets`, `WIDGET_TYPES`, Source/View/Range, stacking, `dashboard.py` (≈1100 lines) | **Removed** | The anti-philosophy: an endless customization engine when the mandate says *one excellent, fixed dashboard*. This is the single biggest delete in the rework. |
| **Generic databases** | `databases/columns/rows`, `formula_engine.py`, `routers/databases.py` | **Removed** | Notion-clone generality. The one real need (grades) gets a dedicated Education module. |
| **Habits as a first-class object** | `habits`, `habit_entries`, `routers/habits.py`, habit heatmap | **Removed → merged into Tasks** | A habit is a recurring task + completion history. Not an object. |
| **Tags** global registry + groups | `tags`, `tag_groups` | **Keep** | Contacts grouping + cross-cutting filter; stays. |
| Notes, attachments, arbitrary object graph | not in webapp | **N/A** | Never built here; storage/notes are external-tool problems the app must not re-solve. |
| Navigation: 6-item scrollable top tabbar | `base.html` | **Rework** | Becomes 4 top items on desktop, bottom nav on mobile. |
| Settings | `settings.py`, many manage pages | **Rework** | Global / Space / Project division of labor. |

Why the dashboard widget system is *removed*, not kept: it costs a schema table,
a ~1600-line router, several templates (`_widget_*.html`), two drag-resize JS
handlers, a Source/View/Range picker, and a preview endpoint — all so the user
can recombine a handful of slices. "One excellent dashboard beats endless
customization." The fixed dashboard renders the same few things with a
fraction of the code, and every removed feature (habits, databases) also
*starves* the widget-machine of its reason to exist.

Why habits "are" a recurring task: a habit has a definition (frequency) and a
log. That is precisely a recurring VTODO plus a per-instance completion log. Two
unmerged concepts today (habits table vs tasks.recurrence) become one.

---

## 2. Core objects (the entire data model)

| Object | Storage | Notes |
|---|---|---|
| **Space** | `spaces` (replaces `project_groups`) | Highest level. Has a template (kind), identity, module set, fixed dashboard scope. |
| **Project** | `projects`, now `space_uid` FK | Groups work inside a space; inherits behavior from the space's template. |
| **Task** | `tasks` (VTODO), + `task_completions` | Recurring tasks (existing `recurrence`) replace habits; `task_completions` is the completion history. |
| **Event** | `events` (VEVENT) | Calendar item. |
| **Contact** | `contacts` (vCard) | Global. Grouped by tags; archive state built in. |
| **Settings** | — | Global / Space / Project division of labor; configured in-app, not a new data object. |

Rules that hold the model together:
- A **task/event lives in a list/calendar** (`tasks.list_path`, `events.calendar_path`); a **list/calendar belongs to a project** (`project_uid`); a **project belongs to a space** (`space_uid`). Three layers, no graph table.
- **Contacts are global.** No per-contact project column. A contact "belongs to" a space/project *by tag* (a tag name matching a project/space name), rendered as a saved filter.
- **No generic databases, no habits-as-entities, no dashboard_widgets, no object graph, no attachments.**
- Local-only tables are kept to the tiny set that has no CalDAV equivalent (`schedule_*`, `task_checklist_items`, tags registry, `task_completions`, `app_meta`).

---

## 3. Architecture

```
Browser (server-rendered HTML, no-JS-first)
        │ reads                              │ writes
        ▼                                    ▼
     SQLite cache ◄── full-refresh sync ─CalDavBridge──► Radicale
       (disposable mirror)                                (SOT, portability)
```

Unchanged. The rework only changes *what tables exist* and *how the front-end is
laid out*, not the sync backbone.

**Portability mandate (data philosophy):** the app owns as little as possible and
everything is exportable. Radicale already makes tasks/events/contacts portable
(CalDAV/CardDAV). Add:
- **ICS export** for events (and per-space calendar export).
- **CSV export** for tasks, contacts (and the grade table).
- **JSON export** for the JSON-only local tables (schedule, projects, spaces,
  tags), so nothing is trapped in this app's cache.

---

## 4. Navigation

- **Desktop — top nav:** `Dashboard · Calendar · Tasks · Settings` (4 items; theme
  toggle becomes a Settings). Removed: `Data` (was databases), `Habits`.
- **Mobile — bottom nav:** the same 4 items.
- **Spaces** intentionally are **not** in the nav. They are reached from the
  Dashboard's Spaces section (one tap from home).
- **Calendar** sub-nav keeps Month/Week/Day/Agenda; the Schedule and Contacts
  and Projects/Habits surfaces are reached from Settings + a Space/Project's own
  page, never as peers of the four core tabs.
- **Contacts:** reachable from Settings and from each Space/Project's
  contact-by-tag section (saved filter).

*Trade-off:* fewer permanent destinations. Benefit: every tab is a primary
verb (Do-this-today, When, Then, Configure) and the app's surface instantly maps
onto the mental model. Cost: accidental over-nesting; mitigated because Settings
use a consistent launcher and the breadcrumb Home › Space › Project is the sole
drill-down path.

---

## 5. Design system — Material You (M3)

Replace the hand-rolled flat-card custom UI with one mature design system.

- **Adopt Material Design 3 tokens** (color roles + `on`/`container` roles,
  elevation, shape, type scale) implemented in the existing `style.css` through
  CSS custom properties, keeping the manifest win: **all interaction stays
  server-rendered, no-JS-first HTML** (forms, inline edit), because that is the
  webapp's oldest and best constraint.
- **Light/dark** continue via `data-theme` + `prefers-color-scheme`; M3 dynamic
  color optional (derive a neutral M3 palette per theme; true dynamic color is a
  mobile-only flourish and not worth a host of contrast bugs).
- **Components:** one shared set — buttons, chips, cards, segmented control,
  dialog/sheet, app bar, bottom nav, FAB-as-quickadd — restyled to M3 but *not*
  swapped for a JS component framework (no `@material/web`; it would fight the
  server-rendered model and no-JS stance). Trade-off documented: adopting the
  *language* (tokens, elevation, principles) now, JS-heavy framework only if a
  true SPA/PWA for offline is later justified.

**Share the same component/token language on desktop nav and mobile bottom nav**
first-class: one `style.css` with breakpoints, not two skins.

---

## 6. Feature by feature

### 6.1 Dashboard (fixed layout, one Customize modal)

```
Desktop                          Mobile
┌───────────────────────────┐   ┌─────────────────────┐
│ Today Tasks   │ Month     │   │ Today Tasks         │
│               │           │   └─────────────────────┘
│               │ Week      │   │ Month Calendar       │
│               │ Agenda    │   └─────────────────────┘
│               │           │   │ Week Agenda          │
└───────────────┴───────────┘   └─────────────────────┘
│ Spaces (cards)              │     Spaces
└─────────────────────────────┘     ...
```

Fixed sizes and order by default, responsive but predictable — but **not** "no
customization": the whole grid is arranged through one **Customize modal**
(Phase 3/10, `/dashboard/customize`) over the existing widget machinery
(add/move/up/down/delete/stack-dissolve/Filters). No inline drag, no scattered
page controls — one surface, then the page renders read-only again.
Data:
- **Today Tasks** — overdue + due today, across all spaces (open only), with
  one quick-add + one inline complete.
- **Month Calendar** — mini month, busy-dots, tap a day → day view. Fixed.
- **Week Agenda** — next 7 days grouped by day (tasks + events). Fixed.
- **Spaces** — card per space, each with a per-space headline (progress summary
  and a one-tap Open).

### 6.2 Tasks (global) + recurring tasks

- Global Tasks page, with a **space → project → (multi-select)** and
  Upcoming/Completed/Archived filters (each independent, as today's already were;
  upgraded to add a space dimension + multi-select projects).
- Start date always defaults to today (kept); the Table / Kanban / Timeline views
  remain.
- **Recurring tasks replace habits.** A recurring VTODO (existing `recurrence`
  RRULE, surfaced as "Recurring") produces occurrences; tapping marks them done.
  Each completed instance appends to `task_completions(task_uid, due_date,
  completed_at)`.
- The **heatmap + streaks UI currently built for habits is kept** but fed from
  `task_completions`, and shown on a recurring task's detail — it is a view over
  completion history, not a separate object.
- Per the Directive: completed recurring instances *may* be cleaned automatically
  while preserving the `task_completions` history (history never deleted).

### 6.3 Calendar

- Global Calendar: Month/Week/Day/Agenda, multi-calendar visibility — kept.
- **Space-specific behavior** via the space's template:
  - **Personal**: that space's tasks and events, on the shared calendar.
  - **Education**: recurring class schedules (existing parity/odd-even weeks),
    homework deadlines, university events; the "next class in 5 days" countdown
    is computed from `schedule_classes` + parity.
- **Projects create independent events** — e.g. "Conference with Professor",
  which need not belong to any class. This is already possible (an event in any
  calendar under a project); the Education space just surfaces them.

### 6.4 Contacts (global)

- Delete the notion of many per-topic address books. Keep the global
  Active/Archived split (already built) and archive state = moving the vCard.
- **Lists become saved filters**, not containers: a "Friends" / "Work" screen is
  just a saved tag filter over the global contact pool. Reuse the tags machinery;
  normalize into one "Contacts" view with a filter bar (tags + archive).
- A contact's "spaces/projects" is derived from its tags (a tag equal to a
  project or space name) — rendered as self-links, no per-contact FK.
- Contacts on a Space/Project page are shown through that saved tag filter.

### 6.5 Spaces + templates

- Each space has a **kind/template**: `personal`, `professional`, `education`,
  or custom. The template is not hardcoded UI — it is a material preset that
  seeds:
  - which modules are on/off;
  - the space's fixed dashboard scope.
  - project behavior (Personal: tasks/events/contacts; Professional:
    kanban/timeline/milestones/contacts; Education:
    classes/schedule/homework/grades/professors).
- Projects inside a space **inherit** that template (default module set, view
  options), with per-project overrides optional. Nothing hardcoded into the
  templates by name.

### 6.6 Education

Every class is a project under Education. Each has:
- professor (contact link `schedule_classes.professor_contact_uid`),
- email (mailto), schedule (day/time/parity, `schedule_classes`), and a
  computed **"Next class in 5 days"** countdown,
- homework (tasks tagged `homework` after a project task list),
- grades (a specialized Grades module, §6.7),
- useful links (a small links list on the project page).

### 6.7 Settings

- **Global:** Spaces (their templates/config), Projects, Theme, Integrations
  (experiments, sync host), export/import.
- **Space:** modules, schedule (Education), space settings (default date range).
- **Project:** metadata, visibility, archive.

Remove configure-to-be-configurable surfaces. Keep it simple.

---

## 7. Migration strategy — delete first

**Delete-then-build**, two columns per phase: everything a phase removes, then
everything it builds. Deleting first forces the build to not lean on precedent
and keeps the schema shrinking, not growing.

Tests are the safety net: **all 24 current test files stay green through
each migration stage** (the schema renames update a handful of them), and each
phase adds tests in `webapp/tests/test_<area>_router.py` per the existing
pattern.

---

## 8. Concrete implementation phases

### Phase 0 — Strategy + docs (this)
Already done. `plans/` and `features/` reset (see READMEs).

### Phase 1 — Data-layer migration (schema only, no UI)
**Delete** (fully, this phase — they have no phase-owning UI left):
- `database_rows` / `database_columns` / `databases` tables, `formula_engine.py`,
  `routers/databases.py`, `databases_list.html` / `database_form.html` /
  `database_detail.html`, the databases router/tests, and the schedule
  auto-provisioning that pre-built a Grade database per class (the class's
  project creation is kept; the University Grades experience is rebuilt as a
  dedicated grade tracker in Phase 9).
- The `Data` tabbar entry from `base.html` and the Databases link in the
  Dashboard "See more" list (dead links once the router is gone; the full 4-item
  nav rework itself is Phase 2).
**Build:**
- `spaces` table (rename `project_groups` → `spaces`); add `projects.space_uid`
  (rename `group_uid`); `init_schema`'s data-preserving migration copies rows
  and drops the old tables/column.
- `task_completions(task_uid, due_date, completed_at)` + db functions.
- db function renames: `list_project_groups`→`list_spaces`, `get_project_group`→
  `get_space`, `upsert_project_group`→`upsert_space`, etc. (keep thin aliases in
  the migration phase only); project row-translator keeps a `group_uid` alias key
  so pre-rename reads keep working.
- Keep `project_uid` FK columns on `task_lists/calendars/addressbooks/
  schedule_classes` exactly as they are.
- Keep the `habits` / `habit_entries` and `dashboard_widgets` tables **fully
  intact** — decision (2026-08-03): habits are *reworked*, not removed (Phase 5
  rebuilds them on recurring tasks + `task_completions`), and the widget
  machinery's own deletion is Phase 3. Dropping the tables now would break their
  routers long before their replacement ships.
**Tests:** update the handful referencing renamed tables; delete the databases tests.

### Phase 2 — Navigation shell + Material tokens
**Delete:** the `Data` tabbar entry is already gone in Phase 1 (the remaining
`Habits` entry had already left the bar on 2026-08-01, so only that check
remains). **Decision (2026-08-03, DONE async):** the widget authoring/preview
machinery (`static/dashboard_widget_preview.js`, widget-resize handlers,
`_widget_workspace.html`) is **NOT deleted now** — dashboard customisation
*stays* and is to be reworked into a friendlier, more visual modal view in a
later phase; until then it is simply left as-is (not surfaced in the shell).
**Build:**
- 4-item nav: `Dashboard · Calendar · Tasks · Settings`; `<nav>` becomes top bar
  on desktop, bottom bar on mobile (two small layout blocks in one `style.css`);
  theme toggle → header button. A global `.app-header` (brand + `#btnTheme`)
  sits above the nav and carries the theme toggle.
- Adopt M3 tokens as CSS custom properties in `style.css` (color roles,
  elevation, shape, type), light/dark via existing `data-theme`; restyle the
  shared components (buttons, chips, cards, FAB) to the tokens.
**Acceptance:** pages render with the new shell; a quick nav check on all.

### Phase 3 — Fixed Dashboard
**Status (2026-08-03):** the rework decision below ("stays, reworked into a
friendlier modal") **shipped** — see Phase 10. The `Edit layout` bar and the
edit-gated Space-settings form were removed and replaced by a **Customize**
modal (`GET /dashboard/customize`, `dashboard_customize.html`): one friendly
flat list per dashboard/Space for add/move/up/down/delete/stack-dissolve and
per-widget Filters, all via the existing widget routes. The add-widget side is
a two-pane **Widget Builder** — configuration fields left, an always-live
preview right (`static/dashboard_widget_builder.js`): Add keeps the modal
open, shows "Added to dashboard." with **[Duplicate]** (re-adds the same config
so a one-filter tweak builds variants like Upcoming → Overdue) and **[Edit]**
(opens the new widget's Filters), re-filling the config from a snapshot after
each add. `dashboard_customize.html` extends `base.html` (`#modal-target`
fragment for modal.js, real page for no-JS); every non-builder form carries
`data-modal-keep-open` (the builder opts out via `data-builder`) so modal.js
refetches and re-renders in place, and `static/dashboard_widget_preview.js`
was refactored into `window.CCWidgetPreview.init(root)` so modal content
re-binds selects + the live preview (both loaded globally in base.html, called
from modal.js `wireContent()`). Entry point: a `Customize` button in each
toolbar; the shared `_widget_workspace.html` empty-state points at it too.
Tests: `tests/test_phase10_customize_modal.py` (13 tests).
**Decision (2026-08-03, DONE async):** *reverses the original delete below.*
Dashboard customisation **stays** — reworked into a **modal view** (shipped,
see above). The machinery — `dashboard_widgets`
table, WIDGET_TYPES/Source/View/Range, add/edit/resize/stack/reorder routes,
`_widget_workspace.html`'s edit-mode branch — is kept intact for that rework
(the `?edit=1` path remains reachable by URL but is no longer surfaced).
*Superseded delete:* WIDGET_TYPES/Source-View-Range, per-space widget grids,
`_widget_*` references.
**Build:** (superseded by the decision) the fixed §6.1 layout is approximated by
the retained default widgets (Today Agenda, Mini Month, Weekly Overview, Spaces)
rendered read-only; the deep "render directly from `db`, no registry" rewrite is
deferred to the customisation-modal rework (itself superseded by the shipped
modal).
**Acceptance:** `/` (and each Space page) shows the fixed widget layout for both
breakpoints with no customization entry points; the widget machinery/tests remain
green (400+ passing).

### Phase 4 — Spaces + templates + project inheritance
**Build (DONE, 2026-08-03):** `spaces.kind` column + `SPACE_KINDS` module map +
`space_kind`/`space_modules` in `db.py` (`personal|professional|education|custom`,
default `custom` for legacy rows via `_ensure_column`). Kind selectors on the New
Space form and the inline Space-edit row in `projects_manage.html` (autosubmit).
`space_detail` reads the space, computes its enabled `modules`, and renders
module-toggled cards -- `projects` (list of the space's projects), `schedule`
(next classes, education only), `contacts` (People = global contacts tagged with
the space name, a saved filter not a FK); the router computes all module data so
templates only iterate `modules`. `project_detail` **inherits** the space's
module set: the Course-info section renders only when the space has the schedule
module (education) enabled; projects with no space keep the old classes-only
behavior. `seed_university_data.py` sets `Courses`=education, `Campus Life`=personal.
**Acceptance:** creating a Space with a template seeds its modules; a Project under
an education Space renders the inherited schedule layout; a non-education one does
not (365 tests green; +5 Phase 4 tests).

### Phase 5 — Habits reworked onto recurring tasks + completion history ✅ DONE
**Delete:** `routers/habits.py`, `habits_list/detail/form` templates, the habit
heatmap templating calls fed by `habit_entries`, and finally the `habits` /
`habit_entries` tables.  **Rework, not removal:** a "habit" becomes an ordinary
recurring task; its day-by-day history comes from the `task_completions` table
built in Phase 1 (automatic historic saving of task state).
**Build:**
- Converge the habits UI onto recurring tasks (the Habits page keeps its concept,
  now backed by recurring tasks + `task_completions` instead of `habit_entries`).
- Recurring task detail reuses the existing recurrence expansion; a **Today**
  marking path appends to `task_completions`; a heatmap/streak view reads
  `task_completions` (reusing the GitHub-grid builder, now fed by completions
  instead of habit_entries).
**Acceptance:** a recurring task marked done on two different due dates → two rows
in `task_completions`; the heatmap/streak reflects both; no writes to
`habit_entries` remain.

**Implemented (2026-08-03):** habits device deleted outright —
`routers/habits.py`, `habits_list/detail/form.html`, `_habit_heatmap.html`,
`_widget_habit_checkin.html`, `habit_checkin.js`, the `/habits/…` routes, the
Settings Habits tab, dashboard "See more" Habits link, and tasks-list habit
rows all removed. `db.py` drops `habits`/`habit_entries` tables + all their
functions (`_migrate_phase5`) with no data migration (no lossless habit→task
mapping exists). The daily track-and-heatmap behavior now lives on recurring
tasks: `complete_task` writes a `task_completions` row for recurring tasks;
a new `POST /tasks/{uid}/completion/{date}/toggle` toggles a day (referer
redirect, `data-modal-keep-open`); `task_detail.html` shows a
`_task_heatmap.html` GitHub-grid + current/longest streak for recurring tasks;
`tasks_list.html`'s Recurring section (was "Habits & Recurring") has a Today
quick-check-off column via the same endpoint. `dashboard.py` dropped the
`habit_checkin` widget, its `habits` source, and the `checklist` view; the
Space default grid is now 3 widgets. Tests: deleted `test_habits_db/`router.py`,
updated dashboard/projects widget tests, added `test_recurring_completions.py`
(9 tests: completion writes, toggle add/remove + referer, detail context,
heatmap/streak helpers, list context). **338 passed.**

### Phase 6 — Calendar space behavior + education ✅ DONE
**Build:** On a calendar: `status` per space; `education` space renders schedule
occurrences (parity & holidays via existing `schedule.py`), and a per-project
"next occurrence" calculation ("in 5 days"); homework deadlines as tasks overlays.
Project/tempo independent events already work — surface on the project page.
**Acceptance:** education calendar shows next-lecture badge.

**Implemented (2026-08-03):** "status per space" = the calendar's behavior is
driven by the active Space filter's kind — an `education` (schedule-module)
Space activates the schedule behavior. Added `schedule.next_occurrence(cls,
settings, holidays, after)` to `src/schedule.py` — the parity + holiday-aware
"next lecture actually happens" compute, shared by both new surfaces (and
refactored routers/schedule.py's `_class_next_occurrence` to reuse it with empty
holidays, preserving its deliberately holiday-ignoring abstract-timetable
behavior). **Education calendar:** `calendar._space_schedule_badges` computes one
badge per class under the filtered Space's projects (off structured schedule
data, not the mirrored events, so it's correct before/without the mirror sync);
every calendar view (month/week/day/agenda) passes `schedule_next_lectures`, and
`_calendar_nav.html` renders a "Next lectures" badge strip ("ALG · Wed 10:00 ·
in 2 days"). **Per-project "in 5 days":** `project_detail` passes
`class_next_lecture` (per class uid → date + label) and the Course-info card in
`_project_university_section.html` renders a `Next: <label>` badge. Homework
deadline overlays (tasks by `due_at` on the calendar, `homework` tag section on
the project page) and project events were already surfaced — kept. Tests: added
`next_occurrence` unit tests (parity, holiday skip, semester end, invalid day)
in test_schedule.py + `test_phase6_calendar_education.py` (6 tests: education
badges on all four views, non-education + unfiltered calendars get none, and the
project-page next-lecture badge). **351 passed.**

### Phase 7 — Contacts global + saved filter ✅ DONE
**Keep:** the Active/Archived two-addressbook migration already shipped.
**Delete:** the old many-addressbook fragmentation if any remains; the
`contacts_list` shows filters by tag (a saved filter UI, not per-contact lists).
**Build:** a "Contacts" view whose filter = a saved tag filter; archive state;
project/space contact cards via tag match.
**Acceptance:** contact tagged `University` appears under the project page's
"People" and under the Contacts tag filter.

**Implemented (2026-08-03):** two-addressbook state was already the shipped
reality (routers/addressbooks.py is read-only: no create/delete routes, just the
two fixed books + project assignment), so "delete the fragmentation" was already
done — nothing left to remove. **Contacts tag filter:** `db.list_contact_tag_names`
(distinct tags actually on contacts, case-preserving/sorted, the narrow sibling
of `list_tag_names_in_use`); `list_contacts` gained a `?tag=` param filtered
case-insensitively against `contacts.tags_json` (Python pass — tags live in a JSON
blob and the list is personal-scale), and `contacts_list.html` renders a "All
tags" `<select>` beside the category filter, with every Active/Archived/Search
link carrying the tag through. **Project "People" via tag match:** `project_detail`
computes `people_contacts` = addressbook-linked contacts (unchanged
`_project_scope`) ∪ every contact tagged with the project's name or its Space's
name, deduped by uid and sorted; the section header is now "People" and renders
the union (a Space's People already did the tag==space-name match from Phase 4).
The phase's acceptance holds: a contact tagged `University` shows under a project
called University (or under its Space) AND under the Contacts tag filter. Tests:
`tests/test_phase7_contacts_global.py` (14 tests). **385 passed** with Phases 7–9.

### Phase 8 — Settings restructure ✅ DONE
**Build:** `routers/settings.py` organizes the existing manage pages
(Projects, Tags, Contacts, Schedule, new Spaces) under `Global / Space / Project`.
Remove the old tab drill-through. Keep it simple, no new horizontal config.
**Acceptance:** 3-level settings nav; every manage page reachable and unchanged
in behavior.

**Implemented (2026-08-03):** `/settings` is now a real hub page
(`settings_index.html`) instead of a 307 redirect to the first section (the old
tab drill-through). Three vertical groups, each a plain card of links to
already-working manage pages — no forms, no new horizontal config:
**Global** = Contacts, Tags, Calendars, Task lists, Address books, Schedule
(semester dates + classes); **Space** = a "Spaces" link to /projects plus each
existing Space (opens its Space page); **Project** = a "Projects" link to
/projects plus each active project (opens its detail page). Spaces and Projects
share the /projects manage page (projects_manage.html nests a Space's projects
under it), so both groups link there and differ by what they list. The manage
pages and their `_settings_nav.html` segmented strip are unchanged in behavior;
base.html's Settings tab now also highlights on the hub (`active_tab='settings'`).
Tests: `tests/test_phase8_settings_hub.py` (6 tests).

### Phase 9 — Education Grades (specialized module, not database) ✅ DONE
**Delete:** the generic `databases`+grid removed in Phase 1 final confirmation.
**Build:** dedicated `grades` storage for a class (`assessment`, `due`, `weight`,
`earned`), with the weighted average computed on read — the WEIGHTAVG logic from
`formula_engine.py` is ported into `grades.py` + templates + `routers/grades.py`,
scoped to one project/class.
**Acceptance:** a class's Grades tab lists each assessment and its weighted
average; it is not a generic grid.

**Implemented (2026-08-03):** `grades` table in `db.py` (one row per assessment
in exactly one class via `class_uid`; local-only, same bucket as
schedule_classes) + CRUD (`upsert_grade`/`get_grade`/`list_grades`/
`delete_grade`/`delete_grades_by_class`, the last called by schedule's class
delete). `src/grades.py::weighted_average` is the WEIGHTAVG port for the
structured shape: sums `earned*weight` over rows where both are numeric, skips
(not zeroes) missing/non-numeric `earned` ("not graded yet"), returns None when
total weight is 0. `routers/grades.py`: `GET /grades/class/{uid}` (lists the
assessments + the computed average badge), `POST` create/edit/delete. Entry
point: the Course-info card on a project page gets a per-class "Grades" button
(opened as a modal, `class_grades.html` is `#modal-target`-wrapped like
schedule_classes.html). Tests: `tests/test_phase9_grades.py` (14 tests).

### Phase 10 — Export / portfolio ✅ DONE
**Build:** ICS/CSV/JSON export routes + a Settings→Export page; a spaces/projects
CSV/JSON dump; a pointer that nothing is ever trapped in the SQLite cache.
**Acceptance:** data round-trips (export → re-import) for each format.
**Status (2026-08-03):** export shipped (`routers/export.py`, `export_index.html`,
Settings→Export row, `tests/test_phase10_export.py` 15 tests) AND the Phase 3
customisation modal shipped on top (see Phase 3 status). Suite green (410
passing).

### Phase 11 — Cleanup & finalize (DOING)
- Delete the leftover desktop directories/docs only in `plans/`/`features/` (the
  cmd should not touch `desktop/` code).
- Grep for orphaned imports (e.g. `formula_engine`, `habits`) → remove.
- Sync `webapp/README.md` and `features/` to the shipped result.
**Status (2026-08-03):** orphaned-import greps cleared; `features/` + `webapp/
README.md` sync in progress (export + customize modal are the remaining deltas);
desktop leftovers in `plans/`/`features/` remain to be pruned by the cmd (per
the mandate line).

---

## 9. Trade-offs and decisions (watch these consciously)

| Decision | Trade-off |
|---|---|
| Keep dashboard customization, as a modal (Phase 3/10 rework) | The old edit-layout bar was a config-heavy surface; the rework keeps the power ("arrange my page") but replaces the surface with a single friendly Customize modal over the same widget machinery, so the dashboard stays zero-config for the default case while customization no longer hides behind `?edit=1`. |
| Remove generic databases | **The** real risk if someone genuinely needed a free-form table. Mitigation: the Education Grades module covers the stated case; a future generic table is a deliberate, separate build — not resurrected on a sidebar. |
| Four-item navigation | Fewer destinations, deeper reach at Settings/Space. Mitigated by breadcrumbs and Settings' consistent launcher. |
| Reuse schedule/tags/checklist as the only local-only extensions | Keeps the schema at ~the mandated object count instead of sprouting one local-only table per screen. |
| Material tokens now, not the whole `@material/web` SPA | Fast, no-JS-compatible, and honest about what "adopt a design system" means for a server-rendered app; the SPA/PWA is logged as a follow-up, not dropped forever. |

---

## 10. Out of scope / deferred (so it isn't re-litigated)

- **DAVx5 mobile hosting** (public Radicale + reverse proxy, from the deleted
  rollout doc) remains a valid option, but it is infrastructure for Radicale, not
  app code — schedule it separately. It does not require building a native mobile app.
- **Dynamic M3 color** (true wallpaper-derived palettes) — below cost for a single user.
- Any native mobile app; the webapp's responsive mobile is the mobile story.
- Re-add generic workspace/boards/attachments — not part of Spaces & Projects.

*If a reader believes one of these should return, write a focused plan + trade-off
and argue from the evidence; this document won't be re-opened by default.*