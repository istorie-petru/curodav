# Plan: Dashboard usability & functionality rework

**Status:** ✅ Shipped (2026-08-07 → 2026-08-10). What landed, point by point against the original plan:

1. **At-a-Glance stats strip** — new widget type `at_a_glance` (`_widget_at_a_glance.html`, `routers/dashboard.py::_render_at_a_glance`), numbers link to the filtered Tasks view.
2. **Default seed reorder** — fresh Home seeds today-oriented widgets; see `_DEFAULT_WIDGETS`.
3. **Greeting header** — dynamic "Good morning/afternoon/evening[, name]" replaces the static "Dashboard" h1 (`_greeting_for_hour`), and a banner with actions bar was added (2026-08-09/10).
4. **Quick-capture is no longer task-only** — the merged "+" button (`/quick/add`, `quick_add.html`) opens one modal with a Task/Event tab switch, replacing the two separate buttons (2026-08-10).
5. **Mobile "See more"** — removed outright rather than "made to earn its slot": the overflow list is gone and the tabbar itself scrolls (see `base.html`).

The rest (visual redesign of the widget system, Space-page defaults) was explicitly out of scope in the plan and remains so. Outcome is in `webapp/`; no further action from this plan.
