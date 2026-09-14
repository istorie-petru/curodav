# Labels & Spaces

`routers/labels.py` — the single organizing mechanism (see `architecture.md` §1.2).
A label is just a name in the `object_labels` join table; any config is a thin
optional `label_config` dict (color/icon/description/parent_name/`generate_space`/
abbreviation). There is **no delete endpoint** — "removing" = `clear_label`
(strips membership everywhere).

## Spaces — labels-as-membership rework (2026-09-14)

A Space (`generate_space=1` label) is a *membership group*, not a taggable
item: a plain or project label optionally belongs to one Space via
`parent_name` (set through a validated dropdown, not free text), and a
Space's own page aggregates everything tagged with any label that belongs
to it — never anything tagged with the Space's own name directly. This
reverses the "direct membership only, never transitive through
`parent_name`" model 1.7 had shipped and confirmed (`plans/open-priority.md`'s
"Spaces — context" section, superseded 2026-09-14) — full spec/six-slice
history in `plans/STATE.md`'s 2026-09-14 entries; this section is the
condensed, current-state summary.

- **Label edit form.** `_label_form_fields.html`'s Space field is a
  `<select name="parent_name">` (`labels.py::_validate_parent_name`: blank
  or must name an existing `generate_space=1` label, 400 otherwise), hidden
  when the label being edited is itself a Space — Spaces don't nest. The
  old free-text `label_group` field/column still exists in the schema but
  is no longer written or read anywhere in the UI.
- **Settings > Labels** (`/settings/labels`) renders one single `<table>`
  (2026-09-16, direct feedback superseded the original one-`<table>`-per-
  Space design below) — a Space's own row is a colored "card" row (light
  `var(--tag-<color>-bg)` tint, rounded corners, plain `.label-cell-icon`
  like any label) with a Usage figure totaled across itself and every
  child, followed by its children as plain rows, then every ungrouped
  label as a plain row with no heading in front of it — no repeated
  per-group header, no special-cased Ungrouped section. (Superseded
  history: 2026-09-14 slice 2 originally shipped one `<table>` per Space,
  each with its own `.label-icon-tile avatar-circle` heading, plus a
  separate "Ungrouped" table.)
- **A Space's own page** (`/spaces/{name}`, `routers/spaces.py::_label_scope`)
  aggregates tasks/events/contacts tagged with any of its child labels
  (`db.list_child_labels`) — a Space's own name carries no aggregation
  meaning any more. A plain/project label's own page is unaffected by the
  Spaces rework (still direct `object_labels` membership only), but see
  "Generated page" below for a separate, later change to what kind of
  page a plain label gets.
- **Dashboard widget grid**, on a Space/Project page, applies this as one
  hard, unconditional scope check (`dashboard.py::_scope_child_names` +
  `_passes_scope`) every item-listing widget goes through via the shared
  `_filtered_tasks`/`_filtered_events`/`_render_contact_list`/
  `_render_habit_checkin` functions — a widget's own optional Filters-panel
  tag selection can no longer show items from outside the page's scope
  (closed a real pre-existing leak where the two were OR'd together
  instead of AND'd). The seeded "Upcoming" stack member shows both tasks
  and events now (was events-only).
- **Migration** (`scripts/migrate_spaces_direct_tags.py`, one-off,
  idempotent, `--dry-run` supported): strips every `object_labels` row that
  directly tags a Space's own name — dead-but-visible data the aggregation
  change above stopped reading. `label_group`'s legacy stored values are
  left alone; nothing reads that column any more.
- **Known gap, not covered by this rework**: the tag-picker vocabulary
  (`db.list_tag_names_in_use`) still offers a Space's own name as an
  assignable tag, same as any plain label — assigning one has no effect on
  that Space's page (same "dead but harmless" shape the migration above
  cleans up for pre-existing rows), but nothing stops a *new* one from
  being created. Excluding Spaces from the picker outright would need its
  own follow-up.

## Manage page (`/settings/labels`)

Rows within each table (see above): rename, merge, recolor (16 colors),
icon picker (grouped `ICON_GROUPS`, ~140 sprite icons), Space assignment,
`generate_space`/project Role picker, abbreviation (max 5), "clear". Bulk
select/merge/clear across the whole page (`static/bulk_select.js`, scoped
to the single `#labels-table` container regardless of how many per-Space
tables live inside it). No client-side search box exists on this page
today (`static/label_search.js` is unreferenced by any template — a
leftover from an earlier, reverted list-based design, not wired to the
current table markup).

## Generated page (`/settings/labels/{name}` / `/spaces/{name}` / `/projects/{name}`)

Three different pages now, by role — `routers/labels.py::label_detail`
(`GET /settings/labels/{name}`) redirects a `generate_space=1` label to
`/spaces/{name}` and an `is_project=1` label to `/projects/{name}`; only
a plain label renders at this URL directly.

- **Space** (`/spaces/{name}`, `routers/spaces.py::space_detail`) — the
  customizable widget grid (`label_detail.html`/`_widget_workspace.html`),
  unchanged: "New widget"/"Reset layout" in edit mode, seeded default
  widgets, the Spaces & Projects widget for its child labels/sub-Spaces.
  The old hardcoded "Projects" section this page used to show above the
  widget grid was removed outright 2026-09-16 (direct request: it
  duplicated the Spaces & Projects widget) — a Space page with no
  manually-added widget instance shows nothing for its children until one
  is added; the widget grid isn't auto-seeded by default (see
  `dashboard.py::_ensure_default_label_widgets`'s own docstring).
- **Project** (`/projects/{name}`, `routers/projects.py::project_detail`)
  — rebuilt 2026-08-30 away from the widget grid: a Kanban board (every
  non-archived task carrying the label, grouped by status, drag-and-drop
  via `static/tasks_board.js`) with an Agenda card above it (future
  events + open due-dated tasks tagged with the label, plus a synthetic
  "Project deadline" row from `label_config.end_date`). No "New
  widget"/"Reset layout" — edit mode only adds the Add/Change banner
  control.
- **Plain label** (`/settings/labels/{name}`, `routers/labels.py::
  label_detail`, template `label_kanban_detail.html`) — 2026-09-16,
  direct request: "plain labels should generate pages like projects, with
  agenda and kanban, not dashboards." Same Kanban+Agenda shape as a
  Project's page, but a deliberately separate, independent
  implementation (own template, own context-building in `labels.py`
  rather than calling into `routers/projects.py`) — direct choice:
  "similar but distinct," so the two can diverge later. No deadline row
  (a plain label has no `start_date`/`end_date`). The widget grid is no
  longer used for plain labels at all; `labels.py`'s own `_label_scope`
  helper (direct `object_labels` membership) was removed as dead code in
  the same pass — nothing called it any more once this page stopped using
  it.

The University module (Course info/Homework, schedule-linked) described
in earlier revisions of this doc is removed entirely — see
`plans/STATE.md`'s 2026-08-15 removal entry.
