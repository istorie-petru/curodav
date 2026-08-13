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
  actions and progress cards. See `features/tasks.md` § Projects. Not
  shipped (deferred to 1.4/1.5, per spec): the project's own Tasks view +
  Week Calendar view, work allocations, hour-based progress (cards use
  completed/total task *count* as the interim proxy), and the global Tasks
  page's project grouping. Side work (Widget consolidation + Streak + Next
  Deadline) not started — optional, doesn't block 1.4+.
- **Next slice:** `1.4` — Work allocations + project week calendar
  (`open-priority.md` § Work allocations, § Task & calendar semantics). Adds
  the calendar-event-linked-to-a-task model and the project's Week Calendar
  view; unlocks real hour-based project-card progress (currently a
  task-count proxy, see `db.projects.py`'s `_project_card`). `open.md`'s
  Command palette actions follow-up is still a fine smaller slice instead,
  whenever a session wants something self-contained.
- **Do not start:** anything under `1.5`+ in `roadmap.md` — 1.5 depends on
  1.4's work allocations landing first.

## Breadcrumbs for 1.4 (Work allocations + project week calendar)

Written at the end of the 1.3 session so the 1.4 session can skip a full
exploration pass. Read `open-priority.md` § Work allocations and § Task &
calendar semantics for the actual spec — this is only "where in the code,"
not "what to build."

- **`label_config.is_project`/`start_date`/`end_date`/`archived_at`** —
  `webapp/src/db.py`, columns added 1.3 (`CREATE TABLE` around line 254,
  `_ensure_column` migrations ~line 700). `db.list_project_labels`,
  `db.project_status`, `db.find_overlapping_project`, `db.archive_project`
  are the 1.3-shipped helpers 1.4 builds on top of, not around.
- **`routers/projects.py`** — the Projects page + promote/dates/demote/
  archive actions (`/projects`). 1.4's Week Calendar view is a new sub-page
  under this same router (e.g. `/projects/{name}/calendar`), not a
  separate router — keep the "one router per surface family" pattern
  `routers/labels.py`'s own docstring describes.
- **`_project_card` in `routers/projects.py`** — `progress` is currently
  completed/total *task count* (1.3's interim proxy, see its own docstring
  note). 1.4 should replace this with real scheduled-work totals once work
  allocations exist, per `open-priority.md`'s "Project progress is based on
  work, not merely task count" rule — this is a known, deliberate stopgap,
  not an oversight to preserve.
- **Work allocations are Events, not a new table** — `open-priority.md` § Work
  allocations: "A work allocation... is a calendar Event linked to that
  task." Look at how `events` currently relates to `tasks`
  (`event_task_relations`, `webapp/src/db.py`) before inventing a new
  relationship — the existing Relations-card plumbing
  (`features/tasks.md` § Relations) may already be most of what's needed,
  possibly extended with a "this relation is a work allocation, not just a
  reference" marker.

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
