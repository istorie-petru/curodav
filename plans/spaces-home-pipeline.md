# Implementation prompt: Home → Space → Project → Item pipeline

**Status:** Ready to implement · logged 2026-08-02
**Supersedes (for this specific piece):** the "List vs. Project" and "Projects as customizable as the Dashboard" sections of [`webapp-ui-design-direction.md`](webapp-ui-design-direction.md) — this doc is the converged, scoped-down version of those two after discussion. The rest of that doc (icon library, pagination, Databases ownership, Schedule/Databases sectioning) is untouched and still open.

Paste this whole document as the task brief for whoever (agent or human) implements it. It is deliberately over-specified — exact files, exact functions to reuse, exact things not to build — because the two hard constraints below are non-negotiable and easy to violate by accident with a well-meaning refactor.

## Hard constraints

1. **Every page that exists today keeps working exactly as it does today.** Dashboard (`/`), Tasks, Calendar, Databases, Projects manage, Habits, Contacts, Schedule, Settings — no behavior change, no visual change, no route change, on any of them, except the one explicitly-listed Dashboard addition in Step 4. If a change would require touching one of these templates/routers beyond what's explicitly listed step-by-step below, stop and flag it instead of doing it.
2. **Reuse before building.** Every concept below (Home, Space, Project, Item, Quick Capture, Inbox) maps onto something that already exists in this codebase. The only genuinely new things are listed explicitly in each step as "New:" — everything else is "Reuse:". If you find yourself writing a new table, a new render function, or a new JS file for something that isn't marked "New" below, stop — the reuse path was missed.
3. **All 327 existing tests stay green** (`uv run pytest` from `webapp/`, currently 327 passed). New routes get their own new tests following the existing per-router test file pattern (`tests/test_<router>_router.py`).

## Concept → existing code map

| Concept | What it is | Status |
|---|---|---|
| **Home** | Daily, cross-space "what needs to happen" secretary view | Already exists: `/` (`routers/dashboard.py`, `templates/dashboard.html`). No new page. |
| **Space** | Weekly view of one `project_groups` row + the projects under it | `project_groups` table already exists (uid, name). No detail page exists yet — this is the one real new page in this whole doc. |
| **Project** | Open-ended (monthly/forever), one project's tasks/calendar/database | Already exists: `/projects/{uid}` (`routers/projects.py`, `templates/project_detail.html`). No changes needed to its logic — only an optional breadcrumb addition (Step 5). |
| **Item** | A task or event's full detail | Already exists: `/tasks/{uid}` modal, event edit modal. No changes. |
| **Quick Capture** | Type-and-Enter capture from anywhere | Already exists as a pattern: `tasks_list.html`'s `#quick-add-form` (title-only `POST /tasks`, no-JS-required, `static/tasks_table.js` adds the stay-on-page fetch behavior on top). Reuse the identical form, just also render it on Home. |
| **Inbox** | Untriaged captures | **Not new storage.** A task with no `project_uid` reachable through its list is already, structurally, unassigned — see Step 3. Inbox is a filtered view, not a table. |
| **Breadcrumb** | Home › Space › Project trail | New, but tiny: one partial template. |
| **Per-space tint** | One subtle background color per Space | New: one column (`project_groups.color`) + a few lines of CSS. Not a new theming system — reuses the *existing* color token set (`--tag-*-bg`/`--tag-*-fg` already defined in `style.css`), same palette every color picker in this app already offers, not a new palette. |

## What NOT to build (scope guardrails)

Explicitly out of scope for this pass — each of these came up in the design discussion but was deferred, don't build them as a side effect of this work:

