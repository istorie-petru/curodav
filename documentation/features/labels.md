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
label), plus page-specific sections: Course info (this label's own recurring
class-meeting events + professor mailto — see `features/schedule.md`, 1.6
turned these from a dedicated `schedule_classes` query into
`db.list_schedule_class_events` + `routers/schedule.py::_class_row`) and
Homework table (`_project_university_section.html`), "Next lecture" badges,
and its own banner. Every section just renders whenever it has matching data;
there's no `enabled_modules`-style gate anymore (removed 2026-08-08).

Creating a schedule class auto-provisions a label named after the course (blue,
book-open icon, `is_project=1`) under the inferred Space label
(`routers/schedule.py::_auto_provision_course_label`).

## Spaces close out 1.7 (2026-08-14)

This generated page (a `generate_space=1` label) is the "Spaces — context"
surface from `plans/open-priority.md`'s Information architecture & view
surfaces section, and the University module above (Course info + Homework) is
that section's "University module adds courses, schedule, professors,
credits, and assignments" line — both were already built (2026-08-08) before
1.7 started, and were confirmed against the spec rather than rebuilt when 1.7
closed. Answers "what belongs to this area of my life?" the same way
`features/today.md`/`features/week.md` answer their own release's question.
