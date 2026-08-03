# Plan: Calendar views vs. the Apple/Google reference doc

**Status:** Proposed · logged 2026-07-19
**Reference:** [`../apple-vs-google-calendar-views.md`](../apple-vs-google-calendar-views.md)
**Feature areas:** [`../features/calendar.md`](../features/calendar.md), [`../features/design-system.md`](../features/design-system.md), [`design-alignment.md`](design-alignment.md)
**Code:** `desktop/src/features/calendar/widgets.py` (996 lines, one file — `MonthGrid`, `WeekGrid`, `DayGrid`, `AgendaList`, `_EventBlock`, `CalendarView`)

## Correction first: Month view is not what `calendar.md` says it is

Before comparing against Apple/Google, a direct read of `widgets.py` turned up a gap between what `calendar.md`'s "Views" section claims and what the code does. `MonthGrid` (lines 47–183) has no mouse-event handling at all beyond the prev/next-month nav buttons. Day cells (`_create_day_cell`) are plain `QFrame`s with no click handler; event chips are plain `QLabel`s with no drag support, no mime data, no `QDrag` anywhere in the file. There's no `eventFilter`, no `dragEnterEvent`/`dropEvent`, nothing in `app.py` wiring a day-click to an agenda panel. Grepping the test suite confirms it: `test_views.py`/`test_interactions.py` have no test exercising a month-view click or drag.

So "Click a day for an agenda side panel," "Drag a chip to reschedule," and "Pan across empty days to create a new event" — all three claimed in `calendar.md`'s Month grid bullet — describe zero lines of actual code. By contrast, Week/Day's drag-to-move and drag-to-resize (`_EventBlock`) are real, were bug-fixed twice (2026-07-18/19, see `calendar.md`), and have a passing test. This matters for prioritization below: Month view isn't behind Apple/Google on some nuanced visual point, it's non-interactive. `calendar.md` should be corrected to say so; that's a one-line doc fix, done separately from this plan.

## What the reference doc actually implies for this app

The app's own design direction (`design-system.md`, "ModernPlasma Productivity" reference) is explicitly low-chrome, native-Qt-palette, macOS/Darkly-styled — no persistent sidebar-heavy toolbar, minimal custom QSS. That's Apple's philosophy, not Google's: Google's Calendar is deliberately chrome-heavy (persistent sidebar, mini month-picker, search icon, density toggle) because its center of gravity is shared/collaborative scheduling. This app has no collaboration story (no accounts, no invitees, no RSVP — confirmed by `EventDetails` having no attendee field, just `location`/`meeting_url`/`reminders`, none of which are even exposed in the inspector yet per `calendar.md`'s "Event detail" correction). So the default posture below is: adopt Apple's low-chrome model, and only borrow the specific Google mechanics that are pure usability wins with no added chrome (a continuous multi-day bar, a current-time line — Apple has a quiet version of the latter too, so this isn't actually a Google-only idea).

Explicitly **not** recommended: Apple's three month-view density modes (Compact/Stacked/Details). That's an iPhone-screen-size accommodation; on a desktop window there's no small-screen pressure driving it, and building three renderers for one grid to solve a problem this app doesn't have would be scope for its own sake. The current single "Details"-equivalent (truncated title chips + "+N more") is the right choice already, once it's made interactive.

## Priority-ordered items

### 1. Make Month view interactive (highest priority — closes the doc/code gap above)

Three separate pieces, each independently useful:

- **Click a day → open its agenda.** Subclass the current `QFrame` day cell (`_create_day_cell`) as a small `_DayCell(QFrame)` that overrides `mousePressEvent` and emits a `day_clicked(date)` signal up to `MonthGrid`, then `CalendarView`. Cheapest option: reuse `AgendaList` filtered to a single date rather than building a new side panel — `AgendaList._rebuild` already takes a date range (see `DAYS_TO_SHOW` and `expand_recurring_objects(self._objects, today, today + timedelta(...))`); generalize that to accept an explicit `(start, end)` instead of always "today + 30" and reuse it as the click target. Avoids a second agenda-rendering implementation.
- **Click a chip → open the inspector**, same `open_object_requested` signal `_EventBlock.context_action` already uses in Week/Day. This is the cheap win: chips are `QLabel`s today; either swap to a small clickable label subclass or wrap in a button-like frame. Do this before drag — it's most of the value (open/edit) for a fraction of the effort.
- **Drag a chip to reschedule.** Real effort: needs `QDrag`/`QMimeData` on the chip (carry the object id) and `dragEnterEvent`/`dropEvent` on `_DayCell` to accept it and shift `due_at`/`start_at` by the day delta — same delta-shift logic `_EventBlock`'s move handler already uses (`old_start + timedelta(...)`), just day-granularity instead of minute-granularity, and updating `due_at` (a date string) rather than `start_at` (a datetime string) for the common case of an all-day/dateless task. Sequence after the two items above since click-to-open alone removes most of the urgency.

Pan-to-create (empty-cell drag spanning multiple days to create a multi-day event) is the least valuable of the three original claims — this app's events are typically single-day per `calendar.md`'s model — and can be dropped from scope rather than built to match a stale doc.

### 2. Multi-calendar color-coding (real feature gap, not a doc error)

`calendar.md`'s "Multi-calendar" section describes named, color-coded calendars with a legend panel and per-calendar visibility toggle. Checked against the code: `EventDetails.calendar_id` exists on the model and in the SQLite schema (`core/db/schema.py:49`) but has exactly three references in the whole `desktop/` tree — all just the field declaration (`object.py`, `schema.py`, `registry.py`). Nothing reads it, nothing writes it, no UI sets it. Every chip and block in `app.py`'s QSS (`cal-event-chip`, `cal-event-block`) renders from one single global `{accent}` color — there is no per-calendar color anywhere today. The "legend panel" and "pastel palette" described in `calendar-rework-history.md` were built for the old Flutter client (explicitly marked historical, pre-rewrite) and never carried over to the PySide6 rebuild.

