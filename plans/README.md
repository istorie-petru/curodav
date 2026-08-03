# Plans

This folder holds forward-looking documents: specific features that are planned but not yet built, and system-level design docs that govern how the whole app is built (data model, sync, storage).

- **Feature plans** (this folder, top level) — a scoped, actionable spec for one upcoming piece of work. Currently: `tasks-ux-rework.md`, `design-alignment.md`, `calendar-and-tasks-rework.md`, `webapp-ui-design-direction.md` (superseded by `spaces-v2-university-material.md`'s Material decision — pending deletion once that ships), `webapp-action-pipelines-audit.md`, `webapp-usability-and-davx5-rollout.md` (the implementation schedule for the two preceding docs, plus the DAVx5/mobile-hosting phase), `spaces-home-pipeline.md` (Home→Space→Project pipeline), `spaces-v2-university-material.md` (extends the Space page with real content, Contacts-by-tag, Habits-as-recurring-tasks, a hardcoded University module, and Material Design).
- **`systems/`** — architecture-level references that apply across every feature (`architecture.md`) and the historical decision record for how the app got here (`decisions-log.md`). These aren't "to-do" items; they're the constraints and rationale future plans should build on top of.
- **`expansion-deferred.md`** — features that were explicitly scoped out of v1/v2 (media tracker, infra dashboard, mobile, etc.), kept here so the reasoning isn't lost and someone doesn't accidentally re-litigate a closed decision.

## Workflow

When a plan here is finished, its outcome is documented (or an existing doc is updated) in [`../features/`](../features/README.md) — that folder describes what's actually built, this one describes what's intended. A finished plan should be deleted or reduced to a one-line pointer at that point, not left duplicating the features doc.
