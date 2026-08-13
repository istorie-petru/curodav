# State

Single source of truth for "where are we right now." Read this file — and
only this file — at the start of a session working toward 2.0. Don't re-read
`roadmap.md` / `open-priority.md` / `open.md` in full; they're expanded specs
for reference, not session-start context. Update this file at the end of every
session, right before the final commit of that session.

## Right now

- **Shipped:** `1.2`, complete (2026-08-13) — task model settled: flat tasks
  + work allocations, subtask hierarchy removed. Side work: Universal command
  surface steps 1–4 and 6 all landed — `db.search_entities` query layer,
  `GET /api/search` + `/search` page, Ctrl-K/Cmd-K overlay
  (`static/command_palette.js`), and the Relations-card picker wiring (the
  old `linkable_events`/`linkable_tasks` `<select>` pools are gone). See
  `features/tasks.md` § Search & the command surface. Not shipped: step 5's
  fuller scope (command-palette *actions* — create/complete/delete/label from
  the overlay) — tracked as an optional follow-up in `open.md` § Command
  palette actions, not a blocker for anything.
- **Next slice:** `1.3` — Project-enabled label stack (`open-priority.md` §
  Project-enabled label stack). It's the hard gate for 1.4–1.7 — start here
  next. `open.md`'s Command palette actions follow-up is a fine smaller slice
  instead, whenever a session wants something self-contained.
- **Do not start:** anything under `1.4`+ in `roadmap.md` — it depends on the
  project stack (`1.3`) landing first.

## Breadcrumbs for 1.3 (Project-enabled label stack)

Written at the end of the 1.2 session so the 1.3 session can skip a full
exploration pass. Read `open-priority.md` § Project-enabled label stack for
the actual spec — this is only "where in the code," not "what to build."

- **`label_config` table** — `webapp/src/db.py`, `CREATE TABLE` around line
  250. Has `generate_space` (Space page toggle) but no bounded period or
  lifecycle columns yet; 1.3 needs to add something like `is_project`,
  `start_date`, `end_date`, `status` (Open/Pending/Pending Archiving/Archived)
  here. Existing precedent for adding columns to this table: the
  `_ensure_column` migration helper (`db.py` ~line 700).
- **`project_label_for(conn, object_type, object_id)`** — `db.py` ~line 2126.
  The current heuristic ("whichever attached label isn't a Space, chosen
  alphabetically") that `open-priority.md`'s "Known open risks" flags as
  interacting directly with this rework. 1.3 either resolves or deliberately
  supersedes it once a label can be explicitly project-enabled instead of
  inferred.
- **`routers/labels.py`** — label management (`manage_labels`,
  `label_detail`) lives here today; `label_detail.html`/`labels_manage.html`
  are the templates. The project stack's dedicated sidebar page + Tasks view
  + Week Calendar view (per the spec) are new surfaces, but the "a label can
  carry extra behavior" plumbing (`_label_scope`, `set_label`) is the
  existing pattern to extend rather than duplicate.
- **Project cards' work-based progress** needs completed vs. scheduled work
  per task — depends on the 1.1 aggregation service
  (`webapp/src/derived_state.py`) for the counting pattern, even though work
  allocations themselves aren't Slice 1.3's job (that's 1.4).

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
