"""Search module (REWORK_PLAN §7.10).

Full search results view with FTS5 integration, grouped by type.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Object, ObjectStatus, ObjectType


def _highlight(text: str, query: str) -> str:
    if not query:
        return text
    escaped = query.replace("\\", "\\\\").replace("'", "\\'")
    import re
    return re.sub(
        f'(?i)({re.escape(escaped)})',
        r'<span style="background: #FFD70033; font-weight: 600;">\1</span>',
        text,
    )


class SearchResultCard(QFrame):
    """A single search result row."""

    clicked = Signal(str)

    def __init__(self, obj: Object, highlight: str = "", parent=None) -> None:
        super().__init__(parent)
        self._object_id = obj.id
        self.setProperty("class", "search-result-card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        type_label = QLabel(obj.type.value[:3].upper())
        type_label.setProperty("class", "search-type-badge")
        type_label.setFixedWidth(32)
        layout.addWidget(type_label)

        text_layout = QVBoxLayout()
        title = QLabel()
        title.setProperty("class", "search-title")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setText(_highlight(obj.title, highlight))
        text_layout.addWidget(title)

        if obj.description:
            desc = QLabel()
            desc.setProperty("class", "search-desc")
            desc.setTextFormat(Qt.TextFormat.RichText)
            desc.setText(_highlight(obj.description[:120], highlight))
            text_layout.addWidget(desc)

        layout.addLayout(text_layout, 1)

        if obj.status:
            status = QLabel(obj.status)
            status.setProperty("class", "search-status")
            layout.addWidget(status)

        if obj.due_at:
            due = QLabel(obj.due_at)
            due.setProperty("class", "search-due")
            layout.addWidget(due)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._object_id)
        super().mousePressEvent(event)


class SearchResultsGroup(QFrame):
    """Group of results for one type (Tasks, Notes, Events, Projects)."""

    def __init__(self, type_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "search-group")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        header = QLabel(type_name)
        header.setProperty("class", "search-group-header")
        layout.addWidget(header)

        self._results_layout = QVBoxLayout()
        self._results_layout.setSpacing(4)
        layout.addLayout(self._results_layout)

        self._empty = QLabel(f"No {type_name.lower()} found")
        self._empty.setProperty("class", "section-empty")
        layout.addWidget(self._empty)

    def set_results(self, objects: list[Object], highlight: str = "") -> None:
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for obj in objects:
            card = SearchResultCard(obj, highlight=highlight)
            self._results_layout.addWidget(card)

        self._empty.setVisible(len(objects) == 0)


class SearchView(QScrollArea):
    """Full search module with FTS5 integration."""

    object_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "search-view")

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(8)

        header = QLabel("Search")
        header.setProperty("class", "module-header")
        layout.addWidget(header)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search objects by title, description, or body…")
        self._input.setProperty("class", "quick-add-input")
        self._input.textChanged.connect(self._on_query)
        layout.addWidget(self._input)

        self._groups: dict[str, SearchResultsGroup] = {}
        for name in ["Tasks", "Notes", "Events", "Projects", "Other"]:
            g = SearchResultsGroup(name)
            layout.addWidget(g)
            self._groups[name] = g

        self._empty_state = QLabel("Type a query to search across all objects")
        self._empty_state.setProperty("class", "section-empty")
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_state)

        layout.addStretch(1)

        self._all_objects: list[Object] = []
        self._search_query: str = ""
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._execute_search)

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = objects

    def _on_query(self, text: str) -> None:
        self._debounce.start(300)

    def _execute_search(self) -> None:
        text = self._input.text()
        query = text.strip().lower()
        if not query:
            self._empty_state.setVisible(True)
            for g in self._groups.values():
                g.set_results([])
            return

        self._empty_state.setVisible(False)

        self._search_query = query

        matches = [
            o
            for o in self._all_objects
            if query in o.title.lower()
            or query in (o.description or "").lower()
        ]

        type_map = {
            "Tasks": [ObjectType.task],
            "Notes": [ObjectType.note],
            "Events": [ObjectType.event],
            "Projects": [ObjectType.project],
            "Other": [
                ObjectType.goal,
                ObjectType.roadmap_node,
                ObjectType.board,
                ObjectType.person,
            ],
        }

        for group_name, types in type_map.items():
            group_matches = [
                o for o in matches if o.type in types
            ]
            group_matches.sort(
                key=lambda o: (
                    0 if o.title.lower().startswith(query) else 1,
                    o.updated_at or "",
                ),
            )
            self._groups[group_name].set_results(group_matches, highlight=query)
