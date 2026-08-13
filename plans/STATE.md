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
  [`/remove`]). See `features/tasks.md` § Work allocations (1.4);
  `open-priority.md` § Work allocations / § Task & calendar semantics are
  annotated with what shipped vs. what's still open. 20 new tests
  (`test_work_allocations.py`), full suite 968 passed.
- **Next slice:** `1.4` slice 2 — the project's Week Calendar view
  (`open-priority.md` § Project pages & views' Week Calendar bullet), the
  drag-and-drop scheduling surface the task-detail "Work sessions" card is
  the interim substitute for. This is also the first time a `/projects/{name}`
  detail page needs to exist at all — the Projects page today only shows
  cards. Once that view exists: wire `_project_card`'s `progress` to real
  `db.task_work_hours` totals (currently the 1.3 task-count proxy) and hide
  a completed task's future allocations from that calendar (`open-priority.md`
  § Task & calendar semantics' "future allocations are hidden" rule — not
  wired into any calendar view yet, deliberately, since none existed to wire
  it into before this slice). `open.md`'s Command palette actions follow-up
  is still a fine smaller slice instead, whenever a session wants something
  self-contained.
- **Do not start:** anything under `1.5`+ in `roadmap.md` — 1.5 depends on
  1.4's Week Calendar view landing first.

## Breadcrumbs for 1.4 slice 2 (project week calendar)

Written at the end of the 1.4-slice-1 session so the next 1.4 session can
skip a full exploration pass. Read `open-priority.md` § Project pages &
views (the Week Calendar bullet) and § Task & calendar semantics for the
actual spec — this is only "where in the code," not "what to build."

- **`db.create_work_allocation`/`list_work_allocations_for_task`/
  `task_work_hours`/`delete_work_allocation`/`work_allocation_task_uid`/
  `sync_work_allocation_titles`** — `webapp/src/db.py`, added 1.4 slice 1
  (search "1.4 (Work allocations" for the whole block, right after
  `related_events_for_task`). These are what the calendar view's
  drag-to-create/resize/delete interactions should call — don't reinvent
  the event-creation or hour-math logic, it's already here and tested
  (`test_work_allocations.py`).
- **`routers/projects.py`** — the Projects page + promote/dates/demote/
  archive actions (`/projects`), no `/projects/{name}` detail route yet.
  The Week Calendar view is a new sub-page under this same router (e.g.
  `/projects/{name}/calendar`), not a separate router — keep the "one
  router per surface family" pattern `routers/labels.py`'s own docstring
  describes. The project's Tasks view (the other principal view the spec
  calls for) can be a thinner slice reusing `_tasks_toolbar.html`-style
  filtering by the project's label — check whether it's worth building
  alongside the calendar view in the same session or splitting further.
- **`_project_card` in `routers/projects.py`** — `progress` is still
  completed/total *task count* (1.3's interim proxy, see its own docstring
  note) even after slice 1 — `db.task_work_hours` exists per-task now but
  nothing aggregates it to project level yet. Swap this once the calendar
  view makes creating allocations actually reachable for a real project's
  tasks, per `open-priority.md`'s "Project progress is based on work, not
  merely task count" rule.
- **Hiding future allocations of a completed task** — `open-priority.md` §
  Work allocations: "future allocations are hidden from the active
  calendar" once a task completes, without deleting them. Not implemented
  anywhere yet (deliberately deferred, see slice 1's annotation in
  `open-priority.md`) — needs a filter applied wherever the project
  calendar renders events, likely keyed off `db.work_allocation_task_uid`
  + the linked task's `status`.
- **Task-detail "Work sessions" card stays** — `_task_work_allocations.html`
  (task_detail.html/task_form.html) is the plain-form fallback the spec
  implies should keep working alongside the drag-and-drop surface, not
  something the calendar view replaces or removes.

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
