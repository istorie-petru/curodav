# Roadmap

The single build order across both open-work docs. It merges the rework
([`open-priority.md`](open-priority.md)) with the app-local and low-priority
work ([`open.md`](open.md)) into nine minor releases — **1.1 → 1.9** — that
culminate in the next full release, **2.0**.

**Version:** the app is at **1.3** (1.0 was the first full release; 1.1 —
Virtual & derived states — shipped 2026-08-13; 1.2 — task model settled,
Universal command surface side work — shipped 2026-08-13; 1.3 — project-
enabled labels + lifecycle — shipped 2026-08-13). Minor releases are
numbered `1.1` … `1.9`; once everything on this roadmap is implemented, the
next full release is **2.0**. See the versioning rules in
[`abandoned.md`](abandoned.md).

## The two tracks

- **Track A — the rework** (`open-priority.md`): changes that reshape the
  architecture and presentation. This is the main line of the roadmap.
- **Track B — app-local & low priority** (`open.md`): features that don't
  touch the whole app. Non-blocking; slotted alongside Track A releases.

Track B items are "side work" — they can be moved between releases freely and
never hold Track A up.

## Release map

| Release | Main work (Track A) | Side work (Track B) | Depends on |
|---|---|---|---|
| `1.1` | ~~Virtual & derived states~~ — **shipped 2026-08-13** | Data health; Contacts parity | — |
| `1.2` | ~~Task-model decision~~ **resolved 2026-08-13** (flat tasks + work allocations, subtasks removed) | ~~Universal command surface~~ **shipped 2026-08-13** (search/navigate; command actions optional follow-up) | 1.1 |
| `1.3` | ~~Project-enabled labels + lifecycle~~ **shipped 2026-08-13** | Widget consolidation (not started — optional, doesn't block 1.4+) | 1.2 |
| `1.4` | Work allocations + project week calendar | Project check-in (optional) | 1.3 |
| `1.5` | Task management & grouping | — | 1.3–1.4 |
| `1.6` | Schedule & recurrence rework | Configurable views + optional Schedule | 1.3 |
| `1.7` | Information architecture & view surfaces | — | 1.1, 1.3, 1.4 + widgets |
| `1.8` | Offline-first editing & synchronization | Pagination | 1.1 (WebDAV) + data health |
| `1.9` | Deployment & polish: DAVx5 hosting | Remaining app-local items | domain + server |
| `2.0` | Full release — everything implemented | — | all of 1.1–1.9 |

## Release detail

### 1.1 — Model foundations

**SHIPPED 2026-08-13** — see `features/tasks.md` (§ Importance, Urgency, and
the virtual states) and the now-removed § Virtual & derived states in
`open-priority.md`. Everything else reads the output of this release, so it went
first: temporal states (`Today`, `Overdue`, …) are query projections, not
labels; the shared aggregation service computes the counts and workload every
surface needs; Importance/Urgency replace WebDAV priority (with the WebDAV
representation settled here — the sync work in 1.8 builds on it).

Side work (independent): **Data health & maintenance** (verified backups — the
prerequisite for trusting offline sync in 1.8) and **Contacts field parity**.

### 1.2 — Task model settled

**Task-model decision** (`open-priority.md` § Subtask model — the open
conflict): **resolved 2026-08-13** — **flat tasks + work allocations**. The
subtask hierarchy is removed outright; the schema change is applied (the old
`tasks.parent_uid` column stays on disk, never written or read again) before any
further task work. Small, but a hard gate for 1.3.

Side work (independent): **Universal command surface** (search / picker /
command palette) — **shipped 2026-08-13**: `db.search_entities` query layer,
`GET /api/search` + `/search`, Ctrl-K/Cmd-K, and the Relations-card picker
(`features/tasks.md` § Search & the command surface). Command-palette
*actions* (create/complete/delete/label from the overlay) didn't ship —
tracked as an optional follow-up in `open.md` § Command palette actions.

### 1.3 — The project stack

**SHIPPED 2026-08-13** — projects are labels with Project behavior:
`label_config.is_project` + a bounded `start_date`/`end_date`, the
Open → Pending → Pending Archiving → Archived lifecycle (computed at read
time — only `archived_at` is stored, the user's explicit confirmation — see
`db.project_status`), the overlap rule (`db.find_overlapping_project`), and
a dedicated `/projects` page with progress cards. `project_label_for`'s old
"any non-Space label is the project" heuristic is superseded (an explicit
`is_project=1` label now wins; the heuristic is only a fallback for data
that predates 1.3). See `features/tasks.md` § Projects for the shipped
shape. Card progress is completed/total *task count*, not hours — real
work-based (hour) progress needs 1.4's work allocations, which don't exist
yet; the project's own Tasks/Week Calendar views are 1.4's job too, not
this release's.

Side work (not started, optional, doesn't block 1.4+): **Widget
consolidation + Streak + Next Deadline** — must land before 1.7's Dashboard
rework so the widget grid is already consolidated.

### 1.4 — Work & time

**Work allocations + project week calendar** (`open-priority.md` § Work
allocations, Task & calendar semantics): allocations as calendar events linked
to tasks (a task's estimated work = the sum of its blocks), the project
scheduling surface with draggable unscheduled tasks, and the task↔event
edit/delete semantics.

Side work (optional): **Project check-in** — a small post-stack addition.

### 1.5 — Task management

**Task management & grouping** (`open-priority.md` § Task model): the global
Tasks page as a table groupable by project, single-project-per-task, deadline
vs. work-allocation distinction, completed tasks staying visible. Uses the
allocations from 1.4.

### 1.6 — Scheduling

**Schedule & recurrence rework** (`open-priority.md` § Schedule & recurrence
rework): courses become project labels + recurring events; generalized
non-working-day policy, named holiday calendars, manual occurrence exceptions,
and configurable terminology.

Side work: **Configurable views + optional Schedule module** — best landed now
that the reworked views are stable, since it toggles them.

### 1.7 — New surfaces

**Information architecture & view surfaces** (`open-priority.md` § Information
architecture & view surfaces): Dashboard (orientation), Today (execution), Week
(planning), Spaces (context), built on the aggregation service (1.1), the
project stack (1.3), and work allocations (1.4), with the consolidated widget
grid (1.3).

### 1.8 — Trust & offline

**Offline-first editing & synchronization** (`open-priority.md` § Offline-first
editing & synchronization) — the largest engineering item. Its sync model
(identifiers, tombstones, conflict resolution, work-allocation conflict
semantics) must be written before code. It starts on the WebDAV mapping from 1.1
and is trusted only once verified backups (data health, 1.1) exist.

Side work: **Pagination / collapsible sections** (Phase B of webapp usability).

### 1.9 — Deployment & polish

**DAVx5 mobile hosting** (`open.md` § Webapp usability + DAVx5 hosting) —
CalDAV/CardDAV sync to a phone via a public HTTPS reverse proxy. Pure infra, no
app code; blocked on an external domain + server. Any remaining app-local items
(Contacts parity if not already shipped, project check-in, leftover Track B work)
close out here.

### 2.0 — Full release

With 1.1–1.9 implemented, the next full release is **2.0**: a stable, supported
version of the reworked app.

## Things that can slip past the map

- **DAVx5 hosting** is blocked on infrastructure the repo can't provide
  (domain + server) — run it whenever that exists, not strictly in 1.9.
- **Project check-in** is explicitly optional — skip it without affecting
  anything.
- All side work can move between releases; only the Track A dependencies in the
  release map are load-bearing.

## Reading the plan

- Section-level detail lives in the two source docs; this roadmap is only the
  ordering. Each section in those docs still gets expanded into a full phase
  spec (acceptance line, concrete slices) when you give it a go-ahead, and is
  removed from `plans/` once shipped — see "How open work gets tracked" in
  either doc.
