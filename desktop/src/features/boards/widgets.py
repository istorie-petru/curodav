"""Kanban Boards module (REWORK_PLAN §7.7).

Column-by-status layout. Drag cards between columns = status change.
Supports add/delete/duplicate and double-click → inspector.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QMimeData, Signal
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType

BOARD_COLUMNS = [
    ("Todo", ObjectStatus.active),
    ("In Progress", ObjectStatus.in_progress),
    ("Waiting", ObjectStatus.waiting),
    ("Done", ObjectStatus.done),
]

CARD_MIME = "application/x-commandcenter-card"


class KanbanCard(QFrame):
    """A draggable card in a kanban column."""

    def __init__(self, obj: Object, parent=None) -> None:
        super().__init__(parent)
        self._object_id = obj.id
        self._obj = obj
        self.setProperty("class", "kanban-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        title = QLabel(obj.title)
        title.setProperty("class", "kanban-card-title")
        title.setWordWrap(True)
        layout.addWidget(title)

        if obj.due_at:
            due = QLabel(obj.due_at)
            due.setProperty("class", "kanban-card-due")
            layout.addWidget(due)

        self._drag_start_pos = None

    @property
    def object_id(self) -> str:
        return self._object_id

    @property
    def obj(self) -> Object:
        return self._obj

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start_pos is None:
            return
        if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < 10:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(CARD_MIME, self._object_id.encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        parent_view = self._find_boards_view()
        if parent_view and hasattr(parent_view, "open_object_requested"):
            parent_view.open_object_requested.emit(self._object_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        parent_view = self._find_boards_view()
        menu = QMenu(self)
        edit_a = QAction("Edit", self)
        edit_a.triggered.connect(
            lambda: parent_view and parent_view.open_object_requested.emit(self._object_id)
        )
        menu.addAction(edit_a)

        dup_a = QAction("Duplicate", self)
        dup_a.triggered.connect(self._duplicate)
        menu.addAction(dup_a)

        move_menu = menu.addMenu("Move to column")
        for title, status in BOARD_COLUMNS:
            if status != self._obj.status:
                act = QAction(title, self)
                act.setData(status)
                act.triggered.connect(lambda checked, s=status: self._move_to(s))
                move_menu.addAction(act)

        menu.addSeparator()
        del_a = QAction("Delete", self)
        del_a.triggered.connect(self._delete)
        menu.addAction(del_a)

        menu.exec(event.globalPos())

    def _find_boards_view(self) -> QWidget | None:
        p = self.parent()
        while p:
            if isinstance(p, BoardsView):
                return p
            p = p.parent()
        return None

    def _duplicate(self) -> None:
        import copy
        dup = copy.deepcopy(self._obj)
        dup.id = str(uuid.uuid4())
        dup.title = f"{dup.title} (copy)"
        now = datetime.now(timezone.utc).isoformat()
        dup.created_at = now
        dup.updated_at = now
        FileRepository().write_object(dup)
        bv = self._find_boards_view()
        if bv and hasattr(bv, "_refresh"):
            bv._refresh()

    def _move_to(self, status: str) -> None:
        self._obj.status = status
        self._obj.updated_at = datetime.now(timezone.utc).isoformat()
        FileRepository().write_object(self._obj)
        bv = self._find_boards_view()
        if bv and hasattr(bv, "_refresh"):
            bv._refresh()

    def _delete(self) -> None:
        reply = QMessageBox.question(
            self, "Delete card",
            f"Delete \"{self._obj.title}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            FileRepository().delete_object(self._object_id)
            bv = self._find_boards_view()
            if bv and hasattr(bv, "_refresh"):
                bv._refresh()


class KanbanColumn(QFrame):
    """A single kanban column: header + card list + add button."""

    def __init__(self, title: str, status: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._status = status
        self.setProperty("class", "kanban-column")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._header = QLabel(f"{title} ({status})")
        self._header.setProperty("class", "kanban-column-header")
        layout.addWidget(self._header)

        self._card_list = QVBoxLayout()
        self._card_list.setSpacing(4)
        layout.addLayout(self._card_list)

        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("+ Add card …")
        self._add_input.setProperty("class", "quick-add-input")
        self._add_input.returnPressed.connect(self._commit_add)
        layout.addWidget(self._add_input)

    def set_cards(self, objects: list[Object]) -> None:
        while self._card_list.count():
            item = self._card_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for obj in objects:
            card = KanbanCard(obj)
            self._card_list.addWidget(card)

        self._header.setText(f"{self._title}  ({len(objects)})")

    @property
    def status(self) -> str:
        return self._status

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()
            self.setProperty("class", "kanban-column-drop")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("class", "kanban-column")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event) -> None:
        self.setProperty("class", "kanban-column")
        self.style().unpolish(self)
        self.style().polish(self)

        raw = event.mimeData().data(CARD_MIME).data()
        if not raw:
            return
        object_id = raw.decode("utf-8")
        repo = FileRepository()
        obj = repo.read_object(object_id)
        if obj is not None and obj.status != self._status:
            obj.status = self._status
            obj.updated_at = datetime.now(timezone.utc).isoformat()
            repo.write_object(obj)
            bv = self._find_boards_view()
            if bv and hasattr(bv, "_refresh"):
                bv._refresh()

    def _find_boards_view(self) -> QWidget | None:
        p = self.parent()
        while p:
            if isinstance(p, BoardsView):
                return p
            p = p.parent()
        return None

    def _commit_add(self) -> None:
        text = self._add_input.text().strip()
        if not text:
            return
        self._add_input.clear()
        object_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        obj = Object(
            id=object_id,
            type=ObjectType.task,
            title=text,
            status=self._status,
            created_at=now,
            updated_at=now,
        )
        FileRepository().write_object(obj)
        bv = self._find_boards_view()
        if bv and hasattr(bv, "_refresh"):
            bv._refresh()


class BoardsView(QScrollArea):
    """Kanban board view: horizontal column layout."""

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "boards-view")
        self._file_repo: FileRepository | None = None
        self._all_objects: list[Object] = []

        container = QWidget()
        self.setWidget(container)

        columns_layout = QHBoxLayout(container)
        columns_layout.setContentsMargins(16, 8, 16, 8)
        columns_layout.setSpacing(12)

        self._columns: list[KanbanColumn] = []
        for title, status in BOARD_COLUMNS:
            col = KanbanColumn(title, status)
            columns_layout.addWidget(col, 1)
            self._columns.append(col)

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = objects
        self._refresh()

    def _refresh(self) -> None:
        for col in self._columns:
            col_objs = [o for o in self._all_objects if o.status == col.status]
            col.set_cards(col_objs)
