# Plan: Dashboard usability & functionality rework

**Status:** Planning only — pausing here for your go-ahead before touching code, since this is more of a judgment call (what belongs on a home screen) than a mechanical fix like the last few passes.
**Target codebase:** `webapp/` — `routers/dashboard.py`, `dashboard.html`, `_widget_*.html` templates, `static/style.css`.

---

## 1. What's actually there today (audit, not assumptions)

The widget system itself is genuinely good: 9 widget types (Today's Agenda, Mini Calendar, Weekly Overview, Upcoming Events, Overdue Tasks, Project Preview, Habit Check-in, Calendar+Agenda, Contact List, Filled Cards), resizable (third/half/two-thirds/full width × short/medium/tall/xl height), reorderable, stackable, with a real add/customize modal. Widgets are already reasonably actionable, not just read-only — Today's Agenda and Overdue Tasks both have an inline "mark done" checkbox right in the row, no navigating away needed.

The problems are in what a *new* dashboard actually shows and how it orients you, not in the underlying system:

1. **Overdue Tasks isn't in the default seed.** A fresh Home ships with Calendar+Agenda, Today's Agenda, Weekly Overview, Upcoming Events (`routers/dashboard.py`'s `_DEFAULT_WIDGETS`) — the one widget that answers "what did I drop" isn't there until you manually add it. For a task-management-flavored app, that's arguably the single most important thing to surface by default, not an opt-in.
2. **No at-a-glance summary.** Nothing on the page answers "how am I doing" in under two seconds — no overdue count, no "3 due today," nothing. You have to actually read through widget contents to know if you're behind. Every widget type that exists renders a *list*; none renders a *number*.
3. **No orientation/context at the top.** The page header is a static "Dashboard" `<h1>` — no date, no sense of "what today is" before you start reading widgets below.
4. **Quick-capture is task-only.** The one friction-reducing shortcut on Home (`#quick-add-form`) only creates tasks. Jotting down an event ("dentist at 3pm") or a quick note needs a full navigate-away-and-back trip.
5. **Mobile's "See more" is a bare link list** (Projects/Habits/Settings) with no information in it — on a screen already worse-positioned to show much, it wastes the one spot with a plain nav list instead of anything useful.

## 2. Real-user-design reasoning behind what I'd change

The organizing principle for a personal command-center home screen: **answer "what needs me right now" before anything else, in the order of how urgent it is** — overdue, then today, then this week, then everything else. Right now the default layout doesn't reflect that priority order at all (Weekly Overview, a full-width block, currently outranks Overdue Tasks, which isn't even present).

Second principle: **orientation before detail.** A glance at the top of the page should answer "am I behind" before you read a single list. That's what a stats strip is for — not decoration, a triage tool.

Third: **reduce the cost of capturing a thought**, since the whole value of a quick-add box is that friction near zero is what makes people actually use it instead of opening a phone notes app instead. Task-only quick-add is half the value.

I'm deliberately *not* proposing a visual redesign of the widget system itself (colors, card style, grid mechanics) — it already works, resizes, and reorders well, and a full teardown risks specifically the kind of low-value churn this app's own house rules warn against. This is about **defaults and one missing widget type**, not rebuilding what's already good.

## 3. Proposed changes

### 3.1 New widget type: "At a Glance" stats strip
A new `WIDGET_TYPES` entry — a compact row of number+label pairs (Overdue, Due today, Due this week, optionally Habits streak-active-today) computed the same way the existing Overdue/Today/Weekly widgets already query, just aggregated to counts instead of full lists. Each number links straight to the filtered Tasks view that explains it (e.g. "3 overdue" → `/tasks?status_filter=active&date_filter=overdue`, whatever the real filter param combination is — check `routers/tasks.py`'s actual filter vocabulary before wiring this). Full-width, short height, first in the default seed order.

### 3.2 Default seed reorder + addition
New default order: **At a Glance** (top, full width) → **Overdue Tasks** + **Today's Agenda** side by side (was Calendar+Agenda + Today's Agenda) → **Calendar+Agenda** (moved down, still useful but not the first thing) → **Weekly Overview**. Overdue Tasks added to `_DEFAULT_WIDGETS`, not just available as an opt-in add.
This only affects *fresh* installs (`_ensure_default_widgets`' one-time seed, per its own docstring) — existing widget layouts are never touched, consistent with that function's already-documented "customizable means reshape from here, not that it starts blank" contract.

### 3.3 Header: date + light greeting
Replace the static "Dashboard" `<h1>` with the current date (e.g. "Friday, August 7") and a one-line, non-gimmicky context line only when there's something worth saying (e.g. "3 things need you today" when the at-a-glance numbers are non-zero, nothing extra when the day's actually clear — a manufactured "Good morning!" with nothing behind it is worse than no greeting at all).

### 3.4 Quick-capture: add an event option
Extend the single quick-add box into a two-tab or toggle affordance (Task / Event) — same title-only, Enter-to-submit, no-JS-required pattern the task version already uses, just posting to `/events` instead when Event is selected. Keep it a plain form with a working no-JS fallback, matching the existing quick-add's own stated design constraint.

### 3.5 Mobile "See more": make it earn its slot
Add the at-a-glance numbers (§3.1) to the top of the mobile-only "See more" card, above the existing Projects/Habits/Settings links — the same information desktop gets from the stats widget, since mobile's narrower viewport is exactly where "how am I doing at a glance" matters most and is currently entirely absent.

## 4. What I'm explicitly not doing here

- No visual/token redesign (colors, card shape, spacing) — the M3 pass already covers this app-wide, this plan is about content and defaults.
- No changes to the widget *system* (add/resize/reorder/stack mechanics) — it works.
- No new backend features beyond the stats aggregation query (§3.1), which is arithmetic over data every other widget already fetches, not a new capability.
- Not touching Space/label pages' widget grids (`routers/labels.py`'s `label_detail` reuses this same system) — scoping this to Home specifically since that's what was asked; the same defaults question could be asked about Space pages later but that's a separate call.

## 5. Open questions before I implement

1. **Stats strip exact metrics** — Overdue/Due today/Due this week is my proposed set; do you want habit streaks or anything else in it too?
2. **Quick-capture UI**: a tab switcher (Task/Event) above one input, or two separate always-visible inputs? Tabs are more compact; two inputs need no interaction to switch but take more vertical space.
3. **Greeting line**: fine with the "only speak when there's something to say" approach in §3.3, or did you want something closer to a literal "Good morning" style greeting regardless of whether anything's due?
