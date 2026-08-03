# Audit: user-action pipelines in the webapp (Tasks, Calendar, Dashboard)

**Status:** Open · audit only, no code changes · logged 2026-08-01
**Scope:** `webapp/` only, limited to the three primary daily-use categories per explicit request: Tasks, Calendar (including the Schedule modal, now reached from Calendar), Dashboard. Contacts/Habits/Projects/Databases/Settings were deliberately excluded from this pass.
**Method:** every action below was traced against the actual current templates/routers/JS, not general impressions — file and line references throughout are real, not illustrative. A "pipeline" here means: trigger → intermediate steps → what the user sees change → final state, end to end.

This is a snapshot after a large round of interaction-layer work already shipped this session (toast/undo, confirm sheets, sheet-modals, pointer-events, loading feedback, FAB, edit-mode gating). The findings below are what's genuinely still inconsistent or friction-heavy on top of that baseline, not a re-statement of what's already fixed.

---

## 1. Tasks

### Create
**Table view** (`tasks_list.html`) and **Board view** (`tasks_board.html`): "+ New task" button → opens `/tasks/new` as a modal (`data-modal`) → `task_form.html` → Save → full page reload of `/tasks`.
**Timeline view**: same button, plus a genuinely different path — click-and-drag on empty canvas creates a task directly (no form at all), defaulting to a 1-day span from wherever you dragged.

Assessment: consistent entry point (same button, same modal, same form) across Table/Board. Timeline's drag-create is a nice accelerator but is the *only* one of the three views that lets you skip the form entirely — there's no equivalent "type a title, hit Enter, done" quick-add anywhere in Table or Board, even though this is by far the most common action in a task manager. Every other new-task path requires opening a full field-grid form (title, description, due date, priority, status, list, tags, recurrence) even if all you wanted was to jot down a title.

**Recommendation:** a single-line quick-add input pinned to the top of Table/Board (title only, Enter to submit, defaults for everything else) would remove the modal round-trip for the majority case. The form stays as-is for anyone who wants the full fields.

### View / Edit
Table & Board: click a task title → opens `/tasks/{uid}` as a modal (`task_detail.html`, view-only) → separate "Edit" button inside that → opens `/tasks/{uid}/edit` as a *second* modal layer (replaces the first modal's content).
Timeline: click a bar → same detail modal directly (no separate view step described in the bar itself, but the endpoint is the same).

Assessment: this is a two-step "view, then click Edit to actually change anything" pipeline for every field except status/priority/due date/checklist/subtasks (which edit inline from the detail view itself). That's an unusual split — you can toggle a checklist item, add a subtask, or delete the task straight from the view, but changing the title or description requires a second modal hop. Calendar's event flow, by contrast, has no separate view step at all (see below) — clicking an event goes straight to the editable form. The inconsistency between "Tasks view-then-edit" and "Calendar edit-directly" is worth resolving one way or the other, not necessarily by copying Calendar's approach (task detail's checklist/subtasks genuinely benefit from a dedicated view), but the split itself should be a deliberate choice, not an artifact of the two features being built at different times.

### Status change (the actual "mark done" action)
There are **two different pipelines for the same outcome**, and they behave differently:
- **Status pill dropdown** (Table view, `tasks_table.js`): change the `<select>`, fires a `fetch()` POST to `/tasks/{uid}/update-field`, the pill recolors in place. No reload, no page flicker. This is the good version.
- **"Mark done" checkbox** (Table view, same row, `tasks_list.html` line 71-73; Subtasks list in `task_detail.html` line 97): plain form POST to `/tasks/{uid}/complete`, which redirects to `/tasks` with `status_code=303` — a full page reload just to flip one task to done, even though the row already has a Status pill sitting right next to it that can do the exact same thing inline.

This is the single clearest inconsistency found in this audit: **two controls in the same row, one instant, one a full reload, for an overlapping outcome.** The checkbox is also a strictly worse version of "set status to Done" via the pill — it does nothing the pill can't already do inline.

**Recommendation:** either drop the checkbox entirely (the Status pill already covers "mark done" — select "Done" from the dropdown) and free up that column, or make the checkbox POST via the same `tasks_table.js` fetch pattern (`update-field`, `field: "status", value: "done"`) instead of a page-reloading form. The second option preserves the one-click affordance for the single most common action in the app without the reload.

### Delete
Table row, `task_detail.html`, `task_form.html`: all three delete forms lack `data-delete-undo` / `data-confirm-sheet`, so all three fall through to `app.js`'s generic fallback — a confirm sheet reading only *"Delete this item? This cannot be undone."* Compare to Dashboard's widget delete or Projects/Habits/Databases' archive actions, which either get a specific message or real undo.

A task is one of the cheapest, most redoable objects in this app to accidentally delete and regret — arguably a *better* undo candidate than the dashboard widget delete that already has one. It currently has none, and its confirm message doesn't even mention that deleting a parent task cascades to its subtasks (the button *label* says "(and its subtasks)" when subtasks exist, but the confirm sheet text is generic and doesn't repeat that warning at the moment of confirmation).

