"""Dashboard / Today module (REWORK_PLAN §7.3).

Sections: stats strip, pinned, overdue, today, upcoming, quick-add row.
Default landing page of the app.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType
from ...core.utils.date_utils import today_str
from ...features.shared.create import create_task_from_quickadd
from ...widgets import ObjectCard


class StatsStrip(QFrame):
    """Row of count stats: open tasks, overdue, due today, active projects."""

    stat_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "stats-strip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._stats: dict[str, QLabel] = {}
        for label, key in [
            ("Open Tasks", "open_tasks"),
            ("Overdue", "overdue"),
            ("Due Today", "due_today"),
            ("Active Projects", "active_projects"),
        ]:
            card = QFrame()
            card.setProperty("class", "stat-card")
            card_layout = QVBoxLayout(card)

            value_label = QLabel("—")
            value_label.setProperty("class", "stat-value")
            card_layout.addWidget(value_label)

            name_label = QLabel(label)
            name_label.setProperty("class", "stat-label")
            card_layout.addWidget(name_label)

            self._stats[key] = value_label
            layout.addWidget(card)

        layout.addStretch(1)

    def update_counts(
        self,
        open_tasks: int,
        overdue: int,
        due_today: int,
        active_projects: int,
    ) -> None:
        self._stats["open_tasks"].setText(str(open_tasks))
        self._stats["overdue"].setText(str(overdue))
        self._stats["due_today"].setText(str(due_today))
        self._stats["active_projects"].setText(str(active_projects))


class SectionGroup(QFrame):
    """A labeled section with a list of object cards."""

    card_clicked = Signal(str)

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        empty_text: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "section-group")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)

        header_layout = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setProperty("class", "section-title")
        header_layout.addWidget(title_label)

        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setProperty("class", "section-subtitle")
            header_layout.addWidget(sub_label)

        header_layout.addStretch(1)
        layout.addLayout(header_layout)

        # One bordered container per section, rows flush against each other
        # inside it -- the grouped-list-card pattern from the design doc
        # (macOS System Settings-style), not a stack of individually
        # bordered cards with gaps between them.
        self._list_box = QFrame()
        self._list_box.setProperty("class", "section-list-box")
        self._card_list = QVBoxLayout(self._list_box)
        self._card_list.setContentsMargins(0, 0, 0, 0)
        self._card_list.setSpacing(0)
        layout.addWidget(self._list_box)

        self._empty_label = QLabel(empty_text)
        self._empty_label.setProperty("class", "section-empty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._empty_text = empty_text
        self._toggle_empty()

    def set_cards(self, objects: list[Object]) -> None:
        while self._card_list.count():
            item = self._card_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, obj in enumerate(objects):
            card = ObjectCard(obj, flush=True)
            card.clicked.connect(self.card_clicked)
            # last row in the box has no bottom hairline
            if i == len(objects) - 1:
                card.setProperty("class", "object-card-flush-last")
            self._card_list.addWidget(card)

        self._toggle_empty(objects)

    def _toggle_empty(self, objects: list | None = None) -> None:
        has_items = objects is not None and len(objects) > 0
        self._empty_label.setVisible(not has_items)
        self._list_box.setVisible(has_items)


class QuickAddRow(QFrame):
    """Inline quick-add input: title + optional tokens (REWORK_PLAN §7.3)."""

    object_created = Signal(Object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "quick-add-row")
        self._file_repo: FileRepository | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Quick add — type title, then !1-!4 @today @tomorrow #project >tag …"
        )
        self._input.setProperty("class", "quick-add-input")
        self._input.returnPressed.connect(self._commit)
        layout.addWidget(self._input, 1)

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def _commit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        repo = self._file_repo
        if repo is None:
            return
        obj = create_task_from_quickadd(text, repo)
        self.object_created.emit(obj)


class DashboardView(QScrollArea):
    """The Today dashboard — default landing page."""

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "dashboard-view")

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        self._stats = StatsStrip()
        layout.addWidget(self._stats)

        # 2026-07-19: Pinned and Upcoming sections removed -- Dashboard is
        # now strictly Overdue + Today. This is also where the Tasks
        # module's Smart-list view was "integrated into Dashboard" per the
        # rework: the Smart tab's other saved filters (Upcoming/All Open/
        # High Priority/Waiting/Completed/Archived) moved to a filter-chip
        # bar above the Tasks Table view instead (`table_view.py`) rather
        # than living here, since Dashboard is deliberately narrower now
        # (only what's overdue or due today, nothing else).
        self._overdue_section = SectionGroup(
            "Overdue",
            subtitle=f"(as of {today_str()})",
            empty_text="Nothing overdue — nice work",
        )
        self._overdue_section.card_clicked.connect(self.open_object_requested)
        layout.addWidget(self._overdue_section)

        self._today_section = SectionGroup(
            "Today",
            subtitle=today_str(),
            empty_text="Nothing due today",
        )
        self._today_section.card_clicked.connect(self.open_object_requested)
        layout.addWidget(self._today_section)

        self._quick_add = QuickAddRow()
        layout.addWidget(self._quick_add)

        layout.addStretch(1)

    def set_file_repo(self, repo: FileRepository) -> None:
        self._quick_add.set_file_repo(repo)

    def set_objects(self, objects: list[Object]) -> None:
        today = today_str()

        overdue = [
            o
            for o in objects
            if o.due_at and o.due_at < today and ObjectStatus.is_open(o.status)
        ]
        due_today = [
            o
            for o in objects
            if o.due_at == today and ObjectStatus.is_open(o.status)
        ]
        open_tasks = [
            o
            for o in objects
            if o.type == ObjectType.task and ObjectStatus.is_open(o.status)
        ]
        active_projects = [
            o
            for o in objects
            if o.type == ObjectType.project
            and ObjectStatus.is_open(o.status)
        ]

        overdue.sort(key=lambda o: o.due_at or "")
        due_today.sort(key=lambda o: o.due_at or "")

        self._stats.update_counts(
            open_tasks=len(open_tasks),
            overdue=len(overdue),
            due_today=len(due_today),
            active_projects=len(active_projects),
        )
        self._overdue_section.set_cards(overdue)
        self._today_section.set_cards(due_today)
