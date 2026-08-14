# Open work — priority

The high-priority work: the changes that reshape the app's internal architecture
and its presentation as a whole — the project-enabled label stack and everything
that comes with it (new pages, new UI, task-model changes), the Schedule /
recurrence rework, the virtual / derived-state model, the new view surfaces, and
offline-first sync. Low-priority or app-local features live in
[`open.md`](open.md); the single build order across both is in
[`roadmap.md`](roadmap.md); shipped work lives in
[`features/`](../features/README.md); what's been deliberately cut lives in
[`abandoned.md`](abandoned.md).

**Version:** the app is at **1.1** (1.0 was the first full release; 1.1 —
Virtual & derived states — shipped 2026-08-13). This
rework ships as minor releases `1.2` … `1.9` and is complete with the **2.0**
full release. The versioning scheme and full phase history (0.1 → 1.0) are in
[`abandoned.md`](abandoned.md); the release-by-release order is in
[`roadmap.md`](roadmap.md).

## Build order — how these land most optimally

The sections below are grouped by feature, not presented as one coherent plan.
This chapter proposes the dependency-driven order to implement them in. Each
step is sized to ship on its own.

1. ~~**Virtual & derived states**~~ — **shipped 2026-08-13** (see
   `features/tasks.md` § Importance, Urgency, and the virtual states). Settled
   the temporal-state model (temporal states are not labels), the shared
   aggregation service, and Importance / Urgency, including their WebDAV
   representation. Every other surface (project cards, Week, Today, Dashboard)
   reads their output, and the sync work builds on the WebDAV mapping fixed
   here.
2. ~~**Task model decision**~~ — **resolved 2026-08-13** (part of release 1.2).
   Chose **flat tasks + work allocations**: the parent-task/subtask hierarchy is
   removed outright (the old `tasks.parent_uid` column stays on disk but is never
   written or read). Work allocation replaces subtasks being individually
   scheduled, and outcome/parent aggregation is reproduced by a project label
   plus its tasks. The project stack and the Week view build on this model.
3. **Project-enabled label stack** — projects as labels with a bounded period
   and lifecycle, project pages (cards, tasks view, week calendar), work
   allocations, and the task/calendar semantics. The core of the rework.
4. **Schedule & recurrence rework** — generalized recurrence with a
   non-working-day policy, named holiday calendars, manual occurrence
   exceptions, and configurable terminology; courses become project labels +
   recurring events. Builds on the project stack.
5. **Information architecture & view surfaces** — Dashboard (orientation), Today
   (execution), Week (planning), Spaces (context). These are the new pages / UI;
   they consume the aggregation service and work allocations.
6. **Offline-first editing & synchronization** — the largest engineering item;
   its sync model must be written before any code. Can start in parallel with
   steps 3–5 once step 1's WebDAV mapping is fixed.

## Project-enabled label stack

**Status:** **1.3 shipped 2026-08-13** — the label + lifecycle + cards half
of this section (is_project/start_date/end_date/archived_at on
label_config, the computed Open/Pending/Pending Archiving/Archived
lifecycle, the overlap rule, project_label_for's supersession, and the
dedicated `/projects` page) is implemented; see `features/tasks.md` §
Projects for the shipped shape and `plans/roadmap.md`'s 1.3 subsection for
what's explicitly deferred. **Still open, for 1.4/1.5:** the project's own
Tasks view + Week Calendar view (§ Project pages & views), work allocations
(§ Work allocations, § Task & calendar semantics), and the global Tasks
page's project grouping (§ Task model) — the rest of this section's spec
below is still the reference for those slices, not yet built.

### Projects are labels, not a stored thing

A project is not a separate organizational primitive from labels. A project is a
user-created label with the **Project behavior** enabled: this adds a bounded
period (start and end dates), project-specific views, workload aggregation, and
a project lifecycle. Labels remain the universal organizational mechanism; the
label stays usable across the rest of the application, so a project can combine
with other labels such as `University`, `Historiography`, or `Important` without
introducing a second hierarchy.

Empty labels are valid and useful. A label with no linked entities or history
can be promoted to a project directly, and Project behavior can be removed to
demote it back to a normal label — both by default, without deleting the label.
If a project contains data, removing Project behavior drops its project-specific
semantics and views but preserves the label and every entity associated with it.

A project has exactly one start date and one end date. The end date is
authoritative: it is the project's actual deadline, not an estimate. A project
cannot have multiple active periods or several independent end dates. A project
may exist without tasks; a project with no work is still a valid bounded
organizational context.

Projects may not overlap another project that uses the same project context. If
the user creates or modifies a project so that its period overlaps a disallowed
project, the application shows a warning and requires the user to resolve the
conflict rather than silently accepting the state.

A project represents an outcome or area of work that exists over a period of
time. Its dates describe the project's overall horizon, not the period during
which every associated task must be worked on. A project such as
`Conference XYZ`, running from August 11 to October 13, can contain tasks that
have no independent start or due date. The project provides the context and
deadline; the individual work is scheduled separately.

### Project lifecycle

Project status is explicit, not inferred purely from dates:

- **Open** — the project is active and at least one task remains incomplete.
- **Pending** — all project tasks are completed, but the project has not been
  formally closed.
- **Pending Archiving** — the project has reached the point where the user must
  confirm closure before archival.
- **Archived** — the user has explicitly confirmed the project is finished and
  it has been closed.

The end date does not automatically archive a project, and completing all tasks
does not silently archive it; the user must have the opportunity to verify the
project is actually finished, because a project may contain information or
events that remain useful after its tasks are completed. The end date remains
authoritative regardless of the lifecycle state, so the two are represented
independently: the deadline describes when the project ends; status describes
whether the work is completed and whether closure has been confirmed. A project
may therefore reach its end date with tasks still incomplete, or all tasks may
be completed before the end date.

### Project pages & views

**Tasks view shipped 2026-08-14 (1.4 slice 2)** — see `features/tasks.md` §
Projects, "Project detail page + Tasks view": `GET /projects/{name}`, tasks
filtered by the project's label, reusing the global Tasks page's row
markup/inline editing. **Still open**: "create, edit... and organize" beyond
what the reused row already offers (no project-scoped sort/filter/bulk
actions).

