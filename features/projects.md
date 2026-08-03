# Feature: Projects

**Code:** `desktop/src/features/projects/widgets.py`
**Status:** Implemented

A project is an object of `type=project`, serving as a structural parent for tasks, notes, and other objects via `parent_id`.

## Project detail view

- **Header** — title, description, color chip, derived progress bar. Progress is always computed (`done / total child tasks`), never stored.
- **Milestones** — inline list from `project_details.milestones` (`[{id, title, due_at, done}]`) — not separate objects, detail rows of the project. Inline add/remove.
- **Task list** — every object with `parent_id = project`, sortable/filterable, inline completion.
- **Links** — objects linked to the project (notes, related events, etc.) — see `tags-and-linking.md`.

## Navigation

Projects appear as a nav entry/collapsible section in the sidebar, each showing name + progress bar. The Tasks filter sidebar has a "By project" section listing projects with counts.

## Quick-create

Typing `#new-project-name` in any quick-add input creates the project on the fly and assigns the current task to it. A dedicated project-creation dialog (title, description, color, milestones) is also available from any module.

## Cascade behavior

Deleting or archiving a project cascades to its children (structural relationship, not associative — see `tags-and-linking.md`).
