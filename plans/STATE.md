# State

Single source of truth for "where are we right now." Read this file — and
only this file — at the start of a session working toward 2.0. Don't re-read
`roadmap.md` / `open-priority.md` / `open.md` in full; they're expanded specs
for reference, not session-start context. Update this file at the end of every
session, right before the final commit of that session.

## Right now

- **Shipped:** `1.3`, complete (2026-08-13) — project-enabled label stack:
  `label_config.is_project` + `start_date`/`end_date`/`archived_at`, the
  computed Open/Pending/Pending Archiving/Archived lifecycle
  (`db.project_status`), the overlap rule (`db.find_overlapping_project`),
  `project_label_for`'s supersession (an explicit `is_project=1` label now
  wins over the old "first non-Space label" heuristic), and the dedicated
  `/projects` page (`routers/projects.py`) with promote/dates/demote/archive
  actions and progress cards. See `features/tasks.md` § Projects.
- **Shipped:** `1.4` slice 1, complete (2026-08-13) — work allocations' data
  model + semantics: `event_task_relations.is_work_allocation`,
  `db.create_work_allocation`/`list_work_allocations_for_task`/
  `task_work_hours`/`delete_work_allocation`/`work_allocation_task_uid`,
  title-sync both directions (`upsert_task` -> allocation events; editing an
  allocation event's title -> the task), and a plain-form "Work sessions"
  card on the task detail/edit modals (`POST /tasks/{uid}/work-allocations`
  [`/remove`]). See `features/tasks.md` § Work allocations (1.4). 20 new
  tests (`test_work_allocations.py`).
- **Shipped:** `1.4` slice 2, complete (2026-08-14) — the project detail
  page: `GET /projects/{name}` (`routers/projects.py::project_detail`) and
  its Tasks view (every task carrying the project's label, open/completed
  split, the same interactive row — pill-selects, inline due date,
  delete-with-undo — the global Tasks page uses, extracted into a shared
  `_task_row.html` macro so neither page duplicates the markup). "+ New
  task" opens `/tasks/new?project=<name>`, which now pre-checks that label
  on the form even for a brand-new project with no tasks yet (a real gap
  `list_tag_names_in_use` alone had — fixed in `new_task_form`). Project
  cards' "Open" link now points here instead of `label_detail`. See
  `features/tasks.md` § Projects, "Project detail page + Tasks view". 12
  new tests (`test_project_detail.py`), full suite 980 passed.
- **Shipped:** `1.4` slice 3, complete (2026-08-13) — the project's **Week
  Calendar view**: `GET /projects/{name}/calendar`
  (`routers/projects.py::project_calendar`), reusing the global Week grid's
  own layout math (`grid_layout.layout_day`) rather than duplicating it. An
  "Unscheduled tasks" list (open project tasks with no work allocation yet,
  `{project} > {task} · {remaining}h` items using `db.task_work_hours`, not
  `_task_row.html`) drags onto the grid to create a work allocation
  (`create_allocation` -> `db.create_work_allocation`); existing blocks
  drag to move/resize (`move_allocation`, a plain `start_at`/`end_at` edit)
  or delete (`delete_allocation` -> `db.delete_work_allocation`, block
  only, never the task). Ordinary events and other projects' allocations
  render as subdued context (`.context-event`); this project's own
  allocations are prominent (`.work-allocation`). Added a Tasks/Week
  Calendar tab switcher to `project_detail.html`, following
  `calendar_week.html`'s own `.segmented.calendar-subnav` precedent. This
  was the last piece of "Project pages & views" and closes out 1.4's main
  line — see `features/tasks.md` § Projects, "Week Calendar view". 15 new
  tests (`test_project_calendar.py`), full suite 995 passed. **1.4 is now
  fully shipped** (`pyproject.toml` bumped to `1.4.0`); still open and
  deliberately deferred (doesn't block 1.5+): `_project_card`'s `progress`
  wired to real `db.task_work_hours` totals (still the 1.3 task-count
  proxy), and hiding a completed task's future allocations from the
  calendar (`open-priority.md` § Task & calendar semantics' "future
  allocations are hidden" rule).
- **Shipped:** `1.5` slice — **single-project-per-task**, complete
  (2026-08-13) — `db.upsert_task`'s `tags` argument now rejects a label set
  carrying more than one `is_project=1` label at once
  (`db.MultipleProjectLabelsError`, raised before anything is written, so a
  rejected call leaves no partial write). Wired into the task create/edit
  forms (`routers/tasks.py`'s `create_task`/`update_task`, surfaced as
  `HTTPException(400, ...)`, same convention as this app's other plain-form
  validation errors) and the Tasks page's bulk "Add label" action (`POST
  /tasks/bulk`, applied per-uid so non-conflicting tasks in the same batch
  still get their label, 400 with the rejected uids listed) — the three real
  paths that could put a second project label on a task. No client-side
  prevention in the labels picker itself (`_widget_list_multiselect.html` is
  shared by tasks/events/contacts/habits with no project concept); rejecting
  server-side with a clear message was the smaller, more consistent change.
  Enforcement is write-boundary only — a pre-existing task with two project
  labels (direct DB edit, restored backup) is left untouched until something
  next writes new tags for it, confirmed by test. See `features/tasks.md`
  § Task model, 12 new tests (`test_single_project_per_task.py`), full suite
  1007 passed.
- **Shipped:** `1.5` slice — **Tasks page groupable by project**, complete
  (2026-08-13) — `GET /tasks` takes a `group_by` query param (`"none"`
  default/absent, fully backward-compatible with existing links/bookmarks;
  `"project"`). `group_by=project` clusters the Table view's open/completed
  splits under project-name headers (`routers/tasks.py::
  _group_tasks_by_project`, reusing `db.project_label_for` — the same
  per-task "which label is the project" lookup the project detail page
  uses), named groups sorted alphabetically, a "No project" bucket sorted
  last. Composes with every existing date/status/importance/urgency/label/
  search filter and the active `sort`/`dir` — grouping is applied after
  both, so a group's tasks keep the page's sort order; the existing
  completed-stays-visible-but-separated split is preserved, just grouped
  independently on each side. A "Group by" toggle (None/Project) was added
  to `_tasks_toolbar.html`, Table-view only, following the same
  `_filter_dropdown.html` single-select pattern and shared
  `#tasks-filters-form` every other Tasks filter already uses. Grouping
  only adds header `<tr>`s and splits rows across more `<tbody>` elements —
  `_task_row.html` markup and `static/tasks_table.js`'s selectors are
  unchanged. See `features/tasks.md` § Task model, "Table view groupable by
  project", 10 new tests (`test_tasks_grouping.py`), full suite 1017
  passed.
- **Shipped:** `1.5` slice — **deadline-vs-work-allocation distinction**,
  complete (2026-08-13) — the two concepts already existed as separate
  fields/mechanisms (`due_at` vs. `db.task_work_hours`), but the global
  Tasks table and the project detail page's Tasks view (shared
  `_task_row.html` macro) only ever showed "Due" — work-allocation status
  was invisible on the primary task-management surface. Added a
  "Scheduled" column (`{completed}/{scheduled}h`, plain text and a
  distinct label from the editable "Due" date cell) to both. Added
  `db.task_work_hours_bulk(conn, task_uids)` — one batched query per page
  (grouped by `task_uid`) instead of an N+1 of `list_work_allocations_for_
  task` calls, since no existing "aggregate X across many tasks" batch
  precedent existed in `db.py` to reuse; `db.task_work_hours` itself is
  unchanged. Wired into `routers/tasks.py::list_tasks` and
  `routers/projects.py::project_detail`, both attaching `task["work_hours"]`
  before rendering. See `features/tasks.md` § Task model, "Deadline-vs-
  work-allocation distinction," 8 new tests (`test_task_scheduled_
  column.py`), full suite 1025 passed. **1.5 is now fully shipped**
  (`pyproject.toml` bumped to `1.5.0`).
- **Next slice:** `1.6` — Schedule & recurrence rework (`roadmap.md`'s 1.6
  row, `open-priority.md` § Schedule & recurrence rework): courses as
  project labels + recurring events, generalized non-working-day policy,
  named holiday calendars, manual occurrence exceptions, configurable
  terminology. `open.md`'s Command palette actions follow-up (1.2 side
  work) and 1.4's optional Project check-in side work are both still fine
  smaller, self-contained slices instead, whenever a session wants one.

## Breadcrumbs for 1.4's two still-deferred items

1.4's main line (work allocations + both project views) is fully shipped.
Two small pieces were deliberately deferred throughout 1.4 (per
`open-priority.md`'s own "still open" notes) and don't block 1.5 — pick
either up as its own small, self-contained slice whenever convenient,
not as part of a 1.5 slice:

- **`_project_card`'s `progress`** (`routers/projects.py`) — still
  completed/total *task count* (1.3's interim proxy). `db.task_work_hours`
  exists per-task (1.4 slice 1) and is now reachable for a real project's
  tasks via the Week Calendar view (slice 3) — swap `progress` to
  aggregate `task_work_hours` across a project's tasks, per
  `open-priority.md`'s "Project progress is based on work, not merely task
  count" rule.
- **Hiding a completed task's future allocations** — `open-priority.md` §
  Work allocations: "future allocations are hidden from the active
  calendar" once a task completes, without deleting them. Not implemented
  anywhere yet — needs a filter applied in `routers/projects.py::
  project_calendar` (and any future calendar view that renders work
  allocations), keyed off `db.work_allocation_task_uid` + the linked
  task's `status`.

## How to run a session (slice discipline)

1. Read this file. That's the whole session-start cost.
2. Pick **one** slice — one roadmap bullet, sized to ship standalone (the
   roadmap docs already size sections this way; if a section still feels big,
   split it into a smaller committable piece rather than attempting it whole).
3. Before writing code, open only the specific section of `open-priority.md`
   or `open.md` the slice belongs to (use grep/section headers, not a full
   read) — the docs are long because they cover nine releases, not because one
   slice needs all of it.
4. Implement, then run the affected test file(s) directly
   (`pytest tests/test_x.py -q`), not the full suite, while iterating.
5. Before calling the slice done: run the full suite once
   (`cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q`), commit
   with a message following the existing `Released X.Y — ...` / descriptive
   style, bump `pyproject.toml` version if the slice completes a release.
6. Update the "Right now" section above with the new position. Update
   `roadmap.md`'s table row and the relevant doc section (strike through /
   mark resolved, matching how `1.1`/`1.2` were closed out) in the same
   commit. Remove the finished section from `open-priority.md`/`open.md` and
   summarize the shipped outcome in `features/`, per each doc's own "How open
   work gets tracked" footer.
7. Stop. Don't chain multiple slices in one session unless they're trivially
   small (a doc-only correction, a one-line fix) — bigger sessions cost more
   tokens per slice and make the commit history harder to audit, not easier.

## Cheap verification, every session

```bash
git status --short                                    # catch uncommitted WIP from a prior session
cd webapp && PYTHONPATH=src ../.venv/bin/python -m pytest -q   # full suite, ~11s, 921+ tests
```

Run both before assuming a clean starting point — WIP has been left
uncommitted before (1.2 sat complete-and-passing but uncommitted until a
session checked `git status`).

## Where the detail actually lives (read on demand, not up front)

| Need | File | Read |
|---|---|---|
| Full release order / dependencies | `plans/roadmap.md` | the one table + the current release's subsection only |
| Rework spec (projects, schedule, views, sync) | `plans/open-priority.md` | the one `##` section for the current slice |
| App-local/low-priority spec | `plans/open.md` | the one `##` section for the current slice |
| Data model / layering rules | `features/architecture.md` | before touching schema or a new entity type |
| What's shipped, for cross-reference | `features/README.md` + linked docs | only if the slice touches an existing surface |
| Why something was cut, versioning history | `plans/abandoned.md` | rarely — only if reopening a past decision |

## Notes for future sessions

- Test env: `.venv/bin/python` at repo root, run from `webapp/` with
  `PYTHONPATH=src`. The system `python3` (3.14) is not the project venv.
- Git identity in this repo: `istorie.petru <126282015+istorie-petru@users.noreply.github.com>`.
- Commit message convention: `Released X.Y — <summary>` for a release-closing
  commit (see `git log`); plain descriptive messages for side-work-only or
  partial slices that don't close a release.
