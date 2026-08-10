# 20 Testing Scenarios: Home / Space / Project Dashboard Interaction

> **Context (2026-08-05):** Dashboard widgets now live on three pages --
> **Home** (`/`), **Space** (`/projects/groups/{uid}`), and
> **Project** (`/projects/{uid}`) -- each scoped via `space_uid` /
> `project_uid` columns on the `dashboard_widgets` table.
>
> **Upcoming change:** Calendar (`/calendar`) and Tasks (`/tasks`) pages
> are moving into the sidebar as **widgets** (widget types already exist:
> `calendar_agenda` = month grid + agenda; `today_agenda`, `weekly_overview`,
> `upcoming_events`, `overdue_tasks` = tasks slices). These scenarios must
> cover the migration path and the cross-scope isolation it relies on.
>
> **Bug on deck (reported):** deleting **all** widgets from any page causes
> `_ensure_default_*_widgets` to re-seed defaults on the next load instead
> of honoring the "No widgets yet" empty state. Each scope has its own
> variant of this bug.

---

## Category A -- The "Delete All Re-Seeds" Bug (3 scenarios)

### Scenario 1: Home -- delete every widget, reload, defaults reappear
**Scope:** Home page (`/`)
**Setup:** Any existing widgets on Home.
**Steps:**
1. Navigate to Home in edit mode.
2. Delete every widget one by one (including dissolving any stacks by
   removing all members).
3. Confirm the empty-state UI ("No widgets yet") appears *before* reload.
4. Hard-refresh the page.

**Expected:** The empty-state UI stays. Widget list stays `[]` in the DB.
**Actual (bug):** `_ensure_default_widgets` runs on reload, sees zero
widgets, re-seeds the 4 default widgets
(`calendar_agenda`, `today_agenda`, `weekly_overview`, `upcoming_events`).
The empty state never persists.
**Root cause:** `dashboard.py:_ensure_default_widgets` (line 797) gate
is `if db.list_dashboard_widgets(conn): return` -- true idempotency
requires "ever seeded," not "has widgets right now." Compare the
*one-time backfill* pattern (`_backfill_mini_calendar_widget`, line 928)
which correctly uses `app_meta`.
**Fix target:** Persist a one-time flag per scope in `app_meta` (e.g.
`"dashboard_home_seeded_v1"`) set on first seed; skip seeding if already
set, **regardless of current widget count**. Same pattern applies to
`_ensure_default_space_widgets` and `_ensure_default_project_widgets`.

### Scenario 2: Space -- delete every widget, reload, defaults reappear
**Scope:** Space page (`/projects/groups/{uid}`)
**Setup:** A Space with at least one widget (or fresh-visited Space).
**Steps:**
1. Visit the Space page -> defaults are seeded (4 widgets:
   `calendar_agenda`, `weekly_overview`, `project_preview`, `habit_checkin`).
2. Enter edit mode, delete all 4 widgets.
3. Confirm empty-state appears.
4. Hard-refresh.

**Expected:** Empty state persists. DB `dashboard_widgets` for this
`space_uid` stays `[]`.
**Actual (bug):** `_ensure_default_space_widgets` (line 839) re-seeds
because `list_dashboard_widgets(conn, space_uid=uid)` returns `[]`.
**Cross-risk:** The Space's `default_range_days` setting is read *during*
re-seeding (line 852), so the re-seeded widgets will silently re-grab the
space's range preference -- masking the fact that the user *wanted* empty.

### Scenario 3: Project -- delete every widget, reload, defaults reappear
**Scope:** Project page (`/projects/{uid}`)
**Setup:** A Project linked to a Space (so `group_uid` is set).
**Steps:**
1. Visit the Project page -> defaults seeded (4 widgets:
   `calendar_agenda`, `weekly_overview`, `today_agenda`, `contact_list`).
2. Delete all 4 in edit mode.
3. Confirm empty state.
4. Hard-refresh.

**Expected:** Empty state persists. DB rows for this `project_uid` stay `[]`.
**Actual (bug):** `_ensure_default_project_widgets` (line 895) re-seeds
because `list_dashboard_widgets(conn, project_uid=uid)` returns `[]`.
**Subtle variant:** The re-seed reads `project["group_uid"]` (line 907)
to resolve `default_range_days` from the parent Space -- so even after the
user explicitly cleared the project dashboard, the next load silently
recreates widgets with the Space's range baked in.

---

## Category B -- Widget Stack Lifecycle (4 scenarios)

### Scenario 4: Stack two Home widgets, unstack one, delete the remaining member -> re-seed
**Scope:** Home page.
**Steps:**
1. Add two widgets (e.g. `calendar_agenda` + `today_agenda`).
2. Drag one onto the other to stack them -> a `type="stack"` row is
   created, both members get `group_uid = stack_uid`.
3. Use "Unstack" on one member -> `_dissolve_if_singleton` (line 1480)
   fires; since 1 member remains, the stack is **not** dissolved, the
   other member stays top-level.
4. Delete the remaining top-level widget.

**Expected:** Dashboard is now empty (`[]`).
**Bug triggered:** Reload -> Scenario 1 variant: defaults re-appear.
**Stack-specific risk:** Check that the dissolved widget (from step 3)
got `group_uid = None` and a correct `position` (stack position + offset,
line 1471) -- if the position math is off, it may sort ahead of where the
stack was or collide.

### Scenario 5: Stack on a Space page, then delete ALL stack members -> re-seed with doubled-up defaults
**Scope:** Space page.
**Setup:** Space page with a stack of 2 widgets.
**Steps:**
1. On a Space page, stack widget A onto widget B.
2. Delete widget B (a stack member).
3. `_dissolve_if_singleton` fires: A is the sole remaining member, so the
   stack container is dissolved via `_dissolve_stack` (line 1442), which
   promotes A to top-level **but does NOT delete A** -- it only deletes the
   stack row itself (line 1477).
4. Now delete A manually.
5. Reload.

**Expected:** Empty state on the Space page.
**Bug triggered:** `_ensure_default_space_widgets` re-seeds 4 widgets.
**Check:** Did the dissolve in step 3 leave a ghost `stack` row? Verify
`db.list_dashboard_widgets(conn, space_uid=uid)` -- after step 3 it
should show 1 widget (A, top-level, no group_uid), not 2 (A + a stray
empty stack). The existing test `test_delete_widget` at line 243 does NOT
cover this dissolve-promotes-then-delete path for the last member.

### Scenario 6: Dissolve a stack container directly, verify members survive with correct width
**Scope:** Home page.
**Steps:**
1. Stack a `mini_month_calendar` (width `third`) onto a `today_agenda`
   (width `two_thirds`).
2. The stack container inherits the target's width
   (`two_thirds`, from `stack_widget` line 1538).
3. Click "Dissolve stack" (the stack container's delete button,
   `_widget_workspace.html` line 90 -- note it says "Dissolve" not
   "Remove").

**Expected:** Both widgets re-appear as top-level cards. Both inherit the
**stack's** width (`two_thirds`) via `_dissolve_stack` line 1472-1475,
**not** their original type defaults. Positions are staggered by 0.001
offset (line 1471) so they stay in relative order at the stack's old spot.
**Bug risk:** The dissolve width propagation might not survive if the stack
had no explicit width in its config (edge case: stack created via
`stack_widget` when neither widget had a `width` set -- line 1538 uses
`target`'s config width which defaults to type's `default_width`).
**Verification:** Both widgets render side-by-side at `two_thirds` each
(which will overflow the 6-col grid -> 12 cols) or at least at a
sane width, not collapsing to `third`.

### Scenario 7: Delete a stack member from a 3-member stack, verify the other two cohere
**Scope:** Project page.
**Steps:**
1. Add 3 widgets to a Project page.
2. Stack all 3 by drag-dropping sequentially.
3. Delete the middle member (by uid).

**Expected:** Stack still has 2 members. `_dissolve_if_singleton`
returns early (2 > 1, line 1489). The remaining 2 widgets keep their
relative `position` order within the stack. No data loss.
**Bug risk:** After deletion, does `unstack` / `resize` / `reorder` on the
*remaining* members still work? The JS `app.js` intra-stack reorder
handler (line 573+) posts `after_uid` values -- a deleted member's uid
could still be in a client-side `after_uid` if the DOM wasn't cleaned
before a second operation.

---

## Category C -- Cross-Scope Isolation (3 scenarios)

### Scenario 8: Stack widgets from different pages -- should be rejected, but test via raw POST
**Scope:** Home + Space.
**Steps:**
1. Add widget H1 on Home, widget S1 on Space.
2. Via JS drag-and-drop (edit mode), attempt to drag S1 onto H1.
3. ALSO: send a raw POST to `/dashboard/widgets/{S1_uid}/stack-onto` with
   `target_uid=H1_uid` (bypassing client-side guard).

**Expected (both):** HTTP 400, "cannot stack widgets from different
pages together" (line 1517-1524). DB unchanged.
**Bug risk:** The guard at line 1517 checks
`moved.get("space_uid") != target.get("space_uid")`. If one widget has
`space_uid = ""` (Home, stored as NULL in DB, read back as `None` by
`_widget_row_to_dict`) and the other has `space_uid = "space1"`, the
comparison `None != "space1"` is `True` -> correctly rejected. BUT: what
if both are Home (`space_uid=None`) but one was *manually* moved to a
Space via a forged POST to `/edit`? The `edit_widget` endpoint
(line 1341) does NOT let you change `space_uid` -- it's read from the
existing row (line 1359). Good. But `add_widget` does take `space_uid` as
a hidden form field (line 1296) -- a forged request could cross-scope. The
scope guard in `add_widget` (line 1318) only blocks *excluded widget types*,
not wrong-space_uid values. This is by design (the page identity is the
form field), but worth a negative test.

### Scenario 9: Move (reorder) a Space widget using a Home widget's uid as after_uid
**Scope:** Home + Space.
**Steps:**
1. Add H1 on Home (position 0), S1 on Space (position 0).
2. POST `/dashboard/widgets/{S1_uid}/reorder` with `after_uid={H1_uid}`.

**Expected:** HTTP 400, "after_uid not found in the same collection"
(line 1685). `reorder_widget` (line 1646) scopes `all_widgets` to
`space_uid`/`project_uid` (line 1676), then filters to same `group_uid`
(line 1678). H1_uid won't be in S1's collection.
**But:** This test does NOT exist in `test_dashboard_router.py` (only
`test_reorder_does_not_mix_widgets_from_different_pages` at line 643
covers Home vs Space, not Home vs Space via raw POST). Add it.

### Scenario 10: Delete a Home widget whose uid is spoofed to point at a Space widget
**Scope:** Home + Space.
**Steps:**
1. Add S1 on Space.
2. POST `/dashboard/widgets/{S1_uid}/delete` with `edit=1` -- the route
   derives `space_uid` from the widget row (line 1611), NOT from a form
   field.

