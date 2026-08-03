# Feature: Tags & linking

**Code:** `desktop/src/widgets/inspector.py`, `desktop/src/widgets/object_card.py`, `desktop/src/features/shared/filter_bar.py`, `desktop/src/features/shared/link_picker.py`
**Status:** Implemented

This is shared infrastructure every object type (task, event, note, project, goal, roadmap node, board) uses identically — not a module of its own.

## Two kinds of relationships

1. **Structural (`parent_id`)** — tree-shaped, ownership: subtask→task, task→project, note→notebook. One parent max. Deleting/archiving cascades down. Displayed nested/indented.
2. **Associative (`links.json`)** — graph-shaped, free-form: "this note is about that event", "this task blocks that task". No cascade, any-to-any. Link types: `related`, `blocks`, `references`, `mentions`.

## Link management UI

- **Link picker dialog** (`shared/link_picker.py`) — search/browse all objects, select one, choose a link type; writes via `FileRepository.write_links()`.
- **Linked items section** (in the inspector) — shows linked object cards with type badges (`blocks`=danger color, `references`=accent, `mentions`=success, `related`=neutral). "+" opens the link picker; each link has a delete button.
- **Backlinks section** — read-only, populated from the `links.to_id` index. Click a backlink card to navigate to that object.
- **Wikilinks** — `[[Title]]` in note bodies auto-creates `mentions` links on save (see `notes.md`).

## Tags

- Tags are separate entities (name, optional color, created/deleted timestamps), many-to-many via `object_tags`.
- **Primary tags** (categorization level, e.g. `critoracy`, `academic`, `ardor`, `personal`) get fixed semantic colors hardcoded in QSS. **Secondary tags** (free-form, e.g. `writing`, `exam`, `meeting`) render as dashed-outline chips.
- Displayed as small colored capsules on every card/row rendering the object.
- **Tag editor** (in the inspector) — current tags as removable chips; an autocompleting add-tag input (`features/tasks/tag_autocomplete.py`) creates a new tag on the fly if it doesn't exist yet; colors editable via a small preset picker.
- **Tag manager** (Settings) — lists all tags with name/color/usage count; inline rename, recolor, **merge** (added 2026-07-19), delete (cascades to `object_tags`).

## Reworked 2026-07-19 — merge action, write-through rename/merge, autocomplete everywhere

- **Merge.** Each row in Settings → Tags now has a "Merge into…" button — pick another existing tag, and every object carrying the source tag gets the destination tag instead (deduped, not duplicated); the source tag is then deleted.
- **Rename and merge now write through to the actual object files**, not just the SQLite tag cache. Previously `Database.rename_tag` only updated the `tags` table; that table (and `object_tags`) is itself *rebuilt from* each object's own `tags` field on reindex (`Database.upsert_object`), so a rename looked correct for the rest of the session and silently reverted on the next reindex/restart — the same class of bug as the 2026-07-18 Kanban/Timeline drag-persistence fixes (see `tasks.md`/`boards.md`). Both `TagsTab._rename` and `._merge` (`features/settings/widgets.py`) now iterate every object via `FileRepository`, rewrite its `tags` list, and `write_object()` before touching the DB cache. Delete already removed tags from objects via the DB cascade; it now also rewrites the underlying files for consistency.
- **Autocomplete everywhere a tag gets typed by name.** `features/shared/tag_names.py` holds a process-wide cache of every tag currently in use, refreshed once per data reload (`MainWindow._refresh_current_module`) from the full object list — cheaper than each field independently querying the DB. `features/tasks/tag_autocomplete.py::install_tag_completer()` wires a `QCompleter` sourced from that cache into any `QLineEdit`; used by the inspector's tag input (`multi=False`, whole-field completion) and the Table view's Tags cell editor (`multi=True`, completes only the fragment after the last comma in a `"tag1, tag2"`-style field).

## Filtering

`TagFilterBar` (`shared/filter_bar.py`) is a reusable widget embedded above every list view (Tasks, Dashboard sections, search results). Click a chip to toggle include/exclude; active filters are highlighted. Multiple tags: AND within a filter type (primary/secondary), OR between types.
