"""LinkPicker — modal dialog to search objects and create links (PHASE 4).

Shows a search bar + results list + link type selector + create button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ...core.db.database import Database


class LinkPicker(QDialog):
    """Pick an object and link type, then emit the result."""

    def __init__(self, db: Database, current_object_id: str, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._current_object_id = current_object_id
        self.setWindowTitle("Create link")
        self.setMinimumSize(400, 500)
        self._result: dict | None = None
        self._build_ui()

    @property
    def result(self) -> dict | None:
        return self._result

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search objects by title…")
        self._search.setProperty("class", "quick-add-input")
        self._search.textChanged.connect(self._search_objects)
        layout.addWidget(self._search)

        self._results = QListWidget()
        self._results.setProperty("class", "filter-list")
        layout.addWidget(self._results, 1)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Link type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(["related", "blocks", "references", "mentions"])
        type_row.addWidget(self._type_combo, 1)
        layout.addLayout(type_row)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        create_btn = QPushButton("Create link")
        create_btn.setProperty("class", "inspector-save-btn")
        create_btn.clicked.connect(self._create)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

        self._search_objects("")

    def _search_objects(self, query: str) -> None:
        self._results.clear()
        rows = self._db.search_objects_by_title(query)
        for r in rows:
            if r["id"] == self._current_object_id:
                continue
            item = QListWidgetItem(f"[{r['type']}] {r['title']}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self._results.addItem(item)

    def _create(self) -> None:
        current = self._results.currentItem()
        if not current:
            return
        to_id = current.data(Qt.ItemDataRole.UserRole)
        link_type = self._type_combo.currentText()
        self._result = self._db.create_link(self._current_object_id, to_id, link_type)
        self.accept()
