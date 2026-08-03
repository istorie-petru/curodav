"""Reusable ObjectCard widget — icon + title + status + due date + priority.

Used in every list, search result, and link picker. Click to open the object
detail. Ported from the Flutter ObjectCard concept (ARCHITECTURE.md §8.1).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Object


class ObjectCard(QFrame):
    """Icon + title + status + due date + priority.

    `flush=True` renders as one row of a grouped list (no individual
    border/radius/shadow of its own -- just a bottom hairline, meant to sit
    directly against the next row inside a shared container) instead of a
    free-standing bordered card. Matches the "ModernPlasma Productivity"
    design doc's grouped-list pattern (macOS System Settings-style: one
    elevated container, hairline row separators) -- see
    `features/dashboard/widgets.py::SectionGroup`, the only current caller.
    Default (flush=False) is unchanged for every other caller (search
    results, link picker, project task list).
    """

    clicked = Signal(str)

    def __init__(self, obj: Object, parent: QWidget | None = None, flush: bool = False) -> None:
        super().__init__(parent)
        self._object_id = obj.id
        self._obj = obj
        self._flush = flush
        self._build_ui(obj)

    def _build_ui(self, obj: Object) -> None:
        self.setFrameShape(QFrame.StyledPanel)
        self.setProperty("class", "object-card-flush" if self._flush else "object-card")

        layout = QHBoxLayout(self)
        if self._flush:
            layout.setContentsMargins(10, 7, 10, 7)
        else:
            layout.setContentsMargins(9, 6, 9, 6)

        icon_label = QLabel(obj.icon or "•")
        icon_label.setProperty("class", "card-icon")
        layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        title_label = QLabel(obj.title)
        title_label.setProperty("class", "card-title")
        text_layout.addWidget(title_label)

        meta_parts = []
        if obj.status:
            meta_parts.append(obj.status)
        if obj.due_at:
            meta_parts.append(obj.due_at)
        if obj.priority:
            meta_parts.append(f"P{obj.priority}")

        if meta_parts:
            meta_label = QLabel(" · ".join(meta_parts))
            meta_label.setProperty("class", "card-meta")
            text_layout.addWidget(meta_label)

        if obj.tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(4)
            tag_row.setContentsMargins(0, 2, 0, 0)
            for t in obj.tags:
                chip = QLabel(t)
                chip.setProperty("class", "tag-chip")
                tag_row.addWidget(chip)
            tag_row.addStretch(1)
            text_layout.addLayout(tag_row)

        layout.addLayout(text_layout, 1)

    def mousePressEvent(self, event) -> None:
        if event.button() == event.button().RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        else:
            self.clicked.emit(self._object_id)
        super().mousePressEvent(event)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setProperty("class", "object-context-menu")

        edit_action = QAction("Edit", self)
        edit_action.triggered.connect(lambda: self.clicked.emit(self._object_id))
        menu.addAction(edit_action)

        dup_action = QAction("Duplicate", self)
        dup_action.triggered.connect(self._duplicate)
        menu.addAction(dup_action)

        menu.addSeparator()

        copy_action = QAction("Copy link", self)
        copy_action.triggered.connect(self._copy_link)
        menu.addAction(copy_action)

        menu.addSeparator()

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self._delete)
        menu.addAction(delete_action)

        menu.exec(pos)

    def _duplicate(self) -> None:
        from copy import deepcopy
        import uuid
        from datetime import datetime, timezone
        dup = deepcopy(self._obj)
        dup.id = str(uuid.uuid4())
        dup.title = f"{dup.title} (copy)"
        now = datetime.now(timezone.utc).isoformat()
        dup.created_at = now
        dup.updated_at = now
        from ..core.filerepo.repository import FileRepository
        FileRepository().write_object(dup)

    def _copy_link(self) -> None:
        QApplication.clipboard().setText(self._object_id)

    def _delete(self) -> None:
        reply = QMessageBox.question(
            self, "Delete object",
            f"Delete \"{self._obj.title}\"?\nThis soft-deletes the object.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from ..core.filerepo.repository import FileRepository
            FileRepository().delete_object(self._object_id)


class ObjectListTile(QFrame):
    clicked = Signal(str)

    def __init__(self, obj: Object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._object_id = obj.id

        self.setFrameShape(QFrame.StyledPanel)
        self.setProperty("class", "object-list-tile")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 4, 9, 4)

        icon_label = QLabel(obj.icon or "•")
        icon_label.setProperty("class", "tile-icon")
        layout.addWidget(icon_label)

        title_label = QLabel(obj.title)
        title_label.setProperty("class", "tile-title")
        layout.addWidget(title_label, 1)

        if obj.due_at:
            due_label = QLabel(obj.due_at)
            due_label.setProperty("class", "tile-due")
            layout.addWidget(due_label)

        status_label = QLabel(obj.status)
        status_label.setProperty("class", "tile-status")
        layout.addWidget(status_label)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._object_id)
        super().mousePressEvent(event)
