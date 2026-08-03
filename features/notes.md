# Feature: Notes

**Code:** removed 2026-07-19 (was `desktop/src/features/notes/widgets.py`)
**Status:** Removed — the module UI is gone; the underlying data model is not

## What happened

The Notes module (split-pane markdown editor, note-list sidebar, wikilinks/backlinks, daily notes) was removed from the app on 2026-07-19, along with Roadmap (see `roadmap-goals.md`) — both are planned to come back later as a folder-and-markdown-first feature, a different design than the object-model-backed implementation described below, which is kept here as the historical record of what was built and how.

**What's still true:** `ObjectType.note` and `NoteDetails` (`core/models/object.py`) still exist untouched — nothing purges or migrates existing `note`-type objects. A note created before this change, or synced in from another device that still has an older build, still opens fine in the generic Inspector (title, description, tags, linking all work) — it just has no dedicated editor UI, note list, or backlinks panel anymore. It's also still indexed by Search, to the extent Search works at all (see `../STRESS_TEST_2026-07-17.md`).

**What was removed alongside the module:** the Calendar day-cell "Open daily note" context menu action and the `daily_note_requested` signal chain it drove — both existed only to open the now-gone Notes module, so they were deleted rather than left as dead ends. See `window-and-menu.md` for the navigation-level changes and `calendar.md` for the calendar-side cleanup.

## What was built (historical — describes the removed implementation)

- **Editor** — split-pane markdown editor (edit source / rendered preview, or toggle mode). Preview used `QTextBrowser` with `markdown-it-py` rendering.
- **Note list** — a left-side sidebar listing all notes (newest-updated first), each showing icon, title, an 80-character body preview, and the update timestamp. Search/filter by title within the list. "New note" button at the top.
- **Wikilinks and backlinks** — `[[Title]]` syntax in a note body was parsed on save and materialized into `mentions`-type entries in `links.json` (autocomplete suggested existing object titles while typing). Every note view had a **Backlinks** section listing objects that link to the current note. See `tags-and-linking.md` for the underlying link model, which is unaffected by this removal (still used by every other object type).
- **Daily notes** — notes with `is_daily=true` and a `daily_date`, created/opened from the Calendar or a "Journal" smart list. Fixed 2026-07-18 (see `calendar.md`) that `is_daily`/`daily_date` weren't persisting at all due to `Object.details` never being serialized — a fix that landed the day before the module itself was removed.
- **Search** — full-text search across all note bodies via FTS5, with result highlighting.