**Recommendation:** give task delete the same `data-delete-undo="{{ task.title }}"` treatment as the dashboard widget (delay-based, cancelable, no backend change needed) for the common case, and keep an explicit `data-confirm-sheet` with the subtask-cascade warning specifically when `subtasks` is non-empty (a real "this will also delete N subtasks" message, not "this cannot be undone").

### Reorder / bulk actions
Kanban drag-and-drop between columns exists and works (touch and mouse, per the earlier pointer-events pass). There is no bulk select/bulk action anywhere in Tasks (no "select 5 tasks, delete/tag/move them together") — every action is single-row. For a to-do app used daily this is a common request once the list grows; noting it here as a gap rather than a broken pipeline, since it was never built, not regressed.

### Filter / search
Table & Board share the same filter-bar shape (search + list + date/status/priority selects), each `onchange="this.form.submit()"` — a full page reload per filter change. This is consistent across both views, which is good, but it does mean every filter tweak is a full round trip rather than an instant client-side or fetch-based re-render. Given the table is typically small (the codebase's own comment elsewhere estimates ~15 rows), this is a reasonable, deliberate tradeoff (no-JS-required, server is always the source of truth) rather than an oversight — flagging it only because it's the slowest-feeling part of Tasks' everyday use, not because it's wrong.

---

## 2. Calendar (Month/Week/Day/Agenda + the Schedule modal)

### Create
Month view: click a day (no drag) → 1-day quick-add; click-and-drag across days → multi-day range — both go straight to `/events/new` prefilled, as a modal.
Week/Day view: hover previews a snapped ghost block; click creates a 1-hour event; click-and-drag picks a custom length — same modal.
Agenda view: no create-by-click (it's a list, not a grid) — only the toolbar's "+ New event" button.

Assessment: this is the most refined create pipeline in the app — hover preview, snap-while-dragging, and a sensible click-vs-drag distinction (a tap creates a sensible default, a drag lets you be precise) are all present and, per the earlier pointer-events work, functional on touch too (with the known, deliberate tradeoff that touch gets tap-to-create but not drag-to-create on Month/Week/Day, since that surface also needs to remain scrollable). Agenda's lack of any create shortcut is a minor, defensible gap (there's no "empty space" to click in a list view).

### View / Edit
Clicking an existing event goes **directly** to the editable form (`event_form.html`) — no separate read-only detail view the way Tasks has one. One click, one modal, immediately editable.

This is worth calling out explicitly as the *better* pattern relative to Tasks' two-step view-then-edit — not because Tasks is wrong to have a richer detail view (checklists/subtasks genuinely need one), but because the Calendar pattern proves the one-step version is what this app defaults to everywhere else, making Tasks' extra hop the outlier rather than the norm.

### Delete
Same finding as Tasks: `event_form.html`'s delete button has no `data-delete-undo`/`data-confirm-sheet`, falls to the generic confirm-sheet. An event is just as cheap to recreate as a task, and is arguably an *easier* undo candidate (no cascade concerns at all, unlike a task with subtasks) — currently gets the least helpful treatment of any deletable object in the app.

### Move / resize
Week/Day drag-to-move and drag-to-resize an event: works, snaps live, shows a drop-hover cue on the destination column, persists via `/events/{uid}/reschedule`, then **always does a full page reload on completion** (`calendar.js`'s `end()`: `.finally(() => window.location.reload())`) — even though the drag itself was a smooth, optimistic, no-reload interaction the whole way through. The same is true of Schedule's identical drag mechanics (`schedule_grid.js`).

This is a real seam: 100% of the interaction feels instant and modern until the very last step, where it hard-reloads the page. Contrast with Tasks' Kanban drag (`tasks_board.js`), which does the DOM move optimistically and only reloads *on failure* — success is silent, no reload at all.

**Recommendation:** make Calendar/Schedule's drag-to-move match Kanban's own pattern — trust the optimistic client-side position on success, only reload (or toast + revert) on an actual failure response. This removes the one remaining moment where a fluid drag interaction ends in a jarring flash.

### Schedule (now a Calendar-nav modal button)
Table view inline edits (`schedule_table.js`) and the weekly grid's drag (`schedule_grid.js`) both work inside the modal now (this session's fix). Holidays are a collapsed section on the same page rather than a separate destination. Settings moved fully to the app Settings hub. This category's pipeline is now the most consistent it's been — flagging only the same generic-delete-confirm and full-reload-on-drag-success issues already named above, since Schedule shares both scripts with Calendar.

### Multi-calendar visibility
The calendar-visibility multiselect (`_calendar_nav.html`) toggles each calendar via its own real POST + page reload per checkbox click, one request per toggle. If someone wants to hide three calendars at once, that's three separate page reloads. A "apply" step, or converting the toggles to fetch-based (matching the Status pill's pattern in Tasks) would remove the reload-per-click cost — flagged as low-priority since calendar visibility isn't a frequent action, but it's the same "checkbox that reloads the page" pattern already flagged as the Tasks checklist item above.

