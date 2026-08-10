# Design: fewer, more capable dashboard widgets

**Status:** Design only, per your "could you design something" phrasing — not implemented yet, waiting on your go-ahead (and a couple of calls below) before touching code.
**Target codebase:** `webapp/` — `routers/dashboard.py`'s `WIDGET_TYPES`/`WIDGET_SOURCES`/`WIDGET_VIEWS`/`WIDGET_RANGES`, the `_widget_*.html` templates, and the widget-add/edit forms.

---

## 1. Why this is worth doing — the app already diagnosed its own problem

`dashboard.py` currently has **11 widget types**. Reading its own comments, this isn't a fresh observation — a prior pass already wrote this down and only half-fixed it:

> "Choosing a widget used to be one flat list... seven names that don't obviously relate to each other even though four of them are really the same underlying data, tasks+events, just sliced differently."

That prior pass built a friendlier Source → View → Range *picker* on top of the same 11 underlying types, rather than actually reducing how many types exist. The picker makes choosing less confusing; it doesn't make the dashboard itself simpler, and every one of the underlying types is still only medium-developed on its own. Concretely, today:

| Type | What it actually shows |
|---|---|
| `today_agenda` | Overdue + due-today tasks, today's events |
| `weekly_overview` | Tasks/events for the next N days, grouped by day |
| `upcoming_events` | Events only, flat list, next N days or all |
| `overdue_tasks` | Overdue tasks only |
| `at_a_glance` | Overdue/today/this-week *counts* (added last session) |
| `mini_month_calendar` | Small month grid, busy-day dots |
| `calendar_agenda` | Mini calendar + a 7-day agenda, stacked in one widget |
| `project_preview` | Spaces/projects as a list with progress bars |
| `filled_cards` | Spaces as colored Material cards |
| `habit_checkin` | Daily habit check-off |
| `contact_list` | Contacts filtered by label |

Five of these (`today_agenda`, `weekly_overview`, `upcoming_events`, `overdue_tasks`, and now `at_a_glance`) are all views over the exact same tasks+events data. `calendar_agenda` is literally two other widgets (`mini_month_calendar` + `weekly_overview`) pre-glued together. `project_preview`/`filled_cards` are two visual treatments of the identical Spaces/Projects data. That's the sprawl — and worth owning: my own dashboard-usability pass last session made this *worse*, adding `at_a_glance` and defaulting `overdue_tasks` into the seed on top of the existing five, without removing anything.

## 2. Proposed set: 11 types → 6

