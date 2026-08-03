# Feature: Search & command palette

**Code:** `desktop/src/features/search/` (`widgets.py`, `command_palette.py`), `desktop/src/core/search/`
**Status:** Code exists; **the actual search is non-functional** — see [`../STRESS_TEST_2026-07-17.md`](../STRESS_TEST_2026-07-17.md)

> **Verified broken (2026-07-17):** `core/db/database.py` defines `_upsert_fts()` to populate the FTS5 index, but nothing calls it — the index is created empty and stays empty, so `SearchEngine.search()` returns no results for any real query. Even fixing that call site isn't enough: the table inserts `rowid=object_id`, and object ids are UUID strings, which SQLite rejects for an FTS5 rowid (`datatype mismatch`) — the rowid strategy needs to change, not just get wired up. A bare `"` in a query also crashes the search with an unhandled `OperationalError`. `search_by_prefix()` (used for autocomplete) is unaffected — it queries the plain `objects` table with `LIKE`, not FTS5.

Intended design (not currently working): entirely client-side and local — every device has all the data, so there's no round trip. SQLite **FTS5** external-content tables over `objects(title, description)` and `note_details(body)`, kept current by the same watchdog-driven cache updates that back every other query. Query pipeline: exact title prefix → FTS ranked (bm25) → tag/type/status filters.

## Global search bar

Always-visible input in the top bar. Results grouped by type (Tasks, Notes, Events, Projects, ...). Click to navigate. Matching terms are highlighted in results via FTS5's `snippet()`.

## Command palette (`Ctrl+K`)

Overlay with two modes:

1. **Object search** (default) — same FTS5 query as global search, with keyboard navigation (↑↓ to select, Enter to open).
2. **Action mode** (type `>`) — app-wide actions: "New task", "New event", "Go to Today", "Toggle dark mode", etc.

The command palette and the search screen share one search service (`core/search/`) — there's no separate index or query logic between them.