This is bigger than item 1: it needs (a) a place to define calendars — reuse `ProjectDetails.color`'s pattern (a small persisted list of `{id, name, color}`, likely alongside tag colors in `settings.json` rather than a new SQLite table, consistent with how tags/visibility-toggles are already per-device `Meta`/settings rather than schema, per `calendar-rework-history.md`'s own reasoning for why visibility was a preference not a column) and (b) UI to assign an event's `calendar_id` — which depends on `calendar.md`'s already-flagged gap that the inspector has *no* event-specific fields UI at all yet (no location, meeting-url, or calendar-selector control exists). Building calendar-color assignment without that inspector UI first would mean no way to actually set `calendar_id` on an event. **Recommend sequencing:** build the event-specific inspector section (calendar.md's own open item) and the calendar-color-picker as one combined piece of work, then wire `cal-event-chip`/`cal-event-block` QSS to read per-object color via a dynamic property instead of a fixed class, mirroring how `priority-1..4` already varies by dynamic property today.

### 3. Current-time indicator line (Week/Day grids)

Cheap, self-contained. Neither Apple's thin quiet line nor Google's bold red one exists in this app at all today — `calendar.md` doesn't claim it, and there's no such widget in `WeekGrid`/`DayGrid`. Add a thin `QFrame` positioned absolutely (same overlay technique `_EventBlock` already uses — `block.setGeometry(...)` on the scroll-area's container) at `top = current_minutes_from_midnight / 60 * HOUR_HEIGHT`, spanning the day-column(s) currently in view, only drawn when the visible date range includes today. Refresh on a `QTimer` (60s interval is plenty). Given the app's low-chrome direction, default to Apple's quieter treatment (a slim line, not full-saturation red) — consistent with `design-system.md`'s "Left alone, deliberately" preference for restraint over Google's more assertive style elsewhere in this same file.

### 4. Click/drag-to-create in Week/Day time grid

Currently absent for both platforms' equivalent (Apple: tap-and-hold an empty slot; Google: click for inline quick-create popover). This app has no click-to-create anywhere in the time grid — `_EventBlock` only exists for already-created events, and the grid `QFrame` hour cells (`cal-hour-cell`) have no mouse handling. Recommend Apple's modal-editor pattern over Google's inline popover: the app already has one editing surface (`InspectorPanel`, per `design-alignment.md`) and a second, competing quick-create popover would fragment that — especially since `design-alignment.md` already has an open item to turn `InspectorPanel` into a slide-over. Simplest implementation: click an hour cell → create a new `Object(type=event, start_at=<clicked time>, ...)`, write it, then emit `open_object_requested` to open it in the existing inspector immediately, same as clicking an existing block does today.

### 5. Continuous multi-day/all-day bar in Month view (Google-style)

Google draws one continuous colored bar across the cells a multi-day event spans; Apple truncates per-cell (this app currently does the latter — `MonthGrid._rebuild` matches objects to a single `day_date` per cell, no spanning). This is worth borrowing regardless of the Apple/low-chrome default above, because it's a legibility improvement with no chrome cost, not a stylistic Google-ism. Real effort, though: `QGridLayout` cells don't support a widget spanning arbitrary non-adjacent visual space cleanly when other content shares the row. The `WeekGrid`/`DayGrid` precedent is the way to do this — those don't fight the grid layout for event positioning at all, they lay hour-cells with `QGridLayout` for the static background *and then* position `_EventBlock`s as absolutely-geometried overlay children on top of the same container. Do the same for Month: keep the day-number grid as-is, add a second overlay pass that draws multi-day-spanning bars in the space above each week-row's cells. Sequence this after item 2 (calendar colors) since a spanning bar is exactly the kind of element that most wants per-calendar color to be legible when several span the same week.

### 6. Interactive "+N more" (Month view)

Currently a static, unclickable `QLabel` (`_rebuild`, the `more = QLabel(f"+{len(day_objs) - 3} more")` line). Google expands it into a popover; cheapest fix here is a `QMenu`/small popup listing the overflow items' titles, opened on click, each entry wired to `open_object_requested` — a few-line change once item 1's day-cell click handling exists to hang it off of.

### 7. Agenda view — no change needed

`AgendaList` is already a persistent, equal-status tab in the view switcher (`CalendarView.__init__`, `views = [("Month", ...), ("Week", ...), ("Day", ...), ("Agenda", "agenda")]`) with rich per-entry rendering (time, icon, title, priority, type badge) — structurally that's Google's first-class Schedule view, not Apple's minimal, buried List view. Given this app is a single-user daily-driver tool rather than a collaboration surface, that's the right call already and the doc doesn't suggest changing it.

## Suggested build order

1 (Month click-to-open + click-to-open-chip) → 3 (now-line, independent, cheap, do any time) → 6 (interactive +N, depends on 1) → 4 (click-to-create in time grid) → 1's drag-to-reschedule tail → 2 (calendar colors, bundled with the inspector's missing event fields) → 5 (spanning multi-day bar, depends on 2 for color legibility).

Items 1 (partial), 3, 4, and 6 are each small, independently shippable, and testable the same way the existing recurrence/overlap work was (drive the real widget, write, read back off disk — `calendar.md`'s established verification pattern). Items 2 and 5 are real features, not polish, and should each get their own session rather than being folded into a "make it look more like X" pass — same reasoning `calendar-and-tasks-rework.md` already applied to CalDAV.
