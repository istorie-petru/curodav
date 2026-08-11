# Labels & Spaces

`routers/labels.py` — the single organizing mechanism (see `architecture.md` §1.2).
A label is just a name in the `object_labels` join table; any config is a thin
optional `label_config` dict (color/icon/description/parent_name/`generate_space`/
abbreviation). There is **no delete endpoint** — "removing" = `clear_label`
(strips membership everywhere).

## Manage page (`/labels`)

Flat sortable rows (ungrouped or grouped by parent), client-side search
(`label_search.js`), actions: rename, merge, recolor (16 colors), icon picker
(grouped `ICON_GROUPS`, ~140 sprite icons), parent, `generate_space` toggle,
abbreviation (max 5), "clear".

## Generated page (`/labels/{name}`)

One page for both cases via `_label_scope`:

- a `generate_space` label is a **Space** — aggregates tasks/events/contacts/
  classes of its child labels, **direct membership only** (never transitive
  through `parent_name`);
- a plain label is a **project-style page**.

Both render the shared widget grid (`_widget_workspace.html`, scoped to the
label), plus page-specific sections: Course info (linked schedule classes +
professor mailto) and Homework table (`_project_university_section.html`),
"Next lecture" badges, and its own banner. `enabled_modules` (schedule/grades/
homework/tasks/events/contacts) gates which sections render; the widget grid is
never gated by it.

Creating a schedule class auto-provisions a label named after the course (blue,
book-open icon) under the inferred Space label
(`_auto_provision_university_project`).
