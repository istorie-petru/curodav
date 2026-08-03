"""Calendar module (REWORK_PLAN §7.5).

Month/week/day/agenda views. Month grid with event chips and task indicators.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import QDate, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType
from ...core.recurrence import expand_recurring_objects
from ...core.utils.interval_packing import pack_intervals

HOUR_HEIGHT = 56
ALL_DAY_HEIGHT = 28
MIN_EVENT_HEIGHT = 16
SNAP_MINUTES = 15


# Side-by-side layout for overlapping events (2026-07-19) -- the actual
# packing algorithm now lives in core/utils/interval_packing.py, shared
# with the Tasks timeline's per-project row-packing. Re-exported under the
# old name here since it's still what this module's own code (and tests)
# call it.
_pack_overlaps = pack_intervals


class _ChipLabel(QLabel):
    """A QLabel that reports left-clicks instead of ignoring them.

    Used for month-view event chips and the "+N more" overflow label, both
    of which previously had no click handling at all (plain QLabel). Emits
    and accepts the event so it doesn't also propagate to the parent
    `_DayCell` as a day-click.
    """

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class _DayCell(QFrame):
    """A month-view day cell that reports clicks on its empty area.

    Chips inside it are `_ChipLabel`s and accept their own clicks first, so
    only clicks that land outside any chip reach here.
    """

    clicked = Signal(object)  # emits the cell's `date`

    def __init__(self, day_date: date, parent=None) -> None:
        super().__init__(parent)
        self._date = day_date

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._date)
            event.accept()
        else:
            super().mousePressEvent(event)


class _HourCell(QFrame):
    """A week/day-grid hour cell that reports clicks on its empty area.

    `_EventBlock`s are separate overlay widgets stacked on top, so a click
    on an occupied slot hits the block instead of bubbling here.
    """

    clicked = Signal(object)  # emits the slot's `datetime`

    def __init__(self, slot_start: datetime, parent=None) -> None:
        super().__init__(parent)
        self._slot_start = slot_start

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._slot_start)
            event.accept()
        else:
            super().mousePressEvent(event)


class MonthGrid(QWidget):
    """Traditional month calendar grid.

    Days show event chips and task indicators. Click a day to see its agenda.
    """

    day_clicked = Signal(object)  # emits `date` of the clicked cell
    object_clicked = Signal(str)  # emits object id of a clicked chip

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "month-grid")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self._header_layout = QHBoxLayout()
        self._prev_btn = QPushButton("<")
        self._prev_btn.setProperty("class", "cal-nav-btn")
        self._prev_btn.clicked.connect(self._prev_month)
        self._header_layout.addWidget(self._prev_btn)

        self._month_label = QLabel()
        self._month_label.setProperty("class", "cal-month-label")
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_layout.addWidget(self._month_label, 1)

        self._next_btn = QPushButton(">")
        self._next_btn.setProperty("class", "cal-nav-btn")
        self._next_btn.clicked.connect(self._next_month)
        self._header_layout.addWidget(self._next_btn)
        self._layout.addLayout(self._header_layout)

        self._grid = QGridLayout()
        self._grid.setSpacing(2)
        self._layout.addLayout(self._grid)

        self._current_year = date.today().year
        self._current_month = date.today().month
        self._objects: list[Object] = []

        self._rebuild()

    def set_objects(self, objects: list[Object]) -> None:
        self._objects = objects
        self._rebuild()

    def _prev_month(self) -> None:
        if self._current_month == 1:
            self._current_month = 12
            self._current_year -= 1
        else:
            self._current_month -= 1
        self._rebuild()

    def _next_month(self) -> None:
        if self._current_month == 12:
            self._current_month = 1
            self._current_year += 1
        else:
            self._current_month += 1
        self._rebuild()

    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        month_name = calendar.month_name[self._current_month]
        self._month_label.setText(f"{month_name} {self._current_year}")

        days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, day_name in enumerate(days_of_week):
            label = QLabel(day_name)
            label.setProperty("class", "cal-dow")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(label, 0, i)

        _, num_days = calendar.monthrange(self._current_year, self._current_month)
        first_weekday = calendar.monthrange(self._current_year, self._current_month)[0]
        first_weekday = (first_weekday + 1) % 7

        # Expand recurring tasks/events into per-occurrence copies for the
        # visible month before matching them to day cells below -- without
        # this, a recurring object only ever shows on its own anchor date
        # (see core/recurrence.py).
        month_start = date(self._current_year, self._current_month, 1)
        month_end = date(self._current_year, self._current_month, num_days)
        visible_objects = expand_recurring_objects(self._objects, month_start, month_end)

        today = date.today()
        row = 1
        col = first_weekday
        for day in range(1, num_days + 1):
            day_date = date(self._current_year, self._current_month, day)
            cell = self._create_day_cell(day, day_date)
            if day_date == today:
                cell.setProperty("class", "cal-day-today")
            elif day_date < today:
                cell.setProperty("class", "cal-day-past")
            else:
                cell.setProperty("class", "cal-day")

            day_objs = [
                o
                for o in visible_objects
                if o.due_at == day_date.isoformat()
                and ObjectStatus.is_open(o.status)
            ]
            if day_objs:
                cell_layout = cell.layout() or QVBoxLayout(cell)
                for o in day_objs[:3]:
                    short = o.title[:18] + "…" if len(o.title) > 18 else o.title
                    chip = _ChipLabel(short)
                    chip.setProperty("class", "cal-event-chip")
                    chip.setToolTip(o.title)
                    chip.clicked.connect(lambda oid=o.id: self.object_clicked.emit(oid))
                    cell_layout.addWidget(chip)
                if len(day_objs) > 3:
                    overflow = day_objs[3:]
                    more = _ChipLabel(f"+{len(overflow)} more")
                    more.setProperty("class", "cal-dow")
                    more.clicked.connect(lambda objs=overflow: self._show_overflow_menu(objs))
                    cell_layout.addWidget(more)

            self._grid.addWidget(cell, row, col)
            col += 1
            if col > 6:
                col = 0
                row += 1

    def _create_day_cell(self, day: int, day_date: date) -> _DayCell:
        cell = _DayCell(day_date)
        cell.setProperty("class", "cal-day")
        cell.clicked.connect(self.day_clicked.emit)
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(4, 4, 4, 4)
        day_label = QLabel(str(day))
        day_label.setProperty("class", "cal-day-number")
        layout.addWidget(day_label)
        layout.addStretch(1)
        return cell

    def _show_overflow_menu(self, objs: list[Object]) -> None:
        """Popup listing a day's overflow events past the first 3 chips.

        Click-through-to-open on each entry, analogous to Google Calendar's
        "+N more" popover -- previously this was a static, unclickable label.
        """
        menu = QMenu(self)
        menu.setProperty("class", "object-context-menu")
        for o in objs:
            action = QAction(o.title, self)
            action.triggered.connect(lambda checked=False, oid=o.id: self.object_clicked.emit(oid))
            menu.addAction(action)
        menu.exec(QCursor.pos())


class _EventBlock(QFrame):
    """A positioned event block in the time grid (week/day views).

    - Drag the body to move (reschedule) the event.
    - Drag the bottom 8px edge to resize (change duration).
    - Right-click for context menu.
    """

    time_changed = Signal(str, str, str)  # object_id, new_start_at, new_end_at
    context_action = Signal(str, str)  # object_id, action

    RESIZE_MARGIN = 8

    def __init__(self, obj: Object, start_at: str, end_at: str, parent=None):
        super().__init__(parent)
        self._obj = obj
        self._start_at = start_at
        self._end_at = end_at
        self.setProperty("class", "cal-event-block")
        self.setMouseTracking(True)

        label = QLabel(obj.title[:30], self)
        label.setProperty("class", "cal-event-block-title")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setContentsMargins(4, 2, 4, 2)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(label)
        lay.addStretch()

        self._mode: str | None = None  # None | "move" | "resize"
        self._drag_start_y = 0
        self._orig_geometry = None

    def _is_near_bottom(self, pos_y: float) -> bool:
        return self.height() - pos_y <= self.RESIZE_MARGIN

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if not event:
            return
        if self._mode == "move" and self._orig_geometry:
            dy = event.position().y() - self._drag_start_y
            if abs(dy) >= 4:
                delta_minutes = round(dy / HOUR_HEIGHT * 60 / SNAP_MINUTES) * SNAP_MINUTES
                new_top = self._orig_geometry.top() + int(delta_minutes / 60 * HOUR_HEIGHT)
                new_top = max(0, new_top)
                self.move(self.x(), new_top)
        elif self._mode == "resize" and self._orig_geometry:
            dy = event.position().y() - self._drag_start_y
            if abs(dy) >= 4:
                # Snap live, in the same fixed SNAP_MINUTES increments the
                # move branch above (and mouseReleaseEvent's commit) use --
                # previously this branch grew the block by the raw pixel
                # delta and only snapped once, on release, so the live
                # resize looked continuous even though the persisted value
                # was quantized. Now what you see while dragging is what
                # gets saved.
                delta_minutes = round(dy / HOUR_HEIGHT * 60 / SNAP_MINUTES) * SNAP_MINUTES
                new_height = self._orig_geometry.height() + int(delta_minutes / 60 * HOUR_HEIGHT)
                min_h = int(SNAP_MINUTES / 60 * HOUR_HEIGHT)
                if new_height >= min_h:
                    self.setFixedHeight(new_height)
        else:
            if self._is_near_bottom(event.position().y()):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_y = event.position().y()
            self._orig_geometry = self.geometry()
            if self._is_near_bottom(event.position().y()):
                self._mode = "resize"
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            else:
                self._mode = "move"
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if not self._mode:
            return

        if self._mode == "move":
            dy = self.y() - self._orig_geometry.top()
            delta_minutes = round(dy / HOUR_HEIGHT * 60 / SNAP_MINUTES) * SNAP_MINUTES
            if delta_minutes != 0:
                old_start = datetime.fromisoformat(self._start_at)
                old_end = datetime.fromisoformat(self._end_at)
                new_start = (old_start + timedelta(minutes=int(delta_minutes))).isoformat()
                new_end = (old_end + timedelta(minutes=int(delta_minutes))).isoformat()
                self.time_changed.emit(self._obj.id, new_start, new_end)
                self._start_at = new_start
                self._end_at = new_end

        elif self._mode == "resize":
            dh = self.height() - self._orig_geometry.height()
            delta_minutes = round(dh / HOUR_HEIGHT * 60 / SNAP_MINUTES) * SNAP_MINUTES
            if delta_minutes != 0:
                old_end = datetime.fromisoformat(self._end_at)
                new_end = (old_end + timedelta(minutes=int(delta_minutes))).isoformat()
                self.time_changed.emit(self._obj.id, self._start_at, new_end)
                self._end_at = new_end

        self._mode = None
        self._orig_geometry = None

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setProperty("class", "object-context-menu")

        open_action = QAction("   Open", self)
        open_action.triggered.connect(lambda: self.context_action.emit(self._obj.id, "edit"))
        menu.addAction(open_action)

        dup_action = QAction("   Duplicate", self)
        dup_action.triggered.connect(lambda: self.context_action.emit(self._obj.id, "duplicate"))
        menu.addAction(dup_action)

        menu.addSeparator()

        delete_action = QAction("   Delete", self)
        delete_action.triggered.connect(lambda: self.context_action.emit(self._obj.id, "delete"))
        menu.addAction(delete_action)

        menu.exec(event.globalPos())


class WeekGrid(QWidget):
    """7-column × 24-hour time grid with positioned event blocks."""

    cell_clicked = Signal(object)  # emits `datetime` of an empty slot's start

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "week-grid")

        self._week_start: date | None = None
        self._objects: list[Object] = []
        self._blocks: list[_EventBlock] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav = QHBoxLayout()
        nav.setContentsMargins(8, 4, 8, 4)
        self._prev_btn = QPushButton("<")
        self._prev_btn.setProperty("class", "cal-nav-btn")
        self._prev_btn.clicked.connect(self._prev_week)
        nav.addWidget(self._prev_btn)

        self._week_label = QLabel()
        self._week_label.setProperty("class", "cal-month-label")
        self._week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._week_label, 1)

        self._next_btn = QPushButton(">")
        self._next_btn.setProperty("class", "cal-nav-btn")
        self._next_btn.clicked.connect(self._next_week)
        nav.addWidget(self._next_btn)
        outer.addLayout(nav)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self._grid_container = QWidget()
        self._scroll.setWidget(self._grid_container)

        # Current-time indicator -- a thin overlay line, same absolute-
        # geometry technique _EventBlock already uses, kept alive across
        # rebuilds (not part of the QGridLayout that gets discarded each
        # _rebuild) and repositioned on a timer so it advances without a
        # full grid rebuild.
        self._now_line = QFrame(self._grid_container)
        self._now_line.setProperty("class", "cal-now-line")
        self._now_line.hide()
        self._now_timer = QTimer(self)
        self._now_timer.setInterval(60_000)
        self._now_timer.timeout.connect(self._update_now_line)
        self._now_timer.start()

        self._go_to_today()

    def _go_to_today(self) -> None:
        today = date.today()
        self._week_start = today - timedelta(days=today.weekday())
        self._rebuild()

    def _prev_week(self) -> None:
        if self._week_start:
            self._week_start -= timedelta(weeks=1)
            self._rebuild()

    def _next_week(self) -> None:
        if self._week_start:
            self._week_start += timedelta(weeks=1)
            self._rebuild()

    def set_objects(self, objects: list[Object]) -> None:
        self._objects = objects
        self._rebuild()

    def _rebuild(self) -> None:
        if self._week_start is None:
            return

        # Clear old blocks
        for b in self._blocks:
            b.setParent(None)
            b.deleteLater()
        self._blocks.clear()

        week_end = self._week_start + timedelta(days=6)
        self._week_label.setText(
            f"Week of {self._week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
        )
        # Expand recurring tasks/events for the visible week -- see
        # core/recurrence.py; without this a recurring object only shows on
        # its own anchor date.
        visible_objects = expand_recurring_objects(self._objects, self._week_start, week_end)

        container = self._grid_container
        # Remove old layout
        old = container.layout()
        if old:
            QWidget().setLayout(old)

        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(1)

        days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        empty_header = QLabel()
        grid.addWidget(empty_header, 0, 0)

        for col, day_name in enumerate(days_of_week):
            header = QLabel(day_name)
            header.setProperty("class", "cal-dow")
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(header, 0, col + 1)

        # All-day events strip
        all_day_row = 1
        all_day_container = QWidget()
        all_day_container.setProperty("class", "cal-all-day")
        all_day_lay = QHBoxLayout(all_day_container)
        all_day_lay.setContentsMargins(2, 2, 2, 2)
        all_day_lay.setSpacing(2)
        grid.addWidget(all_day_container, all_day_row, 0, 1, 8)
        for col in range(7):
            day = self._week_start + timedelta(days=col)
            day_objs = [
                o for o in visible_objects
                if o.due_at == day.isoformat()
                and ObjectStatus.is_open(o.status)
            ]
            for o in day_objs:
                if o.start_at is not None:
                    continue
                chip = QLabel(o.title[:24])
                chip.setProperty("class", "cal-event-chip")
                chip.setToolTip(f"{o.title} (all day)")
                all_day_lay.addWidget(chip)

        # Time grid rows
        label_col = 0
        day_col_start = 1
        for hour in range(24):
            row = all_day_row + 1 + hour
            time_label = QLabel(f"{hour:02d}:00")
            time_label.setProperty("class", "cal-time-label")
            time_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            time_label.setFixedHeight(HOUR_HEIGHT)
            grid.addWidget(time_label, row, label_col)

            for col in range(7):
                day = self._week_start + timedelta(days=col)
                slot_start = datetime(day.year, day.month, day.day, hour)
                cell = _HourCell(slot_start)
                cell.setProperty("class", "cal-hour-cell")
                cell.setFixedHeight(HOUR_HEIGHT)
                cell.clicked.connect(self.cell_clicked.emit)
                grid.addWidget(cell, row, day_col_start + col)

        # Position event blocks as overlays on the scroll content
        for col in range(7):
            day = self._week_start + timedelta(days=col)
            day_start = datetime(day.year, day.month, day.day)
            day_end = day_start + timedelta(days=1)
            day_objs = [
                o for o in visible_objects
                if o.due_at == day.isoformat()
                and ObjectStatus.is_open(o.status)
            ]

            # First pass: clip every timed event to this day's span.
            clipped: list[tuple[datetime, datetime, Object]] = []
            for o in day_objs:
                if o.start_at is None:
                    continue
                end_str = o.details.get("end_at") if o.details else None
                try:
                    sd = datetime.fromisoformat(o.start_at)
                except (ValueError, TypeError):
                    continue
                try:
                    ed = datetime.fromisoformat(end_str) if end_str else sd + timedelta(hours=1)
                except (ValueError, TypeError):
                    ed = sd + timedelta(hours=1)
                block_s = max(sd, day_start)
                block_e = min(ed, day_end)
                if block_s >= block_e:
                    continue
                clipped.append((block_s, block_e, o))

            # Second pass: pack overlapping events side by side within the
            # day column instead of stacking them directly on top of each
            # other (see _pack_overlaps).
            layout_info = _pack_overlaps([(s, e, o.id) for s, e, o in clipped])
            day_width = container.width() // 7 if container.width() > 0 else 140
            if day_width < 1:
                day_width = 1

            for block_s, block_e, o in clipped:
                minutes_from_midnight = (block_s - day_start).total_seconds() / 60
                duration_minutes = (block_e - block_s).total_seconds() / 60
                top = minutes_from_midnight / 60 * HOUR_HEIGHT
                height = max(duration_minutes / 60 * HOUR_HEIGHT, MIN_EVENT_HEIGHT)

                lane, lanes = layout_info.get(o.id, (0, 1))
                lane_width = max((day_width - 4) // lanes, 12)
                lane_x = day_col_start * day_width + col * day_width + 2 + lane * lane_width

                block = _EventBlock(o, block_s.isoformat(), block_e.isoformat(), container)
                block.setProperty("class", "cal-event-block")
                block.setGeometry(
                    lane_x,
                    int((all_day_row + 1) * (HOUR_HEIGHT + 1) + top),
                    max(lane_width - 1, 10),
                    int(height),
                )
                block.show()
                self._blocks.append(block)

        self._update_now_line()

    def _update_now_line(self) -> None:
        """Reposition the current-time line; hidden if today isn't visible.

        Neither this app nor `calendar.md` had any current-time indicator at
        all before this -- Apple's is a quiet, low-saturation line, which is
        what this matches given the app's own low-chrome design direction
        (see `design-system.md`) rather than Google's bolder red treatment.
        """
        if self._week_start is None:
            self._now_line.hide()
            return
        today = date.today()
        week_end = self._week_start + timedelta(days=6)
        if not (self._week_start <= today <= week_end):
            self._now_line.hide()
            return

        container = self._grid_container
        day_width = container.width() // 7 if container.width() > 0 else 140
        col = (today - self._week_start).days
        now = datetime.now()
        minutes_from_midnight = now.hour * 60 + now.minute
        top = minutes_from_midnight / 60 * HOUR_HEIGHT
        all_day_row = 1  # matches the literal used throughout _rebuild above
        day_col_start = 1

        x = day_col_start * day_width + col * day_width
        y = int((all_day_row + 1) * (HOUR_HEIGHT + 1) + top)
        self._now_line.setGeometry(x, y, day_width, 2)
        self._now_line.show()
        self._now_line.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._blocks:
            self._rebuild()

    def navigate_to_date(self, dt: date) -> None:
        self._week_start = dt - timedelta(days=dt.weekday())
        self._rebuild()


class DayGrid(QWidget):
    """Single-column 24-hour time grid."""

    cell_clicked = Signal(object)  # emits `datetime` of an empty slot's start

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "day-grid")

        self._current_date: date | None = None
        self._objects: list[Object] = []
        self._blocks: list[_EventBlock] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav = QHBoxLayout()
        nav.setContentsMargins(8, 4, 8, 4)
        self._prev_btn = QPushButton("<")
        self._prev_btn.setProperty("class", "cal-nav-btn")
        self._prev_btn.clicked.connect(self._prev_day)
        nav.addWidget(self._prev_btn)

        self._day_label = QLabel()
        self._day_label.setProperty("class", "cal-month-label")
        self._day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._day_label, 1)

        self._next_btn = QPushButton(">")
        self._next_btn.setProperty("class", "cal-nav-btn")
        self._next_btn.clicked.connect(self._next_day)
        nav.addWidget(self._next_btn)
        outer.addLayout(nav)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self._grid_container = QWidget()
        self._scroll.setWidget(self._grid_container)

        # Current-time indicator -- see WeekGrid's copy of this for the
        # rationale; same pattern, single-column version.
        self._now_line = QFrame(self._grid_container)
        self._now_line.setProperty("class", "cal-now-line")
        self._now_line.hide()
        self._now_timer = QTimer(self)
        self._now_timer.setInterval(60_000)
        self._now_timer.timeout.connect(self._update_now_line)
        self._now_timer.start()

        self._go_to_today()

    def _go_to_today(self) -> None:
        self._current_date = date.today()
        self._rebuild()

    def _prev_day(self) -> None:
        if self._current_date:
            self._current_date -= timedelta(days=1)
            self._rebuild()

    def _next_day(self) -> None:
        if self._current_date:
            self._current_date += timedelta(days=1)
            self._rebuild()

    def set_objects(self, objects: list[Object]) -> None:
        self._objects = objects
        self._rebuild()

    def _rebuild(self) -> None:
        if self._current_date is None:
            return

        for b in self._blocks:
            b.setParent(None)
            b.deleteLater()
        self._blocks.clear()

        self._day_label.setText(self._current_date.strftime("%A, %d %B %Y"))

        container = self._grid_container
        old = container.layout()
        if old:
            QWidget().setLayout(old)

        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # Expand recurring tasks/events for the visible day -- see
        # core/recurrence.py; without this a recurring object only shows on
        # its own anchor date.
        visible_objects = expand_recurring_objects(
            self._objects, self._current_date, self._current_date
        )

        # All-day strip
        day_objs = [
            o for o in visible_objects
            if o.due_at == self._current_date.isoformat()
            and ObjectStatus.is_open(o.status)
        ]

        all_day_container = QWidget()
        all_day_container.setProperty("class", "cal-all-day")
        all_day_lay = QHBoxLayout(all_day_container)
        all_day_lay.setContentsMargins(2, 2, 2, 2)
        all_day_lay.setSpacing(2)
        grid.addWidget(all_day_container, 0, 0, 1, 2)

        for o in day_objs:
            is_all_day = o.start_at is None
            chip = QLabel(o.title[:30])
            chip.setProperty("class", "cal-event-chip")
            chip.setToolTip(f"{o.title} ({'all day' if is_all_day else 'timed'})")
            chip.setWordWrap(False)
            all_day_lay.addWidget(chip)

        # Hour rows
        for hour in range(24):
            row = 1 + hour
            time_label = QLabel(f"{hour:02d}:00")
            time_label.setProperty("class", "cal-time-label")
            time_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            time_label.setFixedHeight(HOUR_HEIGHT)
            grid.addWidget(time_label, row, 0)

            slot_start = datetime(
                self._current_date.year, self._current_date.month, self._current_date.day, hour
            )
            cell = _HourCell(slot_start)
            cell.setProperty("class", "cal-hour-cell")
            cell.setFixedHeight(HOUR_HEIGHT)
            cell.clicked.connect(self.cell_clicked.emit)
            grid.addWidget(cell, row, 1)

        # Position timed event blocks (skip tasks/events without start_at)
        day_start = datetime(self._current_date.year, self._current_date.month, self._current_date.day)
        day_end = day_start + timedelta(days=1)

        clipped: list[tuple[datetime, datetime, Object]] = []
        for o in day_objs:
            if o.start_at is None:
                continue
            end_str = o.details.get("end_at") if o.details else None
            if not end_str and o.due_at:
                end_str = o.due_at
            try:
                sd = datetime.fromisoformat(o.start_at)
            except (ValueError, TypeError):
                continue
            try:
                ed = datetime.fromisoformat(end_str) if end_str else sd + timedelta(hours=1)
            except (ValueError, TypeError):
                ed = sd + timedelta(hours=1)
            block_s = max(sd, day_start)
            block_e = min(ed, day_end)
            if block_s >= block_e:
                continue
            clipped.append((block_s, block_e, o))

        # Pack overlapping events side by side instead of stacking them
        # directly on top of each other (see _pack_overlaps).
        layout_info = _pack_overlaps([(s, e, o.id) for s, e, o in clipped])
        day_width = container.width() if container.width() > 0 else 300
        available = max(day_width - 88, 50)

        for block_s, block_e, o in clipped:
            minutes_from_midnight = (block_s - day_start).total_seconds() / 60
            duration_minutes = (block_e - block_s).total_seconds() / 60
            top = minutes_from_midnight / 60 * HOUR_HEIGHT
            height = max(duration_minutes / 60 * HOUR_HEIGHT, MIN_EVENT_HEIGHT)

            lane, lanes = layout_info.get(o.id, (0, 1))
            lane_width = max(available // lanes, 40)
            lane_x = 80 + lane * lane_width

            block = _EventBlock(o, block_s.isoformat(), block_e.isoformat(), container)
            block.setProperty("class", "cal-event-block")
            block.setGeometry(
                lane_x,
                int((1) * (HOUR_HEIGHT + 1) + top),
                max(lane_width - 2, 30),
                int(height),
            )
            block.show()
            self._blocks.append(block)

        self._update_now_line()

    def _update_now_line(self) -> None:
        """Reposition the current-time line; hidden unless today is shown."""
        if self._current_date != date.today():
            self._now_line.hide()
            return

        container = self._grid_container
        day_width = container.width() if container.width() > 0 else 300
        now = datetime.now()
        minutes_from_midnight = now.hour * 60 + now.minute
        top = minutes_from_midnight / 60 * HOUR_HEIGHT

        x = 80  # matches the lane_x base used for event blocks above
        width = max(day_width - x, 30)
        y = int((1) * (HOUR_HEIGHT + 1) + top)
        self._now_line.setGeometry(x, y, width, 2)
        self._now_line.show()
        self._now_line.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._blocks:
            self._rebuild()

    def navigate_to_date(self, dt: date) -> None:
        self._current_date = dt
        self._rebuild()


class AgendaList(QWidget):
    """Chronological list of upcoming events and tasks, grouped by day."""

    DAYS_TO_SHOW = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "agenda-list")

        self._objects: list[Object] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QLabel("Upcoming (next 30 days)")
        header.setProperty("class", "section-title")
        header.setContentsMargins(16, 8, 8, 4)
        outer.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self._container = QWidget()
        self._scroll.setWidget(self._container)

    def set_objects(self, objects: list[Object]) -> None:
        self._objects = objects
        self._rebuild()

    def _rebuild(self) -> None:
        container = self._container
        old = container.layout()
        if old:
            QWidget().setLayout(old)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        today = date.today()
        # Expand recurring tasks/events across the visible window -- see
        # core/recurrence.py; without this a recurring object only shows on
        # its own anchor date.
        visible_objects = expand_recurring_objects(
            self._objects, today, today + timedelta(days=self.DAYS_TO_SHOW - 1)
        )
        grouped: dict[date, list[Object]] = {}
        for o in visible_objects:
            if not o.due_at or not ObjectStatus.is_open(o.status):
                continue
            try:
                d = date.fromisoformat(o.due_at)
            except ValueError:
                continue
            # Only show today and the next DAYS_TO_SHOW days
            delta = (d - today).days
            if delta < 0 or delta >= self.DAYS_TO_SHOW:
                continue
            grouped.setdefault(d, []).append(o)

        for d in sorted(grouped):
            items = grouped[d]
            items.sort(key=lambda x: (x.start_at or x.due_at or ""))

            day_header = self._build_day_header(d)
            layout.addWidget(day_header)

            for o in items:
                row = self._build_entry(o)
                layout.addWidget(row)

        layout.addStretch()

    def _build_day_header(self, d: date) -> QWidget:
        h = QWidget()
        h.setProperty("class", "agenda-day-header")
        hl = QHBoxLayout(h)
        hl.setContentsMargins(0, 12, 0, 4)

        today = date.today()
        if d == today:
            label_str = "Today"
        elif d == today + timedelta(days=1):
            label_str = "Tomorrow"
        else:
            label_str = d.strftime("%A, %d %b %Y")

        label = QLabel(label_str)
        label.setProperty("class", "agenda-day-label")
        hl.addWidget(label)

        count_objs = expand_recurring_objects(self._objects, d, d)
        count = QLabel(f"{len([o for o in count_objs if o.due_at == d.isoformat() and ObjectStatus.is_open(o.status)])} items")
        count.setProperty("class", "agenda-day-count")
        hl.addWidget(count)
        hl.addStretch()

        return h

    def _build_entry(self, o: Object) -> QWidget:
        row = QWidget()
        row.setProperty("class", "agenda-entry")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 2, 0, 2)
        rl.setSpacing(8)

        time_str = ""
        if o.start_at:
            try:
                dt = datetime.fromisoformat(o.start_at)
                time_str = dt.strftime("%H:%M")
            except (ValueError, TypeError):
                pass
        time_label = QLabel(time_str if time_str else "All day")
        time_label.setProperty("class", "agenda-entry-time")
        time_label.setFixedWidth(50)
        rl.addWidget(time_label)

        icon_label = QLabel(o.icon or "○")
        icon_label.setProperty("class", "agenda-entry-icon")
        rl.addWidget(icon_label)

        title_label = QLabel(o.title[:40])
        title_label.setProperty("class", "agenda-entry-title")
        rl.addWidget(title_label, 1)

        prio_str = ""
        if o.priority and o.priority <= 2:
            prio_str = f"P{o.priority}"
        if prio_str:
            prio_label = QLabel(prio_str)
            prio_label.setProperty("class", f"priority-{o.priority}")
            rl.addWidget(prio_label)

        type_label = QLabel(o.type.value.upper()[:4])
        type_label.setProperty("class", "agenda-entry-type")
        rl.addWidget(type_label)

        return row


class CalendarView(QScrollArea):
    """Calendar module container with view switcher and all 4 views."""

    view_changed = Signal(str)
    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "calendar-view")

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._switcher = QWidget()
        self._switcher.setProperty("class", "cal-view-switcher")
        switcher_layout = QHBoxLayout(self._switcher)
        switcher_layout.setContentsMargins(8, 4, 8, 4)
        switcher_layout.addStretch()

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_buttons: list[QPushButton] = []
        views = [("Month", "month"), ("Week", "week"), ("Day", "day"), ("Agenda", "agenda")]
        self._view_names = [v[1] for v in views]
        for label, key in views:
            btn = QPushButton(label)
            btn.setProperty("class", "cal-view-btn")
            btn.setCheckable(True)
            btn.setChecked(key == "month")
            self._view_group.addButton(btn, self._view_names.index(key))
            switcher_layout.addWidget(btn)
            self._view_buttons.append(btn)

        self._view_group.idClicked.connect(self._on_view_switched)
        layout.addWidget(self._switcher)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._month_grid = MonthGrid()
        self._stack.addWidget(self._month_grid)

        self._week_grid = WeekGrid()
        self._stack.addWidget(self._week_grid)

        self._day_grid = DayGrid()
        self._stack.addWidget(self._day_grid)

        self._agenda = AgendaList()
        self._stack.addWidget(self._agenda)

        self._all_objects: list[Object] = []

        # Month view: click a day to zoom into Day view (matches Apple
        # Calendar's tap/double-click-to-zoom behavior described in
        # apple-vs-google-calendar-views.md); click a chip or overflow entry
        # to open it. Previously MonthGrid had no click handling at all.
        self._month_grid.day_clicked.connect(self._on_month_day_clicked)
        self._month_grid.object_clicked.connect(self.open_object_requested.emit)

        # Week/Day: click an empty slot to create a new event there and
        # open it immediately in the inspector -- previously there was no
        # way to create an event from the time grid at all.
        self._week_grid.cell_clicked.connect(self._on_grid_cell_clicked)
        self._day_grid.cell_clicked.connect(self._on_grid_cell_clicked)

    def _on_month_day_clicked(self, day_date: date) -> None:
        self.navigate_to_date(day_date)
        self._switch_to_view("day")

    def _switch_to_view(self, key: str) -> None:
        idx = self._view_names.index(key)
        self._view_buttons[idx].setChecked(True)
        self._on_view_switched(idx)

    def _on_grid_cell_clicked(self, slot_start: datetime) -> None:
        """Create a new event at the clicked empty time-grid slot and open
        it in the inspector right away, same as clicking an existing block
        does -- the week/day grid had no click-to-create before this."""
        now = datetime.now(timezone.utc).isoformat()
        end_at = (slot_start + timedelta(hours=1)).isoformat()
        obj = Object(
            id=str(uuid.uuid4()),
            type=ObjectType.event,
            title="New event",
            status=ObjectStatus.active,
            due_at=slot_start.date().isoformat(),
            start_at=slot_start.isoformat(),
            created_at=now,
            updated_at=now,
            details={"end_at": end_at},
        )
        FileRepository().write_object(obj)
        self._all_objects.append(obj)
        self.set_objects(self._all_objects)
        self.open_object_requested.emit(obj.id)

    def _on_view_switched(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        current_view = self._view_names[idx]
        self.view_changed.emit(current_view)
        # Refresh the selected view with current objects
        for btn in self._view_buttons:
            btn.setChecked(self._view_buttons.index(btn) == idx)
        self._refresh_current_view()

    def _refresh_current_view(self) -> None:
        current = self._stack.currentWidget()
        if current and hasattr(current, "set_objects"):
            current.set_objects(self._all_objects)

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = [
            o
            for o in objects
            if o.type in (ObjectType.task, ObjectType.event)
            and o.due_at is not None
        ]
        if hasattr(self._stack.currentWidget(), "set_objects"):
            self._stack.currentWidget().set_objects(self._all_objects)
        QTimer.singleShot(0, self._connect_block_actions)

    def navigate_to_date(self, dt: date) -> None:
        """Navigate all views to a specific date."""
        self._month_grid._current_year = dt.year
        self._month_grid._current_month = dt.month
        self._month_grid._rebuild()
        self._week_grid.navigate_to_date(dt)
        self._day_grid.navigate_to_date(dt)

    def _connect_block_actions(self) -> None:
        """Wire context_action and time_changed signals from all _EventBlocks."""
        for block in self.findChildren(_EventBlock):
            block.context_action.connect(self._on_block_context_action)
            block.time_changed.connect(self._on_block_time_changed)

    def _on_block_time_changed(self, object_id: str, new_start_at: str, new_end_at: str) -> None:
        """Persist a drag-to-move or drag-to-resize from the week/day grid.

        Previously this only mutated the in-memory Object and re-rendered --
        it looked like it worked (the block visibly moved/resized) but
        nothing was ever written to disk, so the change was lost on the
        next reindex or restart. Same bug for both move and resize, since
        both go through this one handler; fixed for both here.
        """
        for o in self._all_objects:
            if o.id == object_id:
                o.start_at = new_start_at
                o.updated_at = datetime.now(timezone.utc).isoformat()
                if o.details is None:
                    o.details = {}
                o.details["end_at"] = new_end_at
                FileRepository().write_object(o)
                break
        self.set_objects(self._all_objects)

    def _on_block_context_action(self, object_id: str, action: str) -> None:
        if action == "edit":
            self.open_object_requested.emit(object_id)
        elif action == "duplicate":
            import uuid
            from datetime import datetime, timezone
            src = next((o for o in self._all_objects if o.id == object_id), None)
            if src:
                now = datetime.now(timezone.utc).isoformat()
                dup = Object(
                    id=str(uuid.uuid4()),
                    type=src.type,
                    title=f"{src.title} (copy)",
                    status=src.status,
                    priority=src.priority,
                    due_at=src.due_at,
                    tags=list(src.tags) if src.tags else [],
                    created_at=now,
                    updated_at=now,
                )
                self._all_objects.append(dup)
                self.set_objects(self._all_objects)
        elif action == "delete":
            self._all_objects = [o for o in self._all_objects if o.id != object_id]
            self.set_objects(self._all_objects)