- **No customizable per-Space widget layout.** The Space page (Step 2) is a fixed template using existing render logic, not a new instance of the `dashboard_widgets` system. No new `dashboard_widgets` rows, no new "scope" column on that table.
- **No item-level project tagging.** Task/event → project membership stays exactly as it is today: via the list/calendar's `project_uid`, resolved through `_filtered_tasks`/`_filtered_events`. Do not add a `project_uid` column to `tasks`/`events`.
- **No new top-level nav tabs.** Do not add "Spaces" (or individual space names) to `base.html`'s `.tabbar`. It already has 4 items and this codebase's own CSS comments note it already needed horizontal-scroll handling for that. Spaces are reached from Home (Step 4), not the tabbar.
- **No auto-directing of captured items.** Inbox items are triaged by hand (Step 3's "Move to list" reuse). No text-parsing/matching logic to guess a project from a task's title.
- **No material/texture/elevation theming.** Per-space identity is a single background tint (Step 6), not shadows, borders, or layout changes per space.
- **No changes to `tasks_list.html`, `calendar_*.html`, `databases_list.html`, `habits_list.html`, or any router's existing routes/behavior**, beyond Step 4's Dashboard addition and Step 5's optional breadcrumb include.

## Steps

### Step 1 — `project_groups.color`, migration only

In `db.py`: add `color TEXT NOT NULL DEFAULT 'blue'` to the `project_groups` table, following the exact `_ensure_column` pattern already used repeatedly in `init_schema` (e.g. the `professor_contact_uid`/`project_uid` additions). Update `upsert_project_group` to accept/persist `color` (default `'blue'` if omitted, same default convention `upsert_project`/`upsert_habit` already use). Add a `color` `<select>` (reusing the same `colors` list already passed into `projects_manage.html`) next to each group's name field in `projects_manage.html`'s existing group-editing row — this is the one small, additive touch to that page: one new field on an existing form, not a new page or layout change.

### Step 2 — Space page: new route + template, built from reused pieces

**New:** `GET /projects/groups/{uid}` in `routers/projects.py` (the router already owns `/groups` POST/edit/delete — add the missing GET). Renders a new `templates/space_detail.html`.

**Reuse, not new:**
- The "this week" agenda: don't write new aggregation logic. In the route handler, resolve `project_uids = [p["uid"] for p in db.list_projects(conn) if p["group_uid"] == uid]`, then call the *existing* `routers.dashboard._filtered_tasks(conn, {"project_uid": pid})` / `_filtered_events(conn, {"project_uid": pid}, start=week_start, end=week_end)` once per project and merge — OR (preferred, see Step 2a) extend the existing filter function to accept a project-set directly so this is one call, not a loop.
- The list of projects under this group: reuse the exact card markup `projects_manage.html` already renders per project (`cell-tag cal-{{ p.color }}` badge + name + Open link) — factor it into a small shared macro/partial if convenient, but the visual result should be identical to what's already on the manage page, not a new card design.
- Week-of-N task/event rendering: reuse `_widget_weekly_overview.html`'s existing markup/logic (`_render_weekly_overview` in `dashboard.py`) by calling that render function with the resolved project-set config, same as Today's Agenda above.

**Step 2a (the one sanctioned touch to `dashboard.py`):** extend `_passes_filters`/`_filtered_tasks`/`_filtered_events` in `routers/dashboard.py` to accept an optional `config["group_uid"]`, resolved once per call to the set of that group's project uids, alongside the existing single `config["project_uid"]` check. This is additive and backward-compatible — every existing widget config that never sets `group_uid` is unaffected, verify via the existing dashboard test suite staying green. Do not add a `group_uid` column to `dashboard_widgets` — this is a query-time resolution, not new storage (see "No customizable per-Space widget layout" above).

### Step 3 — Inbox: a filtered view, not a table

**New:** `GET /tasks/inbox` in `routers/tasks.py` (or a query param on the existing route, e.g. `/tasks?list_path=__unassigned__` — pick whichever is less invasive once you're in the code; a dedicated route is probably cleaner since it needs a different empty-state message, not different query logic). Filter to tasks whose `list_path` resolves to a `task_lists` row with `project_uid IS NULL` (reuse `db.list_task_lists`/`db.list_tasks`, no new query primitives needed) and reuse `tasks_list.html`'s existing table rendering (same template, filtered dataset, a different page title/empty-state copy — "Nothing to triage" instead of "No tasks yet").

Triage itself needs **no new mechanism** — `tasks_list.html`'s existing bulk-actions bar already has a "Move to list" select (`#bulk-list-select`, posts to the existing move-to-list endpoint). Assigning an Inbox item's project happens by moving it to a project-linked list, exactly the same action a user already has for any task today.

### Step 4 — Home gets two small additions, nothing else changes

In `templates/dashboard.html` only:

1. **Quick Capture.** Copy `tasks_list.html`'s `#quick-add-form` markup verbatim (same `POST /tasks`, no `list_path` hidden field so it lands in the default list — which, per Step 3's definition, makes it an Inbox item unless that default list already has a `project_uid`). Place it near the top of the page, above the existing widget grid.
2. **Space cards.** A small new section (reuse `.cell-tag`/card styling already in `style.css`, no new component) listing `db.list_project_groups(conn)` as clickable cards linking to `/projects/groups/{uid}` (Step 2). This is the *only* way to reach a Space — confirms the "no new tabbar entry" guardrail above.

Nothing else on `dashboard.html` changes. The existing widget grid, its edit-layout flow, and every existing widget type are untouched.

### Step 5 — Breadcrumb partial (optional polish, do last)

**New:** `templates/_breadcrumb.html`, a one-line partial: `Home › {{ space.name if space }} › {{ project.name if project }}`, each segment a real link. Include it at the top of `space_detail.html` (Step 2) and, optionally, at the top of `project_detail.html` if that project has a `group_uid` (a two-line addition to an existing template: fetch the group via `db.get_project` → `group_uid` → `db.list_project_groups`, and `{% include %}` the partial — not a restructure of that page).

### Step 6 — Per-space tint

In `space_detail.html`'s wrapping element, set a CSS custom property from the group's `color` (Step 1) using the *existing* token variables already defined in `style.css` (`--tag-{color}-bg`), e.g. `style="--space-tint: var(--tag-{{ group.color }}-bg)"`, and add one small CSS rule scoped to `.space-page` that applies `--space-tint` as a subtle wash behind the content area (not per-widget, not per-card — one wash behind the whole page). Contrast-check both light and dark mode before calling this done (the existing `--tag-*-bg` tokens already have separate light/dark values in `style.css`, confirm the wash stays subtle in both, not just the one you tested in).

## Acceptance criteria

- `uv run pytest` from `webapp/`: 327 existing tests still pass, unchanged.
- New tests: `tests/test_projects_router.py` gets coverage for the new `GET /projects/groups/{uid}` route (renders, 404s on unknown uid, shows correct project subset); `tests/test_tasks_router.py` gets coverage for `/tasks/inbox` (only shows unassigned tasks, moving a task to a project-linked list removes it from the Inbox result).
- Manual check: load `/`, `/tasks`, `/calendar`, `/databases`, `/projects`, `/habits`, `/contacts`, `/schedule` — every one of them renders identically to before this change, except `/` (Dashboard) now additionally shows the Quick Capture form and Space cards.
- A task created via Home's Quick Capture with no list_path shows up in `/tasks/inbox`; moving it to a project-linked list makes it show up on that project's page and disappear from Inbox.
- A Space page shows this week's tasks/events pooled from every project under that group, and the group's chosen color as a subtle background wash, in both light and dark mode.