1. **At a Glance** — unchanged. Already minimal, already earns its place (nothing else shows a number instead of a list).
2. **Agenda** (new, replaces `today_agenda` + `weekly_overview` + `upcoming_events` + `overdue_tasks`) — one configurable widget instead of four:
   - Overdue items always lead, clearly marked — never something you have to remember to add a second widget for, which is the actual reason today's dashboard has both an Overdue widget *and* Today's Agenda (whose own query already silently included overdue anyway — the two currently overlap without either of them saying so).
   - Below that: the selected **Range** (Today / Next 7 days / Next 30 days / All upcoming), grouped by day when the range spans more than one day, flat when it's just Today.
   - A **Show** toggle: Tasks & Events / Tasks only / Events only (this is what preserves `upcoming_events`' events-only case without needing its own type).
   - Inline "mark done" checkboxes throughout, same as today's Today's Agenda/Overdue Tasks already have.
   - This is the "more fledged out" half of the ask: one widget that's strictly more capable than any single one of the four it replaces, not a lowest-common-denominator merge.
3. **Mini Calendar** — unchanged. A spatial/visual view is genuinely different from a list, worth keeping distinct.
4. **Spaces & Projects** (new, replaces `project_preview` + `filled_cards`) — one widget, a **Style** toggle: List (progress bars, compact — today's `project_preview`) or Cards (colored Material tiles — today's `filled_cards`), same underlying data either way. Enrichment while I'm in there: each row/card also shows a due-this-week count, not just overall progress — genuinely more informative than either original, not just a re-skin.
5. **Habit Check-in** — unchanged. Focused, already good, no overlap with anything else.
6. **Contact List** — unchanged. Same reasoning.

**Cut entirely: `calendar_agenda`.** Its exact effect — a mini calendar with a 7-day agenda underneath — is trivially reproduced by placing a Mini Calendar widget next to an Agenda widget (range = Next 7 days), which the grid already does well. One fewer type to explain in the picker, zero capability lost. Existing widgets of this type get migrated into that pair automatically (see §4), not silently deleted.

Net: **6 types**, each one either unchanged-because-it-was-already-good, or genuinely more capable than what it replaces — not just fewer for its own sake.

## 3. What doesn't change

- The widget grid mechanics themselves (add/resize/reorder/stack, the Customize modal) — already good, untouched.
- Per-page scoping (`_SCOPE_EXCLUDED_TYPES` — e.g. Filled Cards/Spaces&Projects not offered on a page that's already showing one Space) — same idea, updated for the new type names.
- The Source → View → Range *picker* concept — still the right shape for choosing a widget, just pointed at fewer, better Views (`calendar_tasks` source keeps `agenda`/`mini_calendar`/`at_a_glance_view`, loses `upcoming_list`/`overdue_list`/`calendar_agenda_view` as separate views since Agenda's own Range+Show config now covers what those used to be for).

## 4. Migration — nobody's existing dashboard silently breaks or loses data

Every current widget type maps onto the new set automatically, preserving intent as closely as possible:

| Old type (+ config) | New type + config |
|---|---|
| `today_agenda` | `agenda`, range=today |
| `weekly_overview`, range_days=7 (or unset) | `agenda`, range=next_7_days |
| `weekly_overview`, range_days=30 | `agenda`, range=next_30_days |
| `upcoming_events`, range_days=7/30/unset | `agenda`, range=next_7_days/next_30_days/all_upcoming, show=events_only |
| `overdue_tasks` | `agenda`, range=none, show_overdue=true (a "just overdue" range) |
| `calendar_agenda` | **two** widgets: `mini_month_calendar` (same filters) + `agenda` range=next_7_days, positioned adjacent to preserve the original side-by-side look |
| `project_preview` | `spaces_projects`, style=list |
| `filled_cards` | `spaces_projects`, style=cards |

Runs once (same `app_meta`-flag-guarded, idempotent pattern `_ensure_default_widgets`/`_relax_legacy_not_null` already use elsewhere in this app), rewriting every existing `dashboard_widgets` row's `type`/`config` in place — not deleting and reseeding, so hand-picked widths/heights/positions/filters survive untouched.

## 5. Decisions (confirmed 2026-08-07)

1. Agenda groups by day whenever its Range spans more than one day, flat list for Today — no separate toggle.
2. Spaces & Projects gets the due-this-week-count enrichment, not a pure re-skin.
3. Two more widgets confirmed missing from the original 11 and worth building new, not migrated from anything existing:

## 6. Two new widgets (net-new capability, not consolidation)

### 7. Streak
Current daily completion streak (consecutive days, including today if you've already completed something) + a small 7–14 day trend of tasks completed per day.

**Real data gap, flagging before building this rather than faking it:** this app has no reliable way to know *which day* a plain (non-recurring) task was completed. `tasks.status` flips to done/archived, but nothing records *when* that happened — `updated_at` changes on any edit, not just completion, so it can't tell "completed today" from "edited today for an unrelated reason while already done." (Recurring tasks already have this — `task_completions(task_uid, due_date, completed_at)` — but that's a different, narrower mechanism scoped to recurring check-offs, not every task.)

Proposed fix, small and justified: add a nullable `tasks.completed_at` timestamp column, set the moment a task's status transitions to done/archived (wherever that transition already happens — the "mark done" endpoints already used by Today's Agenda/Overdue Tasks' inline checkboxes), untouched on any other edit. This is the one schema change in the whole plan; everything else here is either pure consolidation of existing widgets or a read-only new widget over data that already exists.

**✅ Done (2026-08-07), ahead of the rest of this design's implementation:** `tasks.completed_at`, auto-managed centrally in `db.upsert_task` (set on the active→done/archived transition, cleared on the reverse, left alone on an unrelated edit while already done, and never re-computed for a JSON backup restore — that path writes the real historical value directly, see `routers/export.py`'s `_restore`). Tests in `webapp/tests/test_task_completed_at.py` (7 tests). Full suite green (525 passed). The Streak widget itself (reading this column) is still pending the rest of this design's implementation.

### 8. Next Deadline
A single, prominent countdown to whichever open task or event has the soonest due date/start time — "2 days until [title]," or an overdue variant if it's already passed. Deliberately the simplest possible selection rule (soonest date, full stop) rather than a priority-weighted pick — more predictable and trustworthy than a "smart" pick that might surprise you. Empty state ("Nothing on the horizon") when there's genuinely nothing due. No schema change needed — this is a read-only query over `due_at`/`start_at`, both already indexed.

Updated total: **8 widget types** (was 11): At a Glance, Agenda, Mini Calendar, Spaces & Projects, Habit Check-in, Contact List, Streak, Next Deadline.
