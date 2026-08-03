"""TimelineView — Gantt-like bar chart for tasks (PHASE 5).

Horizontal bars along a date axis, Week zoom only (2026-07-18: Day zoom
was removed -- keeping a single, always-current-quarter-ish week window
is simpler to reason about than a zoom toggle, and Month zoom was already
removed 2026-07-20 for being a squeezed, low-value view). Drag a bar to
reschedule, drag its edges to resize duration, drag it vertically to pick
its row, drag the gutter/grid boundary to resize the project-label
column, or click-and-drag an empty grid cell to create a new task in that
exact space.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import (
    QInputDialog,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectType
from ...core.utils.interval_packing import pack_intervals

BAR_COLORS = [
    "#7c3aed", "#0891b2", "#059669", "#d97706", "#dc2626", "#4f46e5",
    "#0d9488", "#b45309", "#9333ea", "#0284c7",
]

NO_PROJECT_LABEL = "(No project)"
# Widened 2026-07-20 from 6px -- a 6px-wide hit target was unreliable to
# actually land a real mouse click on, even though the underlying resize
# logic itself worked correctly (verified via exact-pixel QTest
# simulation). 10px is still narrow enough not to swallow normal "move"
# clicks on typical bar widths.
HANDLE_WIDTH = 10
GUTTER_WIDTH = 92  # default width of the project-swimlane label column
# Feature (2026-07-18): the gutter column is now user-resizable (drag the
# boundary between it and the date grid) -- these bound how far, so it
# can never be dragged down to unreadable or up to swallowing the whole
# view.
MIN_GUTTER_WIDTH = 60
MAX_GUTTER_WIDTH = 280
GUTTER_RESIZE_HOT_ZONE = 4  # px on either side of the boundary that grabs it


class TimelineCanvas(QWidget):
    """Paints the Gantt bars. Supports drag-to-reschedule and edge resize."""

    task_rescheduled = Signal(str, str, str)  # object_id, new_start_at, new_due_at
    context_action = Signal(str, str)  # object_id, action
    # Feature (2026-07-18): emitted after a click-and-drag on an empty
    # grid cell creates a new task there -- see _finish_create_drag. Not
    # added to self._objects/painted here; the app is expected to persist
    # it into its own object list and re-call set_objects (the same
    # round-trip every other creation path in the app already goes
    # through), so the canvas doesn't need its own separate "optimistic"
    # bookkeeping.
    task_created = Signal(Object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._objects: list[Object] = []
        self.setMinimumHeight(200)
        self._day_width = 24
        self._row_height = 36
        self._header_height = 40
        self.setMouseTracking(True)

        self._drag_mode: str | None = None  # "move" | "resize_left" | "resize_right"
        self._drag_idx: int = -1
        self._drag_orig = None  # (start_d, due_d)
        self._drag_start_x = 0

        # Column resize (2026-07-18): dragging the boundary between the
        # gutter and the date grid resizes the project-label column. Kept
        # as its own independent state (not folded into _drag_mode/
        # _drag_idx above) since it isn't about any particular task bar.
        self._gutter_width = GUTTER_WIDTH
        self._resizing_gutter = False
        self._gutter_resize_start_x = 0.0
        self._gutter_width_at_press = GUTTER_WIDTH

        # Click-create (2026-07-18): click-and-drag (or a plain click, as
        # a 1-day special case) on an empty grid cell stakes out a date
        # range and, on release, creates a new task spanning it -- see
        # mousePressEvent/mouseMoveEvent/_finish_create_drag. Also its own
        # independent state for the same reason as the gutter resize above.
        self._creating = False
        self._create_pid: str | None = None
        self._create_local_idx = 0
        self._create_row = -1
        self._create_start_day: date | None = None
        self._create_end_day: date | None = None

        # Vertical drag (2026-07-18): lets a "move" drag also change which
        # row within the task's own project block it lands on, not just
        # its dates. _drag_start_y/_drag_y_offset drive a smooth per-pixel
        # visual follow while the drag is in progress (see _bar_rect);
        # _drag_orig_local_lane/_drag_group_lanes are the row bookkeeping
        # captured at press time, used on release to compute the target
        # row. See mousePressEvent/mouseMoveEvent/mouseReleaseEvent and
        # _assign_swimlanes for how the target row is actually honored
        # without creating overlaps.
        self._drag_start_y = 0.0
        self._drag_y_offset = 0.0
        self._drag_orig_local_lane = 0
        self._drag_group_lanes = 1

        # Project swimlanes (2026-07-19): row assignment per object id, and
        # (start_row, row_count, label, pid) per project group for the
        # gutter labels -- see _assign_swimlanes. `pid` (added 2026-07-18)
        # is what lets _draw_gutter/_gutter_row_hit look up and persist
        # per-row custom names on the actual project Object.
        self._row_of: dict[str, int] = {}
        self._project_labels: list[tuple[int, int, str, str | None]] = []
        # pid -> (row_offset, lanes_used) for the same groups as
        # _project_labels, but keyed for O(1) lookup during a drag instead
        # of a linear scan of _project_labels.
        self._group_range_by_pid: dict[str | None, tuple[int, int]] = {}
        self._total_rows = 0

    def set_objects(self, objects: list[Object]) -> None:
        self._objects = [o for o in objects if o.type == ObjectType.task and o.due_at]
        # Feature (2026-07-18): per-row gutter labels (see _draw_gutter)
        # read/write a project's own `details` dict (to persist custom row
        # names -- see _row_label), so the canvas needs the actual Object,
        # not just its title.
        self._project_objects: dict[str, Object] = {
            o.id: o for o in objects if o.type == ObjectType.project
        }
        self._project_titles = {oid: o.title for oid, o in self._project_objects.items()}
        self._assign_swimlanes()
        self._compute_range()
        self.update()

    def _assign_swimlanes(self) -> None:
        """Group tasks by project (`parent_id`), bin-pack each project's
        tasks into the minimum number of rows needed so none of that
        project's own tasks visually overlap (reusing the calendar's
        interval-packing algorithm -- see core/utils/interval_packing.py),
        and stack the resulting per-project row blocks vertically. Tasks
        from different projects never share a row -- each group gets its
        own contiguous row range. Previously every task was just one flat
        row in whatever order it happened to be in, with no project
        grouping at all. This is what guarantees no two overlapping tasks
        in the same project ever land on the same row, at any zoom --
        the packing itself is zoom-independent (it operates purely on
        each task's start/due dates), so it holds for Day and Week zoom
        identically.
        """
        groups: dict[str | None, list[Object]] = {}
        for obj in self._objects:
            groups.setdefault(obj.parent_id, []).append(obj)

        def group_sort_key(pid: str | None) -> str:
            if pid is None:
                return "￿" + NO_PROJECT_LABEL  # sort last
            return self._project_titles.get(pid, "￾" + pid)

        # Local (within-project) lane from the previous computation, keyed
        # by object id -- passed to pack_intervals as `preferred` so an
        # edit that doesn't actually create a new conflict doesn't bounce
        # the task to a different row. See pack_intervals' docstring.
        #
        # Bug (2026-07-18): naively trusting `preferred` let a task keep a
        # *higher* lane than it actually needed once it was no longer
        # sharing a cluster with whatever it used to overlap -- e.g. two
        # tasks packed into lanes 0/1 while overlapping; drag one apart so
        # they no longer overlap at all, and the second one kept lane 1
        # (its old preference was still technically "free") instead of
        # collapsing back to lane 0, leaving a phantom empty row. Greedy
        # lowest-free-lane packing is provably optimal for interval graphs
        # regardless of processing order, so a first, preference-free pass
        # tells us the true minimum lane count each item's cluster needs;
        # a preferred lane is only honored if it fits within that natural
        # bound, so stability can never inflate a cluster past its optimum.
        #
        # Feature (2026-07-18): manual vertical placement. A task the user
        # explicitly drags to a specific row (mouseReleaseEvent, "move"
        # mode with a vertical component) gets `details["timeline_lane"]`
        # persisted -- unlike the ordinary stability preference above,
        # this is *not* clamped to the natural minimum, since the whole
        # point is letting the user deliberately leave empty rows for
        # visual grouping. It still can't cause an actual overlap: if the
        # requested lane is genuinely occupied by another task active at
        # the same time, pack_intervals' own fallback (this is still just
        # a "preferred lane if free" hint) drops it to the lowest lane
        # that's actually free instead.
        prev_local_lane: dict[str, int] = getattr(self, "_local_lane_of", {})
        next_local_lane: dict[str, int] = {}

        self._row_of = {}
        self._project_labels = []
        self._group_range_by_pid = {}
        row_offset = 0
        for pid in sorted(groups, key=group_sort_key):
            tasks = groups[pid]
            intervals = []
            for o in tasks:
                try:
                    due = date.fromisoformat(o.due_at)
                except (ValueError, TypeError):
                    continue
                try:
                    start_d = date.fromisoformat(o.start_at[:10]) if o.start_at else due
                except (ValueError, TypeError):
                    start_d = due
                # exclusive end (due date's task still occupies that day)
                intervals.append((start_d, due + timedelta(days=1), o.id))

            manual_lane = {
                o.id: o.details["timeline_lane"]
                for o in tasks
                if isinstance(o.details.get("timeline_lane"), int)
            }
            natural = pack_intervals(intervals)
            clamped_preferred = {
                obj_id: prev_local_lane[obj_id]
                for obj_id, (_, natural_lanes) in natural.items()
                if obj_id in prev_local_lane and prev_local_lane[obj_id] < natural_lanes
            }
            clamped_preferred.update(manual_lane)  # manual placement wins, unclamped
            packed = pack_intervals(intervals, preferred=clamped_preferred)
            lanes_used = 1
            for obj_id, (lane, lanes) in packed.items():
                self._row_of[obj_id] = row_offset + lane
                next_local_lane[obj_id] = lane
                lanes_used = max(lanes_used, lanes)

            label = self._project_titles.get(pid, NO_PROJECT_LABEL) if pid else NO_PROJECT_LABEL
            self._project_labels.append((row_offset, lanes_used, label, pid))
            self._group_range_by_pid[pid] = (row_offset, lanes_used)
            row_offset += lanes_used

        self._total_rows = row_offset
        self._local_lane_of = next_local_lane

    def _row_for(self, idx: int) -> int:
        if idx < 0 or idx >= len(self._objects):
            return idx
        return self._row_of.get(self._objects[idx].id, idx)

    # 2026-07-20: calendar-month-aligned window, replacing an earlier
    # rolling today-N..today+M design -- shows the previous, current, and
    # next calendar month. 2026-07-18: this used to also drive a narrower
    # "Day zoom" window (just the current month, at a wider per-day
    # pixel width); Day zoom was removed as a whole mode, so only this
    # one (formerly "Week zoom") window/day_width combination remains.
    # Still extended below to cover any task outside the default window
    # either way.
    _MONTH_SPAN = 1  # 1 month before and 1 month after -- 3 months total

    @staticmethod
    def _month_bounds(base: date, offset_months: int) -> tuple[date, date]:
        """First and last day of the calendar month `offset_months` away
        from base's month (negative = earlier, positive = later),
        handling year rollover."""
        month_index = base.month - 1 + offset_months  # 0-based for divmod
        year = base.year + month_index // 12
        month = month_index % 12 + 1
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        return first, last

    def _compute_range(self) -> None:
        today = date.today()
        self._start, _ = self._month_bounds(today, -self._MONTH_SPAN)
        _, self._end = self._month_bounds(today, self._MONTH_SPAN)
        for obj in self._objects:
            if obj.due_at:
                try:
                    d = date.fromisoformat(obj.due_at)
                    if d < self._start:
                        self._start = d
                    if d > self._end:
                        self._end = d
                except (ValueError, TypeError):
                    pass
            if obj.start_at:
                try:
                    d = date.fromisoformat(obj.start_at[:10])
                    if d < self._start:
                        self._start = d
                    if d > self._end:
                        self._end = d
                except (ValueError, TypeError):
                    pass
        total_days = max((self._end - self._start).days, 14)
        self._total_days = total_days
        self.setMinimumWidth(total_days * self._day_width + self._gutter_width + 20)
        self.setMinimumHeight(self._total_rows * self._row_height + self._header_height + 20)

    def _grid_line_day_indices(self) -> list[int]:
        """Every day offset gets a header label + vertical gridline --
        showing days as the actual interval unit is the whole point of
        this view (week-boundary-only gridlines, and Month/Day zoom, were
        all removed at various points, ending with just this one mode)."""
        return list(range(self._total_days + 1))

    def _week_start_indices(self) -> list[int]:
        """Day offsets where a "Week NN" heading should be drawn: every
        Monday within the visible range, plus day 0 itself if the range's
        first visible day isn't a Monday (so a leading partial week still
        gets labeled instead of showing no heading at all)."""
        indices = [i for i in range(self._total_days + 1) if (self._start + timedelta(days=i)).weekday() == 0]
        if self._total_days >= 0 and self._start.weekday() != 0:
            indices = [0] + indices
        return indices

    # ----- bar geometry helpers -----

    def _bar_rect(self, idx: int) -> QRectF | None:
        if idx < 0 or idx >= len(self._objects):
            return None
        obj = self._objects[idx]
        try:
            due = date.fromisoformat(obj.due_at)
        except (ValueError, TypeError):
            return None
        start = obj.start_at
        try:
            start_d = date.fromisoformat(start[:10]) if start else due
        except (ValueError, TypeError):
            start_d = due

        day_from = max(0, (start_d - self._start).days)
        day_to = min(self._total_days, (due - self._start).days + 1)
        if day_to <= day_from:
            day_to = day_from + 1

        x1 = day_from * self._day_width + self._gutter_width
        x2 = day_to * self._day_width + self._gutter_width
        y = self._header_height + self._row_for(idx) * self._row_height + 6
        # Vertical drag (2026-07-18): the actual row (_row_of) only gets
        # reassigned on release (see mouseReleaseEvent/_assign_swimlanes)
        # -- reassigning it live on every mouse-move would mean re-running
        # the packing algorithm continuously during a drag, fighting the
        # drag itself. Instead, while this bar is the one being dragged in
        # "move" mode, follow the mouse smoothly by offsetting the painted
        # position directly; _drag_y_offset is 0 whenever no drag is in
        # progress, so this is a no-op the rest of the time.
        if idx == self._drag_idx and self._drag_mode == "move":
            y += self._drag_y_offset
        h = self._row_height - 12
        return QRectF(x1, y, max(x2 - x1, 4), h)

    def _hit_test(self, pos) -> tuple[int, str | None]:
        """Return (idx, mode) or (-1, None)."""
        for idx in range(len(self._objects) - 1, -1, -1):
            rect = self._bar_rect(idx)
            if rect is None:
                continue
            if not rect.contains(pos):
                continue
            # Defensive: a bar narrower than both handle zones combined
            # (HANDLE_WIDTH*2) isn't reachable through the current Day
            # (80px/day) or Week (24px/day) zoom widths, but was in an
            # earlier Month zoom that's since been removed, and this
            # guards against it recurring if day_width ever shrinks
            # again. Checking "left
            # handle" unconditionally first meant every click anywhere on
            # such a bar -- including right at its right edge -- always
            # resolved to resize_left, since pos.x() - rect.x() is small
            # for the *entire* bar when the bar itself is small. That
            # silently broke right-edge resizing specifically on
            # single-day/no-start tasks (resize_left's own guard rejects a
            # start date past the due date, a no-op) while giving no
            # visible error. Below the combined handle width there's no
            # room for a neutral "move" zone anyway, so split the bar at
            # its midpoint instead: whichever half was actually clicked
            # wins, so a right-edge click is never misread as the left
            # handle just because the bar is short.
            if rect.width() <= HANDLE_WIDTH * 2:
                if pos.x() < rect.center().x():
                    return (idx, "resize_left")
                return (idx, "resize_right")
            # Check left handle
            if pos.x() - rect.x() <= HANDLE_WIDTH:
                return (idx, "resize_left")
            # Check right handle
            if rect.right() - pos.x() <= HANDLE_WIDTH:
                return (idx, "resize_right")
            return (idx, "move")
        return (-1, None)

    def _x_to_date(self, x: float) -> date:
        day_float = (x - self._gutter_width) / self._day_width
        return self._start + timedelta(days=int(round(day_float)))

    def _x_to_day_index(self, x: float) -> int:
        """Floor-based day-*column* index under pixel `x` -- which grid
        cell (not nearest date boundary) contains this x, clamped to a
        valid index. Bug (2026-07-18): click-create selection used
        `_x_to_date` (round-to-nearest-day) for this, which snaps to
        whichever day *boundary* is closer rather than the day *column*
        actually under the pointer -- roughly the left half of a column
        rounds down and the right half rounds up, so the highlighted cell
        didn't line up with the column the mouse was actually over,
        making the selection box look shifted/oddly-shaped relative to
        the grid rather than cleanly covering whole cells."""
        idx = int((x - self._gutter_width) // self._day_width)
        return max(0, min(self._total_days - 1, idx))

    def _grid_row_hit(self, pos) -> tuple[str | None, int, int] | None:
        """Return (pid, local_idx, global_row) for the swimlane row under
        `pos`, but only within the date-grid area (to the right of the
        gutter) -- used by mousePressEvent to start a click-create drag on
        empty space. None if `pos` isn't over a known row of the grid at
        all (including the gutter itself, the header, or space below the
        last project's block)."""
        if pos.x() <= self._gutter_width or pos.y() < self._header_height:
            return None
        row_idx = int((pos.y() - self._header_height) // self._row_height)
        for row_start, row_count, _label, pid in self._project_labels:
            if row_start <= row_idx < row_start + row_count:
                return (pid, row_idx - row_start, row_idx)
        return None

    # ----- mouse interaction -----

    def mousePressEvent(self, event) -> None:
        if not event or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()

        # Column resize (2026-07-18): a narrow hot zone straddling the
        # gutter/grid boundary, checked first since it's a thin target
        # that would otherwise be shadowed by bar hit-testing or the
        # click-create fallback below.
        if abs(pos.x() - self._gutter_width) <= GUTTER_RESIZE_HOT_ZONE:
            self._resizing_gutter = True
            self._gutter_resize_start_x = pos.x()
            self._gutter_width_at_press = self._gutter_width
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            event.accept()
            return

        idx, mode = self._hit_test(pos)
        if idx < 0 or mode is None:
            # Click-create (2026-07-18): pressing on empty grid space --
            # not a bar, not the gutter, not the resize hot zone -- stakes
            # out the start of a new task's date range. See
            # mouseMoveEvent/_finish_create_drag for the rest of the
            # gesture; a plain click with no drag at all still creates a
            # 1-day task, since _create_start_day == _create_end_day then.
            row_hit = self._grid_row_hit(pos)
            if row_hit is not None:
                pid, local_idx, global_row = row_hit
                self._creating = True
                self._create_pid = pid
                self._create_local_idx = local_idx
                self._create_row = global_row
                self._create_start_day = self._start + timedelta(days=self._x_to_day_index(pos.x()))
                self._create_end_day = self._create_start_day
                event.accept()
            return
        self._drag_mode = mode
        self._drag_idx = idx
        self._drag_start_x = event.position().x()
        self._drag_start_y = event.position().y()
        self._drag_y_offset = 0.0
        obj = self._objects[idx]
        if mode == "move":
            # Capture the row bookkeeping needed to turn a vertical drag
            # into a target row on release -- see mouseMoveEvent /
            # mouseReleaseEvent and _assign_swimlanes' manual placement
            # handling.
            group_offset, group_lanes = self._group_range_by_pid.get(obj.parent_id, (0, 1))
            self._drag_orig_local_lane = self._row_for(idx) - group_offset
            self._drag_group_lanes = group_lanes
        try:
            start_d = date.fromisoformat(obj.start_at[:10]) if obj.start_at else date.fromisoformat(obj.due_at)
        except (ValueError, TypeError):
            start_d = date.fromisoformat(obj.due_at)
        # Bug (2026-07-20): a task with no explicit start_at renders using
        # due_at as a stand-in start (see _bar_rect/here, both fall back
        # the same way). Resizing from the *right* only ever wrote
        # due_at -- so on every repaint, the still-unset start_at kept
        # re-resolving to that same (just-moved) due_at, and both edges of
        # the bar walked forward together. Visually indistinguishable from
        # a move, even though only due_at was being written. Resizing from
        # the *left* never showed this because that path writes start_at
        # explicitly on the very first drag, which permanently breaks the
        # fallback from then on -- that's why "left works, right doesn't,
        # only for single-day/no-start tasks" was the exact symptom.
        # Fixed by freezing start_at to its resolved value the moment any
        # resize drag begins, whichever edge is grabbed, so due_at can
        # move independently from here on.
        if mode in ("resize_left", "resize_right") and not obj.start_at:
            obj.start_at = start_d.isoformat()
        self._drag_orig = (start_d, date.fromisoformat(obj.due_at))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not event:
            return
        if self._resizing_gutter:
            dx = event.position().x() - self._gutter_resize_start_x
            # Keep this an int (not a raw float pixel offset) -- geometry
            # elsewhere (_bar_rect, _draw_header/_draw_grid, ...) mixes it
            # into drawLine/int-based coordinates that don't all tolerate
            # a float transparently.
            self._gutter_width = int(
                max(MIN_GUTTER_WIDTH, min(MAX_GUTTER_WIDTH, self._gutter_width_at_press + dx))
            )
            self._compute_range()
            self.update()
            return
        if self._creating:
            self._create_end_day = self._start + timedelta(
                days=self._x_to_day_index(event.position().x())
            )
            self.update()
            return
        if self._drag_mode and self._drag_idx >= 0 and self._drag_orig:
            dx = event.position().x() - self._drag_start_x
            delta_days = int(round(dx / self._day_width))

            # Vertical drag (2026-07-18): tracked independently of the
            # horizontal delta_days early-return below, purely for smooth
            # per-pixel visual feedback (_bar_rect offsets the dragged
            # bar's paint position by this while a "move" drag is live).
            # The actual row reassignment only happens on release -- see
            # mouseReleaseEvent -- so a vertical-only drag (no date
            # change at all) still needs this to repaint, hence it's
            # computed before the `if delta_days == 0: return` guard,
            # which previously would have swallowed a purely-vertical
            # mouse move with no visible effect.
            if self._drag_mode == "move":
                self._drag_y_offset = event.position().y() - self._drag_start_y

            if delta_days == 0:
                self.update()
                return
            orig_start, orig_due = self._drag_orig
            min_start = self._start
            max_due = self._start + timedelta(days=self._total_days)

            if self._drag_mode == "move":
                new_start = max(min_start, orig_start + timedelta(days=delta_days))
                new_due = new_start + (orig_due - orig_start)
                if new_due > max_due:
                    new_due = max_due
                    new_start = new_due - (orig_due - orig_start)
                self._objects[self._drag_idx].start_at = new_start.isoformat()
                self._objects[self._drag_idx].due_at = new_due.isoformat()
            elif self._drag_mode == "resize_left":
                new_start = max(min_start, orig_start + timedelta(days=delta_days))
                if new_start < orig_due:
                    self._objects[self._drag_idx].start_at = new_start.isoformat()
            elif self._drag_mode == "resize_right":
                new_due = min(max_due, orig_due + timedelta(days=delta_days))
                if new_due > orig_start:
                    self._objects[self._drag_idx].due_at = new_due.isoformat()
            self.update()
        else:
            pos = event.position()
            if abs(pos.x() - self._gutter_width) <= GUTTER_RESIZE_HOT_ZONE:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                return
            idx, mode = self._hit_test(pos)
            if mode == "resize_left" or mode == "resize_right":
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif mode == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif self._grid_row_hit(pos) is not None:
                # Empty, creatable grid cell (2026-07-18) -- a distinct
                # cursor hints a click-drag here does something, rather
                # than looking identical to dead space.
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing_gutter:
            self._resizing_gutter = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
            return
        if self._creating:
            self._finish_create_drag()
            return
        if self._drag_mode and self._drag_idx >= 0 and self._drag_orig:
            obj = self._objects[self._drag_idx]
            # Vertical drag (2026-07-18): translate the accumulated pixel
            # offset into a target row within this task's own project
            # block, and persist it as a manual placement (see
            # _assign_swimlanes) -- but only if the user actually moved
            # vertically. A plain horizontal reschedule (the common case)
            # must not implicitly pin a row the user never touched, or
            # every ordinary drag would start silently freezing rows that
            # were previously free to auto-compact.
            if self._drag_mode == "move":
                delta_rows = round(self._drag_y_offset / self._row_height)
                if delta_rows != 0:
                    target_local = self._drag_orig_local_lane + delta_rows
                    # Clamp rather than leaving unbounded: a stray huge
                    # drag shouldn't be able to pin a task hundreds of
                    # rows away by accident. A handful of rows past the
                    # group's current size is enough headroom to
                    # deliberately open up new empty rows for spacing.
                    target_local = max(0, min(target_local, self._drag_group_lanes + 4))
                    obj.details = dict(obj.details)
                    obj.details["timeline_lane"] = target_local
            # Persist the drag -- previously only the in-memory Object was
            # mutated (above, in mouseMoveEvent) and this signal just
            # triggered a re-render; nothing was written to disk, so the
            # reschedule/resize reverted on reindex/restart (same bug as
            # the calendar week/day grid -- see STRESS_TEST_2026-07-17.md).
            FileRepository().write_object(obj)
            # Bug (2026-07-18): row/swimlane assignment (_assign_swimlanes)
            # only ran inside set_objects(). mouseMoveEvent mutates the
            # dragged task's start/due dates in place and just repaints, so
            # once a drag ended, the task kept whatever row it was packed
            # into *before* the move -- even after it no longer overlapped
            # anything in that row. Recompute the packing (and the date
            # range, since a drag can push a task outside the previous
            # window) now that the dates are final, so rows merge back down
            # immediately instead of only on the next full set_objects().
            self._assign_swimlanes()
            self._compute_range()
            self.task_rescheduled.emit(obj.id, obj.start_at or "", obj.due_at)
        self._drag_mode = None
        self._drag_idx = -1
        self._drag_orig = None
        self._drag_y_offset = 0.0
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def _finish_create_drag(self) -> None:
        """Turn a completed click-create drag (see mousePressEvent/
        mouseMoveEvent) into an actual new task, written to disk in the
        exact row and date range the user selected. Emits task_created
        rather than appending directly to self._objects -- the app is
        responsible for persisting new objects into its own list and
        round-tripping back through set_objects, same as every other
        creation path (quick-add, the calendar's "+ New event", etc.)."""
        start_d = min(self._create_start_day, self._create_end_day)
        due_d = max(self._create_start_day, self._create_end_day)
        now_iso = datetime.now(timezone.utc).isoformat()
        new_obj = Object(
            id=str(uuid.uuid4()),
            type=ObjectType.task,
            title="New task",
            status="active",
            start_at=start_d.isoformat(),
            due_at=due_d.isoformat(),
            parent_id=self._create_pid,
            created_at=now_iso,
            updated_at=now_iso,
        )
        # Land in the exact row the user dragged across, not wherever
        # auto-packing would otherwise put it -- same manual-placement
        # mechanism as a vertical bar drag (see _assign_swimlanes). Row 0
        # doubles as both the project's header label *and* a real task
        # row, so this applies uniformly regardless of which row index
        # was clicked; pack_intervals' own "preferred if free, else
        # lowest free" fallback still guarantees no actual overlap if
        # something else already occupies that row at these dates.
        new_obj.details = dict(new_obj.details)
        new_obj.details["timeline_lane"] = self._create_local_idx
        FileRepository().write_object(new_obj)

        self._creating = False
        self._create_pid = None
        self._create_local_idx = 0
        self._create_row = -1
        self._create_start_day = None
        self._create_end_day = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.task_created.emit(new_obj)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        # Feature (2026-07-18): double-clicking any gutter label opens a
        # rename prompt -- see _rename_row/_set_row_name/_row_label. This
        # now includes row 0 (previously off-limits): the project's own
        # name row can get a custom *display* label too, distinct from
        # (and without touching) the project's actual title everywhere
        # else in the app -- _set_row_name only ever writes to the
        # project's `details`, never `obj.title`. Checked before the bar
        # hit-test below since the gutter sits to the left of where any
        # bar can ever be (_hit_test never returns a match there anyway,
        # but this also short-circuits before opening a modal dialog on
        # top of an in-progress bar edit).
        gutter_hit = self._gutter_row_hit(event.position())
        if gutter_hit is not None:
            pid, local_idx = gutter_hit
            if pid is not None:
                self._rename_row(pid, local_idx)
            return
        idx, mode = self._hit_test(event.pos())
        if idx >= 0:
            self.context_action.emit(self._objects[idx].id, "edit")
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        idx, mode = self._hit_test(event.pos())
        if idx < 0:
            return
        obj = self._objects[idx]
        menu = QMenu(self)
        menu.setProperty("class", "object-context-menu")

        open_action = QAction("   Open", self)
        open_action.triggered.connect(lambda: self.context_action.emit(obj.id, "edit"))
        menu.addAction(open_action)

        dup_action = QAction("   Duplicate", self)
        dup_action.triggered.connect(lambda: self.context_action.emit(obj.id, "duplicate"))
        menu.addAction(dup_action)

        menu.addSeparator()

        up_action = QAction("   Set Status", self)
        status_menu = QMenu("Set Status", self)
        for s in ("active", "in_progress", "waiting", "done"):
            sa = QAction(s.replace("_", " ").title(), self)
            sa.triggered.connect(lambda checked, v=s: self.context_action.emit(obj.id, f"status:{v}"))
            status_menu.addAction(sa)
        menu.addMenu(status_menu)

        delete_action = QAction("   Delete", self)
        delete_action.triggered.connect(lambda: self.context_action.emit(obj.id, "delete"))
        menu.addAction(delete_action)

        menu.exec(event.globalPos())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._draw_header(p)
        self._draw_grid(p)
        self._draw_gutter(p)
        self._draw_bars(p)
        self._draw_create_selection(p)
        p.end()

    def _draw_header(self, painter: QPainter) -> None:
        # 2026-07-18: this used to branch on self._zoom ("day" vs.
        # everything else); Day zoom was removed as a whole mode, so only
        # the two-row "Week NN" heading + per-day number layout below
        # remains -- see the module docstring.
        #
        # A two-row header: row 1 is a "Week NN" heading, drawn once per
        # week (spanning that whole week's width, not per-day) so it
        # never fights for space with day labels. Row 2 is a bare day
        # number per day.
        #
        # 2026-07-20 fix: previously this was a single row where a
        # Monday's label used "%b %d" (e.g. "Jul 06", ~6 characters)
        # squeezed into a single 24px-wide day column -- the text
        # overflowed past its own column and visually overlapped the
        # following days' bare-number labels. Splitting the week
        # context into its own dedicated row above removes the need
        # for any per-day label to carry the month at all, so every
        # day's row-2 label is a short, fixed-width "%d" that always
        # fits within its own 24px column, and row 1's wider "Week
        # NN" text has the entire week's ~168px to breathe in instead
        # of fighting a single day's 24px.
        # Clip each "Week NN" label to the width actually available
        # before the *next* label starts, instead of drawing at a
        # bare (x, y) point with no boundary. A leading partial week
        # (when the visible range doesn't start on a Monday) can be
        # only a couple of days wide -- narrower than "Week NN"
        # itself -- and an unclipped label bled into the following
        # week's label with no gap between them. Qt's rect-based
        # drawText clips to the rect by default (no TextDontClip
        # flag), so a too-narrow slot now just truncates instead of
        # overlapping.
        font = QFont("IBM Plex Mono", 8)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#666"), 1))
        week_indices = self._week_start_indices()
        for pos, i in enumerate(week_indices):
            d = self._start + timedelta(days=i)
            x = i * self._day_width + self._gutter_width
            wk = d.isocalendar()[1]
            next_x = (
                week_indices[pos + 1] * self._day_width + self._gutter_width
                if pos + 1 < len(week_indices)
                else self._total_days * self._day_width + self._gutter_width
            )
            painter.drawText(
                QRectF(x + 2, 2, max(next_x - x - 4, 0), 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"Week {wk}",
            )
        painter.setPen(QPen(QColor("#444"), 0.5))
        painter.drawLine(int(self._gutter_width), 20, self.width(), 20)
        painter.setPen(QPen(QColor("#666"), 1))
        for i in self._grid_line_day_indices():
            d = self._start + timedelta(days=i)
            x = i * self._day_width + self._gutter_width
            painter.drawText(x + 2, 32, d.strftime("%d"))

    def _draw_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#333"), 0.5))
        for i in range(self._total_rows + 1):
            y = self._header_height + i * self._row_height
            painter.drawLine(0, y, self.width(), y)
        for i in self._grid_line_day_indices():
            x = i * self._day_width + self._gutter_width
            painter.drawLine(x, self._header_height, x, self.height())
        # Separator between the project-label gutter and the day columns
        # -- brighter while being actively dragged, as feedback that the
        # resize is "grabbed" (2026-07-18, see mousePressEvent).
        sep_color = QColor("#8ab4ff") if self._resizing_gutter else QColor("#555")
        painter.setPen(QPen(sep_color, 2 if self._resizing_gutter else 1))
        painter.drawLine(int(self._gutter_width), 0, int(self._gutter_width), self.height())

    def _default_row_label(self, pid: str | None, local_idx: int) -> str:
        """The label a row would have with no custom override: the
        project's own title (or "(No project)") for row 0, "Row N" for
        every row after it. Used both as _row_label's fallback and as the
        "did the user just type the default back in" check in
        _set_row_name."""
        if local_idx == 0:
            return self._project_titles.get(pid, NO_PROJECT_LABEL) if pid else NO_PROJECT_LABEL
        return f"Row {local_idx}"

    def _row_label(self, pid: str | None, local_idx: int) -> str:
        """The label for the `local_idx`-th row of a project's swimlane
        block, honoring any custom override in
        `details["timeline_row_names"]` -- see _set_row_name. This
        includes row 0 (2026-07-18): the project's *display* name in this
        gutter can now be overridden independently of the project's
        actual title, same mechanism as any other row.
        """
        default = self._default_row_label(pid, local_idx)
        obj = self._project_objects.get(pid) if pid else None
        if obj is None:
            return default
        row_names = obj.details.get("timeline_row_names")
        if isinstance(row_names, dict):
            custom = row_names.get(str(local_idx))
            if custom:
                return custom
        return default

    def _draw_gutter(self, painter: QPainter) -> None:
        """Feature (2026-07-18): previously one label per project,
        vertically centered across the whole swimlane block -- which told
        you a block of rows belonged to some project, but not which row
        was which once a project had more than one row. Now the project
        name is drawn only in the block's first row, and every row below
        it (until the next project's block starts) gets its own "Row N"
        label -- both customizable via _set_row_name/_rename_row
        (double-click any gutter label, including the project's own).
        Text is elided (not just hard-truncated at a fixed character
        count) since the column itself is now user-resizable -- a fixed
        truncation length would either waste a wide column or overflow a
        narrow one."""
        for row_start, row_count, label, pid in self._project_labels:
            for local_idx in range(row_count):
                y = self._header_height + (row_start + local_idx) * self._row_height
                is_header = local_idx == 0
                font = QFont("IBM Plex Mono", 8)
                font.setBold(is_header)
                painter.setFont(font)
                painter.setPen(QPen(QColor("#ccc") if is_header else QColor("#888")))
                text = painter.fontMetrics().elidedText(
                    self._row_label(pid, local_idx), Qt.TextElideMode.ElideRight, self._gutter_width - 8
                )
                painter.drawText(
                    QRectF(4, y, self._gutter_width - 8, self._row_height),
                    Qt.AlignmentFlag.AlignVCenter,
                    text,
                )

    def _gutter_row_hit(self, pos) -> tuple[str | None, int] | None:
        """Return (pid, local_idx) for the swimlane row under `pos`, or
        None if `pos` isn't over the gutter at all."""
        if pos.x() > self._gutter_width or pos.y() < self._header_height:
            return None
        row_idx = int((pos.y() - self._header_height) // self._row_height)
        for row_start, row_count, _label, pid in self._project_labels:
            if row_start <= row_idx < row_start + row_count:
                return (pid, row_idx - row_start)
        return None

    def _set_row_name(self, pid: str | None, local_idx: int, text: str) -> None:
        """Persist a custom name for row `local_idx` of project `pid`'s
        swimlane block -- including row 0, the project's own display name
        in this gutter (2026-07-18; previously off-limits). This never
        touches the project's actual `title`, only its `details`, so
        renaming a row here doesn't rename the project anywhere else in
        the app. An empty string, or the default text typed back in,
        clears the override instead of storing a redundant copy of it."""
        if pid is None:
            return
        obj = self._project_objects.get(pid)
        if obj is None:
            return
        row_names = dict(obj.details.get("timeline_row_names") or {})
        text = text.strip()
        default = self._default_row_label(pid, local_idx)
        if not text or text == default:
            row_names.pop(str(local_idx), None)
        else:
            row_names[str(local_idx)] = text
        obj.details = dict(obj.details)
        if row_names:
            obj.details["timeline_row_names"] = row_names
        else:
            obj.details.pop("timeline_row_names", None)
        FileRepository().write_object(obj)
        self.update()

    def _rename_row(self, pid: str, local_idx: int) -> None:
        current = self._row_label(pid, local_idx)
        title = "Rename project display name" if local_idx == 0 else "Rename row"
        text, ok = QInputDialog.getText(self, title, "Display label:", text=current)
        if ok:
            self._set_row_name(pid, local_idx, text)

    def _draw_bars(self, painter: QPainter) -> None:
        for idx, obj in enumerate(self._objects):
            # Reuse _bar_rect (rather than recomputing x1/x2/y/h separately,
            # as this used to) so the live vertical-drag offset applied
            # there for the dragged bar (see _bar_rect) is actually
            # reflected on screen instead of only affecting hit-testing.
            rect = self._bar_rect(idx)
            if rect is None:
                continue
            x1 = rect.x()
            y = rect.y()
            h = rect.height()

            color = QColor(BAR_COLORS[idx % len(BAR_COLORS)])
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 3, 3)

            # Highlight dragged bar
            if idx == self._drag_idx:
                hl = QPen(QColor("#fff"), 2)
                painter.setPen(hl)
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 3, 3)
                painter.setPen(Qt.PenStyle.NoPen)

            # Progress fill
            if obj.progress:
                fill_w = rect.width() * obj.progress
                fill = QColor(color)
                fill.setAlpha(80)
                painter.setBrush(fill)
                painter.drawRoundedRect(QRectF(x1, y, fill_w, h), 3, 3)

            # Title
            font = QFont("IBM Plex Mono", 8)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#fff")))
            painter.drawText(QRectF(x1 + 4, y, rect.width() - 8, h), Qt.AlignmentFlag.AlignVCenter, obj.title)

            # Resize-handle grip marks: a purely visual affordance so a bar
            # wide enough to actually resize shows *where* to grab it,
            # rather than relying on the cursor shape alone (which only
            # appears after the pointer is already over the hit target).
            if rect.width() >= HANDLE_WIDTH * 3:
                grip_pen = QPen(QColor(255, 255, 255, 140), 1.5)
                painter.setPen(grip_pen)
                gx1 = x1 + HANDLE_WIDTH / 2
                gx2 = x1 + rect.width() - HANDLE_WIDTH / 2
                gy1 = y + h * 0.3
                gy2 = y + h * 0.7
                painter.drawLine(QRectF(gx1, gy1, 0, 0).topLeft(), QRectF(gx1, gy2, 0, 0).topLeft())
                painter.drawLine(QRectF(gx2, gy1, 0, 0).topLeft(), QRectF(gx2, gy2, 0, 0).topLeft())
                painter.setPen(Qt.PenStyle.NoPen)

    def _draw_create_selection(self, painter: QPainter) -> None:
        """Feature (2026-07-18): live preview of an in-progress
        click-create drag (see mousePressEvent/mouseMoveEvent) -- a
        translucent highlight over the whole grid cell(s) selected so
        far, painted on top of everything else so it's never hidden
        behind an existing bar.

        Bug (2026-07-18): the first version of this reused the *bar*
        look -- inset a few px from the row's edges with rounded corners,
        like a task bar being previewed. That's misleading here: this
        isn't previewing a bar's shape, it's highlighting which grid
        cell(s) are selected, so it should look like a spreadsheet range
        selection -- a sharp-cornered rectangle that exactly covers the
        selected cells edge-to-edge, flush with the surrounding
        gridlines, not a smaller shape floating inside them. Also
        switched _create_start_day/_create_end_day (see
        mousePressEvent/mouseMoveEvent) from _x_to_date's round-to-
        nearest-day to _x_to_day_index's floor-based day-*column* lookup,
        so the highlighted cell(s) actually line up with the column
        under the pointer instead of sometimes bleeding into the
        neighboring one."""
        if not self._creating or self._create_start_day is None or self._create_end_day is None:
            return
        start_d = min(self._create_start_day, self._create_end_day)
        due_d = max(self._create_start_day, self._create_end_day)
        day_from = max(0, (start_d - self._start).days)
        day_to = min(self._total_days - 1, (due_d - self._start).days)  # inclusive last day column
        x1 = day_from * self._day_width + self._gutter_width
        x2 = (day_to + 1) * self._day_width + self._gutter_width
        y = self._header_height + self._create_row * self._row_height
        rect = QRectF(x1, y, x2 - x1, self._row_height)

        fill = QColor("#7c3aed")
        fill.setAlpha(70)
        painter.setBrush(fill)
        painter.setPen(QPen(QColor("#c4b5fd"), 2))
        painter.drawRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)


class TimelineView(QWidget):
    """Gantt-like timeline. Week zoom only (2026-07-18: Day zoom removed
    as a whole mode -- see the module docstring); with only one mode left
    there's nothing left to toggle, so the zoom button row that used to
    sit above the canvas is gone too.

    2026-07-20: this is itself just a thin `QScrollArea` wrapper around
    `TimelineCanvas` -- previously the (now-removed) zoom toolbar lived
    *inside* the scrolled widget alongside the canvas, so scrolling right
    on a wide canvas scrolled the toolbar off-screen with it. Restructured
    so only the canvas is inside the QScrollArea.
    """

    task_rescheduled = Signal(str, str, str)  # object_id, new_start_at, new_due_at
    context_action = Signal(str, str)  # object_id, action
    task_created = Signal(Object)  # see TimelineCanvas.task_created

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "tasks-view")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll, 1)

        self._canvas = TimelineCanvas()
        self._canvas.task_rescheduled.connect(self.task_rescheduled)
        self._canvas.context_action.connect(self.context_action)
        self._canvas.task_created.connect(self.task_created)
        self._scroll.setWidget(self._canvas)

    def set_objects(self, objects: list[Object]) -> None:
        self._canvas.set_objects(objects)
