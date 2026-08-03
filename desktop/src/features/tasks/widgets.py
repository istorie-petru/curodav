"""Tasks module (REWORK_PLAN §7.4).

Table/Timeline/Board view switcher with a shared quick-add row. The old
Smart-list view (sidebar of saved filters: Today/Upcoming/All Open/High
Priority/Waiting/Completed/Archived, with individually-carded task rows)
was removed 2026-07-19 and its role split in two: "Today"/"Overdue" moved
to the Dashboard module (the only two that matter for a daily landing
page), and the rest of the saved filters became a chip filter bar embedded
directly above the Table view (`table_view.py::SMART_FILTERS`/
`TaskTableFilterBar`) instead of a separate view of their own.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectType
from ...core.utils.date_utils import parse_date_token
from ..shared.create import create_task_from_quickadd


class TaskQuickAdd(QFrame):
    """Inline quick-add with token syntax (REWORK_PLAN §7.4)."""

    task_created = Signal(Object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "quick-add-row")
        self._file_repo: FileRepository | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Quick add — !1-!4 @today @tomorrow @next-week #project >tag"
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
        self.task_created.emit(obj)

    @staticmethod
    def parse_tokens(text: str) -> dict:
        """Parse quick-add tokens from text.

        Returns dict with title, priority, due_at, parent_id, tags.
        """
        tokens = text.split()
        title_parts = []
        priority = None
        due_at = None
        parent_id = None
        tags = []

        for token in tokens:
            if token.startswith("!") and len(token) == 2:
                try:
                    p = int(token[1])
                    if 1 <= p <= 4:
                        priority = p
                except ValueError:
                    title_parts.append(token)
            elif token.startswith("@"):
                parsed = parse_date_token(token)
                if parsed:
                    due_at = parsed
                else:
                    title_parts.append(token)
            elif token.startswith("#"):
                parent_id = token[1:]
            elif token.startswith(">"):
                tags.append(token[1:])
            else:
                title_parts.append(token)

        return {
            "title": " ".join(title_parts) if title_parts else text,
            "priority": priority,
            "due_at": due_at,
            "parent_id": parent_id,
            "tags": tags,
        }


class TasksView(QWidget):
    """Full Tasks module: shared quick-add row + view switcher (Table/
    Timeline/Board) + stacked views.

    The Smart-list view (and its own `TaskFilterBar`/`TaskRow`/
    `TaskListView`) was removed 2026-07-19 -- see module docstring. Table
    is now the default view (was Smart)."""

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "tasks-view")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._quick_add = TaskQuickAdd()
        self._quick_add.task_created.connect(self._on_quick_add_created)
        layout.addWidget(self._quick_add)

        # Toolbar: view switcher only now (the old filter dropdown moved
        # into the Table view itself as a chip bar -- see table_view.py).
        toolbar = QWidget()
        toolbar.setProperty("class", "cal-view-switcher")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(8)
        tb_layout.addStretch(1)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_names = ["table", "timeline", "board"]
        for label, key in [("Table", "table"), ("Timeline", "timeline"), ("Board", "board")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "table")
            btn.setProperty("class", "cal-view-btn")
            self._view_group.addButton(btn, self._view_names.index(key))
            tb_layout.addWidget(btn)
        self._view_group.idClicked.connect(self._on_view_switched)

        layout.addWidget(toolbar)

        # Stacked widget for views
        self._stack = QStackedWidget()

        from .table_view import TaskTableView
        self._table_view = TaskTableView()
        self._table_view.open_object_requested.connect(self.open_object_requested)
        self._stack.addWidget(self._table_view)

        from .timeline_view import TimelineView
        self._timeline_view = TimelineView()
        self._timeline_view.task_rescheduled.connect(self._on_timeline_rescheduled)
        self._timeline_view.context_action.connect(self._on_task_context_action)
        self._stack.addWidget(self._timeline_view)

        from .kanban_view import KanbanBoard
        self._kanban_board = KanbanBoard()
        self._kanban_board.open_object_requested.connect(self.open_object_requested)
        self._stack.addWidget(self._kanban_board)

        layout.addWidget(self._stack, 1)

        self._all_objects: list[Object] = []

    def set_file_repo(self, repo: FileRepository) -> None:
        self._quick_add.set_file_repo(repo)

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = objects
        self._table_view.set_objects(objects)
        self._timeline_view.set_objects(objects)
        self._kanban_board.set_objects(objects)

    def _on_quick_add_created(self, obj: Object) -> None:
        self._all_objects.append(obj)
        self.set_objects(self._all_objects)

    def _on_task_context_action(self, object_id: str, action: str) -> None:
        """Handles the right-click menu shared by the Timeline bar (Table
        and Kanban have their own row/card context menus).

        2026-07-20 fix (carried over): duplicate/delete/status never
        actually wrote anything to disk -- each branch only mutated
        `_all_objects` (an in-memory Python list) and re-rendered via
        `set_objects`, so a status change, a duplicate, or a delete looked
        like it worked for the rest of the session and silently reverted
        on the next restart. Exactly the same class of bug as the
        2026-07-18 Kanban-drag/Timeline-drag persistence fix (see
        `../boards.md`/`../tasks.md`).

        2026-07-19 rework: status changes now also set `progress` via
        `progress_for_status()` -- progress is derived from status, not
        independently editable anywhere in the app anymore.
        """
        from ...core.models import progress_for_status

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
                    progress=src.progress,
                    due_at=src.due_at,
                    start_at=src.start_at,
                    parent_id=src.parent_id,
                    tags=list(src.tags) if src.tags else [],
                    created_at=now,
                    updated_at=now,
                )
                FileRepository().write_object(dup)
                self._all_objects.append(dup)
                self.set_objects(self._all_objects)
        elif action == "delete":
            FileRepository().delete_object(object_id)
            self._all_objects = [o for o in self._all_objects if o.id != object_id]
            self.set_objects(self._all_objects)
        elif action.startswith("status:"):
            from datetime import datetime, timezone
            new_status = action.split(":", 1)[1]
            for o in self._all_objects:
                if o.id == object_id:
                    o.status = new_status
                    o.progress = progress_for_status(new_status)
                    o.updated_at = datetime.now(timezone.utc).isoformat()
                    FileRepository().write_object(o)
                    break
            self.set_objects(self._all_objects)

    def _on_timeline_rescheduled(self, object_id: str, start_at: str, due_at: str) -> None:
        self._table_view.set_objects(self._all_objects)

    def _on_view_switched(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        objects = self._all_objects
        if idx == 0:
            self._table_view.set_objects(objects)
        elif idx == 1:
            self._timeline_view.set_objects(objects)
        elif idx == 2:
            self._kanban_board.set_objects(objects)
