# Notes

Notes are the fourth Quick Capture entity type (`!n`, see
[`quick-capture.md`](../plans/quick-capture.md) for the full capture syntax),
alongside the pre-existing tasks/events/contacts. Deliberately minimal, per
the design doc's own scope: a note is free-text content plus labels, nothing
else — no title field (the content's first non-blank line serves that
purpose everywhere one is needed, `db.note_title`).

## Data model

`notes` table: `uid`, `content`, `created_at`, `updated_at`. Labels via the
same `object_labels` table every other entity type uses (`object_type =
'note'`) — a note participates in the label/Space system exactly like a
task, event, or contact. `db.upsert_note`/`get_note`/`delete_note`/
`list_notes` mirror contacts' own CRUD shape.

Not the same concept as `contacts.notes` (a free-text field on a contact) —
same English word, unrelated schema.

## Surfaces

- `GET /notes` — a plain list page (`templates/notes.html`), search box,
  each row opening the edit form.
- `GET /notes/new` / `POST /notes` — create.
- `GET /notes/{uid}/edit` / `POST /notes/{uid}` — edit (one shared
  `note_form.html` for both, `note=None` on the create path).
- `POST /notes/{uid}/delete` — delete.

Not a primary tabbar destination (a deliberate, separate UI decision this
slice didn't make) — reached via the command palette (search result or the
"Notes" page-navigation entry, see `tasks.md` § Search & the command
surface) or a direct `/notes` visit.

## Findability

A note is a fourth type in `db.search_entities`/`_search_notes` — the same
query layer tasks/events/contacts already share, so a captured note shows
up in Ctrl-K, `/search`, and the palette's label/delete actions immediately,
not just as a database row nothing ever surfaces again.
