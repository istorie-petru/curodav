# Dashboard

Home page at `/`, powered by a registry-driven widget system
(`routers/dashboard.py`'s `WIDGET_TYPES`). Adding a widget type = one registry
entry + a render function; add/edit/reorder/delete machinery is generic.

## Widget types (14)

| Type | Shows | Default width |
|---|---|---|
| `today_agenda` | Today's Agenda — overdue + due-today tasks and today's events | half |
| `weekly_overview` | next-N-days day-by-day breakdown (`range_days`: 7/30) | full |
| `upcoming_events` | next events from now (`limit` + optional `range_days`) | third |
| `overdue_tasks` | open tasks past due, most-overdue first | third |
| `at_a_glance` | 3-number stats strip (Overdue / Due today / Due this week), each linking to the matching filtered Tasks view | third |
| `mini_month_calendar` | month grid, busy dots only, prev/next | half |
| `calendar_agenda` | mini calendar + 7-day agenda combined | third |
| `habit_checkin` | check-off-today per active habit (checkbox for target=1, count + `+1` stepper for target>1), no-JS forms | half |
| `project_preview` | child-label progress bars | third |
| `contact_list` | contacts filtered by labels, `limit` | third |
| `filled_cards` | Material-You filled squares per Space, linking to `/labels/{name}` | full |
| `important_urgent` | open tasks flagged important/urgent that aren't already due/overdue (`limit`, default 8) — ported from the retired `/today` page (1.9 side work), see `features/today.md` | half |
| `scheduled_work_today` | today's work-allocation sessions + a completed-hours total — ported from the retired `/today` page (1.9 side work) | third |
| `quick_links` | visual tile grid of every Space + every open project (label icon/color, `filled_cards`' own CSS reused) — Home-only, 1.9 side work | full |

`important_urgent`/`scheduled_work_today` are addable through the existing
Source/View picker (both under the `calendar_tasks` source, as
`important_urgent_view`/`scheduled_work_view`); `quick_links` has its own
`quick_links` source/`quick_links_view` view, since it reads `label_config`
directly and has no tasks/events filter (`uses: set()`, same as
`project_preview`/`filled_cards`).

Plus the `stack` container type (not in the registry): drag a widget onto another
card → one shared-width card with both stacked; members share `group_uid`; stacks
can't nest; deleting a stack dissolves it back to top level (never destroys
members).

## Adding / arranging

- **Widget Builder** with always-live preview (`POST /dashboard/widgets/preview`,
  `dashboard_widget_preview.js`) — pick Source/View/Range (`WIDGET_SOURCES`,
  `WIDGET_VIEWS`, `WIDGET_RANGES`), resolved via `_resolve_selection`.
- **Customize modal** (`/dashboard/customize`, `dashboard_customize.html`): one
  friendly flat list per dashboard/Space for add/move/up/down/delete/stack-dissolve
  and per-widget filters.
- **Filters** use the shared label vocabulary; a task's "project" is always
  inherited from its list — no per-task project field.
- Grid is masonry over 6 virtual columns (app.js); width is each type's
  `default_width` (manual width/height pickers were removed).

## Seeding & scope

- One-time per page (`app_meta` keys): `_seed_agenda_stack_layout` (Today's
  Agenda + stacked At a Glance/Upcoming Events/Overdue Tasks) for Home and every
  label page; `_backfill_mini_calendar_widget` one-time migration. Reset layout
  re-seeds.
- Scope rules: Home offers all types; a generated Space page excludes
  `filled_cards` + `quick_links`; a plain label (Project) page excludes
  `filled_cards` + `project_preview` + `quick_links` (`quick_links`'s "every
  Space + every project" view is meaningless once you're already inside
  one, same reasoning `filled_cards`/`project_preview` were already excluded
  for).

## Page chrome

- Server-side time-of-day greeting ("Good morning/afternoon/evening, {name}",
  driven by Settings' display name).
- Per-page **banner** (cover image) — see `banners.md`.
- **Quick add**: the merged "+" button opens one modal (`/quick/add`,
  `quick_add.html`) with a Task/Event tab switch; the tab switcher retargets the
  footer Save via `form=`. Same form fields as the full task/event forms.

## Display fixes (1.9 side work)

- `_widget_upcoming_events.html`'s date+time column was a fixed 110px `<td>`
  holding both an ISO date and a time on the same line, which wrapped onto
  two lines at that width — widened to 150px + `white-space:nowrap`. Audited
  every other `_widget_*.html` partial for the same fixed-narrow-column
  date+time pattern; none of the rest combine a date and a time in one
  column (most show just a time, e.g. `today_agenda`'s event rows, or just a
  date, e.g. `overdue_tasks`'s due-date cell), so this was the only fix
  needed.

## Endpoints

`/` (view, `?edit=`, `?cal_year=`/`?cal_month=`), `/quick/add`,
`/dashboard/customize`, `/dashboard/reset`, `/dashboard/widgets` (add),
`/dashboard/widgets/preview`, and per-widget `/{uid}/edit`, `/{uid}/delete`,
`/{uid}/move`, `/{uid}/reorder`, `/{uid}/stack-onto`, `/{uid}/unstack`.