**Expected:** The widget is deleted from Space, redirect to
`/projects/groups/space1?edit=1`.
**Bug check:** Confirm `delete_widget` (line 1607) uses
`widget.get("space_uid")` from `db.get_dashboard_widget(conn, uid)`
(line 1609) -- so even if the URL path claims a Home widget, the DB row
dictates the redirect. The existing test
`test_delete_widget_redirects_to_its_own_space` (line 637) covers the
happy path. Add a variant: delete a Space widget while *on* the Home page
(via a forged link/form) and verify it redirects back to the Space, not Home.

---

## Category D -- Calendar + Tasks Migration as Widgets (5 scenarios)

### Scenario 11: Replace the Calendar page -- add `calendar_agenda` on every scope, verify range filtering
**Scope:** Home, Space, Project.
**Prerequisite:** The Calendar page (`/calendar`) will be demoted to a
leftover or removed. The `calendar_agenda` widget (template
`_widget_calendar_agenda.html`, line 536) renders a mini month grid +
upcoming agenda, scoped via `config["group_uid"]` (Space) or
`config["project_uid"]` (Project).
**Steps:**
1. On each page, add a `calendar_agenda` widget.
2. On the Space page, verify it reads `group_uid` from config (auto-set by
   `add_widget` line 1321) and shows only events/tasks from that Space's
   projects (via `_filtered_events`/`_filtered_tasks` -> `_group_project_uids`,
   line 75).
3. On the Project page, verify it reads `project_uid` and shows only that
   Project's linked calendars/lists.

**Expected:** The widget's data set matches the *page scope*, not the old
global set. The `weekly_overview` sibling widget inherits the Space's
`default_range_days` (line 859-860 for Space, line 912-913 for Project).
**Bug risk:** `_filtered_tasks` / `_filtered_events` both accept EITHER
`group_uid` OR `project_uid` in config, but a widget could have both set
(e.g. if a user edits a Space-scoped widget's filters and the Project
field survives). The filter at line 60 (`if project_filter and
project_by_list.get(list_uid) != project_filter: return False`) would
**AND** them -- a task must match the group AND the project. This may be
unintended; verify the UI doesn't let `project_uid` persist on a
Space widget.

### Scenario 12: Replace the Tasks page -- no equivalent single widget exists; test all tasks-derived widget types cover the old `/tasks` surface
**Scope:** Home, Space, Project.
**Steps:**
1. Enumerate what `/tasks` (Table view) showed: all open tasks, filterable
   by list/space/project/tags/status/priority, sortable by due date.
2. Map to widget types:
   - `today_agenda` => tasks due today (too narrow to replace the full list).
   - `overdue_tasks` => overdue open tasks only.
   - `weekly_overview` => grouped-day view, next N days.
   - `upcoming_events` => events only, no tasks.
3. **Gap identified:** There is **no** widget type that renders the full
   open-task list with the table columns (status, priority, list,
   project, tags, due date, sortable). The `today_agenda` widget
   (`_widget_today_agenda.html`) renders a small card list, not a table.

**Expected (bug report):** Moving `/tasks` behind widgets requires a new
widget type (e.g. `task_table` or `task_board`) OR keeping `/tasks` as a
fallback. The current 7 widget types do not cover it.
**Risk:** If `/tasks` is removed without a replacement widget, users lose
the ability to see all open tasks at once. At minimum, a `task_list`
widget (full open tasks, with the same table columns) must be added before
the page can be deprecated.

### Scenario 13: Scope-excluded widget types still hidden after the migration -- `project_preview` on a Project page
**Scope:** Project page.
**Steps:**
1. Visit any Project page in edit mode.
2. Click "New widget" -> open the Customize modal.
3. Inspect the Source/View picker (`_widget_builder_fields.html`).

**Expected:** The "Projects" source (`_widget_sources_for_scope`,
line 749) should be **absent** or greyed out, because both its views
(`cards` -> `project_preview`, `filled_cards_view` -> `filled_cards`) are
in `_SCOPE_EXCLUDED_TYPES["project"]` (line 708). You cannot add a
*project preview* widget to the project page (it would be circular).
**Bug check:** The `add_widget` route also enforces this at line 1318
(`_excluded_widget_types`). But the **preview** endpoint
(`preview_widget`, line 1255) does NOT apply the scope guard -- a forged
preview POST could render a project-scoped `project_preview`. Low risk
visually, but a consistency check.

### Scenario 14: Add a `contact_list` widget on a Project page, verify it pools the right address books
**Scope:** Project page.
**Steps:**
1. Create a Project with 2 linked address books (via
   `set_addressbook_project` or the project's "Contacts" section).
2. Add a `contact_list` widget from the Project page.
3. Verify the widget's `config` has `project_uid` set (auto by
   `add_widget` line 1324, like `group_uid`).

**Expected:** `_render_contact_list` (dashboard.py line ~560) should resolve
`config["project_uid"]` and list only contacts from that Project's linked
address books. If `project_uid` is not in `config`, it falls back to
global contacts.
**Bug risk:** Verify `add_widget` actually sets `config["project_uid"]`
for *every* widget type added from a Project page, not just
`calendar_agenda`/`weekly_overview`. The code at line 1321-1324 applies
`group_uid`/`project_uid` universally -- confirm this is right for
`habit_checkin` (which uses `project_uid` in `_render_habit_checkin`,
line 394-396) and `contact_list`.

### Scenario 15: Add calendar_agenda widget on Home with a specific project filter -- does it leak scope?
**Scope:** Home page.
**Steps:**
1. On Home, add a `calendar_agenda` widget.
2. In its Filters editor, set "Project" = "My Project".
3. Save.

**Expected:** The widget shows events/tasks for "My Project" only, even
on the global Home page. `config` will have `project_uid` set but
`space_uid` / `project_uid` columns are NULL (line 1334-1335).
**Bug risk:** If the user later **deletes** this filtered widget and
the re-seed fires (Scenario 1 bug), the re-seeded `calendar_agenda` will
be **unfiltered** (global), silently discarding the user's project
filter. This is the migration-dangerous variant: the user customized
their "Calendar" widget, deleted everything, and the "new" calendar
widget shows *everything* -- a regression from the old `/calendar` page's
sticky filter behavior.

---

## Category E -- Scope Auto-scoping & Range Inheritance (4 scenarios)

### Scenario 16: New Space -- defaults auto-scope, then verify range_days inheritance
**Scope:** Space page.
**Steps:**
1. Create a Space ("University") with `default_range_days = 90`.
2. Visit `/projects/groups/{new_space_uid}`.
3. Confirm the seeded `weekly_overview` widget has
   `config["range_days"] == 90` (line 859-860).
4. Change the Space's `default_range_days` to `7` (via
   `edit_project_group`, projects.py line 225).
5. Reload the Space page.

**Expected:** The existing `weekly_overview` widget keeps `range_days = 90`
(its seeded value). Re-seeding does NOT run again (idempotent gate at
line 849 -- "once *that space* has any widget").
**Bug check:** If the user deletes ALL widgets (Scenario 2), the re-seed
**will** pick up `default_range_days = 7` -- silently overriding the
user's prior range choice. This is the data-loss aspect of the bug: not
just widget count, but the Space's `default_range_days` preference gets
re-applied without consent.

### Scenario 17: Project in a Space -- weekly_overview inherits the Space's range, NOT a Project-local setting
**Scope:** Project page.
**Setup:** A Space with `default_range_days = 14` containing Project P.
**Steps:**
1. Visit `/projects/{P_uid}`.
2. The seeded `weekly_overview` should have `range_days = 14`
   (line 907-913 reads `project["group_uid"]` -> `group["default_range_days"]`).

**Expected:** 14, inherited from the parent Space.
**Bug risk:** If Project P has NO `group_uid` (ungrouped project),
`group` is None (line 907), `project_range = 7` (line 908). Verify the
fallback works. If P is moved to a Space *after* seeding, the existing
widget does NOT retroactively update its `range_days` -- it's baked at
seed time. This may surprise users who move projects between Spaces.

### Scenario 18: Edit a Space-scoped widget's Project filter to a project OUTSIDE the Space -- should be rejected or auto-corrected
**Scope:** Space page.
**Steps:**
1. Create Space S1 with Project P1 (and optionally P2 also in S1).
2. On `/projects/groups/S1`, add a `today_agenda` widget (auto-scopes to
   `group_uid = S1` via line 1321).
