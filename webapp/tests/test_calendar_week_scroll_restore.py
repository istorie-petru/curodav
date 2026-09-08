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

    def test_refresh_week_captures_scroll_top_before_the_swap(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        # The capture must read .time-grid-wrap's scrollTop off the node
        # that's still attached (weekEl), before refreshRegion's swap.
        assert 'weekEl.querySelector(".time-grid-wrap")' in script
        assert "oldScroller.scrollTop" in script

    def test_refresh_week_restores_scroll_top_after_the_swap(self):
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        # The restore must happen after refreshRegion resolves, against the
        # freshly re-queried #week-grid node, not the stale detached one.
        assert 'weekEl = document.getElementById("week-grid")' in script
        assert 'newScroller.scrollTop = scrollTop' in script

    def test_refresh_week_only_restores_when_a_scroller_existed(self):
        """No .time-grid-wrap on the page (shouldn't happen on Week, but
        defensive) must not throw -- capture is guarded to null, restore
        checks both the captured value and the new scroller before writing."""
        script = (_STATIC_DIR / "async_calendar.js").read_text()
        assert "var scrollTop = oldScroller ? oldScroller.scrollTop : null;" in script
        assert "if (scrollTop !== null && weekEl)" in script
        assert "if (newScroller) newScroller.scrollTop = scrollTop;" in script