---

## 3. Dashboard

### Create (add a widget)
"Add widget" is a `<details>`/`<summary>` disclosure at the bottom of the page containing a full field-grid form (type, title, width, project, tags, limit, task lists, calendars) → Save → full page reload. This is the only "create" pipeline on the Dashboard (there's nothing else to create here) and it's reasonably discoverable, but it's positioned at the very bottom of the page, below every existing widget — on a dashboard with several widgets already, a new user has to scroll past all of them to find how to add one. The "No widgets yet" empty state does surface a hint ("Add one below"), but only when the dashboard is empty; once it has even one widget, the add-widget control has no visible presence above the fold.

**Recommendation:** surface "Add widget" as a persistent toolbar button (next to the new "Edit layout" toggle) rather than only as a footer disclosure — the disclosure panel itself can stay as the actual form, just triggered from a visible, always-present entry point instead of scroll-to-find.

### Edit layout (move/delete widgets)
Just shipped this session: hidden by default, revealed via the "Edit layout" toggle (`?edit=1`, no JS). Once revealed, move up/down is a plain form POST + full reload per click (`/dashboard/widgets/{uid}/move`) — three widgets down means three page reloads. Same underlying pattern as Kanban's *old* behavior before that was upgraded to optimistic drag-and-drop.

**Recommendation:** the widget grid is a strong candidate for the same treatment Kanban already got — drag a widget card to reorder, optimistic DOM move, POST in the background, reload only on failure. This would also make "reorder" and "resize" (the Width picker) feel like one coherent "arrange your dashboard" interaction instead of two separate form-based tools (a details/summary Filters panel for width, plain buttons for order).

### Delete (remove a widget)
This one already has the good pattern — `data-delete-undo` (this session's own earlier work), row hides immediately, toast with Undo, no confirm-sheet needed since it's cheap to redo. Worth noting as the one Dashboard action that's already at the standard the rest of the app should be brought up to.

### Habit check-in / project preview widgets
Checkbox toggle (`/habits/{uid}/entries/{date}/toggle`) and the quantity "+1" button both redirect back to referer on success — correctly lands back on the Dashboard rather than bouncing to the habit's own page (this session's fix). This is a full page reload per click, though, same as the Calendar visibility toggles above — checking off a habit re-renders the entire Dashboard (every other widget's data too) just to update one row's checkmark.

**Recommendation:** lowest priority of everything in this document (it works, and dashboards are viewed, not spammed with clicks), but if this widget sees heavy daily use, converting the toggle/+1 buttons to the same `fetch()`-and-update-in-place pattern `tasks_table.js` already established would remove the full-page flash for what's meant to be a fast, frequent tap.

### Month navigation (mini calendar)
Prev/next arrows, plain links (`?cal_year=&cal_month=`), full reload — consistent with this app's stated no-JS-required philosophy, and consistent with how Calendar's own month view already works. Not flagged as an issue; included here only to note it was checked and found consistent, not overlooked.

---

## Cross-cutting patterns (same issue appearing in more than one category)

1. **Delete confirmation is a two-tier system in practice, and Tasks/Events landed on the worse tier.** Dashboard widgets, and Projects/Habits/Databases archive actions (from earlier sessions) get either real undo or a specific, accurate confirm message. Task and Event delete — arguably the two most frequently deleted object types in the whole app — get only the generic fallback. This is the highest-value fix in this document: it's a small, mechanical change (add `data-delete-undo` or a specific `data-confirm-sheet` message to two forms) with outsized benefit given how often these two actions happen.

2. **"Optimistic on success, reload only on failure" is inconsistently applied.** Kanban drag-and-drop and the Status-pill inline edit both do this correctly. Calendar/Schedule's drag-to-move, Dashboard's widget reorder, the calendar-visibility multiselect, and the "Mark done" checkbox all instead reload-on-every-success, even when the interaction leading up to that point was otherwise fluid (especially true for Calendar's drag, which makes the very last frame of an otherwise well-built interaction the worst part of it).

3. **One-click actions that duplicate a slower path in the same view** — the Tasks "Mark done" checkbox duplicates the Status pill; both exist in the same row. Worth resolving by removing the redundant slow path rather than leaving both.

4. **Create is form-first everywhere except Timeline's drag-create.** A lightweight quick-add (title-only, Enter-to-submit) doesn't exist anywhere else — Tasks Table/Board, Dashboard widgets, Schedule's Table view all require opening the full field-grid modal even for the simplest possible entry.

## Suggested priority order

1. Task/Event delete → real undo or a specific confirm message (small, high-frequency payoff).
2. Remove or fix the redundant Tasks "Mark done" checkbox.
3. Calendar/Schedule drag-to-move: stop reloading on success.
4. Dashboard: surface "Add widget" above the fold; consider drag-to-reorder for widgets.
5. Everything else in this document (quick-add, bulk actions, fetch-based toggles for habit/calendar-visibility) — genuine improvements, but lower frequency/impact than 1-4.