3. Open its Filters editor. In the Project dropdown
   (`_scoped_collections`, line 758-777), P1 and P2 should appear
   (only the Space's own projects).
4. **Forge** a POST to `/dashboard/widgets/{uid}/edit` with
   `project_uid = P3` where P3 is in a DIFFERENT Space (or ungrouped).

**Expected:** `edit_widget` (line 1341) re-reads `space_uid`/`project_uid`
from the existing row (line 1359-1360), NOT from the form. So the widget's
scope is preserved. But the `project_uid` form field (line 1348) is used
to build `_config_from_form` (line 1372) -- so `config["project_uid"]`
**gets overwritten** to P3 even though the widget's `project_uid` *column*
stays NULL (Home/Space widget).
**Bug:** A Space-scoped widget can silently have `config["project_uid"]`
point outside its Space via a forged edit. The UI prevents this (filtered
dropdown), but the API doesn't guard it. The task filter
(`_passes_filters`, line 60) would then AND the group filter with the
foreign project -- likely showing nothing, with no error.

### Scenario 19: Add a widget on Home, then re-scope it to a Space via the edit form's hidden field -- should be a no-op or rejected
**Scope:** Home -> Space.
**Steps:**
1. Add widget W on Home (no `space_uid`, no `project_uid`).
2. Forge POST to `/dashboard/widgets/{W_uid}/edit` with
   `space_uid = "space1"` (the form doesn't normally include this field).

**Expected:** `edit_widget` does NOT accept `space_uid` as a form field
(it's not in the route signature at line 1341-1354). The widget stays on
Home. Good -- but verify, because `add_widget` DOES accept `space_uid`
(line 1296), creating an asymmetry: `add_widget` can place a widget on a
Space, but `edit_widget` cannot move it. A "move to Space" feature would
need a dedicated endpoint.

---

## Category F -- Resize, Positioning, and Layout Edge-State (1 scenario)

### Scenario 20: Stack with width mismatch -- dissolve inherits stack width, verify grid rendering
**Scope:** Home page.
**Setup:** Two widgets with mismatched widths: `mini_month_calendar`
(default `half`) and `upcoming_events` (default `third`).
**Steps:**
1. Add both to Home (they sit side by side at their type defaults).
2. Drag `upcoming_events` onto `mini_month_calendar` -> a stack is
   created. Per `stack_widget` (line 1538), the stack takes the target's
   (`mini_month_calendar`) width (`half`). `upcoming_events` is now
   `half` too inside the stack.
3. Resize the stack to `full` via the drag handle (POST
   `/dashboard/widgets/{stack_uid}/resize`).
4. Dissolve the stack.

**Expected:** Both widgets re-appear top-level. Both inherit
`full` (the stack's width) via `_dissolve_stack` line 1472-1475.
`mini_month_calendar` was originally `half` -> now `full` (wider than its
type default). `upcoming_events` was `third` -> now `full`.
**Bug risk:** The masonry layout (`app.js` line 269+) packs widgets into
a 6-column grid. Two `full`-width widgets should each take a full row.
But if `_dissolve_stack`'s position math (line 1471:
`stack["position"] + i * 0.001`) places them at e.g. `5.000` and `5.001`,
and the next *real* top-level widget is at `4.0`, they should appear
after it. Verify the sort order in the rendered grid is correct and there
are no position collisions that scramble the visual order.
**Extra:** Repeat after deleting the stack (not dissolving) --
`delete_widget` on a `type="stack"` row calls `_dissolve_stack`
(line 1617) then returns, so the members survive. But if the stack had
0 members at deletion time (race condition from rapid double-clicks in
the UI), `_dissolve_stack` iterates an empty list (line 1464) and then
deletes the stack row -- safe, but the UI's optimistic hide
(`app.js` line ~130, "row.style.display = 'none'") might leave a phantom
card in the DOM if the AJAX response is slow.

---

## Appendix B -- CSS / Visibility / Layout Test Scenarios (35 items)

> **Focus:** Visual layering, overflow, z-index, responsive breakpoints,
> item rendering, and edge-state styling on the dashboard widget grid.
> All references are to `webapp/src/static/style.css` and `app.js` line
> numbers unless otherwise noted.

### Z-Index layering matrix (reference)

| Element | Class selector | z-index | position | notes |
|---------|---------------|---------|----------|-------|
| Sidebar tabs | `.tabbar` (desktop) | 20 | fixed | left rail, 80px wide |
| Sidebar tabs | `.tabbar` (mobile `max-width:720px`) | 100 | fixed | bottom bar, 64px tall |
| Dragging widget | `.widget-card.is-dragging` | 20 | absolute | inside `.dashboard-grid` inside `main` (z-auto) |
| Stack drop label | `.widget-card.is-stack-target::before` | 5 | pseudo | child of `.widget-card` |
| Width resize handle | `.widget-resize-handle` | 2 | absolute | right: -6px, child of `.widget-card` |
| Height resize handle | `.widget-resize-handle-vertical` | 2 | absolute | bottom: -6px, child of `.widget-content` |
| Multiselect panel | `.multiselect-panel` | 40 | absolute | in Customize modal Filters |
| Modal overlay | `.modal-overlay` | 100 | fixed | scrim + dialog |
| Mobile FAB | `.fab` | 90 | fixed | `display:none` on desktop, `flex` on mobile |
| Toast stack | `.toast-stack` | 200 | fixed | undo/delete toasts |

> **Key tension:** `.widget-card.is-dragging` (z-20) and `.tabbar` desktop (z-20)
> share the same z-value but live in *different* stacking contexts
> (tabbar is root-level fixed; widget-card is inside `main`).
> `.fab` (z-90 mobile) is above dragging widgets (z-20) -- if a drag
> happens near the FAB on mobile, the FAB will visually cover the dragged
> card. `.toast-stack` (z-200) is above everything -- toasts always win.

---

### Scenario 21: Dragging a widget card near the desktop sidebar -- z-index collision
**CSS target:** `.widget-card.is-dragging` (z-20, line 1584) vs
`.tabbar` (z-20, line 430).
**Steps:**
1. Enter edit mode on Home with several widgets.
2. Drag a `third`-width widget (data-span="2", ~84px on a 720px viewport)
   toward the left edge of the screen, where the 80px-wide sidebar sits.
3. Observe the dragged card as it crosses the sidebar boundary.

**Expected:** The dragged card should appear *above* the main content area
but the sidebar should remain visible (sidebar is `position:fixed` at
root level; widget is `position:absolute` inside `main` which has
`margin-left:80px`). Since both are z-20 in different contexts, sidebar
wins -- correct.
**Bug risk:** If `main` or `.dashboard-grid` ever gets a `z-index` set
(e.g. during a future refactor), the stacking context could flip and the
sidebar would render *under* a dragged card that's being held over it --
making it impossible to see what's underneath while dragging.
**Verification:** No `z-index` on `main`, `.dashboard-grid`, or
`.widget-card` (non-dragging). Only `.is-dragging` carries z-20.

### Scenario 22: Resize handle (width) on a `third`-width widget overlaps adjacent cards
**CSS target:** `.widget-resize-handle` at `right: -6px` (line 1600),
`.widget-card` `position:absolute` with `box-sizing:border-box` (line 1579).
**Steps:**
1. Add a `third`-width widget (data-span="2") next to a `half`-width widget.
2. Enter edit mode. The resize handle (12px wide at `right: -6px`) extends
   6px past the right edge of the `third` card.
3. Hover the area between the two cards.

**Expected:** The handle on the `third` card should be clickable (z-2 child
of the card). The adjacent `half` card's content should not intercept the
click.
**Bug:** `.widget-card` has `position:absolute` with `z-index:auto`. Siblings
in the same stacking context are painted in DOM order -- whichever card
comes later in the DOM paints on top. If the `half`-width card comes
*after* the `third` card in DOM, its box (including padding) may sit
partially over the resize handle. The handle's z-2 should lift it above
the sibling card's content since z-2 > z-auto of the sibling. But
`.widget-content` has `overflow-x:hidden` (line 1620) creating a new
stacking context at z-auto -- the sibling's overflow-clipped content
won't escape its own scrollport to overlap. So this should be OK, but
**verify** the handle isn't rendered *behind* the sibling card due to
the masonry `transition` on `.widget-card` (line 1580: transitions
`left`, `top`, `width` with `var(--dur-normal)` = 160ms). During a
resize drag, the adjacent card might still be animating to its new
position, and the handle could visually lag or clip.

### Scenario 23: Vertical resize handle clipped by `.widget-content` overflow
**CSS target:** `.widget-resize-handle-vertical` at `bottom: -6px` (line 1623),
`.widget-content` `overflow-y: auto` (line 1620).
**Steps:**
1. Add a `today_agenda` widget on Home. Set its height to `short`
   (180px max-height) via the Customize modal or edit form.
2. Populate it with enough tasks that the table overflows 180px.
3. Enter edit mode. The vertical resize handle (12px, bottom: -6px) should
   sit at the very bottom edge.
4. Hover the bottom edge.

**Expected:** The handle should be fully visible and clickable.
**Bug:** `.widget-content` has `overflow-y: auto`. This creates a scroll
container. Absolutely-positioned descendants extending below the padding
box (`bottom: -6px`) are clipped to the scrollport. The bottom 6px of
the 12px handle is clipped, leaving only 6px visible inside the
content area. Users can still grab the top 6px, but the handle appears
half-cut. This is worse on the `short` height (180px) where there's
least margin for error.
**Fix candidate:** Add `padding-bottom: 6px` to `.widget-content` or move
the vertical handle outside the overflow container (e.g. as a sibling of
`.widget-content` inside `.widget-card`, not inside `.widget-content`).

### Scenario 24: Stacked widgets -- `.widget-resize-handle-vertical` z-index vs `.widget-stack-item` border
**CSS target:** `.widget-stack-item + .widget-stack-item` border-top
(line 1651), `.widget-resize-handle-vertical` z-index:2 (line 1623),
`.widget-stack` `display:flex; flex-direction:column` (line 1649).
**Steps:**
1. Stack three widgets on Home: `today_agenda`, `overdue_tasks`,
   `upcoming_events`.
2. Set different heights: `short`, `medium`, `xl`.
3. Enter edit mode. Each stack member has its own height resize handle.
4. Try to grab the handle on the middle member.

**Expected:** Each handle is independently draggable. The stacked layout
uses `flex-direction:column` with `border-top` separators between items.
**Bug risk:** The `.widget-resize-handle-vertical` has `z-index:2` but is
inside `.widget-content` which has `overflow-y:auto` (its own stacking
context at z-auto). The `.widget-stack-item` sibling's border-top
(line 1651) might overlap the handle if the content area is exactly at
its max-height boundary. Also, two adjacent handles (one at bottom of
member A, one at top of member B) are only 12px+12px=24px apart (handle
heights) with a 1px border between them -- the hit target is 12px each,
leaving a 2px gap that might be hard to hit on touch.

### Scenario 25: Masonry layout fails to position cards on initial load (FOUC)
**CSS target:** `.widget-card` `position:absolute` (line 1579), masonry
`layout()` in app.js (line 307).
**Steps:**
1. Disable JavaScript. Load any dashboard page with widgets.

**Expected:** Cards are `position:absolute` with no inline `left`/`top`/
`width` set. They all stack at `0,0` (top-left of `.dashboard-grid`).
All widget content is rendered but piled on top of each other -- only
the topmost card is visible.
**Bug:** Unlike other layout systems in this app (`.card`, `.filled-cards-grid`,
`.week-overview-grid`), the widget grid has **no CSS fallback** for
`data-span` -> grid-column mapping. The `data-span` attribute is purely
consumed by JS (app.js line 320). With JS disabled, the dashboard is
unusable (all cards overlap). Compare to `--no-JS` behavior on the tabbar
(works), tables (works), or forms (works) -- the widget grid is the one
component that completely breaks without JS.
**Fix candidate:** Add a CSS grid fallback: `.dashboard-grid:not(.is-editing)
{ display: grid; grid-template-columns: repeat(6, 1fr); }` and
`[data-span="2"] { grid-column: span 2; }` etc. This would at least
show cards in the right place (if not skyline-packed) with no JS.

### Scenario 26: Empty state icon alignment on different screen widths
**CSS target:** `.empty-state-rich` (line 818), `.empty-state-icon`
(line 819), `.dashboard-see-more` (line 1655).
**Steps:**
1. Delete all widgets (or on a fresh Space with the bug from
   Scenario 2 present, the empty state won't even show -- but assume the
   fix is applied).
2. Observe the "No widgets yet" message with the home/folder/target icon.
3. Resize the browser window from 1200px down to 720px (mobile breakpoint).

**Expected:** The icon (`width:48px; height:48px; border-radius:50%`)
and text remain centered.
**Bug:** `.empty-state-rich` uses `padding:var(--space-10) var(--space-5)`
(40px/20px) with `text-align:center`, but **no** `display:flex` or
`align-items:center`. The icon is `display:inline-flex` (line 820), so
it sits on the baseline of the text. On wider screens, this looks fine
(centered). But the `.dashboard-grid` has `min-height:200px` (line 1578)
and no `display:flex`/`align-items:center`/`justify-content:center` to
vertically center the empty-state content within that minimum height.
If the empty state text is ~60px tall (icon 48 + title + text), the
200px grid leaves ~140px of empty space below -- the empty state hugs
the top of the grid, not the center. On a full-height viewport this
looks like the "No widgets" message is floating at the top of a sea of
white space.
**Fix candidate:** Add `display:flex; align-items:center; justify-content:center;
min-height:calc(60vh - <toolbar height>);` to `.empty-state-rich`
when it's a direct child of `.dashboard-grid`, or make
`.dashboard-grid:empty` (after fix) use flex centering.

### Scenario 27: `.card:hover` transform causing layout thrash during masonry reflow
**CSS target:** `.card:hover { transform: translateY(-1px) }` (line 513),
`.widget-card` transition on `left/top/width` (line 1580).
**Steps:**
1. Add 8+ widgets of varying widths on Home.
2. Rapidly move the mouse across the dashboard in edit mode.
3. Each widget card hovers in turn, triggering `transform: translateY(-1px)`.

**Expected:** The hover lift is smooth and doesn't affect layout.
**Bug:** `.card:hover` uses `transform` (GPU-accelerated, doesn't trigger
reflow), BUT the masonry layout's `MutationObserver` (app.js line 368-373)
listens for `attributes` changes including `style` and `class`. The
hover adds `.is-hovering`... wait, no -- hover is a CSS pseudo-class, not
a class change. The `transform` is applied via CSS, not inline style.
So the MutationObserver should NOT fire on hover. BUT: the masonry
layout also listens to `childList` (line 369) -- if a widget's content
dynamically changes size (e.g. a `weekly_overview` expands/collapses a
day row), the `.widget-card`'s `offsetHeight` changes (app.js line 343),
and the `MutationObserver` may not catch a content-driven height change
if the child elements don't add/remove classes or attributes. The
`subtree: true` flag (line 370) should catch descendant mutations, but
only for `childList`, `attributes`, and `characterData` -- NOT for
layout/repaint changes. A text node update that changes an element's
height without adding/removing DOM nodes or attributes would NOT trigger
the observer, leaving the masonry layout stale (overlapping cards or
gaps).

**Fix candidate:** The masonry layout should also listen to `window`
`resize` (it does, line 376) and ideally use a `ResizeObserver` on each
`.widget-card` to catch content-driven height changes. Currently it
relies solely on the `MutationObserver` for attribute/class changes and
a 150ms-debounced resize handler.

### Scenario 28: Widget with a very long unbreakable title (URL, no spaces)
**CSS target:** `.widget-content td { word-wrap: break-word }` (line 1621),
`.widget-content { overflow-x: hidden }` (line 1620).
**Steps:**
1. Create a task with a title like
   `https://very-long-subdomain-example.com/a/really/long/path/that/has/no/spaces/or/breakpoints/at/all/anywhere`
2. Ensure this task appears in a `today_agenda` widget (due today) or
   `weekly_overview` widget (due within range).
3. View the widget.

**Expected:** The title should wrap or truncate gracefully.
**Bug:** `word-wrap: break-word` (= `overflow-wrap: break-word`) only
breaks at "legal" breakpoints. A URL with no hyphens/spaces has no legal
break points, so `break-word` may not break it at all (behavior varies
by browser). Combined with `overflow-x: hidden` on `.widget-content`,
the long text is clipped -- the user sees a truncated title with no
ellipsis (`text-overflow: ellipsis` is NOT set, only `overflow-x:
hidden`). The task link is still clickable (it's an `<a>` with
`text-decoration: none` from line 277's link reset), but the user can't
see the full title.
**Fix candidate:** Add `text-overflow: ellipsis; white-space: nowrap;
overflow: hidden;` to the task title `<a>` or its `<td>`, or use
`overflow-wrap: anywhere` instead of `break-word` to allow breaking at
any character.

### Scenario 29: `data-span` attribute not set on a widget card -- masonry treats it as full-width
**CSS target:** `data-span` consumed by app.js line 320
(`parseInt(card.dataset.span, 10) || cols`), `.widget-card` no CSS for
`[data-span]`.
**Steps:**
1. Forge or manually edit a `dashboard_widgets` row to have a `config`
   with no `width` key (simulating a legacy pre-2026-08-02 widget).
2. Load the dashboard. The server renders
   `_widget_workspace.html` line 106: `data-span="{{ wc.width.span }}"`.
3. `wc.width` comes from `_widget_width` (dashboard.py line ~445) which
   falls back to `spec["default_width"]` (line 559 area) when config
   has no `width`.

**Expected:** The card renders with `data-span` = the type's default
(e.g. `calendar_agenda` -> `third` -> span 2, `today_agenda` ->
`half` -> span 3).
**Bug risk:** If `_widget_width` returns a span of 0 or undefined (edge
case in the config resolution), app.js line 320 falls back to `cols`
(6 on desktop = full width). A widget that should be `third` becomes
`full`. This is a silent degradation -- no error, just wrong layout.
Verify the `_widget_width` function handles all cases.

### Scenario 30: Widget resize on mobile -- handle still active but grid is 1-column
**CSS target:** `.widget-resize-handle` (z-2), mobile media query (line 1067+).
**Steps:**
1. Open the dashboard on a phone (<=720px wide).
2. Enter edit mode. All widgets are `data-span=1` (1 column, per
   masonry app.js line 314).
3. Tap and drag the width resize handle.

**Expected:** On mobile, a single column means all widgets are full-width --
resizing is meaningless. The handle should ideally be hidden or disabled.
**Bug:** The resize handler script (app.js line 692-694) only checks
`grid.classList.contains("is-editing")` -- it does NOT check for mobile
breakpoint. So the handle IS active on mobile, and dragging it will
POST to `/resize` with a new width (e.g. `half`), which gets persisted
to the DB. On desktop reload, the widget will be half-width instead of
full-width. This is a UX inconsistency: mobile users can't undo the
width change (there's no visible width difference on 1-col mobile).
**Fix candidate:** Add `&& window.innerWidth > MOBILE_BREAKPOINT` to
the resize handler's guard (line 694), and/or hide
`.widget-resize-handle` via CSS at `@media (max-width:720px)`.

---

### Scenario 31: Tab bar (z-20 desktop) overlaps widget content area -- verify `main` offset
**CSS target:** `.tabbar` z-index:20, fixed left rail (line 428-430),
`main { margin-left:80px }` (line 470).
**Steps:**
1. Load any dashboard page on desktop (>=721px).
2. The tabbar is 80px wide on the left. `main` has `margin-left:80px`.
3. Scroll the page. The tabbar is `position:fixed` (stays in place).
4. Drag a widget card that's wider than the content area near the left
   edge (under the tabbar's x-range).

**Expected:** The tabbar should always be visible (it's `position:fixed`,
above `main`'s content in stacking). The widget card should NOT render
*behind* the tabbar -- if it's dragged there, it should appear above
the white page background but the tabbar (z-20 fixed at root) should
remain clickable/visible.
**Bug risk:** `.widget-card.is-dragging` has `z-index:20`. The tabbar
also has `z-index:20` but at the root stacking context (fixed). Since
`main` creates no stacking context (no z-index set), `main`'s children
(absolute-positioned cards) at z-20 are compared within `main`'s
auto-z context. The tabbar's z-20 is at root level. Root-level z-20
> `main`'s z-auto (0), so the tabbar always wins. BUT: if the FAB is
present on mobile (z-90), it also overlaps the tabbar at the bottom.
This isn't a bug per se, but verify the tab bar's bottom-bar form on
mobile (z-100) correctly covers the FAB (z-90) or vice versa -- the
tabbar (z-100) should be above the FAB (z-90), which is correct since
the FAB sits above the tabbar at `bottom:calc(72px + ...)` -- they don't
overlap vertically.

### Scenario 32: `.widget-stack-item.is-dragging` -- opacity only, no z-lift
**CSS target:** `.widget-stack-item.is-dragging { opacity:.5 }` (line 1594),
app.js intra-stack drag (line 573+).
**Steps:**
1. Stack two widgets on Home.
2. Enter edit mode.
3. Drag one stack member using the `.widget-stack-drag-handle`.

**Expected:** The dragged member fades to 50% opacity. Other members
remain fully opaque.
**Bug:** Unlike `.widget-card.is-dragging` (line 1584) which gets
`z-index:20` and `box-shadow:var(--shadow-popover)`,
`.widget-stack-item.is-dragging` (line 1594) only gets `opacity:.5` --
no z-lift, no shadow. During a drag, the member might visually sink
*behind* its sibling stack items (which have no z-index and sit at
the default stacking order within the flex column). Since
`.widget-stack` is `display:flex; flex-direction:column` (line 1649),
DOM order determines paint order for siblings at the same z-index.
The dragged item, if it's the first child, would be painted first (not
last), so its sibling could overlap it even with `opacity:.5`.
**Fix candidate:** Add `position:relative; z-index:1;` to
`.widget-stack-item.is-dragging` so it always lifts above siblings.

### Scenario 33: Toast (z-200) overlaps modal (z-100) during a delete-with-undo action
**CSS target:** `.toast-stack` z-index:200 (line 1097),
`.modal-overlay` z-index:100 (line 1173).
**Steps:**
1. Open the Customize modal (z-100) from a Space page.
2. Delete a widget from within the modal -- the modal triggers a
   full page reload (data-modal-keep-open, line 17 of
   `dashboard_customize.html`), OR the delete form posts and the page
   reloads.

**Expected:** Since widget delete on the dashboard does a full-page
POST (the form at `_widget_workspace.html` line 51 is a standard
`<form method="post">`, not AJAX), the modal closes on redirect and
the toast appears on the reloaded page. No z-index conflict.
**Bug check (hypothetical):** If the widget delete were ever converted
to AJAX (like the stack/unstack/reorder/resize handlers), the toast
(z-200) would appear *above* the modal (z-100), which is correct. But
if the delete used `data-delete-undo` (the optimistic hide pattern at
app.js line 113), the 4.5s undo timer would overlap the modal. Verify
the widget delete form does NOT use `data-delete-undo` (it uses
`data-confirm-sheet` at `_widget_workspace.html` line 51). Correct.

### Scenario 34: `prefers-reduced-motion` -- masonry transition disabled, verify layout still works
**CSS target:** `* { transition-duration:0.001ms !important }` (line 160-161),
`.widget-card { transition:left/top/width var(--dur-normal)} ` (line 1580).
**Steps:**
1. Enable "Reduce motion" in OS/browser.
2. Enter edit mode. Drag a widget to a new position.
3. Observe the transition.

**Expected:** The card should jump to its new position immediately (no
160ms animation).
**Bug:** The `prefers-reduced-motion` rule at line 160 applies
`transition-duration:0.001ms !important` to ALL elements. But the
masonry layout function (app.js line 356) sets `grid.style.height`
directly -- this has no transition, so it's instant. The `.widget-card`'s
`left`/`top`/`width` transitions (line 1580) ARE affected by the 0.001ms
override. So cards should snap instantly. BUT: the `is-dragging`
state removes transitions (line 1584: `transition:none`), so dragging
itself is already instant. The reduced-motion rule mainly affects the
post-drop repositioning of *other* cards (they transition from their
old position to their new position as the masonry recalculates). With
0.001ms, they snap. This is correct behavior.
**Verify:** No `scroll-behavior: smooth` remains active (line 162
sets `scroll-behavior:auto`).

### Scenario 35: `.widget-content` with `max-height` -- scrollbar appearance shifts the resize handle
**CSS target:** `.widget-content { overflow-y:auto; overflow-x:hidden;
max-height:{{height.px}}px }` (inline from template line 69 +
`overflow-y:auto` from line 1620).
**Steps:**
1. Add a `calendar_agenda` widget set to `short` height (180px max-height).
2. Populate with enough calendar days that the agenda section overflows
   180px.
3. A vertical scrollbar (16px wide) appears inside `.widget-content`.
4. The `.widget-resize-handle-vertical` (line 1622) is `left:0; right:0;
   bottom:-6px` -- it spans the full width of `.widget-content` including
   the area behind the scrollbar.

**Expected:** The resize handle should be fully usable and visible.
**Bug:** The scrollbar occupies 16px of the content width. The
`.widget-resize-handle-vertical` at `right:0` places its right edge at
the content's padding box -- but the scrollbar overlaps the content's
right edge. On some browsers, the scrollbar renders *on top of* the
content (not reducing its width). The handle's `::after` is `width:28px;
height:3px; left:50%` -- centered on the content width. If the scrollbar
appears, the effective content width shrinks by 16px, but the handle
doesn't adjust. The visual center of the handle may appear shifted by
8px. More critically, the handle might be partially obscured by the
scrollbar thumb, making it hard to grab.
**Fix:** Add `padding-bottom: 12px` to `.widget-content` to ensure the
handle plus its 6px overflow is always within the scrollable area, OR
position the vertical handle relative to `.widget-card` (outside
`.widget-content`) instead of inside it.

---

### Scenario 36: `.widget-stack` flex column -- `.widget-stack-item` border collapse
**CSS target:** `.widget-stack { display:flex; flex-direction:column }`
(line 1649), `.widget-stack-item + .widget-stack-item { margin-top:
var(--space-3); padding-top:var(--space-3); border-top:1px solid var(
--separator) }` (line 1651).
**Steps:**
1. Stack 3 widgets. Enter edit mode.
2. Observe the visual separation between stack members.

**Expected:** Each member after the first has a 1px border-top, plus
12px margin-top and 12px padding-top above it.
**Bug:** The `.widget-header` (line 35 of `_widget_workspace.html`)
inside each stack member has no `margin-bottom` or `padding-bottom`
defined. Combined with the stack item's `padding-top:var(--space-3)`
on `.widget-stack-item`, the header of the second member sits 12px
below the border-top. But the header's `<h2>` has `margin:0` (inline
style, line 41 of `_widget_workspace.html`), so there's no extra
spacing issue. HOWEVER: the `.widget-content` inside each stack member
(line 69) has `max-height` set per-widget. If member 1 is `xl` (680px)
and member 2 is `short` (180px), the stack's total height is 680 + 12
(border) + 180 + headers = quite tall. The `.widget-card` wrapper has
no max-height -- it grows with content. On a short viewport, the stack
could exceed the viewport height. Since `.widget-content` has
`overflow-y:auto`, only the individual content areas scroll, not the
stack as a whole. If the stack exceeds viewport height, the user can't
see the bottom members without scrolling the *page* (not the widget).
This isn't a bug per se, but worth noting for very tall stacks.

### Scenario 37: `.card:hover` lift effect on widget cards -- visual conflict with masonry absolute positioning
**CSS target:** `.card:hover { transform:translateY(-1px); box-shadow:
var(--elevation-2) }` (lines 513), `.widget-card` extends `.card`.
**Steps:**
1. Add a `full`-width widget (data-span="6") on Home.
2. Hover it in view mode (not edit mode).
3. The card should lift up 1px with a stronger shadow.

**Expected:** Smooth hover lift, no layout shift for other cards.
**Bug:** `transform: translate3d` or `translateY` creates a
compositing layer. The masonry layout positions cards with
`position:absolute; left/top/width`. If a card is hovered and lifted,
its shadow (which extends beyond its box) might overlap adjacent cards
that are absolutely positioned. Since the lifted card is `position:
absolute` with no z-index change on hover, the shadow renders within
the card's stacking context (z-auto) -- adjacent cards at the same z
level in DOM order could paint over the lifted card's shadow. The
visual effect is that the shadow "disappears" where it overlaps a
sibling. This is a minor cosmetic issue.
**Verify:** The `.widget-card` class list includes both `card` and
`widget-card` (template line 85, 106), so `.card:hover` applies to
widget cards. Confirm this is desired (widget cards DO hover-lift in
view mode) and not an accidental side-effect of reusing the `.card`
class.

### Scenario 38: Customize modal -- widget preview rendering on narrow viewports
**CSS target:** `.widget-preview-content { border:1.5px dashed
var(--border-strong); border-radius:var(--radius-md); padding:
var(--space-3); overflow:hidden }` (line 1860-1863), `.widget-builder`
grid (line 1831).
**Steps:**
1. Open the Customize modal from a Project page.
2. The modal is `width:700px; min-width:500px` (line 1178). On a 720px
   mobile viewport, the modal becomes a bottom sheet (line 1241+):
   `width:100%; height:auto; max-height:80vh; border-radius:0;`.
3. In the mobile bottom-sheet form, the `.widget-builder` grid becomes
   `grid-template-columns:1fr` (line 1850: stacked form above preview).

**Expected:** The preview pane shows the widget rendering correctly.
**Bug:** `.widget-preview-content` has `overflow:hidden` (line 1862).
Inside it, `.widget-preview-card` is reset to `position:static` (line
1868). But the widget template partials (e.g.
`_widget_today_agenda.html`) render `<table>` elements. The table's
natural width might exceed the preview content's width on mobile.
With `overflow:hidden` on `.widget-preview-content`, the table is
clipped but NOT scrollable -- the user can't see overflowing content.
Compare to `.widget-content` on the actual dashboard (line 1620:
`overflow-y:auto; overflow-x:hidden`) which allows vertical scrolling.
The preview has NO vertical overflow handling -- a tall preview just
gets clipped at the `.widget-preview-content` height.
**Fix candidate:** Add `overflow-y:auto` to
`.widget-preview-content` and give it a `max-height` (e.g.
`max-height:400px`).

### Scenario 39: Icon rendering in widget headers -- SVG `use` href on scoped/custom elements
**CSS target:** `{{ icon('edit', 'icon-sm') }}` (Jinja macro, renders
`<svg class="icon"><use href="#icon-edit"></svg>` per `icon()` definition).
**Steps:**
1. Inspect a widget card header in the browser dev tools.
2. The title `<h2>` uses `widget.title or (spec.label if spec else
   widget.type)` (template line 41).
3. The edit button icon: `<svg class="icon"><use href="#icon-edit">`.

**Expected:** The SVG `<use>` references a `<symbol id="icon-edit">`
defined in a sprite sheet injected by `base.html` (or a
`<svg style="display:none">` sprite at the top of the document).
**Bug:** If the icon sprite is injected by `base.html` but the
`<use href="#icon-edit">` is rendered inside a `<template>` tag or a
Shadow DOM boundary, the reference would fail (SVG `<use>` doesn't
cross Shadow DOM boundaries). Since this app uses server-rendered
Jinja2 (no Shadow DOM), this should work. BUT: the `data-modal`
links (line 50 of `_widget_workspace.html`) load content into a modal
via `fetch` and `innerHTML` (modal.js). If the fetched HTML contains
`<svg><use href="#icon-...">`, the `<use>` reference resolves against
the **document's** symbol definitions, which exist in `base.html`. So
the reference should still work after `innerHTML` injection. Verify
this works -- there have been browser bugs where `<use xlink:href>`
(bearing in mind this app uses modern `href` not `xlink:href`) doesn't
resolve in freshly-inserted DOM.
**Verify:** Open a widget's Edit Filters modal and confirm all icons
(e.g. `edit`, `x`, `check-square`) render correctly.

### Scenario 40: `data-modal-keep-open` -- modal re-fetch doesn't re-trigger layout scripts
**CSS target:** N/A (JS behavior), but affects CSS layout via
`dashboard_widget_preview.js` re-binding.
**Steps:**
1. Open the Customize modal from a Space page.
2. Add a widget. The modal stays open (data-modal-keep-open).
3. modal.js re-fetches the Customize URL and replaces `#modal-target`
   innerHTML (dashboard_widget_builder.js, line 103 area).
4. The re-fetched HTML includes new widget cards and a live preview pane.

**Expected:** The widget list in the modal shows the new widget. The
preview pane initializes correctly.
**Bug:** On the first open, `base.html` loads
`dashboard_widget_preview.js` which calls `CCWidgetPreview.init()`
(line 15 of `_widget_workspace.html` comment). This binds event
listeners to form fields for live preview. On the re-fetch (step 3),
the old DOM is replaced -- but `CCWidgetPreview.init()` is NOT called
again (it's a DOMContentLoaded handler or a one-time script). The new
form fields in the re-fetched HTML have NO event listeners. Live
preview breaks after the first add/edit in the modal.
**Verify:** Check if `base.html` or `modal.js` calls
`CCWidgetPreview.init()` after `innerHTML` replacement. If it
doesn't, this is a regression: live preview works on first open but
breaks after any add/edit/delete action within the modal.
**CSS impact:** Without re-init, the `Range` field
(`.widget-range-field`) visibility toggling (JS hides it when the View
doesn't use a range) doesn't fire, so irrelevant fields are
permanently visible -- cluttering the modal form.

---

### Scenario 41: Empty state icon differs per page context -- verify the ternary
**CSS target:** Template line 117:
`{{ icon('home' if not space_uid and not project_uid else ('folder' if space_uid else 'target')) }}`
**Steps:**
1. On Home with no widgets: icon should be `home`.
2. On a Space with no widgets: icon should be `folder`.
3. On a Project with no widgets: icon should be `target`.

**Expected:** Each empty state shows a contextually appropriate icon.
**Bug:** The template uses `space_uid` and `project_uid` from the
`widget_page_context` context (lines 1057-1058: `space_uid or ""`,
`project_uid or ""`). On a Project page, `space_uid` is `""` (falsy)
and `project_uid` is the project's uid (truthy). So the ternary
evaluates: `not space_uid and not project_uid` = `False`, then
`'folder' if space_uid else 'target'` = `target` (since space_uid is
falsy). Correct. But if BOTH `space_uid` and `project_uid` are somehow
set (shouldn't happen per the scope rules, but a forged URL could
try `/projects/groups/X?project_uid=Y`), the icon would be `target`
(project), which is the correct priority (project > space > home).
**Verify:** The empty state renders with the right icon for each
context, including edge cases like a Space with an empty project
inside it (the project page should show `target`, not `folder`).

### Scenario 42: `.widget-section-label` styling -- verify spacing in stacked widgets
**CSS target:** `.widget-section-label` (style.css line 1746-1750).
**Steps:**
1. In `_widget_today_agenda.html` (line 4) and `_widget_upcoming_events.html`,
   `<div class="widget-section-label">Tasks</div>` precedes each section.
2. Inspect the rendered label in dev tools.

**Expected:** `.widget-section-label` exists in style.css (line 1746):
`font-size:11px; text-transform:uppercase; letter-spacing:.04em;
color:var(--fg-tertiary); margin:10px 0 4px`. First-child gets
`margin-top:0` (line 1750).
**Status:** CSS exists and is correct. No bug here -- this scenario is
a verification that section labels are styled (not a bug report as
previously drafted). The label uses `--text-caption` (11px) and
`--fg-tertiary` (muted gray), with 10px top / 4px bottom margin.
**Edge case to verify:** In a tall stack (`xl` height), the section
label's `margin:10px 0 4px` is outside `.widget-content`'s
`overflow-y:auto` scrollport. If the table content pushes the label
to the top of the scroll area and the user scrolls up, the label
sticks at the top (no `position:sticky`). This means section headers
disappear when scrolled out of view. If there are many tasks and the
user scrolls to the Events section, they can't easily find the
"Tasks" label without scrolling back. For a 680px `xl` widget with
10+ tasks, the labels vanish quickly.
**Minor fix candidate:** Add `position:sticky; top:0; background:
var(--surface-container-high); z-index:1;` to
`.widget-section-label` so section headers stick to the top of the
scroll area while the content beneath them scrolls.

### Scenario 43: `min-height: 200px` on `.dashboard-grid` -- empty state floats at top
**CSS target:** `.dashboard-grid { min-height:200px }` (line 1578).
**Steps:**
1. Fix the re-seed bug (Scenario 1). Delete all widgets.
2. Observe the empty state in the grid.

**Expected:** The empty-state content ("No widgets yet" + icon + helper)
should be vertically centered or at least top-aligned with some
breathing room.
**Bug:** `.dashboard-grid` has `min-height:200px` but no
`display:flex; align-items:center; justify-content:center`. The
`.empty-state-rich` child uses `padding:var(--space-10) var(--space-5)`
(40px top/bottom) with `text-align:center`. So there's 40px of padding
above the icon. With a 200px grid and ~80px of content (48px icon +
16px gap + 15px title + 15px text), the content sits ~40px from the
top, leaving ~80px of empty space below. The content is NOT centered.
On a full-height dashboard page (with the toolbar and quick-add form
above), this looks like the empty state is "floating" at the top.
**Fix candidate:** Either increase `.dashboard-grid` min-height to
`60vh` or add flexbox centering when it contains only the empty state.

---

### Scenario 44: `.widget-preview-content .widget-preview-card .dashboard-grid` -- position reset
**CSS target:** Lines 1871-1874: override `position:static` for preview.
**Steps:**
1. Open the Customize modal.
2. The preview pane renders a `.widget-preview-card` which is a
   `.widget-card` (position:absolute by CSS line 1579).
3. The CSS at lines 1871-1874 overrides `position:static` for
   `.dashboard-grid` and `.widget-stack` inside the preview.

**Expected:** The preview card renders as a static block, fitting
within the dashed `.widget-preview-content` box.
**Bug:** The override only covers `.widget-preview-card` itself
(line 1868: `position:static; width:auto;`), `.dashboard-grid`
(line 1871), and `.widget-stack` (line 1872). But `.widget-card`'s
children (the `.widget-header`, `.widget-content`, `.widget-resize-handle`)
are NOT overridden. The `.widget-resize-handle` (width resize,
line 1599: `position:absolute; right:-6px`) would still be
`position:absolute` inside the now-static `.widget-preview-card`. Since
the preview card has no explicit dimensions (it's `width:auto` from the
reset), the absolute-positioned handle with `right:-6px` extends 6px
past the card's computed right edge. Inside
`.widget-preview-content` (which has `overflow:hidden`, line 1862),
this overflow is clipped. So the resize handle is INVISIBLE in the
preview. This is fine visually (we don't want resize handles in the
preview) but it means the preview doesn't accurately represent what
the widget will look like on the actual dashboard.
**Verify:** Also check that `.widget-drag-handle` (the move handle in
edit mode) is hidden in the preview -- it should be, since the preview
is not in edit mode. But if `data-modal-keep-open` re-render includes
`edit_mode=True` context (the Customize modal passes `edit=True` per
dashboard.py line 1145), the drag handles WOULD render in the preview.
This would be a visual bug: drag handles visible in the preview pane
inside the modal.

---

### Scenario 45: Dark mode theme -- verify all widget CSS custom properties swap correctly
**CSS target:** `[data-theme="dark"]` block (line 119-153).
**Steps:**
1. Toggle dark mode (via `#btnTheme` button in the tabbar).
2. Inspect widget cards, empty state, resize handles, stack borders.

**Expected:** All colors should update. `--surface-container-high` maps
to `--bg-elevated` (#2c2c2e in dark). `--border` becomes
rgba(255,255,255,.13). `--separator` becomes rgba(255,255,255,.09).
`--fg-primary` becomes #f5f5f7 (light text on dark bg).
**Bug risk:** The `.widget-resize-handle::after` (line 1602-1606)
uses `background:var(--border-strong)` and on hover
`background:var(--accent)`. Check that `--border-strong` is defined
in dark mode (line 126: `--border-strong:rgba(255,255,255,.22)` -- yes).
The `.widget-resize-handle-vertical::after` (line 1625-1629) uses
the same tokens. Verify the handles are visible in dark mode --
`--border-strong` at rgba(255,255,255,.22) on a `--surface-container-high`
(#2c2c2e) background should provide enough contrast. If not, the 3px-wide
handle bar becomes invisible.
**Extra:** Check the `.widget-stack-item + .widget-stack-item` border-top
(line 1651) uses `--separator` (rgba(255,255,255,.09) in dark) -- this
is a very low-contrast border. In a dark stack with dark cards, the
border between members might be nearly invisible, making stack members
blend together.

### Scenario 46: `word-wrap: break-word` on `.widget-content td` -- table column width
**CSS target:** `.widget-content td { word-wrap:break-word;
overflow-wrap:break-word }` (line 1621), `.widget-content
{ overflow-x:hidden }` (line 1620).
**Steps:**
1. Add a `today_agenda` widget with a task that has a long title
   (e.g. "Review Q3 marketing campaign deliverables and approve budget
   allocation for next quarter").
2. The widget is at `third` width (data-span="2", ~84px on desktop).
3. The `<td>` with the title has no fixed width -- only the completion
   button `<td>` is `width:26px` (inline style, template line 8).

**Expected:** The title `<td>` should take the remaining width and
wrap text as needed.
**Bug:** The `<table>` has no `table-layout: fixed` CSS rule. Without
it, the table uses `auto` layout -- columns size to their content.
The title cell (no width constraint) might expand to fit the full text
on one line, pushing the table wider than the `.widget-content` allows.
Then `overflow-x:hidden` clips the overflow -- the table is wider than
the widget but you can't scroll horizontally to see the rest. The
`word-wrap:break-word` should force wrapping, but `overflow-wrap:
break-word` (which is the same property, alias) only breaks at legal
opportunities. With `table-layout:auto`, the browser first tries to
lay out the table at its natural width (fitting all text without
wrapping), then applies break-word as a fallback. If the text is short
enough to fit without wrapping, no wrapping happens and the cell
doesn't shrink. Only when the cell's content is wider than the table
does breaking kick in. On a 84px-wide widget, even a 10-word title
should wrap -- but if the table's `auto` layout gives the title cell
more space (stealing from the status td), it might not wrap as
expected.
**Fix:** Add `table-layout:fixed; width:100%` to tables inside
`.widget-content`. This forces the title td to wrap at the available
width.

### Scenario 47: `.widget-card` without `.is-editing` -- edit controls hidden but JS still runs
**CSS target:** Edit controls gated by `{% if edit_mode %}` in Jinja
(templates), but JS IIFEs check `grid.classList.contains("is-editing")`
(app.js line 395, 694, 796).
**Steps:**
1. Load Home in view mode (not edit mode).
2. Inspect the widget cards. They should have NO drag handles, NO
   resize handles, NO delete buttons.
3. Open browser console. Type:
   `document.getElementById("dashboard-grid").classList.add("is-editing")`

**Expected:** The masonry layout, drag handlers, and resize handlers
ALL activate immediately (their IIFEs check `.is-editing` at runtime,
not just at DOMContentLoaded).
**Bug:** The IIFEs run on `DOMContentLoaded` (or at script parse time).
If the grid doesn't have `.is-editing` at that moment, the scripts
**return early** (line 395: `if (!grid || !grid.classList.contains
("is-editing")) return;`). So adding `.is-editing` later via console
will NOT activate them -- the event listeners were never bound. This
is fine for production (edit mode is toggled via URL `?edit=1`, causing
a full page reload), but it means there's no runtime toggle. The
template renders different HTML (edit controls present/absent) on a
full reload, and the JS re-binds on each load. This is a deliberate
design choice (no-JS `?edit=1` toggle), not a bug. But verify the
`is-editing` class on `.dashboard-grid` is added by the template
(conditionally): `_widget_workspace.html` line 82:
`<div class="dashboard-grid {% if edit_mode %}is-editing{% endif %}">`.
Correct -- template drives it, JS reads it.

### Scenario 48: `.multiselect-panel` z-index (40) vs `.modal-overlay` z-index (100)
**CSS target:** `.multiselect-panel { z-index:40 }` (line 652),
`.modal-overlay { z-index:100 }` (line 1173).
**Steps:**
1. Open the Customize modal (z-100 overlay).
2. In the modal's Filters form, open a multiselect dropdown
   (e.g. "Tags" or "Task lists" multi-select).

**Expected:** The dropdown panel appears inside the modal, below the
modal's own z-index but above the modal's body content.
**Bug:** The `.multiselect-panel` has `z-index:40` (line 652). The
`.modal-overlay` has `z-index:100`. Since the panel is a child of
the modal (inside `.modal-body`), its effective stacking is within
the modal's context. The modal body has `overflow-y:auto` (line 1214)
creating a scroll container. The dropdown extends `top:
calc(100% + 6px)` (below the trigger), but if the trigger is near the
bottom of the modal body, the panel may extend beyond the modal's
scrollable area. With `overflow-y:auto` on `.modal-body`, the panel
would be clipped at the scrollport boundary -- you can't see options
below the fold. Since `z-index:40` < `.modal-overlay` `z-index:100`,
the panel is below the modal scrim but that's fine (the panel is
*inside* the modal, not competing with it).
**Real bug:** If the multiselect is used on the main dashboard page
(not in the modal), e.g. in the quick-add form or a settings page,
`z-index:40` is BELOW `.tabbar` (z-20 desktop... wait, 40 > 20, so
the panel IS above the tabbar). That's correct. But the panel (z-40)
is BELOW the modal overlay (z-100) -- if both a modal and a
multiselect are open simultaneously (unlikely but possible if a
multiselect is triggered from a page that also has a modal), the
modal scrim would cover the dropdown. This shouldn't happen in
practice (the multiselect is inside the modal).

### Scenario 49: `.widget-card` width transition conflicts with masonry repositioning
**CSS target:** `.widget-card { transition: left var(--dur-normal)
var(--ease-standard), top var(--dur-normal) var(--ease-standard),
width var(--dur-normal) var(--ease-standard) }` (line 1580).
**Steps:**
1. Enter edit mode on Home.
2. Drag a widget to a new position (triggers reorder via
   `insertBefore`, app.js line 462).
3. Immediately resize the same widget (drag the width handle).
4. Release.

**Expected:** The card animates to its new position (160ms), then
resizes to the new width. The masonry layout recalculates on the
`data-span` attribute change (MutationObserver, app.js line 372).
**Bug:** Both the position transition and the resize transition fire
simultaneously if the card is moved AND resized in the same drag
session. The `transition` property applies to `left`, `top`, AND
`width` -- all three animate together. If the masonry layout fires
mid-animation (due to the MutationObserver detecting a `data-span`
change), it sets new `left/top/width` values while the previous
transition is still running. The browser interrupts the old transition
and starts a new one from the current rendered position -- causing a
janky two-step animation. The `transition: var(--dur-normal)
var(--ease-standard)` timing function (line 1580) means the second
transition starts from wherever the first one was interrupted, not
from the final target. This can look like the card "jitters" to its
final position.
**Fix:** Use `transition: none` on `.widget-card.is-resizing` (similar
to `.widget-card.is-dragging` at line 1584 which already sets
`transition:none`). Currently only `.is-resizing` (width) and
`.is-resizing` (height on `.widget-content`) are handled, but the
masonry repositioning via `left/top/width` is not suppressed during
resize. Add `transition:none` to `.widget-card.is-resizing` in CSS.

### Scenario 50: `.widget-content` scroll containment -- task "Mark done" action inside a scrolled widget
**CSS target:** `.widget-content { overflow-y:auto; overflow-x:hidden;
position:relative }` (line 1620), `.widget-content td {
word-wrap:break-word }` (line 1621).
**Steps:**
1. Add a `today_agenda` widget set to `short` height (180px).
2. Add 10 tasks due today -- they overflow the 180px height.
3. Scroll down inside the widget to see task #8.
4. Click the "Mark done" checkbox button (template
   `_widget_today_agenda.html` line 9-11: a `<form>` posting to
   `/tasks/{uid}/complete`).
5. The form POSTs (no-JS by design, line 9-11). The page reloads.

**Expected:** The widget re-renders with the task removed. The widget
scrolls back to top (page reload resets scroll position). The remaining
9 tasks are visible.
**Bug (if AJAX were added later):** If the "Mark done" form were
converted to AJAX (fetch + DOM patch), the scroll position of
`.widget-content` would be preserved. Removing task #8 from the DOM
would shift tasks #9 and #10 up, potentially revealing them. But the
scroll position stays at the same pixel offset -- if task #8 was at
the bottom of the visible area, removing it shifts content up and the
user might see a "jump" where the content above scrolls into view.
More critically: the `.widget-content` has `overflow-y:auto` which
creates a scroll container. If the scrollbar was visible (10 tasks in
180px) and after marking one done only 9 remain (now fitting in 180px
without scrolling), the scrollbar disappears -- causing a 16px layout
shift (content area width increases by 16px). This reflows the table
columns, potentially causing a visual "jump" of all content.
**Verify:** The current no-JS implementation reloads the page, so
scroll position resets. No bug exists currently. But if the team
converts widget inline-actions to AJAX (as part of the
calendar/tasks-as-widgets migration for a smoother UX), this scrollbar
disappearance layout shift must be handled.

---

### Scenario 51: `.empty-state-icon` -- icon SVG size mismatch inside 48px circle
**CSS target:** `.empty-state-icon { display:inline-flex;
align-items:center; justify-content:center; width:48px; height:48px;
border-radius:50%; background:var(--bg-secondary); }` (line 819-821),
`.empty-state-icon .icon { width:22px; height:22px }` (line 824).
**Steps:**
1. Delete all widgets (with the fix from Scenario 1 applied).
2. Inspect the empty-state icon element.

**Expected:** A 48px circular badge with a 22px icon centered inside.
**Bug:** The `.icon` inside `.empty-state-icon` is 22px, but the
`icon()` Jinja macro (base.html) typically renders SVGs with a default
size. Let me check what size `icon('home')` renders at -- it likely
outputs `<svg class="icon" width="16" height="16">` (or similar). The
CSS `.empty-state-icon .icon { width:22px; height:22px }` (line 824)
should override the inline width/height. But if the SVG uses
`viewBox` and the CSS sets `width/height`, the icon scales correctly.
**Verify:** The icon renders crisply at 22px inside the 48px circle,
with equal padding on all sides (48-22=26, /2=13px padding each side).
The `display:inline-flex` with `align-items:center;
justify-content:center` should center it. BUT: `display:inline-flex`
on the icon container means it's an inline-level flex container --
its vertical alignment is `baseline` by default. Inside the
`.empty-state-rich`'s `text-align:center` flow, the icon container
sits on the text baseline. The `.empty-state-title` (`<div>`) below it
has `margin-bottom:4px` (line 825). The spacing between the icon and
title should be consistent. Verify no unexpected gaps from inline
baseline alignment.

### Scenario 52: Mobile `tap-target-size` -- widget drag handle hit area
**CSS target:** `.icon-btn` (style.css line 359-362: `width:28px;
height:28px`), `.icon-btn .icon { width:16px; height:16px }` (line 414),
`.widget-drag-handle` (line 1582: cursor/padding only).
**Steps:**
1. On a phone (720px width), enter edit mode on any dashboard page.
2. The drag handle is a `<button type="button" class="icon-btn
   widget-drag-handle">` (template line 37). The `.icon-btn` class
   sets `width:28px; height:28px` with `padding:0`. The icon inside is
   16px (via `.icon-btn .icon` line 414), centered by
   `display:inline-flex; align-items:center; justify-content:center`.
3. The `touch-action:none` prevents page scroll during drag. The
   `cursor:grab` shows the open-hand cursor.

**Expected:** The handle should be at least 44px x 44px (Apple's
minimum touch target size) for reliable dragging on mobile.
**Bug:** `.icon-btn` is `28px x 28px` (line 360) -- below Apple's 44px
recommended minimum and Google's 48px. The `border-radius:var(
--radius-control)` (12px, line 361) makes the circular hit area
visually smaller. On mobile, a 28px target (with a 12px border-radius
making the clickable area a small circle) is hard to tap accurately,
especially while other fingers hold the screen. The `touch-action:none`
means if the initial tap misses the handle, it goes through to whatever
is underneath (another widget, the page background). If the user's
finger lands on the `.widget-card` padding area (16px on `.card`, line
510) instead of the handle, no drag starts and the card doesn't move.
**Fix candidate:** Add `@media (max-width:720px) { .icon-btn {
min-width:44px; min-height:44px; padding:var(--space-1) } }` to ensure
all icon buttons (drag handles, delete buttons, unstack buttons) meet
mobile tap-target guidelines. Or add `padding:var(--space-2)` (8px) to
`.icon-btn` globally (28px + 16px = 44px), since desktop doesn't suffer
from larger hit areas and the `transform:scale(.92)` on `:active`
(line 367) provides visual feedback that works at any size.
**Fix:** Add `min-width:44px; min-height:44px; padding:var(--space-2)`
to `.icon-btn` in `@media (max-width:720px)` (or globally, since
desktop doesn't suffer). Verify by inspecting `.icon-btn` in
style.css.

### Scenario 53: `.widget-builder` grid gap and preview border on high-DPI screens
**CSS target:** `.widget-builder { display:grid;
grid-template-columns:1fr 1fr; gap:var(--space-4); }` (line 1831),
`.widget-preview-content { border:1.5px dashed var(--border-strong) }`
(line 1861).
**Steps:**
1. Open the Customize modal on a Retina/high-DPI display.
2. Observe the dashed border on the preview content box.

**Expected:** The 1.5px dashed border should render as a crisp,
hairline dashed line.
**Bug:** On high-DPI screens, `1.5px` borders can render as 1 physical
pixel (with subpixel antialiasing) or can disappear entirely depending
on the browser's `devicePixelRatio` handling. If the border doesn't
render crisply, the preview pane looks like it has no boundary --
making it unclear where the preview content ends and the modal body
begins. This is especially problematic because the preview
`overflow:hidden` (line 1862) means content that overflows won't be
visible anyway. A missing border makes overflow invisible.
**Fix candidate:** Use `border:1px dashed` (rounds to 1 device pixel
on most screens) or use a CSS `box-shadow: inset 0 0 0 1px` trick for
crisp high-DPI borders.

### Scenario 54: `--radius-card: 16px` -- widget card corners on a `third`-width card
**CSS target:** `--radius-card:16px` (line 117), applied to `.card`
via `border-radius:var(--radius-card)` (line 509, but need to verify
`.card` uses `--radius-card`).
**Steps:**
1. Add a `third`-width widget (data-span="2"). On a 1120px `main`
   (max-width, line 468), the grid is 1040px (1120 - 80 sidebar -
   padding). 6 columns = ~160px each. `third` = 2 cols = ~336px.
2. The card has `border-radius:16px` on all corners.

**Expected:** The card is a 336px-wide rounded rectangle.
**Bug risk:** With `.widget-resize-handle` at `right:-6px` (sticking
out 6px past the right edge), the handle's `::after` bar
(`width:3px; height:28px; border-radius:var(--radius-pill)`) sits at
`right:5px` from the handle's left edge (which is 6px past the card).
So the bar is at the card's right edge + 5px - 6px = card edge - 1px.
Wait, let me re-read: the handle is `position:absolute; right:-6px;
bottom:0; top:0; width:12px`. Its `::after` is `position:absolute;
top:50%; right:5px; transform:translateY(-50%); width:3px; height:28px`.
So the `::after` bar is 5px from the handle's RIGHT edge. The handle's
right edge is at `right:-6px` = 6px past the card's right border box.
The handle is 12px wide. So the handle spans from 6px past the right
to 18px past the right (6+12). The `::after` bar is at `right:5px`
from the handle's right = 5px from the 18px-past mark = 13px past the
card's right edge. The bar is 3px wide, so it spans from 10px to 13px
past the card's right edge. This is a 3px-wide, 28px-tall bar floating
10-13px outside the card. For a 16px border-radius card, the corner
is a 16px-radius arc. The handle bar at 10-13px past the edge is
barely within the curve zone. It should look fine -- the bar is
centered vertically (top:50%) and slightly outside the horizontal
bounds. No visual bug here, but worth noting the handle extends beyond
the card's visual bounds.

### Scenario 55: `.dashboard-see-more` card visibility toggle at exactly 720px
**CSS target:** `.dashboard-see-more { display:none }` (line 1655),
`@media (max-width:720px) { .dashboard-see-more { display:block } }`
(line 1656-1658).
**Steps:**
1. Resize the browser to exactly 721px wide. The "See more" card
   (Databases, Projects, Habits, Contacts, Settings links) should be
   **hidden** (desktop view has these in the tabbar/sidebar).
2. Resize to exactly 720px. The "See more" card should **appear**.

**Expected:** Clean toggle at the breakpoint.
**Bug:** The `main` element's `max-width` changes at `@media
(min-width:721px)` (line 1123: `main{max-width:none}`). The
`.tabbar` changes from a 80px-wide vertical rail (z-20) to a 64px-tall
horizontal bar (z-100) at the same breakpoint. The
`.dashboard-see-more` toggles at `max-width:720px`. All three breakpoints
are at 720/721px -- consistent. But: the `.fab` (mobile FAB) also
appears at `@media(max-width:720px)` (line 1067). So at exactly 720px,
three things happen simultaneously: tabbar becomes bottom bar, FAB
appears, and "See more" card appears. If any of these have a
race condition in their CSS loading or JS initialization, there could
be a flash where the layout is inconsistent. Verify no
`display:contents` or `visibility:hidden` vs `display:none` mismatch
between the three at the breakpoint.

---

## Appendix C -- CSS Bug Fix Priorities

| Priority | File:Line | Issue | Impact |
|----------|-----------|-------|--------|
| **High** | `_widget_workspace.html:117` | Empty state not vertically centered in `.dashboard-grid` (min-height:200px, no flex centering) | User sees "No widgets" floating at top of empty space |
| **High** | `_widget_today_agenda.html:5` | No `.widget-section-label` sticky positioning | Section labels disappear when scrolled out of view in tall widgets |
| **Medium** | style.css:1620-1623 | `.widget-resize-handle-vertical` at `bottom:-6px` clipped by `.widget-content overflow-y:auto` | Bottom 6px of height resize handle invisible |
| **Medium** | style.css:1580 | No `transition:none` on `.widget-card.is-resizing` | Janky animation when reordering + resizing simultaneously |
| **Medium** | `_widget_today_agenda.html:5` | No `table-layout:fixed; width:100%` on widget tables | Long task titles can cause horizontal overflow + clipping |
| **Medium** | style.css:428-430 | `.tabbar` z-index:20 == `.widget-card.is-dragging` z-index:20 (different stacking contexts) | Fragile -- a future z-index refactor could cause sidebar to disappear under dragged cards |
| **Low** | style.css:1871-1874 | Resize handles not suppressed in Customize modal preview | Preview doesn't match actual dashboard rendering |
| **Low** | style.css:1625-1628 | `.widget-resize-handle-vertical::after` color uses `--border-strong` | In dark mode, rgba(255,255,255,.22) on #2c2c2e may be low-contrast |
| **Low** | style.css:1651 | `.widget-stack-item` border-top uses `--separator` | Very low-contrast border in dark mode (rgba(255,255,255,.09)) |

---

## Appendix D -- Calendar-as-Widget Specific Scenarios (5 items)

### Scenario 56: `calendar_agenda` widget month navigation links hardcode `/?`
**Template:** `_widget_calendar_agenda.html`, lines 17 and 19.
**Steps:**
1. Add a `calendar_agenda` widget on a **Space** page.
2. Click the "Previous month" arrow (`href="/?cal_year=...&cal_month=...#widget-{uid}"`).

**Expected:** Navigate to the Home page with `?cal_year` params.
**Bug:** The nav links hardcode `/?` (Home path). On a Space or Project
page, clicking prev/next should navigate to
`/projects/groups/{uid}?cal_year=...` or `/projects/{uid}?cal_year=...`,
not `/`. The `widget.uid` in the fragment (`#widget-{uid}`) is also
wrong -- Space/Project pages don't use `#widget-` anchors in their
`<h1>` or IDs; the widget card gets `id="widget-{uid}"` from
`_widget_workspace.html` line 85/106, which IS correct. But the base
URL `/` ignores the current page scope.
**Fix:** The link should use the `page_url` context variable (from
`widget_page_context`, line 1060: `_return_url(space_uid, project_uid)`)
instead of hardcoded `/`. Currently:
`href="/?cal_year={{ cal.prev_year }}&cal_month={{ cal.prev_month }}..."`.
Change to:
`href="{{ page_url }}?cal_year=...&cal_month=..."`.

### Scenario 57: `calendar_agenda` widget -- month nav fragment `#widget-{uid}` on Space/Project
**Template:** `_widget_calendar_agenda.html`, line 17/19.
**Steps:**
1. Add `calendar_agenda` on a Space page.
2. Click "Next month" link.
3. The browser navigates to `/projects/groups/{uid}?cal_month=...#widget-{uid}`.

**Expected:** The page loads with the new month. The browser scrolls
to the widget (if the `#widget-{uid}` anchor exists and has an `id`).
**Bug:** The Space page (`space_detail.html`) includes
`_widget_workspace.html` which renders `id="widget-{{ wc.widget.uid }}"`
on the card div (line 85/106). So the anchor target EXISTS. But the
fragment navigation depends on the month param being processed by
`space_detail` route. Check: `space_detail` (projects.py line 447)
takes `uid, request, edit, conn` -- it does NOT accept `cal_year`/`
cal_month` params! Only `dashboard_view` (dashboard.py line 1076-1083)
accepts `cal_year, cal_month`. So clicking the prev/next links on a
Space page navigates to the Space route with `?cal_year=&cal_month=`
query params that are **ignored** -- the month never changes.
**Fix:** `space_detail` and `project_detail` routes need to accept and
forward `cal_year`/`cal_month` to `widget_page_context`'s `nav`
parameter (same as `dashboard_view` does at line 1094). Or the
`calendar_agenda` template should detect the current scope and build
the correct URL with the right query params.

### Scenario 58: `habit_checkin` widget on Project page -- project scoping via `config["project_uid"]`
**Renderer:** `_render_habit_checkin` (dashboard.py line 381-422).
**Steps:**
1. Create a Project with 2 habits (both linked via `project_uid`).
2. Visit the Project page. The default-seeded widgets do NOT include
   `habit_checkin` (see `_DEFAULT_PROJECT_WIDGETS`, line 887-892:
   `calendar_agenda`, `weekly_overview`, `today_agenda`,
   `contact_list`).
3. Manually add a `habit_checkin` widget from the Project page's
   Customize modal.

**Expected:** The widget should show only habits linked to THIS
project (`config["project_uid"]` auto-set by `add_widget` line 1324).
**Bug risk:** `_render_habit_checkin` (line 394-406) checks
`config.get("project_uid")` first, then falls to `config.get("group_uid")`
via `_group_project_uids`. If `add_widget` sets BOTH `config["project_uid"]`
AND `config["group_uid"]` (it doesn't -- it sets `group_uid` for
space_uid and `project_uid` for project_uid, exclusively), there's no
conflict. But if a user manually edits the widget and adds both, the
`project_uid` check takes priority (line 394-396), which might exclude
habits that are in the Space but not in this specific Project. This is
correct behavior (Project page should show Project habits only), but
verify the Configure modal's filter form doesn't silently add
`group_uid` alongside `project_uid`.

### Scenario 59: `contact_list` widget -- address book scoping on Project vs Space
**Renderer:** `_render_contact_list` (dashboard.py line 332-378).
**Steps:**
1. Create a Space with 2 address books and 3 contacts.
2. Create a Project in that Space with 1 linked address book and 2
   contacts.
3. On the Space page, the default-seeded widgets do NOT include
   `contact_list` (see `_DEFAULT_SPACE_WIDGETS`, line 828-836:
   `calendar_agenda`, `weekly_overview`, `project_preview`,
   `habit_checkin`). So `contact_list` is NOT auto-added to Spaces.
4. Manually add `contact_list` on the Space page.
5. Manually add `contact_list` on the Project page.

**Expected:** Space page -- `config["group_uid"]` is set (auto by `add_widget`
line 1321). `_render_contact_list` resolves the group's project names as
implicit tag filters (line 360-362), then filters contacts by those tags
(line 371-376). Project page -- `config["project_uid"]` is set (auto by
`add_widget` line 1324). `_render_contact_list` pools only the Project's
linked address books (line 364-367: `book_paths = {a["uid"] for a in
db.list_addressbooks(conn) if a.get("project_uid") == project_uid}`),
then narrows further by tags (line 371-376).
**Status:** Both `group_uid` AND `project_uid` scoping are correctly
implemented in `_render_contact_list`. No bug. This is a verification
scenario to confirm the Project-scoped contact_list shows only that
project's address books (not the entire Space's contacts). Verify the
`tags_filter` union (line 362) doesn't accidentally exclude all contacts
if the Space has projects with names that don't match any contact tags.

### Scenario 60: Tasks-as-widget gap -- no full task list/table widget type
**Reference:** Scenario 12 (Category D).
**Steps:**
1. Search `WIDGET_TYPES` (dashboard.py line 479-560) for a type that
   renders a full sortable task list.
2. Available types: `today_agenda`, `mini_month_calendar`,
   `weekly_overview`, `upcoming_events`, `overdue_tasks`,
   `project_preview`, `habit_checkin`, `calendar_agenda`,
   `contact_list`, `filled_cards`.
3. `today_agenda` = tasks due today (too narrow).
   `overdue_tasks` = overdue only. `weekly_overview` = grouped by day
   (calendar view, not a flat list). `upcoming_events` = events, not
   tasks. No type renders all open tasks in a flat, sortable table.

**Expected:** There is NO widget type that replaces the `/tasks` page's
full task list (all open tasks, sortable by due date/priority/status,
filterable by list/project/tags).
**Conclusion:** The calendar/tasks-as-widgets migration CANNOT fully
replace the `/tasks` page without first adding a new widget type
(e.g. `task_list` or `task_table`). This is a **feature gap**, not just
a bug. If `/tasks` is removed or hidden, users lose the ability to see
all open tasks at once.
**Priority:** High if the calendar/tasks pages are being removed in
this same sprint.

---

> **Total: 60 scenarios** (20 core dashboard-interaction scenarios in
> Categories A-F [Scenarios 1-20], 35 CSS/visibility/layout scenarios in
> Appendix B [Scenarios 21-55], plus 5 calendar-as-widget edge cases
> in Appendix D [Scenarios 56-60]).
>
> **Category breakdown:** A=3 (re-seed bug), B=4 (stack lifecycle),
> C=3 (cross-scope isolation), D=5 (calendar/tasks migration),
> E=4 (auto-scoping & range), F=1 (resize/position),
> B-appendix=35 (CSS/visibility/layout), D-appendix=5 (calendar edge cases).



```python
# In _ensure_default_widgets (line 797):
def _ensure_default_widgets(conn) -> None:
    if db.get_app_meta(conn, "dashboard_home_seeded_v1"):
        return
    if db.list_dashboard_widgets(conn):
        db.set_app_meta(conn, "dashboard_home_seeded_v1", "1")
        return
    # ... existing seed loop ...
    db.set_app_meta(conn, "dashboard_home_seeded_v1", "1")
```

Same for `_ensure_default_space_widgets` (key:
`"dashboard_space_{uid}_seeded_v1"`) and
`_ensure_default_project_widgets` (key:
`"dashboard_project_{uid}_seeded_v1"`).

This preserves:
- First-visit seeding (flag absent -> seed + set flag).
- Idempotent no-op when widgets already exist (flag absent, widgets present -> set flag, no seed).
- **NEW:** Empty-after-deletion is honored (flag set, 0 widgets -> return early, render empty state).

The existing test `test_is_a_noop_once_any_widget_exists` (line 62) will
need updating: after deleting the last widget and calling
`_ensure_default_widgets` again, it should now assert `len(...) == 0`
(not `len(_DEFAULT_WIDGETS) - 1`), reflecting the corrected behavior.
