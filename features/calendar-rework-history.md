# Calendar rework — what was built, what to test, what's out of scope

> **Historical note (2026-07-17):** written against the old Flutter client
> (`app/`, now removed) and its FastAPI/Postgres HLC/LWW sync. The app was
> subsequently rebuilt in PySide6 with a file-tree + Syncthing sync model —
> see `ARCHITECTURE.md` and `REWORK_PLAN.md`. Kept as a record of the
> calendar feature decisions made here; file paths and the sync mechanism
> below are no longer current.

## Scope, as agreed

"WebDAV/CalDAV feature parity" was clarified to mean: match what a
CalDAV-based calendar client typically *feels* like to use (multiple
calendars/lists, per-list colors and toggles, drag/resize) — not an actual
network integration with a CalDAV/WebDAV server. No CalDAV protocol, auth,
or ICS parsing was built, and none is needed for what was asked. New data
(calendars) syncs through this app's existing HLC/LWW op-log sync, the same
mechanism everything else already uses — no separate sync path was added.

## ⚠️ Required step before this compiles: regenerate Drift code

A new table (`Calendars`) was added to `app/lib/core/db/tables.dart` and
registered in `app/lib/core/db/database.dart`. Drift's `database.g.dart` is
generated code — it was **not** regenerated here (no Flutter/Dart toolchain
in this environment). Before building, run, from `app/`:

```
dart run build_runner build --delete-conflicting-outputs
```

Until that runs, `Calendar`, `CalendarsCompanion`, and `AppDb.calendars` (all
used throughout the new code) won't exist and the project won't compile.
Schema version was bumped 6 → 7 with a migration that creates the table —
existing local databases upgrade automatically on next launch.

## What was built

**Data model** — a new `Calendars` table (id, name, color, created/deleted
at), synced like `Tags`: its own repository (`CalendarRepository`), its own
entry in the field registry (client `field_registry.dart` + server
`registry.json` + `schema.sql`, kept in lockstep same as every other
entity). The existing `event_details.calendar_id` column existed but was
dead code before this — it's now wired up end to end.

**Visibility (toggle lists on/off)** is deliberately *not* a column on the
calendar row — it's a per-device preference stored in `Meta` (same
reasoning as `ThemeSettings`: which calendars you want to see is a display
choice, not shared data). A hidden calendar still keeps its events in the
database; it's filtered out of the visible occurrence list, nothing is
deleted.

**Pastel colors** — an 8-color pastel palette (`calendarPalette` in
`calendar_repository.dart`). Every calendar gets one at creation (assigned
by name hash, or picked explicitly in the "new list" dialog); events with
no calendar (pre-existing data) render in a neutral pastel gray rather than
being left uncolored.

**Dynamic sort** — a Time / Priority / List sort control on the compact
Agenda view. Month and week grids weren't given a sort control because
sorting a spatial grid doesn't mean anything — position there is already
determined by date/time.

**Drag-to-move** — month grid: drag a chip onto a different day; the event
(and its end, if it has one) shifts by that many days, preserving
duration. Week view: drag a block anywhere in the 7-day×hour grid,
including across days; drop position is converted through a single
`GlobalKey` on the whole grid rather than one drop-zone per day column —
simpler, and it already accounts for scroll offset for free via Flutter's
normal global-to-local transform.

**Resize** — week view only (a day cell in month view has no time axis to
resize against). Thin drag handles on the top/bottom edge of each block;
live preview while dragging, snapped to 15 minutes on release, minimum 15
minute duration enforced.

## The one deliberate limitation: recurring events

Dragging or resizing a recurring event's occurrence is **disabled**
(`Occurrence.isRecurring`). The reason: an expanded occurrence's time isn't
independently stored — there's no per-instance exception record, only the
master event's `start_at` + its RRULE. Writing a dragged occurrence's new
time back to the master's `start_at` would re-anchor the *entire series*,
which is only unambiguous for the very simplest recurrence rules and
actively wrong for others (it can shift which days future/past occurrences
fall on). Rather than silently produce a plausible-looking but semantically
wrong result, recurring occurrences render normally but aren't draggable or
resizable. Making single-occurrence edits work for real needs per-instance
exception records (the same concept CalDAV's `RECURRENCE-ID` overrides
solve) — a real feature addition, not a bug fix, and out of scope here.

## What needs hands-on testing (couldn't be verified without a running app)

There is no Flutter SDK or display in this environment, so none of this
was ever actually run. Two spots carry real gesture-conflict risk that only
shows up at runtime:

1. **Month grid**: an event chip's `Draggable` sits inside the grid's own
   pan-to-create gesture region (drag-across-empty-days creates a new
   event). The design relies on Flutter's normal behavior of letting a
   more specific/descendant gesture recognizer (the chip's drag) win over
   a broader ancestor one (the grid's pan) when the gesture starts on the
   descendant — the same precedence a draggable list tile relies on inside
   a scrollable. It should work; it hasn't been run.
2. **Week view resize handles**: the same precedence assumption, nested
   one level deeper — a resize handle's plain drag detector sits inside
   the event block's own `Draggable`. Dragging from the 6px edge strip
   should trigger resize, not a whole-block move; dragging from the middle
   of the block should move it.

If either behaves unexpectedly (e.g. the wrong gesture wins, or both fire),
the fix is usually to make the outer gesture explicitly lose via
`Listener`/`HitTestBehavior` adjustments or an `IgnorePointer` toggle rather
than a rewrite — flagging it now so it's not a surprise.

## Files touched

`core/db/tables.dart`, `core/db/database.dart`, `core/objects/field_registry.dart`,
`core/objects/calendar_repository.dart` (new), `core/services.dart`,
`server/registry.json`, `server/schema.sql`,
`features/calendar/application/providers.dart` (new),
`features/calendar/presentation/calendar_legend.dart` (new),
`features/calendar/presentation/calendar_screen.dart`,
`features/calendar/presentation/week_view.dart`,
`features/calendar/presentation/event_detail_screen.dart`,
`features/calendar/data/calendar_queries.dart`.
