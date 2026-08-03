"""ChecklistEditor — reusable checklist widget (PHASE 5).

Expandable list of QCheckBox + QLineEdit pairs. Add/remove/toggle items.
Persisted to checklist.json via FileRepository.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.filerepo.repository import FileRepository


class ChecklistEditor(QWidget):
    """Expandable checklist with add/remove/toggle."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._file_repo: FileRepository | None = None
        self._object_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._list_layout = QVBoxLayout()
        self._list_layout.setSpacing(4)
        layout.addLayout(self._list_layout)

        self._add_btn = QPushButton("+ Add item")
        self._add_btn.setProperty("class", "inspector-add-btn")
        self._add_btn.clicked.connect(self._add_item)
        layout.addWidget(self._add_btn)

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def load(self, object_id: str) -> None:
        self._object_id = object_id
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._file_repo:
            return
        items = self._file_repo.read_checklist(object_id) or []
        for ci in items:
            self._add_row(ci.get("text", ""), ci.get("done", False))

    def save(self) -> None:
        if not self._file_repo or not self._object_id:
            return
        items = []
        for i in range(self._list_layout.count()):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                row = item.widget().layout()
                if row and row.count() >= 2:
                    cb = row.itemAt(0).widget()
                    edit = row.itemAt(1).widget()
                    if isinstance(cb, QCheckBox) and isinstance(edit, QLineEdit):
                        items.append({"text": edit.text(), "done": cb.isChecked()})
        self._file_repo.write_checklist(self._object_id, items)

    def _add_item(self) -> None:
        self._add_row("", False)

    def _add_row(self, text: str, done: bool) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(done)
        row.addWidget(cb)
        edit = QLineEdit(text)
        edit.setProperty("class", "inspector-checklist-input")
        row.addWidget(edit, 1)
        del_btn = QPushButton("×")
        del_btn.setFixedWidth(24)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        row.addWidget(del_btn)
        container = QWidget()
        container.setLayout(row)
        self._list_layout.addWidget(container)

    def _remove_row(self, row_layout: QHBoxLayout) -> None:
        for i in range(self._list_layout.count()):
            item = self._list_layout.itemAt(i)
            if item and item.widget() and item.widget().layout() is row_layout:
                item.widget().deleteLater()
                break
