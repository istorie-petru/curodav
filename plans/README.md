# Plans

This folder holds forward-looking documents: specific features that are planned but not yet built, and system-level design docs that govern how the whole app is built (data model, sync, storage).

- **Active plans** — the genuinely-open work, with any shipped-outcome pointer noted in each doc's own status line. Current active/kept set: `label-space-rework.md` (✅ shipped — current data-model authority), `command-center-rework.md` (✅ shipped — M3/UI pass record), `webapp-usability-and-davx5-rollout.md` (one Phase B item + Phase C open), `contacts-nextcloud-parity.md` (planning only), `widget-consolidation-design.md` (design only, awaiting go-ahead), `expansion-deferred.md` (deferred-features record). Completed items (`modal-input-design.md`, `settings-rework.md`, `dashboard-usability-rework.md`, `webapp-action-pipelines-audit.md`) are reduced to one-line pointers per the workflow below.
- **`systems/`** — architecture-level references that apply across every feature (`architecture.md`) and the historical decision record for how the app got here (`decisions-log.md`). These aren't "to-do" items; they're the constraints and rationale future plans should build on top of.
- **`expansion-deferred.md`** — features that were explicitly scoped out of v1/v2 (media tracker, infra dashboard, mobile, etc.), kept here so the reasoning isn't lost and someone doesn't accidentally re-litigate a closed decision.

## Cleanup history

Desktop-era plans deleted 2026-08-11 (superseded by the 2026-08-03/06 reworks, see `command-center-rework.md` and `label-space-rework.md`): `tasks-ux-rework.md`, `design-alignment.md`, `calendar-and-tasks-rework.md`, `apple-vs-google-calendar-plan.md`, `spaces-home-pipeline.md`, `spaces-v2-university-material.md`.

## Workflow

When a plan here is finished, its outcome is documented (or an existing doc is updated) in [`../features/`](../features/README.md) — that folder describes what's actually built, this one describes what's intended. A finished plan should be deleted or reduced to a one-line pointer at that point, not left duplicating the features doc.
