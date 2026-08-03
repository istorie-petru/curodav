# Feature: Roadmap & Goals

**Code:** removed 2026-07-19 (was `desktop/src/features/roadmap/widgets.py`)
**Status:** Removed — the module UI is gone; the underlying data model is not

## What happened

The Roadmap module (vertical era-grouped timeline of `roadmap_node` objects) was removed from the app on 2026-07-19, along with Notes (see `notes.md`) — see that doc for the shared rationale (both are planned to return later as part of a folder-and-markdown-first reimagining).

**What's still true:** `ObjectType.roadmap_node` and `ObjectType.goal` still exist in the model, untouched. Existing `roadmap_node`/`goal` objects still open in the generic Inspector. The seed/demo data's three `roadmap_node` entries were removed (they existed purely to populate the now-gone module), but the `goal`-type seed entries were kept — goals don't depend on a dedicated module to make sense generically (a progress-tracked object with a title), unlike roadmap nodes, which were meaningless outside the timeline visualization they were built for.

## What was built (historical — describes the removed implementation)

- **Roadmap** — `roadmap_node` objects grouped by era/year, displayed as a vertical timeline: a left vertical line with a dot per node, each showing year, title, description, and optional links to projects/goals. A "you are here" marker indicated the current position. Eras (e.g. "Foundation", "Formation", "Culmination") were stored as tags or a dedicated era field, not as separate objects.
- **Goals** — objects of `type=goal`, linked to roadmap nodes and projects, tracked on the Dashboard as "active goals" with progress bars. (This Dashboard integration point should be double-checked if goals come back into active use — it wasn't specifically re-verified as part of the 2026-07-19 removal, since goals themselves weren't touched.)
