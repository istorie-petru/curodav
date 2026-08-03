# Performance report — static findings (2026-07-12)

> **Historical note (2026-07-17):** written against the old Flutter client
> (`app/`, now removed and rebuilt in PySide6 — see `ARCHITECTURE.md` and
> `REWORK_PLAN.md`). The specific files and Flutter anti-patterns below no
> longer apply to the current codebase; kept for the record of what was
> investigated and found.

## Why this exists

You reported lag in list scrolling and typing. I can't run the Flutter app or capture live frame traces in this sandbox — there's no Flutter SDK or display server here, only the source tree. What follows is a static scan of the codebase for the two Flutter anti-patterns that cause exactly those symptoms, plus instrumentation code (below) you can run on your own machine to get real numbers.

## Finding 1 — every list in the app is built eagerly, not lazily

`grep` for `ListView(` vs `ListView.builder(` / `ListView.separated(` across `lib/`: **zero** files use the lazy constructors. All 17 screens with lists use `ListView(children: [...])` wrapping a `Column` built with a `for` loop over the full dataset.

This means Flutter constructs every row in the list up front — including rows that are off-screen — every time the list rebuilds. For a short list (5-10 items) this is invisible. For anything longer (a "someday" smart list with 100+ tasks, a contacts list, a big project's task list) this is the standard cause of scroll jank, because layout has to process the whole list instead of just the visible window.

Ranked by likely severity (based on how large that data source typically grows):

| File | Screen | for-loops |
|---|---|---|
| `features/tasks/presentation/tasks_screen.dart` | Tasks — smart lists | 2 |
| `features/tasks/presentation/grouped_view.dart` | Tasks — grouped by project | 6 |
| `features/tasks/presentation/kanban_view.dart` | Tasks — kanban | 4 |
| `features/tasks/presentation/timeline_view.dart` | Tasks — timeline | 3 |
| `features/contacts/presentation/contacts_screen.dart` | Contacts | 5 |
| `features/search/presentation/search_screen.dart` | Search results | 2 |
| `features/dashboard/presentation/today_screen.dart` | Today / dashboard | 8 |
| `features/calendar/presentation/calendar_screen.dart` | Calendar | 6 |
| `features/notes/presentation/notes_screen.dart` | Notes | 2 |
| `features/projects/presentation/project_detail_screen.dart` | Project detail | 7 |
| `app/shell/sidebar.dart` | Sidebar | 7 |

Fix is mechanical and low-risk: swap `ListView(children: [...for loop...])` for `ListView.builder(itemCount: ..., itemBuilder: ...)`. Same visual output, same data, lazy construction. Roughly 15-30 minutes per screen; the tasks list (the one you're most likely scrolling daily) is the highest-value first fix.

Secondary, smaller issue in the same file: `TaskListTile` accepts a `key` parameter but the call site at `tasks_screen.dart:304` never passes one (`TaskListTile(task: task, projectTitle: ...)` with no `key: ValueKey(task.id)`). Without a key, Flutter can't correctly match list items across rebuilds when tasks are reordered, completed, or removed — it falls back to positional matching, which can cause tiles to visually "jump" or rebuild wrongly. Two-line fix, do it alongside the `ListView.builder` conversion.

## Finding 2 — no debounce on any live-search text field

`grep` for `onChanged:` on `TextField`/`TextFormField` alongside a check for any `Timer`/debounce helper in the same file: **9 files** have live `onChanged` handlers wired directly to state with no debounce anywhere in the file.

The one that matches your "typing lag" report most directly:

- `features/search/presentation/search_screen.dart:68` — every keystroke writes to `searchQueryProvider`, which immediately re-triggers a `FutureProvider` that runs an FTS5 query against SQLite. Type a 10-character query and you've fired 10 queries, each racing the previous one.
- `app/palette/command_palette.dart:188` — the ⌘K palette has the same pattern.

Also flagged, lower risk (shorter lists, less likely to be perceptible, but same pattern): `task_detail_screen.dart`, `settings_screen.dart`, `table_view.dart`, `calendar_screen.dart`, `widget_config_dialog.dart`, `linked_section.dart`.

Fix: wrap the state write in a 200-300ms debounce (a single `Timer` that resets on each keystroke and only fires the provider update when it elapses). Small, contained change per file — no architecture impact.

## What this doesn't explain

These two patterns account for scroll jank and typing lag specifically. If "not native feel" is about the interaction design (transitions, platform affordances) rather than raw responsiveness, that's a separate, subjective design question — not something a static scan can measure.

## What I can't tell you from a static scan

How many milliseconds a frame takes, which widget is actually over budget on your hardware with your real data volume, and whether there's a third culprit I haven't spotted from code inspection alone. That needs an actual frame trace, which requires running the app.

## Session 2 (live trace) — corrected diagnosis

A second trace, capturing task-list scrolling and view-mode switching, contradicted part of the original static-scan diagnosis and surfaced two different, measured problems:

- **No evidence of scroll jank.** The eager `ListView(children:...)` pattern (Finding 1 above) still exists and is still worth fixing, but it costs time when the list *rebuilds* — not while scrolling an already-built list, since pure scrolling repaints without rebuilding. The original framing overstated where that cost shows up.
- **Confirmed: a single task edit re-queries unrelated screens.** Editing one task re-fired ~9 providers together, repeatedly — task list, activity feed, project stats, task stats, contacts count, and the full contacts list. Root cause: tasks, projects, contacts, and events are all rows in one shared `objects` table, and drift's `.watch()` invalidates at table granularity, not per-row or per-type — any write to `objects` re-runs every query that reads it, regardless of which type actually changed.
- **Confirmed: an N+1 tag-query storm.** Switching the tasks view to Table mode fired 12 near-simultaneous tag queries — one per visible row, each an independent `objectTagsProvider(objectId)` subscription (`table_view.dart:456`), instead of one batched query for the visible rows.
- **One unexplained anomaly:** a single frame logged `build=0.5ms raster=1.4ms total=24.6ms` — build and raster together don't account for the total, meaning something stalled the pipeline outside both (possibly a GC pause or main-thread I/O). Not enough evidence to diagnose further; flagging rather than guessing.
- **Search still untested** — neither trace captured a search session with more than one keystroke, so the debounce concern from Finding 2 remains a static-scan hypothesis, not a measured one.

### Fixes applied

1. **Batched tag queries** (`core/objects/tag_repository.dart`, `core/objects/presentation/tag_section.dart`, `features/tasks/presentation/table_view.dart`): added `watchTagsForObjects(Set<String>)`, a single query for a whole visible set of rows, plus a `tagsForObjectsProvider` family keyed by a sorted id string (Riverpod families need value-equal keys; a raw `Set`/`List` doesn't have one, a `String` does). The Table view now issues one tags query for all visible rows instead of one per row.
2. **Debounced the aggregate providers implicated in the cross-type cascade**: `activityFeedProvider`, `tagCountsProvider` (dashboard), `contactsProvider`, `taskStatsProvider`, `projectStatusBreakdownProvider` — added via a small `Stream.debounce()` extension (`core/utils/stream_debounce.dart`), 200ms. This does not fix the over-broad invalidation itself (that's a schema-level property of the polymorphic `objects` table and would need a bigger, deliberate change — e.g. per-type change notifications — not a quick patch). It does stop a burst of edits from recomputing the same aggregate a dozen times in a row. Primary lists a user is actively editing (`allTasksProvider`, `smartListProvider`, `taskDetailProvider`) were deliberately left un-debounced — those need to feel instant.

### Still open

- The eager-list-building pattern (Finding 1) is unfixed — it just isn't the scroll-jank cause it looked like. Worth doing for rebuild cost, not scroll cost.
- The root cause of the cascade (shared `objects` table, table-level drift invalidation) is mitigated, not fixed. A real fix means either splitting the table by type or building a type-aware change-notification layer — a real architectural decision, not something to do as a drive-by.
- Search debounce is still unverified and unfixed — need a trace with an actual multi-keystroke search session to know if it matters in practice.

## Getting real numbers (needs your machine)

I added `app/lib/core/diagnostics/perf_diagnostics.dart` and wired it into `main.dart` (debug/profile builds only, zero cost in release). It does two things while you use the app normally:

1. Logs any frame whose build+raster time exceeds 16ms (i.e., missed 60fps), with the duration.
2. Logs every Riverpod provider update with a timestamp, so we can see exactly how many times `searchResultsProvider` (or anything else) fires during a session.

To use it: run `flutter run --profile` (profile mode gives realistic timings; debug mode is artificially slower), redirect or copy the console output while you scroll the laggy list and type in search, and send me that output — I'll turn it into a "component X cost Y ms" breakdown instead of the inference above.
