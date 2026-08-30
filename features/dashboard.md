# Dashboard

Home page at `/`, powered by a registry-driven widget system
(`routers/dashboard.py`'s `WIDGET_TYPES`). Adding a widget type = one registry
entry + a render function; add/edit/reorder/delete machinery is generic.

## Widget types (8)

2026-08-15 widget consolidation (`plans/open.md` § Widget consolidation):
the original 11 types (`today_agenda`/`weekly_overview`/`upcoming_events`/
`overdue_tasks`/`project_preview`/`filled_cards`/`calendar_agenda` plus
`at_a_glance`/`mini_month_calendar`/`habit_checkin`/`contact_list`)
collapsed to 8 — four Agenda-family types merged into one configurable
`agenda`, two Projects-family types merged into one `spaces_projects`,
`calendar_agenda` cut outright (reproduce it by placing Mini Calendar next
to Agenda), plus two brand-new types, Streak and Next Deadline. The three
1.9-side-work additions (`important_urgent`/`scheduled_work_today`/
`quick_links`) were untouched by this pass, so the live registry was 11
types at that point (`important_urgent` is since removed outright along
with the rest of the Importance/Urgency feature, see
`src/derived_state.py`'s module docstring; a further two types, Organize
Today and Weekly Schedule, were added later). A one-time `app_meta`-guarded
migration (`_migrate_widget_consolidation`) rewrote every existing
dashboard's stored widget rows in place — nothing was lost, see its own
docstring for the exact old-type -> new-config translation, and
"Migration" below for the one visual side effect (width).

**2026-08-30, direct requests** ("merge the quick links and spaces &
projects into one data source" / "maybe just remove the next deadline,
what needs organizing and streak widgets - not really that useful"):
`quick_links` retired outright, merged into `spaces_projects`'s own
"cards" style (an unscoped "cards" instance now renders every Space +
every open project, the same set `quick_links` used to render on its
own — see that render function's own comment); `streak`/`next_deadline`/
`organize_today` removed outright, no replacement. A second one-time
`app_meta`-guarded migration (`_migrate_widget_removal_2026_08_30`,
same `widget_page_context` call site as the 2026-08-15 one) rewrites any
existing `quick_links` row to `spaces_projects`/cards in place and
deletes any existing row of the other three types. Back down to 8 types
from the 12 the section header above once counted.

| Type | Shows | Default width |
|---|---|---|
| `agenda` | Consolidated: Range (`today` / `next_7_days` / `next_30_days` / `all_upcoming`, `config["range"]`) picks how far out; Show (`config["show"]`, a subset of `overdue`/`tasks`/`events`, default all three) picks which sections render. `today`/`all_upcoming` render a flat list (Overdue always its own section regardless of Range); `next_7_days`/`next_30_days` render a day-by-day grid. `limit` applies to the `all_upcoming` Tasks/Events sections only. | half |
| `at_a_glance` | 3-number stats strip (Overdue / Due today / Due this week), each linking to the matching filtered Tasks view | third |
| `mini_month_calendar` | month grid, busy dots only, prev/next | half |
| `spaces_projects` | Consolidated: Style (`config["style"]`, `list` default or `cards`) picks List (project/label rows + progress bar) or Cards (Material-You filled squares, no `.widget-card` chrome — see `.widget-card--bare` — one per Space linking to `/spaces/{name}`, plus, when unscoped, one per open project linking to `/tasks`; 2026-08-30 merge, see above). Scope (`config["scope"]`, `space` default or `everything`, Space/Project pages only) picks whether a page's own instance stays auto-scoped to that page's children (projects AND sub-Spaces both) or shows the app-wide list instead | third |
| `habit_checkin` | check-off-today per active habit (checkbox for target=1, count + `+1` stepper for target>1), no-JS forms | half |
| `contact_list` | contacts filtered by labels, `limit` | third |
| `scheduled_work_today` | today's work-allocation sessions + a completed-hours total — ported from the retired `/today` page (1.9 side work) | third |
| `weekly_schedule` | a compact, **static** weekly-pattern grid of a label's long-lived recurring events (a "university timetable" without reviving the removed Schedule module, `plans/abandoned.md`) — a recurring event qualifies once its own rule spans >= 30 days from first to last occurrence (`_is_long_lived_recurrence`, filters out a short recurring reminder while keeping a real standing pattern); every qualifying event's grid slot comes straight from its own `start_at`/`end_at` weekday+time-of-day, not from expanding any one real calendar week — holidays/manual exceptions are deliberately not reflected. Only weekdays with a block become columns, the vertical range is tightened to the events' own time span (not a full 24h day), and a plain agenda-style list renders below the grid for full readable detail | half |

`scheduled_work_today`/`weekly_schedule` are addable through the existing
Source/View picker (both under the `calendar_tasks` source);
`spaces_projects` has its own source, since it reads `label_config`
directly and has no tasks/events filter (`uses: set()`). Agenda's own
view (`agenda_view`, source `calendar_tasks`) is
the one View that exposes both Range and Show controls in the builder
form (`has_range`/`has_show` on its `WIDGET_VIEWS` entry); Spaces &
Projects' view (`spaces_projects_view`) exposes the Style radio
(`has_style`) and, on a Space/Project page only, the Scope radio.
`has_limit` (2026-08-15, expanded scope) marks which Views expose the
Limit field at all — `agenda_view` and `contact_list_view` (the render
functions that actually read `config["limit"]`; `important_urgent_view`
used to be a third such view, removed along with the rest of the
Importance/Urgency feature); generalized from an earlier hardcoded
single-view check once `contact_list` turned out to already support a
limit with no way to set one.

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
- Grid is masonry over 12 virtual columns (app.js; widened from 6,
  2026-08-30 — see below); placement is best-fit among not-yet-placed
  cards, not strict DOM order (2026-08-30 direct report, "the way
  widgets are aranged is not ok" — a short widget's dead-space gap can
  now be backfilled by a later, narrower widget). Width is each type's
  `default_width` unless a widget instance's own **Width** field
  (Filters panel — Auto/25%/50%/75%/100%) overrides it, reinstated
  2026-08-30 (direct request, after the automatic layout still didn't
  land on something the user wanted even with the best-fit fix above —
  reverses the 2026-08-07 "no manual override" decision for width only;
  height stays automatic, no manual height picker came back). See
  `routers/dashboard.py`'s `WIDGET_WIDTHS`/`WIDGET_WIDTH_CHOICES`/
  `_widget_width`.

## Seeding & scope

- One-time per page (`app_meta` keys): `_seed_agenda_stack_layout` — an
  `agenda` (range=today) beside a stack of At a Glance / `agenda`
  (range=all_upcoming, show=[events]) / `agenda` (range=today,
  show=[overdue]) — for Home and every label page;
  `_backfill_mini_calendar_widget` one-time migration. Reset layout
  re-seeds.
- Scope rules: Home offers all types; a generated Space page has no
  exclusions; a plain label (Project) page excludes `spaces_projects`
  (its whole-registry-of-labels view is meaningless once you're already
  inside one page). Before the 2026-08-30 `quick_links` merge, both a
  Space and a Project page also excluded `quick_links` for the same
  "every Space + every project" reason -- gone along with the type.
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

## Widget bodies (shared library, 2026-08-17)

All visual widgets' *bodies* — the content between the shared card
chrome (`_widget_inner.html`) and the widget's own header — compose the
same small component library now, `_widget_items.html`. Before this pass
each widget hand-rolled the same row / pill / stat / empty-state /
filled-card markup with small differences (a bare `.cell-tag` with no color
class rendered as a transparent pill, three arbitrary fixed-width time
columns, inconsistent empty-state markup); they now `{% from
"_widget_items.html" import ... %}` the shared pieces instead:

- `widget_link_row(url, title, leading=..., leading_class=..., right=...)`
  — the simple link-list row (an agenda item, an "Unscheduled work" item,
  a weekly-schedule row). Leading/right cells carry `.widget-row-icon` /
  `.widget-row-time` / `.widget-row-right` classes instead of inline fixed
  widths — `white-space:nowrap` on `.widget-row-time` is what actually
  keeps a date+time cell on one line (no fixed column widths anywhere).
- `widget_pill(text, color, icon_name=...)` — the read-only status pill
  (`.pill-static.pill-{color}`); the `.pill-*` family now covers the full
  16-color identity palette (only 7 of the classes existed before, so e.g.
  a `pink`/`teal` pill rendered uncolored).
- `stat_block(number, label, ...)` — At a Glance's number cells;
  `filled_card(...)` — Spaces & Projects' colored tiles; `widget_empty(
  message, inset=...)` — the empty state; `widget_section_label(text)`;
  `relative_due(days)`; `widget_complete_button(uid)`.

Exceptions, deliberately NOT on the library (documented at the top of each
file): `_widget_mini_month_calendar.html` (a genuinely custom grid layout,
no shared piece applies) and the Spaces & Projects *list* style, whose
`.cell-tag.cal-*` project pill is a label-identity swatch — a different
kind of chip from a status pill (UI guide §6). A structural sweep test
(`test_widget_library.py`) locks the convention: no visual widget may
hand-roll an empty-state, section label, status pill, or fixed-width cell.

## Endpoints

`/` (view, `?edit=`, `?cal_year=`/`?cal_month=`), `/quick/add`,
`/dashboard/customize`, `/dashboard/reset`, `/dashboard/widgets` (add),
`/dashboard/widgets/preview`, and per-widget `/{uid}/edit`, `/{uid}/delete`,
`/{uid}/move`, `/{uid}/reorder`, `/{uid}/stack-onto`, `/{uid}/unstack`.
