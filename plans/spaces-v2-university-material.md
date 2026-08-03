# Plan: Dashboard rework, Spaces v2, Contacts-by-tag, Habits-as-recurring-tasks, University module, Material Design

**Status:** Open, not started · logged 2026-08-02, corrected 2026-08-02 (the previous revision wrongly generalized University into an abstract "building blocks" system — that's not what was asked for. University is hardcoded, as originally specified. The only place a compromise was actually asked for is the Dashboard: it stays editable, not locked into a fixed template.)
**Supersedes:** [`webapp-ui-design-direction.md`](webapp-ui-design-direction.md) (Material replaces its "minimalist/Notion-adjacent" direction — delete that doc once this ships).
**Extends (does not replace):** [`spaces-home-pipeline.md`](spaces-home-pipeline.md) — its Home→Space→Project pipeline and "no new tabbar entries" rule still hold.
**Decisions locked in:** Material Design; habit completions stay local-only with a recurring-task-styled UI; Contacts move to exactly two global CardDAV addressbooks (Active, Archived) with grouping via tags; the Databases engine stays and gets reused (not necessarily generalized) for University's Grades.

---

## 1. Global Dashboard: stays editable, defaults to the requested layout

Not a fixed/locked template. Keep `dashboard_widgets`/`WIDGET_TYPES` exactly as they are today (add/remove/reorder/resize widgets, add more lists later if wanted) — the only two changes:

- **New widget type: Calendar+Agenda stack** (month view + this-week agenda in one widget), added to the existing `WIDGET_TYPES` registry the normal way (one entry, per `webapp/README.md`'s Phase 8 pattern).
- **New default seed for a fresh Home**: this Calendar+Agenda widget at 30% width, and the existing Today's Agenda widget (or a plain Today task list, whichever already fits) at the remaining width, side by side. This is just what a new dashboard starts with — Edit Layout, Add widget, resize, and reorder all keep working exactly as today on top of it.
- **Breakpoints**: desktop full-width and desktop half-width both render the two widgets side by side (30/70); mobile stacks them, tasks above agenda. Still need to confirm which side (left/right) each widget defaults to — the original request said "on it's left" for both, which can't be literally true.

That's the whole Dashboard change. No new "fixed size" flag, no archiving anything.

---

## 2. Spaces v2 (Personal / Professional / University)

Per `spaces-home-pipeline.md`'s Space page: a fixed (non-widget-customizable) page per `project_groups` row, showing:

- Month + week calendar, scoped to the space's projects.
- A task list, date range set per space (Personal: ~90 days; University: upcoming week/month) — a plain setting on the space, not a big config framework.
- Personal space also shows a Habits section (habits linked to a project under this group).
- Contacts shown anywhere in a space are filtered by tag, not by list (see §4).
- Kanban/Timeline stay available as view options on any task list app-wide, not tied to Professional specifically.

---

## 3. Habits: recurring-task UI, local-only log

Habit definitions get surfaced/edited alongside recurring tasks in the UI. `habit_entries` stays a local-only table (no CalDAV sync of completions — VTODO's per-instance completion model is too fragile for what needs to be a fast, trustworthy daily checkbox). The heatmap keeps reading from that local history, same as today.

---

## 4. Contacts: two global addressbooks + tags

Exactly two CardDAV addressbooks system-wide: Active, Archived. Every other grouping (Friends, Family, Professor, etc.) is a tag on the contact, reusing the tag mechanism tasks/events already have. Archiving = actually moving the vCard from Active to Archived (a real CardDAV move), not a local-only flag. Needs a real migration (existing addressbook name → tag, then move the card) written and tested in isolation before anything else touches these tables — this is the one item here with real data-loss risk if rushed.

---

## 5. University module — hardcoded

This is the specific, purpose-built structure asked for, not a generic system:

- **Class = Project**, scoped under the University space.
- **Schedule** = a `schedule_classes` row linked to the class via `project_uid` (already how this works). Shows a computed "in 5 days" countdown from today's date, day-of-week, and odd/even parity.
- **Grades** = a `databases` row, auto-provisioned when a class is created (not built from scratch by the user): default columns (assessment, grade, weight, date, source) plus a `WEIGHTAVG` summary formula, using the existing Databases/`formula_engine.py` engine.
- **Homework** = tasks in the class's linked task list, tagged "Homework."
- **Professor contact + mail button** = `schedule_classes.professor_contact_uid`, already links to a real contact (`routers/schedule.py`'s `_resolve_professor_field`) — this just needs rendering (name + `mailto:` link) on the class's page.
- **Discipline page** = the class's own `/projects/{uid}` page.
- The generic Databases feature (create-any-table-from-scratch) stays in the app as-is for anything else that wants it — University's Grades just doesn't start from a blank table, it starts pre-filled.

---

## 6. Material Design adoption

Elevation/tonal-surface tokens replacing the flat card system, bottom nav on mobile + top app bar on Calendar/Tasks/Settings (Home keeps Space-cards-as-navigation, no new tabbar entries), FAB as the fallback create affordance alongside existing quick-add. Restyle existing interaction wins (optimistic drag, bulk actions, inline edits) rather than rebuilding their behavior. Broadest blast radius of everything here — do last, once the structural changes above have settled, and look at real screenshots before committing token values app-wide.

---

## 7. Settings, filtering, portability

- Full project CRUD in one Settings entry point (mostly exists already — confirm it's not scattered).
- Schedule settings move under University's own space settings tab.
- Multi-select space/project filtering added to the general Calendar/Tasks views.
- Export/portability stays secondary — the existing CalDAV/CardDAV architecture already covers most of it. DAVx5 hosting is its own doc (`webapp-usability-and-davx5-rollout.md`, Phase C), unaffected by this one.

---

## Open questions

1. Dashboard: which widget (Calendar+Agenda vs. task list) defaults to the left vs. right side.
2. Whether Home's mobile view drops the Month calendar or keeps it below the agenda.
3. Whether the generic Databases feature needs any changes at all, or just stays as-is while University's Grades is provisioned on top of it.

## Suggested build order

1. Contacts migration (§4) — real risk, do first and in isolation.
2. University module (§5) — explicitly the first-requested piece, and the professor-contact/schedule data already exists.
3. Dashboard widget addition (§1) + Space page (§2) together — share the same filter/render functions.
4. Habits IA (§3) — smallest, can land anytime.
5. Material Design (§6) last.
