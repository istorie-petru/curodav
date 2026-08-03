# Plan: Align remaining screens to the design reference

**Status:** Open · logged 2026-07-19
**Feature areas:** [`../features/design-system.md`](../features/design-system.md), [`../features/dashboard.md`](../features/dashboard.md), [`../features/tasks.md`](../features/tasks.md), [`../features/calendar.md`](../features/calendar.md)

A design reference was provided ("ModernPlasma Productivity" — a macOS-styled mockup: grouped-list cards, segmented controls, colored badges/pills, mini-sidebars with colored category dots, a right-side inspector slide-over) with the direction to get the app as close to a native Qt/Darkly-macOS look as possible, with minimal QSS overrides. The highest-leverage part of that — the central stylesheet fighting the native theme instead of using it, and the Preferences dialog's structure — is done (see `design-system.md` and `settings.md`, both 2026-07-19). What's below is real, but each item is a structural layout change with wider blast radius than a QSS trim, so it's scoped here rather than rushed in the same pass.

## Mini-sidebars with colored category dots

Both Tasks and Calendar in the design doc have a narrow (150px) second sidebar — "Lists" / "Calendars" — showing each category as a colored dot + name + count, selectable to filter the main view. The app has the equivalent data (tags, projects) and filtering logic (`TagFilterBar`, see `tags-and-linking.md`) but not this specific layout: it currently uses a horizontal filter-chip bar above the list, not a vertical mini-sidebar. Reasonable to build as a new small shared widget (`CategorySidebar` or similar in `features/shared/`) reused by both Tasks and Calendar, rather than two bespoke implementations.

## A real segmented-control widget

The design doc's `SegmentedControl` (Table/Kanban, Month/Week/Day, Light/Dark, etc.) is used everywhere as the standard view-switcher. The app has at least two independent hand-rolled versions of the same idea (`cal-view-btn` in Calendar, whatever Tasks' view switcher currently is) each with their own QSS. Qt has no native segmented control, so *some* custom styling is unavoidable here — but it should be one shared widget class instead of duplicated per module, both for consistency and so a future look change happens in one place.

## Inspector as a slide-over, not a permanently-docked panel

The design doc's inspector is an overlay: it slides in from the right over the content, with a click-outside-to-close backdrop, and doesn't take up permanent width when closed. The app's `InspectorPanel` is a permanently-present widget in the main window's layout (`content_row.addWidget(self._inspector)` in `app.py`) that presumably resizes/hides in place rather than overlaying. Converting it to a real overlay (a frameless child widget positioned over the content stack, shown/hidden with a backdrop click handler like `CommandPalette`'s frameless-dialog pattern) would match the reference more closely and stop it from permanently reserving screen width. Moderate risk: `InspectorPanel` is wired into every module's `open_object_requested` signal, so this touches the main window's layout code, not just one file.

## Smaller items

- **Toolbar height token.** The design doc uses one `--toolbar-h` CSS variable for every module's toolbar row (Tasks, Calendar). Worth confirming the app's per-module toolbars (`TopBar`, Calendar's `cal-view-switcher` row, Tasks' filter row) actually share one fixed height rather than each hardcoding their own — a quick audit, not necessarily a rebuild.
- **Pill-shaped list-assignment chips.** The design doc's inspector shows a task/event's list membership as a row of colored pill chips (click to reassign) rather than a dropdown. The app's tag chips (`tag-chip` class) are visually close already — worth checking whether project/list assignment in the inspector could reuse that exact chip style instead of whatever it currently uses.
- **Badge component reuse.** The design doc's `Badge` (priority, due-count, overdue-count) is one component used consistently. Confirm the app's `priority-1..4` classes and any "N Due"/"N Overdue" labels are visually consistent with each other, not ad hoc per screen.

## Why this is scoped separately, not done now

Each item above touches shared widgets used across multiple modules (`InspectorPanel`, tag/category filtering, view switchers) — the kind of change that's easy to get subtly wrong without being able to see the result, and this session's verification was necessarily headless (no screenshots, only structural/behavioral checks: widget classes assigned correctly, stylesheet length, test suite green). The QSS trim and Settings restructuring done in this same pass were chosen specifically because they were verifiable that way; these aren't. Recommend tackling one item at a time with a look at the actual running app in between, rather than all at once.
