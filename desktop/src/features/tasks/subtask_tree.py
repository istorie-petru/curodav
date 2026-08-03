"""SubtaskTree — parent/child task tree (PHASE 5).

Recursively displays objects with `parent_id == current_task.id`.
Supports expand/collapse, add subtask, and toggle completion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType, progress_for_status


class SubtaskTree(QWidget):
    """Tree of subtasks for a given parent task."""

    subtask_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._file_repo: FileRepository | None = None
        self._parent_id: str | None = None
        self._all_objects: list[Object] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(20)
        layout.addWidget(self._tree, 1)

        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("+ Add subtask …")
        self._add_input.setProperty("class", "inspector-input")
        self._add_input.returnPressed.connect(self._add_subtask)
        add_row.addWidget(self._add_input, 1)
        add_btn = QPushButton("Add")
        add_btn.setProperty("class", "inspector-add-btn")
        add_btn.clicked.connect(self._add_subtask)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def load(self, parent_id: str, all_objects: list[Object]) -> None:
        self._parent_id = parent_id
        self._all_objects = all_objects
        self._tree.clear()
        children = [o for o in all_objects if o.parent_id == parent_id and o.type == ObjectType.task]
        for child in children:
            self._add_tree_item(child, self._tree.invisibleRootItem())

    def _add_tree_item(self, obj: Object, parent_item: QTreeWidgetItem) -> None:
        item = QTreeWidgetItem(parent_item)
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        cb = QCheckBox()
        cb.setChecked(obj.status == ObjectStatus.done)
        cb.stateChanged.connect(lambda s, oid=obj.id: self._toggle_subtask(oid, s))
        row.addWidget(cb)

        title = QLabel(obj.title)
        title.setProperty("class", "task-title")
        row.addWidget(title, 1)

        if obj.due_at:
            due = QLabel(obj.due_at)
            due.setProperty("class", "task-due")
            row.addWidget(due)

        widget.setLayout(row)
        self._tree.setItemWidget(item, 0, widget)

        # Recurse
        grandchildren = [o for o in self._all_objects if o.parent_id == obj.id and o.type == ObjectType.task]
        for g in grandchildren:
            self._add_tree_item(g, item)

    def _add_subtask(self) -> None:
        text = self._add_input.text().strip()
        if not text or not self._file_repo or not self._parent_id:
            return
        self._add_input.clear()
        object_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        obj = Object(
            id=object_id,
            type=ObjectType.task,
            title=text,
            parent_id=self._parent_id,
            status=ObjectStatus.active,
            created_at=now,
            updated_at=now,
        )
        self._file_repo.write_object(obj)
        self.subtask_changed.emit()

    def _toggle_subtask(self, object_id: str, state: int) -> None:
        if not self._file_repo:
            return
        obj = self._file_repo.read_object(object_id)
        if obj:
            obj.status = ObjectStatus.done if state == Qt.CheckState.Checked.value else ObjectStatus.active
            obj.progress = progress_for_status(obj.status)
            obj.updated_at = datetime.now(timezone.utc).isoformat()
            self._file_repo.write_object(obj)
            self.subtask_changed.emit()
