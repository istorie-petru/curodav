"""Command palette overlay (Ctrl+K) — ARCHITECTURE.md §10, REWORK_PLAN §7.10.

Fuzzy-search overlay over all objects + actions. Keyboard-first navigation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class CommandPalette(QDialog):
    """Ctrl+K overlay: search objects + actions."""

    object_selected = Signal(str)
    action_triggered = Signal(str)

    _ACTIONS = [
        ("> New task", "new_task"),
        ("> New event", "new_event"),
        ("> New note", "new_note"),
        ("> Go to Today", "go_today"),
        ("> Toggle dark mode", "toggle_dark"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QVBoxLayout()
        container.setContentsMargins(16, 16, 16, 16)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search objects or type > for actions…")
        self._search_input.setProperty("class", "command-palette-input")
        self._search_input.textChanged.connect(self._on_query_changed)
        container.addWidget(self._search_input)

        self._results_list = QListWidget()
        self._results_list.setProperty("class", "command-palette-results")
        container.addWidget(self._results_list)

        hint_layout = QHBoxLayout()
        hint = QLabel("↑↓ navigate · Enter open · Esc close")
        hint.setProperty("class", "palette-hint")
        hint_layout.addWidget(hint)
        container.addLayout(hint_layout)

        layout.addLayout(container)
        self.setMinimumWidth(500)

    def _on_query_changed(self, text: str) -> None:
        self._results_list.clear()
        if not text.strip():
            return

        if text.startswith(">"):
            query = text[1:].strip().lower()
            for label, action_id in self._ACTIONS:
                if query in label.lower():
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, action_id)
                    self._results_list.addItem(item)
        else:
            item = QListWidgetItem(f"Search: {text}")
            item.setData(Qt.ItemDataRole.UserRole, f"search:{text}")
            self._results_list.addItem(item)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key.Key_Return:
            current = self._results_list.currentItem()
            if current:
                data = current.data(Qt.ItemDataRole.UserRole)
                if data and data.startswith("search:"):
                    query = data[7:]
                    self.object_selected.emit(query)
                else:
                    self.action_triggered.emit(data or "")
                self.accept()
        elif event.key() == Qt.Key.Key_Down:
            idx = self._results_list.currentRow()
            self._results_list.setCurrentRow(
                min(idx + 1, self._results_list.count() - 1)
            )
        elif event.key() == Qt.Key.Key_Up:
            idx = self._results_list.currentRow()
            self._results_list.setCurrentRow(max(idx - 1, 0))
        else:
            super().keyPressEvent(event)
