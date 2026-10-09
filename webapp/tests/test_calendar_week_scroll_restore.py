"""FullCalendar-parity interactions slice 5 (plans/open.md's "Calendar:
FullCalendar-parity interactions" section, plans/STATE.md's own entry for
this slice): Week view's async region refresh no longer resets scroll
position.

Root cause: async_crud.js's refreshRegion() does `current.replaceWith(
fragment)`, a wholesale swap of #week-grid. `.time-grid-wrap` (the actual
`overflow-y:auto` scroll container, style.css) is a child of that swapped
element, so the fresh node always started at `scrollTop: 0`, discarding
whatever position the user had scrolled to. Fix lives entirely in
async_calendar.js's refreshWeek(): capture `.time-grid-wrap`'s scrollTop
before the swap, restore it on the freshly-swapped-in node after.

No backend change (open.md's own scoping note: "Small, contained, no
backend change"), and this repo has no JS unit-test harness for
static/*.js (same recurring gap every prior JS-only calendar slice's own
test file notes) -- covered structurally: `node --check` for syntax, plus
source greps pinning the specific capture/restore behavior so a future
refactor can't silently drop it."""

from __future__ import annotations

import subprocess
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent.parent / "src" / "static"


class TestWeekScrollRestoreStructural:
    def test_async_calendar_js_syntax_is_valid(self):
        subprocess.run(["node", "--check", str(_STATIC_DIR / "async_calendar.js")], check=True)



