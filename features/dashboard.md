# Dashboard

Home page at `/`, powered by a registry-driven widget system
(`routers/dashboard.py`'s `WIDGET_TYPES`). Adding a widget type = one registry
entry + a render function; add/edit/reorder/delete machinery is generic.

## Widget types (12)

2026-08-15 widget consolidation (`plans/open.md` § Widget consolidation):
the original 11 types (`today_agenda`/`weekly_overview`/`upcoming_events`/
`overdue_tasks`/`project_preview`/`filled_cards`/`calendar_agenda` plus
`at_a_glance`/`mini_month_calendar`/`habit_checkin`/`contact_list`)
collapsed to 8 — four Agenda-family types merged into one configurable
`agenda`, two Projects-family types merged into one `spaces_projects`,
`calendar_agenda` cut outright (reproduce it by placing Mini Calendar next
to Agenda), plus two brand-new types, Streak and Next Deadline. The three
1.9-side-work additions (`important_urgent`/`scheduled_work_today`/
`quick_links`) were untouched by this pass, so the live registry is 11
types today. A one-time `app_meta`-guarded migration
(`_migrate_widget_consolidation`) rewrote every existing dashboard's
stored widget rows in place — nothing was lost, see its own docstring for
the exact old-type -> new-config translation, and "Migration" below for
the one visual side effect (width).

| Type | Shows | Default width |
|---|---|---|
| `agenda` | Consolidated: Range (`today` / `next_7_days` / `next_30_days` / `all_upcoming`, `config["range"]`) picks how far out; Show (`config["show"]`, a subset of `overdue`/`tasks`/`events`, default all three) picks which sections render. `today`/`all_upcoming` render a flat list (Overdue always its own section regardless of Range); `next_7_days`/`next_30_days` render a day-by-day grid. `limit` applies to the `all_upcoming` Tasks/Events sections only. | half |
| `at_a_glance` | 3-number stats strip (Overdue / Due today / Due this week), each linking to the matching filtered Tasks view | third |
| `mini_month_calendar` | month grid, busy dots only, prev/next | half |
| `spaces_projects` | Consolidated: Style (`config["style"]`, `list` default or `cards`) picks List (project/label rows + progress bar) or Cards (Material-You filled squares per Space, linking to `/labels/{name}`). Scope (`config["scope"]`, `space` default or `everything`, Space/Project pages only) picks whether a page's own instance stays auto-scoped to that page's children (projects AND sub-Spaces both) or shows the app-wide list instead | third |
| `habit_checkin` | check-off-today per active habit (checkbox for target=1, count + `+1` stepper for target>1), no-JS forms | half |
| `contact_list` | contacts filtered by labels, `limit` | third |
| `important_urgent` | open tasks flagged important/urgent that aren't already due/overdue (`limit`, default 8) — ported from the retired `/today` page (1.9 side work), see `features/today.md` | half |
| `scheduled_work_today` | today's work-allocation sessions + a completed-hours total — ported from the retired `/today` page (1.9 side work) | third |
| `quick_links` | visual tile grid of every Space + every open project (label icon/color, `spaces_projects`' Cards-style CSS reused) — Home-only, 1.9 side work | full |
| `streak` | current + longest run of consecutive days with >=1 task completed (`tasks.completed_at`) | third |
| `next_deadline` | the single soonest open task due date and the single soonest upcoming event | third |
| `organize_today` | "what needs organizing" — open tasks due within 3 days with no work session yet, open Urgency=3 tasks with none (regardless of date), and today's/tomorrow's events with no location or meeting link set (a proxy for the not-yet-shipped Format field, `plans/open.md`). Task rows reuse the planning grids' own `_unscheduled_task_item.html` partial (project pill + title + a "+"/"−" session stepper, `POST /tasks/{uid}/work-allocations[...]`), so a session can be added right from the widget | half |

`important_urgent`/`scheduled_work_today`/`streak`/`next_deadline`/
`organize_today` are addable through the existing Source/View picker (all
under the `calendar_tasks` source); `quick_links` and `spaces_projects`
each have their own source (`quick_links`/`spaces_projects`), since both
read `label_config` directly and have no tasks/events filter (`uses:
set()`). Agenda's own view (`agenda_view`, source `calendar_tasks`) is
the one View that exposes both Range and Show controls in the builder
form (`has_range`/`has_show` on its `WIDGET_VIEWS` entry); Spaces &
Projects' view (`spaces_projects_view`) exposes the Style radio
(`has_style`) and, on a Space/Project page only, the Scope radio.
`has_limit` (2026-08-15, expanded scope) marks which Views expose the
Limit field at all — `agenda_view`, `contact_list_view`, and
`important_urgent_view` (the three render functions that actually read
`config["limit"]`); generalized from an earlier hardcoded single-view
check once `contact_list`/`important_urgent` turned out to already
support a limit with no way to set one.

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

- One-time per page (`app_meta` keys): `_seed_agenda_stack_layout` — an
  `agenda` (range=today) beside a stack of At a Glance / `agenda`
  (range=all_upcoming, show=[events]) / `agenda` (range=today,
  show=[overdue]) — for Home and every label page;
  `_backfill_mini_calendar_widget` one-time migration. Reset layout
  re-seeds.
- Scope rules: Home offers all types; a generated Space page excludes
  `quick_links`; a plain label (Project) page excludes `spaces_projects` +
  `quick_links` (`quick_links`'s "every Space + every project" view, and
  `spaces_projects`' whole-registry-of-labels view, are both meaningless
  once you're already inside one page).
- `spaces_projects`' own **Scope** (2026-08-15, expanded scope,
  `plans/open.md` § Widget consolidation) is a widget-*instance* setting,
  not a second widget type — a Space/Project page's own instance is
  auto-scoped to that page via `config["label_name"]` by default
  (`scope: "space"`, or the key absent), same as every other filtered
  widget type; `scope: "everything"` opts just that one instance out,
  rendering the app-wide list instead (ignoring `label_name` entirely
  inside `_render_spaces_projects`). The Scope field only appears in the
  builder/edit forms when the widget already belongs to a Space/Project
  page (`space_uid`/`project_uid`/`widget.label_name`) — Home has nothing
  to opt out of.

## Migration (2026-08-15 widget consolidation)

`_migrate_widget_consolidation` runs once (`app_meta`-guarded, from
`widget_page_context` so it covers Home + every label page) and rewrites
every existing `dashboard_widgets` row in place: `today_agenda` ->
`agenda`/today/show-all-three; `weekly_overview` -> `agenda`/next_7 or
next_30/show=[tasks,events]; `upcoming_events` -> `agenda`/matching
range/show=[events]; `overdue_tasks` -> `agenda`/today/show=[overdue];
`project_preview`/`filled_cards` -> `spaces_projects`/style
list-or-cards; `calendar_agenda` splits into two rows (the old row
becomes an `agenda`/next_7_days/show=[tasks,events], a brand-new
`mini_month_calendar` row is inserted beside it sharing the same
`group_uid` so a stacked calendar_agenda keeps both halves stacked
together). One deliberate visual trade-off: every migrated (and
newly-added) Agenda widget now renders at `agenda`'s single
`default_width` ("half") regardless of which of the four old types it
used to be — `weekly_overview`/`overdue_tasks`/`upcoming_events` used to
render at "full"/"third"/"third" respectively; a consolidated type can
only have one static default width (manual per-instance width was
already removed, 2026-08-07), and "half" (the most commonly seeded case,
Today's Agenda) was chosen as the safer default over "full" for a
typical flat/today-range widget.

## Page chrome

- Server-side time-of-day greeting ("Good morning/afternoon/evening, {name}",
  driven by Settings' display name).
- Per-page **banner** (cover image) — see `banners.md`.
- **Quick add**: the merged "+" button opens one modal (`/quick/add`,
  `quick_add.html`) with a Task/Event tab switch; the tab switcher retargets the
  footer Save via `form=`. Same form fields as the full task/event forms.

## Display fixes (1.9 side work)

- The old `_widget_upcoming_events.html`'s date+time column was a fixed
  110px `<td>` holding both an ISO date and a time on the same line, which
  wrapped onto two lines at that width — widened to 150px +
  `white-space:nowrap`. That column now lives in `_widget_agenda.html`'s
  own all_upcoming Events section (2026-08-15 consolidation carried the
  fix forward unchanged); audited every other `_widget_*.html` partial for
  the same fixed-narrow-column date+time pattern at the time, none of the
  rest combine a date and a time in one column.

## Endpoints

`/` (view, `?edit=`, `?cal_year=`/`?cal_month=`), `/quick/add`,
`/dashboard/customize`, `/dashboard/reset`, `/dashboard/widgets` (add),
`/dashboard/widgets/preview`, and per-widget `/{uid}/edit`, `/{uid}/delete`,
`/{uid}/move`, `/{uid}/reorder`, `/{uid}/stack-onto`, `/{uid}/unstack`.
