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

## Schedule & recurrence rework

**Status:** "Classes as project labels + recurring events" and "Generalized
recurrence and the non-working-day policy" both shipped 2026-08-14
(`plans/STATE.md`'s 1.6 entries, `features/schedule.md` + `features/
calendar.md`'s Recurrence section). The other two subsections below (manual
recurrence exceptions, configurable terminology) are still full planning
model, no code.

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

### Manual recurrence exceptions

Recurring events must support manual exceptions and overrides. A specific
occurrence can be cancelled, moved, or otherwise modified without destroying the
underlying recurrence rule — for example, a weekly Monday class can have one
occurrence moved to Tuesday or cancelled entirely. This is especially important
for university schedules, where individual classes are routinely cancelled,
moved, or replaced. The recurrence system therefore distinguishes three things:
the recurrence rule, the generated occurrences, and the manual exceptions or
overrides.

(This is the model that resolves the "recurring-event single-occurrence
editing" risk — now specified, not yet implemented.)

### Configurable terminology

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

## Information architecture & view surfaces

The application deliberately distributes information across views according to
the question each view answers, rather than letting the Dashboard become a
container for every feature. Major surfaces have distinct purposes — Dashboard
for orientation, Today for execution, Week for planning, Spaces for context, and
Calendar/Tasks/Contacts for direct management. Views are projections of shared
entity data, not independent representations with duplicated state.

**Status:** decisions recorded — no code. Step 5 of the build order; consumes
the aggregation service and work allocations.

### Dashboard — orientation

Answers **"What's happening in my life?"** A concise overview of the current
situation aggregated from existing entities and system states — not a second
management interface. Widgets prioritize current and upcoming information,
important/urgent items, and high-level workload over exposing every feature at
once.

### Today — execution

Answers **"What am I dealing with now?"** An operational view of the current
day combining today's calendar events, scheduled task work, due/overdue tasks,
important upcoming items, and relevant workload. Generated from existing data —
no separate Today data model.

### Week — planning

Answers **"How should I allocate my time over the coming week?"** Shows calendar
commitments together with schedulable task/subtask work, due dates, remaining
estimated effort, and available time. Unscheduled work is visible and draggable
onto available calendar intervals. A planning surface, not merely another
calendar layout.

### Spaces — context

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

**Status:** decision recorded — no code. The sync model must be written before
implementation (see below).

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

**Before implementation, the synchronization model must explicitly define:**
entity identifiers, local change tracking, ordering, deletion/tombstones,
retries, idempotency, conflict detection, and conflict resolution. A "last write
wins" policy should not be adopted casually because it can silently destroy
offline changes. Offline UI notifications are straightforward; reliable
conflict-safe synchronization is the underlying engineering requirement. Prior
art to draw on: the HLC per-field merge decision preserved in `abandoned.md`.

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
