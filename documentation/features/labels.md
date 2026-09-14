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
- **Settings > Labels** (`/settings/labels`) renders one `<table>` per
  Space (heading = a `.label-icon-tile avatar-circle` in the Space's own
  color/icon + its name) plus one "Ungrouped" table holding every label
  with no parent and the "+ Add label" row — replaces the old flat
  sortable table with a text Group badge. A Space's own row is the first
  row inside its own table (still individually Edit/Delete-able there,
  same as any label) rather than a second, separate mechanism.
- **A Space's own page** (`/spaces/{name}`, `routers/spaces.py::_label_scope`)
  aggregates tasks/events/contacts tagged with any of its child labels
  (`db.list_child_labels`) — a Space's own name carries no aggregation
  meaning any more. A plain/project label's own page
  (`routers/labels.py::_label_scope`) is unaffected: still direct
  `object_labels` membership only, since there's no membership concept for
  a page that isn't a Space.
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

## Generated page (`/labels/{name}` / `/spaces/{name}`)

A `generate_space=1` label's URL (`/labels/{name}`, `/settings/labels/{name}`)
redirects (301) to `/spaces/{name}` — `routers/spaces.py` owns a Space's
own page entirely, `routers/labels.py::label_detail`/`_label_scope` only
ever run for a plain/project label now. Both render the shared widget grid
(`_widget_workspace.html`, scoped to the label), plus a "Projects" section
listing child labels (Spaces only) and the page's own banner. The
University module (Course info/Homework, schedule-linked) described in
earlier revisions of this doc is removed entirely — see `plans/STATE.md`'s
2026-08-15 removal entry; a label's page is just tasks/events/contacts
again.