**Week Calendar view shipped 2026-08-13 (1.4 slice 3)** — see
`features/tasks.md` § Projects, "Week Calendar view": `GET
/projects/{name}/calendar` (`routers/projects.py::project_calendar`), the
Tasks/Week Calendar tab switcher on the project detail page, an
"Unscheduled tasks" list (open project tasks with no work allocation yet,
each item `{project} > {task} · {remaining}h`) that drags onto the week
grid to create a work allocation (`create_allocation`), drag-to-move /
drag-to-resize an existing block (`move_allocation`), and a delete
affordance that only removes the block (`delete_allocation` ->
`db.delete_work_allocation`). Ordinary calendar events render as visually
subdued context (`.context-event`, reduced opacity); this project's own
work allocations render at full color/prominence. **Still open, deferred**
(doesn't block 1.5+): aggregating `task_work_hours` up to the project
card's progress percentage, and hiding a completed task's future
allocations from this calendar (§ Work allocations' "future allocations are
hidden" rule) — see `plans/STATE.md`.

Projects receive a dedicated page in the main sidebar. This page is the primary
interface for connecting project work with calendar time; task scheduling is
deliberately **not** distributed through the global Calendar, which stays
focused on calendar management.

Opening a project provides two principal views:

- **Tasks view** — an easy way to create, edit, complete, filter, and organize
  the tasks belonging to the project. Newly created tasks automatically receive
  the project's label. Completed tasks remain visible.
- **Week Calendar view** — the project's scheduling surface. Unscheduled tasks
  are presented above or beside the calendar and can be dragged into available
  time. A task item carries enough context to identify it, e.g.
  `Conference XYZ > Research · 3h`. Dragging it onto the calendar creates a work
  allocation, which can then be moved or resized directly; resizing changes the
  amount of scheduled work the allocation represents, and a task can be placed
  into multiple independent blocks across different days or weeks.

The project calendar displays ordinary calendar events as surrounding context:
project work allocations are visually prominent, unrelated events visually
subdued (reduced opacity or a restrained hashed treatment), communicating that
time is occupied without becoming a second copy of the global calendar. It
answers one question — **"When can I actually do the work belonging to this
project?"** — and does not attempt to replace the global Calendar.

### Project cards & progress

The Projects page presents current projects as visual cards rather than another
dense database table, using real project data so state is understandable without
opening each project. A card shows:

- project name and labels;
- start and end dates;
- project status (lifecycle state);
- number of tasks;
- completed and remaining tasks;
- total scheduled work;
- completed work;
- remaining work;
- upcoming deadline;
- progress percentage.

Project progress is based on **work**, not merely task count: the percentage
represents completed scheduled work relative to total scheduled work. This
prevents a project with one twenty-hour task from appearing equivalent to a
project with twenty trivial tasks because both contain the same task count. The
exact treatment of unscheduled tasks stays visible — the interface distinguishes
work that exists from work that has actually been scheduled. Completed tasks
remain visible and contribute to the project's historical record.

### Work allocations

**Data model + task-detail UI shipped 2026-08-13 (1.4 slice 1)** — see
`features/tasks.md` § Work allocations (1.4): `event_task_relations.
is_work_allocation`, `db.create_work_allocation`/`list_work_allocations_for_task`/
`task_work_hours`/`delete_work_allocation`, title-sync both directions, and a
plain-form "Work sessions" card on the task detail/edit modals.

**Week Calendar view (drag-and-drop scheduling surface) shipped 2026-08-13
(1.4 slice 3)** — see § Project pages & views above. The plain-form
"Work sessions" card stays alongside it as a fallback, not replaced.
**Still open, deferred** (doesn't block 1.5+): aggregating `task_work_hours`
up to project-card progress (`routers/projects.py`'s `_project_card` still
uses the 1.3 task-count proxy), and hiding a completed task's future
allocations from the active calendar (§ below's "future allocations are
hidden" rule — the project calendar now exists but doesn't filter for this
yet).

Work allocation replaces the previous concept of subtasks being individually
scheduled. A task does not become complex because it requires multiple work
sessions; it can have any number of work allocations — zero, one, or many.
`Research — 6h` may become `Monday 16:00–18:00`, `Thursday 14:00–16:00`,
`Tuesday 17:00–19:00` without creating multiple tasks.

A work allocation represents a planned period of work on a task. It is a
calendar Event linked to that task, not a different kind of calendar object. An
ordinary event represents something that happens; an event created through a
work allocation represents time reserved to perform work on a task. Both use the
same underlying event system.

Work is allocated by directly manipulating calendar blocks. Dragging a task into
a calendar period as many times as necessary keeps every allocation associated
with the same task; moving, resizing, splitting, or deleting an allocation
changes the task's schedule rather than creating or destroying the task.

The estimated work of a task is calculated from its actual calendar allocations
rather than manually entered as an independent estimate. Total planned work is
therefore the sum of the task's work blocks, so the user plans naturally by
placing work on the calendar and the estimate can't drift out of sync with
reality. If the user schedules more work than originally expected, the
application does not silently rewrite previous information or conceal the
discrepancy; the calendar allocations are authoritative for the currently
scheduled amount.

The application retains enough information to distinguish scheduled work from
completed work, so progress is the completed portion of the total scheduled
work; the same workload aggregates at the project level. Completing a task
before all of its future allocations have occurred does not delete those
allocations as historical data — future allocations are hidden from the active
calendar because the work no longer needs to be performed, keeping the task's
history intact without letting obsolete work blocks occupy the schedule.

### Task & calendar semantics

**Title-sync + delete-only-removes-the-block shipped 2026-08-13 (1.4 slice 1)**
— see `features/tasks.md` § Work allocations (1.4). The project's Week
Calendar view (1.4 slice 3) is the first calendar view that renders work
allocations specially (prominent vs. subdued ordinary events) and its
delete affordance uses `db.delete_work_allocation`, matching this rule. The
remaining paragraph's "future allocations are hidden from the active
calendar" rule is still not wired up yet — see the note in § Work
allocations above.

A work allocation is an Event with a task relationship, and that relationship
stays semantically meaningful when the event is edited:

- Changing the title of a work-allocation event changes the associated task
  rather than creating an independent event with a conflicting name; editing the
  task updates the representation of its associated work allocations where
  appropriate.
- Deleting a work allocation removes only that scheduled block — not the task.
  The user is removing planned working time, not the underlying work.
- Deleting an ordinary calendar event affects only that event.
- The distinction is visible in the interface, so deleting a scheduled work
  block is not confused with deleting the task.

The underlying SQL model is authoritative for these relationships. WebDAV
synchronization is an interoperability layer and must not dictate the conceptual
structure of the app's native data model.

### Task model

Tasks are independent units of work; the parent-task/subtask hierarchy is
removed (see the open conflict below). A task may belong to exactly **one**
project label and may additionally carry any number of ordinary labels — never
multiple projects at once, because multiple project ownership would make
workload, progress, deadlines, and scheduling ambiguous. **Shipped
2026-08-13**: enforced at `db.upsert_task`'s `tags` argument
(`db.MultipleProjectLabelsError` if it would give a task more than one
`is_project=1` label at once) — the task create/edit forms and the Tasks
page's bulk "Add label" action all surface this as a plain 400, not a silent
overwrite; a pre-existing task with two project labels from before this
change is left alone until something next writes new tags for it. See
`features/tasks.md` § Task model, "Single project per task." A task may exist
without a project and continue as an ordinary standalone to-do; in-project tasks
are not structurally different, since the project provides context rather than
changing the task's fundamental data model.

Tasks initially require no start date or due date; their primary information is
the work itself (title, description, status, labels, other task metadata). A
task may carry an explicit deadline when the work itself has an independently
meaningful deadline, even inside a project — a project's deadline must not
automatically become the deadline of every task belonging to it.

The distinction between a task deadline and scheduled work is explicit: a
deadline means the work must be completed by a particular time; a work
allocation means the user intends to spend a particular amount of time on it at
a particular time. These are separate concepts. **Shipped 2026-08-13**: the
two fields already existed independently (`due_at`, work allocations via
`db.task_work_hours`), but the global Tasks table (and the project detail
page's Tasks view, sharing the same `_task_row.html` macro) only ever showed
"Due" — work-allocation status was invisible on the primary task-management
surface. A "Scheduled" column (`{completed}/{scheduled}h`, or a dash when
there's no allocation yet — a different label and plain-text styling from
the editable "Due" date input, so the two can't be read as the same kind of
thing) was added to both surfaces. `db.task_work_hours_bulk` computes it for
a whole page in one query instead of one query per row.

The Tasks page provides a database/table-style management interface in which
tasks can be grouped by their project label, letting project work be viewed
together without a separate project-specific task type or hierarchy. Completed
tasks remain visible in project views, so the project retains a meaningful
record of its work. **Shipped 2026-08-13**: `GET /tasks?group_by=project`
clusters the Table view's open/completed splits under project-name headers
(`routers/tasks.py::_group_tasks_by_project`, reusing `db.project_label_for`
— the same per-task "which label is the project" lookup the project detail
page uses), a "No project" bucket sorted last after the named groups, a
"Group by" toggle added to `_tasks_toolbar.html`. Composes with every
existing filter and the active sort — grouping is applied after filtering
and sorting, so a group's tasks keep the page's sort order. Default/absent
`group_by` renders unchanged. See `features/tasks.md` § Task model, "Table
view groupable by project." The deadline-vs-work-allocation distinction
(above) shipped the same day — **this closes out 1.5 entirely.**

The global Calendar remains focused on calendar management — viewing, creating,
editing, moving, and organizing events, without project-specific allocation
controls. The global Tasks page remains focused on managing task metadata. The
Project page is the deliberate meeting point between the two systems: it
provides the context of a project, the work belonging to it, and the calendar
space in which that work can be scheduled.

### Subtask model — resolved (1.2): flat tasks + work allocations

The conflict is settled — **subtasks do not exist**. Tasks are flat and
independent units of work, scheduled individually via work allocations, and a
task belongs to at most one project. The shipped app's real subtasks
(`tasks.parent_uid`) and the earlier recorded decision ("task hierarchy &
contextual planning") that proposed keeping lightweight subtasks — the parent
representing the outcome, subtasks the concrete units of work, with the parent
aggregating estimated/scheduled/completed/remaining work from its descendants —
are both superseded.

The two sides agreed on the schedulable-unit principle (scheduled work is a
calendar event linked to a task — a work allocation), and outcome/parent
aggregation is reproduced by a project label plus its tasks. Release 1.2 removed
the subtask hierarchy outright: `parent_uid` is no longer written or read by any
app code (the column stays physically on disk for pre-1.2 data), the subtask
cascade deletes and "sub" tags are gone, iCal RELATED-TO export/import for
subtask links is removed, and the Relations card holds related events only.

## ~~Schedule & recurrence rework~~ — fully shipped 2026-08-14

**Status:** all four subsections shipped 2026-08-14 (`plans/STATE.md`'s 1.6
entries, `features/schedule.md` + `features/calendar.md`'s Recurrence
section). `pyproject.toml` bumped to `1.6.0`. Kept below as the reference
spec for what shipped.

### ~~Classes as project labels + recurring events~~ — shipped 2026-08-14

The existing Schedule system is reworked around the application's general event
and label model rather than remaining a separate conceptual entity. A university
class is fundamentally a recurring event associated with a project-enabled
label. A course such as `Historiography` is a project-enabled label covering a
semester and contains, under one project context: recurring lectures, recurring
seminars, homework and reading tasks, work allocations, examinations, guest
lectures, office hours, and other ordinary events. All of these share the
project label and appear together in the course's project views without losing
their individual semantics.

A university course does not require a special class entity. A recurring event
is conceptually a recurrence rule plus exceptions and calendar constraints; the
underlying event remains an ordinary Event. Recurring events must support the
existing university-timetable requirements — weekly recurrence, alternating
even/odd weeks, recurrence exceptions, holidays, and conflict detection.

The existing Schedule functionality is reworked as a specialized interface for
creating and managing recurring events efficiently, rather than a separate class
data model. It remains valuable for defining the recurring institutional
events, but the resulting events belong to the same calendar, label, relation,
and project systems as everything else; the project becomes the context in which
the entire course is understood.

### ~~Generalized recurrence and the non-working-day policy~~ — shipped 2026-08-14

The recurrence system is generalized so that any recurring event can specify how
it behaves on non-working days. The system does not encode university-specific
holiday behavior into the event model; recurrence rules support a configurable
non-working-day policy that determines whether occurrences on excluded dates are
skipped.

Holiday calendars are named collections of manually entered dates, maintained by
the user for each year rather than retrieved from an automatic external service.
This keeps scheduling deterministic and lets one system support different legal,
institutional, and personal calendars — e.g. `Romania`, `University`, `Personal`.
Named calendars are reusable sources of date constraints: a recurring event
references a named calendar rather than containing a hard-coded list of dates,
and the engine never assumes every event respects the same calendar — the choice
belongs to the individual event. A university course can use the `University`
calendar, a work-related event the `Romania` calendar, and a personal event no
holiday calendar at all.

A holiday calendar does not define weekend behavior; weekends are an independent
recurrence constraint. A recurring event may therefore ignore holidays and
weekends, respect a named holiday calendar, exclude Saturday, exclude Sunday,
exclude both weekend days, or combine a holiday calendar with either or both
weekend exclusions. A public holiday and a weekend are deliberately different
kinds of constraints even though both may cause an occurrence to be skipped.

The recurrence editor should therefore expose controls conceptually similar to:

```
Holiday policy: None / Configured holidays / Custom
Exclude Saturday: On/Off
Exclude Sunday: On/Off
```

The exact interface can be simplified where appropriate, but the underlying data
should retain these as independent constraints.

### ~~Manual recurrence exceptions~~ — shipped 2026-08-14

Recurring events must support manual exceptions and overrides. A specific
occurrence can be cancelled, moved, or otherwise modified without destroying the
underlying recurrence rule — for example, a weekly Monday class can have one
occurrence moved to Tuesday or cancelled entirely. This is especially important
for university schedules, where individual classes are routinely cancelled,
moved, or replaced. The recurrence system therefore distinguishes three things:
the recurrence rule, the generated occurrences, and the manual exceptions or
overrides.

(This is the model that resolves the "recurring-event single-occurrence
editing" risk — implemented as `event_occurrence_overrides`, see
`features/calendar.md`'s Recurrence section.)

### ~~Configurable terminology~~ — shipped 2026-08-14

The recurring-event editor provides a configurable terminology mode in Settings.
The underlying data model uses neutral semantic names — `holiday_calendar`,
`exclude_holidays`, `exclude_saturday`, `exclude_sunday`. The standard UI
exposes them conventionally (`Exclude configured holidays`, `Exclude Saturday`,
`Exclude Sunday`); an optional playful mode uses intentionally irreverent labels
(`Respects Labor Laws`, `Marx Weekend`). These are presentation-layer choices
only: the database, APIs, synchronization logic, and internal documentation keep
neutral terminology, so changing the interface language never alters the
underlying semantics.

### Why this rework matters

The rework makes the existing university timetable significantly less isolated
from the rest of the application. The timetable is no longer a separate source
of "class objects" that happen to produce calendar events; it is a convenient
interface for defining recurring events within project contexts. Once those
events exist, they participate in the same calendar, label, relation, and
project systems as every other event. The specialized Schedule interface
remains because manually creating dozens of recurring class events would be
absurd, but the resulting data follows the application's general event model.

## ~~Information architecture & view surfaces~~ — fully shipped 2026-08-14

The application deliberately distributes information across views according to
the question each view answers, rather than letting the Dashboard become a
container for every feature. Major surfaces have distinct purposes — Dashboard
for orientation, Today for execution, Week for planning, Spaces for context, and
Calendar/Tasks/Contacts for direct management. Views are projections of shared
entity data, not independent representations with duplicated state.

**Status:** all four "new surface" pieces accounted for as of 2026-08-14
(`plans/STATE.md`'s 1.7 entries). Today and Week were built fresh this release
(slices 1–2); Dashboard (the existing widget-grid Home,
`routers/dashboard.py`) and Spaces (the existing generated label pages,
`routers/labels.py` + `deps.py::sidebar_spaces`) turned out to already satisfy
this section's spec from earlier phases — confirmed against the spec below
rather than rebuilt, per this section's own closing slice. `pyproject.toml`
bumped to `1.7.0`. Kept below as the reference spec for what shipped.

### Dashboard — orientation

**Confirmed 2026-08-14** — pre-existing, not rebuilt for 1.7: `routers/
dashboard.py`'s widget-grid Home already answers this brief (widgets
prioritizing current/upcoming info, important/urgent items, workload, over
exposing every feature). Reused as-is, per this section's own "Dashboard
itself already exists... doesn't require a rebuild unless a future session
finds a real gap" note.

Answers **"What's happening in my life?"** A concise overview of the current
situation aggregated from existing entities and system states — not a second
management interface. Widgets prioritize current and upcoming information,
important/urgent items, and high-level workload over exposing every feature at
once.

### ~~Today — execution~~ — shipped 2026-08-14

**Shipped 2026-08-14 (1.7 slice 1)** — see `features/today.md`: `GET /today`
(`routers/today.py::today_view`), a `/today` tabbar entry right after Home.
An at-a-glance stats strip, a Due & overdue list, a Today's schedule list
(today's ordinary calendar events split from today's scheduled task work —
work-allocation events, via the same `db.work_allocation_task_uid` lookup
`routers/projects.py::project_calendar` uses), and an Important & urgent
list (open tasks whose `derived_state.virtual_states` includes `important`
or `urgent`, excluding whatever's already shown in Due & overdue). No
separate Today data model — everything reads straight off
`db.list_events`/`list_tasks` plus the shared aggregation service (1.1)
each request.

Answers **"What am I dealing with now?"** An operational view of the current
day combining today's calendar events, scheduled task work, due/overdue tasks,
important upcoming items, and relevant workload. Generated from existing data —
no separate Today data model.

### ~~Week — planning~~ — shipped 2026-08-14

**Shipped 2026-08-14 (1.7 slice 2)** — see `features/week.md`: `GET /week`
(`routers/week.py::week_view`), a `/week` tabbar entry. Reuses the same
week-grid geometry (`grid_layout.layout_day`) `routers/calendar.py::
week_view` and `routers/projects.py::project_calendar` already render —
this is a third *purpose* over that geometry (global planning, vs. event
management and one project's own scheduling, respectively), not a third
implementation of it. Unscheduled work (every open task with no allocation
yet, across every project or none, sorted by due date) is listed beside the
grid and drags onto it (`POST /week/allocations`) to create a work
allocation; existing blocks drag to move/resize
(`POST /week/allocations/{event_uid}/move`) or delete
(`POST /week/allocations/{event_uid}/delete`, block only, never the task) —
the same three-endpoint shape `routers/projects.py`'s own trio uses, minus
the "must belong to this project" scoping, and the same client-side drag/
resize script (`static/project_calendar.js`) reused verbatim. Every work
allocation renders prominently regardless of task/project (unlike the
project-scoped calendar, which only prominents one project's own); ordinary
events render as subdued context; due-today tasks show as chips on their
day. **Not implemented**: a computed "available time" number — same
"open grid space visually communicates availability" interpretation
`project_calendar` already established for this identical spec language.

Answers **"How should I allocate my time over the coming week?"** Shows calendar
commitments together with schedulable task/subtask work, due dates, remaining
estimated effort, and available time. Unscheduled work is visible and draggable
onto available calendar intervals. A planning surface, not merely another
calendar layout.

### ~~Spaces — context~~ — confirmed shipped 2026-08-14 (built earlier)

**Confirmed 2026-08-14, closing 1.7** — this surface was already fully built
before 1.7 started (the `generate_space` label flag and its generated page
landed 2026-08-08), so this slice was verification against the spec below,
not new code: `routers/labels.py::label_detail` + `_label_scope` (a
`generate_space=1` label's page — direct `object_labels` membership only,
never transitive through `parent_name`), the nav rail's own Spaces list
(`deps.py::_sidebar_spaces`, `db.list_space_labels`, every Space shown
automatically), the shared widget grid scoped to the label (folding in child
labels' names too, `routers/dashboard.py`'s `widget_page_context`), and the
University module (`_project_university_section.html` — course info with
schedule/room/credits, professor mailto links via `professor_contacts`,
"Next lecture" badges, and a Homework table off tasks tagged `Homework`) that
renders whenever a Space's classes/homework actually exist, no separate
`enabled_modules` gate. See `features/labels.md` § Generated page, tested by
`tests/test_phase2_labels.py`.

Answers **"What belongs to this area of my life?"** Spaces remain contextual
projections generated from labels and extended by specialized modules — not a
manually maintained folder hierarchy. A University Space exposes generic
calendar/task/contact functionality while the University module adds courses,
schedule, professors, credits, and assignments.

### Core management views

Calendar, Tasks, and Contacts stay the direct management interfaces for their
entity types: Calendar manages temporal occurrences, Tasks manages desired
outcomes and their state, Contacts manages people. Other surfaces provide
contextual projections of these entities rather than duplicating their
management logic.

## Offline-first editing & synchronization

**Status:** sync model designed 2026-08-14 (this section) — no implementation
code yet. Its precondition — verified backups (Data health & maintenance,
`open.md`) — **shipped 2026-08-14**. Implementation is scoped into the numbered
slices at the end of this section; per `plans/STATE.md`, the design below was
written and reviewed as its own slice, separate from and before any of them.

The application supports creating, editing, scheduling, and completing entries
while offline; connectivity is not a prerequisite for normal operation. Local
changes are persisted reliably and queued for synchronization. When connectivity
returns, the sync system detects the connection, begins synchronization
automatically, processes pending changes, and communicates the result to the
user.

Synchronization operates in the background. The UI provides clear **non-blocking
status notifications** for entering offline mode, reconnecting, synchronization
in progress, successful synchronization, and synchronization failure — successful
background sync stays unobtrusive, while errors are visible.

The model introduces potential conflicts between tasks, work allocations,
events, labels, and project state, so conflict semantics must be defined
explicitly. In particular, simultaneous changes to work allocations on different
devices must never result in silent data loss. The application retains enough
local state to determine what changed and to reconcile when connectivity
returns.

Source material: this app's own earlier offline/PWA brainstorm
(`plans/ofline-first-pwa.md`, still a rough draft — install-to-offline-shell,
local-data-as-primary, per-change sync records, transparent online/offline
transitions, a small status indicator); the HLC per-field merge decision
preserved in `abandoned.md`'s "Decision history" section (ported forward from
the pre-rework `desktop/` client, never implemented in the current webapp).

### 0. The architectural fork this creates

Everything else in this app is server-rendered Jinja: a request hits a router,
which reads/writes SQLite directly and returns HTML. There is no client-side
data layer today, no JSON API beyond the export/import routes, and no build
step. "Offline-first" cannot be bolted onto that shape — a page that doesn't
exist locally can't render when the network is down. This is the one part of
1.8 that is a real architectural addition, not a rework of what's there:

- A **PWA shell** (manifest, service worker, an app-shell cache) becomes the
  offline entry point. It coexists with the existing server-rendered pages —
  visiting the app online still hits the normal routers; the PWA shell is what
  loads when the network is unavailable or when the installed app is opened
  offline.
- A **local data layer** (IndexedDB) becomes the primary store for the PWA
  shell's own views once installed — "network availability should not be
  checked before ordinary operations" (`ofline-first-pwa.md`). This is a
  second read/write path alongside the server-rendered one, not a replacement
  of it; the plain browser-tab experience (no install, no service worker)
  keeps working exactly as it does today, fully online-only, no change.
- A **thin JSON sync API** (§8 below) is the only new HTTP surface — it does
  not replace or wrap the existing page routers, and the existing routers do
  not gain sync awareness. The sync API's job is narrow: accept a batch of
  field-level operations, apply them with conflict detection, and hand back
  everything newer than what the caller already has.

This means 1.8 is genuinely two builds — the sync engine (server + protocol,
entirely testable with the existing pytest/router-function-call convention, no
browser needed) and the PWA client (service worker, IndexedDB, the offline UI)
— wired together at the end. The slice breakdown at the bottom of this section
keeps them separable for exactly that reason.

### 1. Entity identifiers

Tasks, events, and contacts already carry a stable `uid` (the iCal/vCard
round-trip identifier every export/import path already depends on) — that
`uid` is the sync identifier too, no new column. A device creates a new
entity offline by generating its own `uid` (`str(uuid.uuid4())`, same call
already used everywhere in this codebase) at creation time; a v4 UUID's
collision probability needs no central allocation to stay safe, and this is a
single-user app (`abandoned.md`: "single-user is load-bearing" — no
multi-tenant namespacing question to solve). Two devices independently
creating a task offline always land as two distinct rows once synced, never a
collision.

Work allocations are plain `events` rows (`is_work_allocation=1` on the
`event_task_relations` join) — no separate identifier scheme. Recurrence
overrides are real second `events` rows sharing the master's `uid` with a
`RECURRENCE-ID` (1.6's manual-exceptions design) — sync treats an override
exactly like any other event row; nothing here is new because of recurrence.

Labels are the one pool object with **no uid** — `label_config.label_name` is
already the natural key (globally unique text, per
`features/architecture.md` §1.2), and a label has no delete/rename lifecycle
today ("a label empties itself naturally," no `routers/labels.py` delete
route). Sync therefore never needs to reconcile two different labels claiming
the same name, or a rename race — those operations don't exist in the app to
begin with. `object_labels` rows (the join table) have no uid either; they're
identified by the natural key `(object_type, object_id, label_name)`, and
add/remove are naturally idempotent (`INSERT OR IGNORE` / delete-if-exists) —
see §7 for why this makes label attach/detach commutative rather than
something HLC has to arbitrate.

### 2. Local change tracking — an operation log, not a state diff

Every offline write becomes an **operation record**, appended to a local
outbox (IndexedDB on the client), never a raw "here's my new row" state dump.
Recording *what changed* rather than *what the row now looks like* is what
makes field-level conflict resolution (§7) possible at all — a whole-row
overwrite can't tell the server "only the due date changed, don't touch
anything else this device never touched."

An operation:

```
{ op_id:        <uuid, client-generated>       -- idempotency key, see §5
  entity_type:  "task" | "event" | "contact" | "object_label"
  entity_uid:   <uid>                          -- or the object_labels natural key
  op_type:      "create" | "field_set" | "delete" | "label_add" | "label_remove"
  fields:       { field_name: { value, hlc } } -- field_set/create only
  device_id:    <uuid, generated once per install, stored locally>
  hlc:          <the op's own HLC, see §3>     -- for delete/label_add/label_remove
}
```

`create` is a `field_set` covering every field at once (the whole row as
authored), stamped with one HLC — a plain-form create with no prior state to
conflict against. The outbox is append-only: an op, once written, is never
mutated, only marked "acknowledged" once the server confirms it (or dropped
after a bounded retention once acknowledged, to keep the local store small).

### 3. Ordering — a Hybrid Logical Clock (HLC)

Per-field writes need a total order that survives clock skew between devices
and doesn't require them to be online at the same time to agree on "who's
newer" — plain wall-clock timestamps aren't safe for that (a device with a
clock 10 minutes fast can silently "win" every conflict). An HLC is a triple:

```
(physical_time_ms, logical_counter, device_id)
```

`physical_time_ms` is the device's own clock at the moment of the write.
`logical_counter` increments within the same millisecond (or when a received
HLC's physical time is >= the local clock, per the standard HLC update rule)
so ordering stays correct even when clocks are close or momentarily behind.
`device_id` is the final, deterministic tiebreaker when the first two are
genuinely equal — never "last one processed by the server wins," which
depends on network arrival order, not causal order. Two HLCs compare
lexicographically on that triple; this is a total order, so "which of these
two field writes is newer" always has one unambiguous answer.

Both the client (per device) and the server maintain their own HLC clock,
merged (`max` + increment) on every operation they observe from the other
side — the standard HLC synchronization rule, so a device's clock advances
past whatever it's seen from the server and vice versa.

### 4. Deletion / tombstones

Deleting an entity offline is a `delete` operation, not a row removal —
existing rows (`tasks`/`events`/`contacts`) already have no `deleted`/
tombstone concept; this design adds one (`deleted_at` + the deleting op's HLC)
rather than physically deleting on the first device that gets the change, so
a *concurrent* edit from a second, still-offline device has something to
reconcile against once it syncs (see §7 for the resolution rule — an edit
newer than the tombstone un-deletes the row, rather than the edit being
silently lost against a row that no longer exists to receive it).

**Tombstone retention / GC:** a tombstone must stay visible to every device
long enough for all of them to have observed it before it's purged for real,
or a device that reconnects after a long time offline could "resurrect" a
row everyone else already knows is gone. A configurable retention horizon
(default 90 days, alongside the existing auto-archive-style `app_meta`
presets) governs physical purge; a device whose last successful sync is
older than the horizon cannot safely apply an incremental pull and instead
triggers a full resync (§8) rather than risking a stale tombstone gap.

### 5. Retries and idempotency

Every operation's `op_id` is the idempotency key. The server keeps a bounded
window of recently-applied `op_id`s (per entity is enough — an op only ever
touches one entity) and, on receiving a duplicate, returns the cached result
of the first application rather than re-applying it — this is what makes a
naive "resend the whole pending batch" retry safe after a connection drop
mid-push (client can never be sure whether the server actually received and
applied the last batch before the connection died).

Retry policy: exponential backoff with jitter (a fixed cap, e.g. 30s) while a
push/pull attempt is failing; an immediate attempt on the browser's `online`
event (transparent reconnect, no user action, per `ofline-first-pwa.md`);
periodic background retry while nominally online but a sync attempt is
failing (e.g. the server itself is briefly down). Pending-changes count and
sync state persist in IndexedDB, so a closed-and-reopened PWA resumes exactly
where it left off, per `ofline-first-pwa.md`'s own requirement.

Ops sync in per-entity chronological order (their own HLC order) even though
cross-entity order never matters — this preserves intra-entity causality
(e.g. a task's `create` always arrives and applies before a later `field_set`
against the same `uid`).

### 6. Conflict detection

The server needs to know, per field, "is this incoming write newer than what
I already have" — which means the server must track an **HLC per field**,
not just the row's existing single `updated_at` timestamp. This is new
server-side state (§9) `tasks`/`events`/`contacts` don't carry today.

On receiving a `field_set`/`create` op: for each field in the op, compare its
HLC to the field's currently-stored HLC (absent = treat as smaller than
anything). Newer wins and is applied, with the stored HLC advanced; older is
a silent no-op **for that one field only** — the incoming value is discarded
because a genuinely newer value for that exact field already exists, which
is correct, not lossy (the "loser" write's intent for every *other* field it
touched is unaffected, since detection is per field, not per row).

This silent-no-op-per-field behavior is the normal, expected outcome for
ordinary fields (title, description, due date, importance...) and needs no
user-facing surfacing — it's what "conflict-safe sync" means for the common
case. §7 defines the fields where a plain newer-wins isn't suffient and a
conflict must be surfaced instead of auto-resolved.

### 7. Conflict resolution

**Default rule: per-field last-write-wins by HLC**, exactly as detected in
§6, for every field on every entity, with two deliberate categories of
exception:

**a) Structural/relational operations are commutative by construction, so
they never need HLC arbitration at all:**

- Two devices each **create** a new work allocation (a new event `uid`) for
  the same task while offline, at different times — these are two different
  entities. Both sync in as separate rows; there is no conflict because
  nothing shares an identifier. This is the common "I planned two separate
  work sessions from two devices" case, and by construction it always just
  works.
- `object_labels` add/remove (`label_add`/`label_remove`) on the same
  `(object_type, object_id, label_name)` tuple from two devices are
  idempotent — applying "add" twice or "remove" twice converges to the same
  state regardless of arrival order. No HLC needed; last-applied-wins is
  fine because the two possible operations commute.

**b) Fields representing a committed scheduling decision are conflict-surfaced,
not auto-merged — the one deliberate exception to per-field LWW:**

Two devices independently **moving or resizing the same existing** work
allocation or event (editing its `start_at`/`end_at`) while both offline is
the case the spec's "must never result in silent data loss" line is about.
Plain per-field LWW would pick one device's new time and silently discard
the other's — but these aren't "the same fact measured twice converging on
one true value" the way a title edit is; they're two different, deliberate
scheduling decisions, and discarding one is a real loss of the user's intent
on that device, not noise. For `start_at`/`end_at` on `events` specifically:
if both sides changed the same field while neither had synced the other's
change yet (detected via: the losing write's HLC is *not* an ancestor the
winning device could have already observed — i.e. this is a genuine
concurrent edit, not a normal newer-supersedes-older sequential edit), the
server does not auto-apply either value. Instead it applies the higher-HLC
value as usual (so no device is ever blocked by an unresolved conflict) *and*
records the losing value as an unresolved **sync conflict** (§9) surfaced in
a "Sync conflicts" list (adjacent to Settings > Data health, §9) for the
person to look at and, if the auto-picked side was wrong, manually restore
the other time. Nothing is silently dropped — the losing value is retained
until the person resolves or dismisses it.

**c) App-level invariants must be re-checked after a sync batch, not just
after each individual op:** two devices each attach a *different* project
label to the same task while both offline violates
`db.MultipleProjectLabelsError`'s single-project-per-task rule (1.5) — each
individual `label_add` is a valid, commutative op per (a) above, but the
*combination* is invalid. The server re-validates this specific invariant
after applying a synced batch, exactly the same check `upsert_task`/the bulk
label-add endpoint already perform on an ordinary write (1.5's existing
`MultipleProjectLabelsError`, not new logic): the higher-HLC label_add is
kept, the other is rejected and recorded as a sync conflict the same way as
(b), rather than either silently violating the invariant or silently
dropping the losing device's intent without telling anyone.

No other cross-field/cross-entity invariant in the current data model
(`features/architecture.md`'s "the data model principle") has this
same-batch-violates-an-invariant shape — project-label exclusivity and
work-allocation/event time fields are the two known cases; a future feature
that adds a new invariant should ask this same question (per (b)/(c) above)
before assuming plain per-field LWW is enough.

### 8. Sync protocol shape

Two phases per sync round, always in this order (push before pull, so a
device's own changes are already applied server-side and can't be
immediately re-conflicted against by its own pull):

- **Push:** the client sends every unacknowledged op in its local outbox,
  oldest-HLC-first per entity. The server applies each per §§6–7, records
  applied `op_id`s (§5), and returns, per op, either "applied" or "applied
  with conflict" (§7b/c) plus the conflict record's id.
- **Pull:** the client sends the HLC of the newest change it has already
  observed from the server (its sync cursor, persisted in IndexedDB). The
  server returns every field-level change with a stored HLC newer than that
  cursor — an incremental delta, never a full-table dump — which the client
  applies to its local IndexedDB store the same way §6 applies changes
  server-side (the client's local copy is just another HLC-tracked replica).
  If the client's cursor predates the tombstone GC horizon (§4), the server
  instead responds "cursor too old" and the client performs a full resync
  (fetch-everything-fresh, same shape as the existing `/export/data.json` /
  `restore_backup_payload` round-trip, then reset its cursor to "now").

The UI's status indicator (`ofline-first-pwa.md`: offline / synchronizing /
pending changes / synchronized) is driven directly off outbox size (pending
changes > 0), in-flight push/pull state, and the browser's own
online/offline events — no new signal needed beyond what the outbox and the
last push/pull result already carry.

### 9. New server-side state this requires

Purely sync-infrastructure metadata, not new domain object types — per
`features/architecture.md` §1.4's local-only-module rule, this is config/
bookkeeping the pool itself can't derive, the same category `task_checklist_
items`/`task_completions` already fall into, not a fourth kind of entity:

- **`field_versions(entity_type, entity_uid, field_name, hlc_physical,
  hlc_logical, hlc_device_id)`** — the per-field HLC shadow store §6 needs;
  `tasks`/`events`/`contacts` themselves gain no new columns, this is a
  side table keyed off the existing `uid`.
- **`sync_devices(device_id, last_pushed_hlc, last_pulled_hlc, last_seen_at)`**
  — one row per device that has ever synced; the pull cursor (§8) and the
  eventual "last sync time for connected endpoints/devices" line Data
  Health's own page already reserves a placeholder for (`src/data_health.py`'s
  `health_summary` `sync` key, shipped 2026-08-14 as
  `{"configured": false, ...}` — this is what flips it to configured).
- **`sync_conflicts(id, entity_type, entity_uid, field_name, losing_value,
  losing_hlc, winning_hlc, created_at, resolved_at)`** — §7b/c's surfaced
  conflicts; a "Sync conflicts" list reads this table, lets the person
  restore the losing value (a normal new `field_set` op with a fresh HLC,
  not special-cased) or dismiss it (`resolved_at` set, value discarded for
  good).
- The applied-`op_id` ledger (§5) can live as a column/index on
  `field_versions`/a small dedicated table — an implementation detail for
  the slice that builds it, not a modeling decision this doc needs to fix.

### 10. Explicitly out of scope

- **Real-time collaborative editing (CRDTs).** Not needed without multi-user
  — HLC/LWW is sufficient for one person across N devices
  (`abandoned.md`'s existing "deferred systems" table already rules this
  out for the same reason).
- **Multi-user / sharing.** Single-user remains load-bearing; this design
  assumes every device syncing belongs to the same person.
- **Server-authoritative conflict resolution UI beyond a plain list.** §9's
  Sync conflicts list is deliberately minimal (see the losing value, restore
  or dismiss) — no diff view, no three-way merge editor.

### 11. Acceptance line and implementation slices

**Acceptance:** a task/event/contact created, edited, or deleted on Device A
while offline is visible in the same state on Device B after both have been
online at the same time, with no field silently lost — either it applied
cleanly (the common case) or it's sitting in Sync conflicts (the two flagged
exception cases). Restoring from an old client cursor never resurrects a
tombstoned row past the GC horizon; it forces a full resync instead.

Kept as separable slices — the server-side sync engine has no browser
dependency and is fully testable with this app's existing router-function-
call pytest convention; the PWA client is a second, independent build on top
of it:

1. **Field-HLC shadow store + sync API skeleton** — **shipped 2026-08-14.**
   `field_versions`, `sync_devices`, `sync_applied_ops` (the §5 idempotency
   ledger), the push/pull endpoints (§8, `routers/sync_api.py`'s `POST
   /api/sync/push`/`/api/sync/pull`) and their conflict-detection logic (§6,
   `src/offline_sync.py`), tested entirely server-side (no client, no
   browser) by POSTing synthetic op batches and asserting the resulting
   field values/HLCs. `tasks`/`events`/`contacts` gained a `deleted_at`
   column (§4's tombstone) — the one deliberate departure from §9's "no new
   columns" framing, needed so a delete has somewhere to actually live;
   `field_versions` itself still stores no value, only each field's HLC,
   exactly as §9 describes. §7a (label add/remove commutativity) and §4 (an
   edit newer than the tombstone un-deletes) both fell out of the same
   per-field apply path with no special-casing. Deliberately NOT in this
   slice, per its own scope: the `sync_conflicts` table and §7b/c's two
   conflict-*surfacing* exceptions (event time concurrent-edit detection,
   single-project-per-task re-validation) — ordinary §6 LWW applies to every
   field for now, including `start_at`/`end_at`; slice 2 wires those two
   exceptions into this slice's apply path. No PWA/browser client calls this
   API yet. 19 new tests (`test_offline_sync.py`), full suite 1250 passed.
2. **Sync conflicts surface** — **shipped 2026-08-14.** `sync_conflicts`
   table + `/settings/sync-conflicts` (routers/settings.py, a new hub
   category adjacent to Data health), listing every unresolved conflict
   with Restore (re-applies the losing value as a fresh `field_set`/
   `label_add` op through the normal `apply_op` path, given a synthetic
   `"settings-restore"` device id and a `now` HLC so it always outranks
   every real device's prior write) and Dismiss (`resolved_at` set, value
   discarded for good) actions. Wired both §7b/c exceptions into slice 1's
   `src/offline_sync.py` apply path: (b) `_apply_field_write` detects a
   genuinely concurrent `start_at`/`end_at` edit on an `event` via a
   deliberate simplification instead of full causal/version-vector
   tracking (out of scope, §10) — per §3's HLC merge rule, a losing write
   can only come from a *different* device_id than the current winner if
   neither had observed the other's write yet, so "different device_id on
   both sides of a losing write" is concurrency's own observable
   signature; a losing write from the *same* device as the winner is an
   ordinary reordered/replayed op, not a conflict, and stays a plain §6
   stale no-op. (c) `apply_batch` re-validates single-project-per-task
   after every op in a batch has applied (not per-op, since each
   individual `label_add` is independently valid per §7a) — the highest-
   HLC `label_add` for a task wins, any pre-existing project label from
   before the batch outranks every in-batch addition outright (no in-batch
   HLC to lose against), and every losing add is reverted from
   `object_labels` and recorded as a conflict, with that op's own result
   status patched to `"rejected_invariant"`. 11 new tests extending
   `test_offline_sync.py`, plus a hub-categories fixture update in
   `test_phase8_settings_hub.py`, full suite 1261 passed.
3. **PWA shell** — **shipped 2026-08-14.** `static/manifest.webmanifest`
   (name/icons/`display: "standalone"`/`start_url: "/"`) linked from
   `base.html`; `static/sw.js`, served at the root path by new
   `routers/pwa.py` (`GET /sw.js`, not `/static/sw.js` — a service
   worker's default scope is the directory of the URL it's fetched from,
   so serving it under `/static/` would cap its scope at `/static/*`
   instead of the whole app) and registered by `static/pwa.js` (loaded
   globally in `base.html`, last, as a progressive enhancement). `sw.js`
   precaches the app shell — every static asset `base.html` loads on
   every page, plus a new `GET /offline` fallback page
   (`templates/offline.html`, extends `base.html` so the tabbar/nav
   chrome renders identically offline, ordinary content is just an honest
   "you're offline" message since there's no local data layer yet) — and
   serves it for any navigation request that fails with the network down,
   satisfying `ofline-first-pwa.md`'s "opening the application offline
   should lead directly to the normal interface rather than an error
   page" line, for the app-shell-only scope this slice covers. Static
   assets get a cache-first strategy (safe because every asset URL is
   already cache-busted by `deps.py`'s `static_url()` — a changed file is
   requested under a new URL, never silently serves stale content under
   an old one); real page navigations stay network-first, since this
   app's pages are server-rendered from live SQLite state and must never
   serve a stale cached copy when the network is actually reachable. No
   sync, no IndexedDB, no local read/write path — deliberately deferred
   to slices 4-5. The first genuinely browser-dependent piece of 1.8:
   service worker install/fetch behavior can't be exercised by this app's
   router-function-call pytest convention, so `test_pwa_shell.py`'s 10
   tests cover everything that *is* server-verifiable (manifest validity,
   every icon it references existing on disk, `/sw.js`'s content-
   type/no-store header, the precache list only naming assets that exist,
   `/offline` rendering full chrome, and `routers/pwa.py` actually being
   wired into `main.py`) — actual install/offline-navigation behavior
   needs manual browser verification, not done as part of this slice.
   Full suite 1271 passed.
4. **Local IndexedDB store + read path** — **shipped 2026-08-14.**
   `static/offline_db.js`: an IndexedDB database (`cc-offline`) mirroring
   `tasks`/`events`/`contacts` (one row per entity, written incrementally
   field-by-field — never a whole-row replace) plus a `field_hlc` store
   that replays the exact same §6 per-field-HLC-wins rule the server
   applies to `field_versions`, so a pull can never regress a field even
   if changes ever arrived out of order (today they don't —
   `offline_sync.pull()` already returns them HLC-ascending — but slice
   5's own local writes will need this comparison to already be correct),
   and a `meta` store for `device_id` (generated once via
   `crypto.randomUUID()`, §1's client-generation rule) and the pull
   cursor. `static/offline_sync_client.js` is §8's pull half, client-side:
   `POST /api/sync/pull` with the stored cursor, apply the returned
   changes into the mirror, advance the cursor, on the page's `load`
   event and the browser's `online` event. Deliberately push-free (no
   local writes exist yet to push) and retry-free (§5's backoff is slice
   6) — a single best-effort attempt per trigger, silent no-op on
   failure. A `full_resync` response is handled as "clear the cursor and
   pull again once," which today is exactly correct because nothing has
   ever been physically purged (§4's GC is slice 7) — a `None` cursor
   pull already returns everything. Loaded globally in `base.html` (not
   just on `/offline`) so the mirror is already warm from ordinary online
   browsing by the time the network actually drops. `templates/
   offline.html` gained `#offline-local-data`, rendered by new
   `static/offline_shell.js` straight from the mirror (`getAllTasks`/
   `getAllEvents`, filtering out soft-deleted rows) with zero network
   calls of its own — open tasks by due date and upcoming events by start
   time, reusing `search.html`'s own plain `.checklist`/`.checklist-row`
   list styling rather than inventing a second one. Deliberately partial:
   labels/tags aren't mirrored (`object_label` ops are commutative, §7a,
   and never flow through the field-HLC pull this slice mirrors), so the
   local list shows title/due/time only, no project pill — an honest
   scope line, not a bug. The static "nothing synced yet" empty-state
   markup stays as the fallback for a device that has never completed a
   pull. `sw.js`'s own precache list (bumped to `cc-shell-v2`) grew the
   three new scripts, so they're available to `/offline` even fully
   offline. Verified two ways: `test_pwa_shell.py`'s structural checks
   (same "read the JS source, assert the shape" level as slice 3's own
   sw.js tests — 6 new tests, full suite 1277 passed), plus a one-off
   Node + `fake-indexeddb` smoke run (not part of the pytest suite, no
   new runtime dependency added to it) exercising `offline_db.js`'s real
   merge logic end-to-end: newer-HLC writes apply, older-HLC writes are
   rejected, a `deleted_at` write removes the row from `getAllTasks`, and
   `device_id`/cursor round-trip through IndexedDB correctly. Still no
   local writes anywhere (slice 5) — this slice is read-only, same
   boundary as `ofline-first-pwa.md`'s "viewing... should be executed
   locally" without yet covering "creating and editing."
5. **Local write path + outbox** — offline create/edit/delete queues as ops
   (§2) instead of failing; still no sync engine, so pending changes just
   accumulate.
6. **Sync engine** — the push/pull loop (§8), retry/backoff (§5), the status
   indicator, wiring slices 1–5 together end to end.
7. **Tombstone GC** — the retention horizon (§4) and the forced-full-resync
   path for a stale cursor.

## The data model principle

The resulting architecture preserves a small number of strong primitives rather
than creating specialized entities for every workflow:

- **Label** — organizes entities and may enable additional behavior.
- **Project-enabled Label** — a bounded context: start date, end date, project
  lifecycle, workload aggregation, and dedicated views.
- **Task** — work that needs to be completed.
- **Work Allocation** — connects a task to a specific amount of calendar time.
- **Event** — something occurring at a particular time, including work
  allocations.
- **Recurrence Rule** — causes events to occur repeatedly.
- **Holiday Calendar** — configurable date constraints for recurring events.
- **Exceptions** — modify individual occurrences without destroying their
  recurrence rules.

This keeps the semantic model independent from WebDAV while allowing the app to
expose and synchronize appropriate data through CalDAV/CardDAV. Specialized
interfaces such as the university Schedule editor remain useful because they
simplify complex workflows, but they operate on the same underlying entities as
everything else.

**Labels provide context. Project behavior gives a label a bounded outcome and
lifecycle. Tasks represent work. Work allocations place that work into time.
Events represent things that happen. Recurrence determines when repeated events
occur, while named calendars and exceptions determine which occurrences are
valid.**

## Known open risks

- **`project_label_for` heuristic** (`db.py`): a schedule class/habit picks
  "the project" as whichever attached label isn't a Space, chosen alphabetically
  when more than one non-Space label qualifies. Low risk at current usage; flag
  a decision if it ever needs to be relied on at higher stakes. Interacts
  directly with the project-stack rework.
- **Recurring-event exceptions**: the exception model is now specified (see
  "Manual recurrence exceptions") but not implemented — the master-RRULE plus
  occurrence-override engine still needs building and testing.

---

## How open work gets tracked

A focused plan starts its life as a section here. When you give it a go-ahead,
expand it into a full phase spec (acceptance line, concrete slices); when it
ships, describe the outcome in [`features/`](../features/README.md) and remove
the section from this file.
