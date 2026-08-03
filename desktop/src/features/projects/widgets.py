"""Project views (PHASE 6).

ProjectOverview — list of all projects with progress bars.
ProjectDetailView — full-page detail for a single project.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType
from ...widgets import ObjectCard

_GoBackCallback = Callable[[], None]


class ProjectCard(QFrame):
    """A single project card in the overview list."""

    clicked = Signal(str)

    def __init__(self, obj: Object, progress: float, parent=None) -> None:
        super().__init__(parent)
        self._project_id = obj.id
        self.setProperty("class", "object-card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        title = QLabel(f"#{obj.title}")
        title.setProperty("class", "card-title")
        layout.addWidget(title)

        if obj.description:
            desc = QLabel(obj.description)
            desc.setProperty("class", "card-meta")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(progress * 100))
        bar.setFormat(f"{int(progress * 100)}%")
        bar.setProperty("class", "task-progress")
        layout.addWidget(bar)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._project_id)
        super().mousePressEvent(event)


class ProjectOverview(QScrollArea):
    """Project list view — shows all projects with progress bars."""

    open_project_requested = Signal(str)
    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "dashboard-view")

        container = QWidget()
        self.setWidget(container)
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 16, 24, 16)
        self._layout.setSpacing(8)

        header = QLabel("Projects")
        header.setProperty("class", "module-header")
        self._layout.addWidget(header)

        self._projects_layout = QVBoxLayout()
        self._projects_layout.setSpacing(6)
        self._layout.addLayout(self._projects_layout)

        self._empty_label = QLabel("No projects yet — use #project-name in quick-add to create one")
        self._empty_label.setProperty("class", "section-empty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._empty_label)

        self._layout.addStretch(1)

    def set_objects(self, objects: list[Object]) -> None:
        while self._projects_layout.count():
            item = self._projects_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        projects = [o for o in objects if o.type == ObjectType.project]
        self._empty_label.setVisible(len(projects) == 0)
        for p in projects:
            children = [o for o in objects if o.parent_id == p.id]
            total = len(children)
            done = sum(1 for c in children if c.status == ObjectStatus.done)
            progress = done / total if total > 0 else 0.0
            card = ProjectCard(p, progress)
            card.clicked.connect(self.open_project_requested)
            self._projects_layout.addWidget(card)


class ProjectDetailView(QScrollArea):
    """Full-page project detail view."""

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "dashboard-view")
        self._file_repo: FileRepository | None = None
        self._all_objects: list[Object] = []
        self._project_id: str | None = None

        container = QWidget()
        self.setWidget(container)
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 16, 24, 16)
        self._layout.setSpacing(8)

        back_btn = QPushButton("← Back to projects")
        back_btn.setProperty("class", "cal-nav-btn")
        back_btn.clicked.connect(self._go_back)
        self._layout.addWidget(back_btn)

        self._title_edit = QLineEdit()
        self._title_edit.setProperty("class", "inspector-input")
        self._title_edit.setStyleSheet("font-size: 20px; font-weight: 600;")
        self._layout.addWidget(self._title_edit)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Project description…")
        self._desc_edit.setProperty("class", "inspector-input")
        self._layout.addWidget(self._desc_edit)

        self._progress_bar = QProgressBar()
        self._progress_bar.setProperty("class", "task-progress")
        self._layout.addWidget(self._progress_bar)

        mil_label = QLabel("Milestones")
        mil_label.setProperty("class", "inspector-field-label")
        self._layout.addWidget(mil_label)

        self._milestones_layout = QVBoxLayout()
        self._milestones_layout.setSpacing(4)
        self._layout.addLayout(self._milestones_layout)

        add_mil_btn = QPushButton("+ Add milestone")
        add_mil_btn.setProperty("class", "inspector-add-btn")
        add_mil_btn.clicked.connect(self._add_milestone)
        self._layout.addWidget(add_mil_btn)

        tasks_label = QLabel("Tasks")
        tasks_label.setProperty("class", "inspector-field-label")
        self._layout.addWidget(tasks_label)

        self._tasks_layout = QVBoxLayout()
        self._tasks_layout.setSpacing(4)
        self._layout.addLayout(self._tasks_layout)

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "inspector-save-btn")
        save_btn.clicked.connect(self._save)
        self._layout.addWidget(save_btn)

        self._layout.addStretch(1)
        self._back: _GoBackCallback | None = None

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def set_go_back_callback(self, callback) -> None:
        self._back = callback

    def _go_back(self) -> None:
        if self._back:
            self._back()

    def load_project(self, project_id: str, all_objects: list[Object]) -> None:
        self._project_id = project_id
        self._all_objects = all_objects
        obj = next((o for o in all_objects if o.id == project_id), None)
        if not obj:
            return

        self._title_edit.setText(obj.title)
        self._desc_edit.setText(obj.description or "")

        children = [o for o in all_objects if o.parent_id == project_id]
        total = len(children)
        done = sum(1 for o in children if o.status == ObjectStatus.done)
        pct = int((done / total * 100)) if total > 0 else 0
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(pct)
        self._progress_bar.setFormat(f"{done}/{total} tasks ({pct}%)")

        while self._milestones_layout.count():
            item = self._milestones_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        milestones = self._file_repo.read_milestones(project_id) if self._file_repo else []
        if milestones is None:
            milestones = []
        for ms in milestones:
            self._add_milestone_row(ms.get("text", ""), ms.get("done", False))

        while self._tasks_layout.count():
            item = self._tasks_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for child in children:
            card = ObjectCard(child)
            card.clicked.connect(self.open_object_requested)
            self._tasks_layout.addWidget(card)

    def _add_milestone(self) -> None:
        self._add_milestone_row("", False)

    def _add_milestone_row(self, text: str, done: bool) -> None:
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
        row.addWidget(del_btn)
        container = QWidget()
        container.setLayout(row)
        del_btn.clicked.connect(lambda c=container: self._remove_milestone(c))
        self._milestones_layout.addWidget(container)

    def _remove_milestone(self, container: QWidget) -> None:
        container.deleteLater()

    def _save(self) -> None:
        if not self._file_repo or not self._project_id:
            return
        obj = self._file_repo.read_object(self._project_id)
        if obj:
            obj.title = self._title_edit.text()
            obj.description = self._desc_edit.text()
            obj.updated_at = datetime.now(timezone.utc).isoformat()
            self._file_repo.write_object(obj)

        milestones = []
        for i in range(self._milestones_layout.count()):
            item = self._milestones_layout.itemAt(i)
            if item and item.widget():
                row = item.widget().layout()
                if row and row.count() >= 2:
                    cb = row.itemAt(0).widget()
                    edit = row.itemAt(1).widget()
                    if isinstance(cb, QCheckBox) and isinstance(edit, QLineEdit):
                        milestones.append({"text": edit.text(), "done": cb.isChecked()})
        self._file_repo.write_milestones(self._project_id, milestones)
