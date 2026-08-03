"""Kanban board as a Task view — columns by status with drag-and-drop."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QMimeData, Signal
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType, progress_for_status
from ...core.utils.date_utils import relative_date_label
from ...features.settings.widgets import load_settings, save_settings

BOARD_COLUMNS = [
    ("Todo", ObjectStatus.active),
    ("In Progress", ObjectStatus.in_progress),
    ("Waiting", ObjectStatus.waiting),
    ("Done", ObjectStatus.done),
]

CARD_MIME = "application/x-commandcenter-card"

# Customizable card "frontmatter" -- which fields render on a kanban card
# (2026-07-19 rework: previously fixed to priority/due-date/tags, no way
# to add/remove any of them). (key, label, default-on).
CARD_FIELDS = [
    ("priority", "Priority", True),
    ("due_at", "Due date", True),
    ("project", "Project", False),
    ("tags", "Tags", True),
]
_CARD_FIELD_KEYS = [f[0] for f in CARD_FIELDS]
CARD_FIELDS_SETTINGS_KEY = "kanban_card_fields"


def _load_card_fields() -> set[str]:
    settings = load_settings()
    saved = settings.get(CARD_FIELDS_SETTINGS_KEY)
    if isinstance(saved, list):
        valid = [k for k in saved if k in _CARD_FIELD_KEYS]
        return set(valid)
    return {k for k, _label, default in CARD_FIELDS if default}


def _save_card_fields(fields: set[str]) -> None:
    settings = load_settings()
    settings[CARD_FIELDS_SETTINGS_KEY] = [k for k in _CARD_FIELD_KEYS if k in fields]
    save_settings(settings)


class _KanbanCard(QFrame):
    """A draggable card in a kanban column."""

    card_action = Signal(str, str)  # object_id, action ("edit"|"duplicate"|"delete"|"status:xxx")

    def __init__(self, obj: Object, visible_fields: set[str] | None = None, project_title: str = "", parent=None) -> None:
        super().__init__(parent)
        self._object_id = obj.id
        self._obj = obj
        self.setProperty("class", "kanban-card")
        fields = visible_fields if visible_fields is not None else _load_card_fields()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        title = QLabel(obj.title)
        title.setProperty("class", "kanban-card-title")
        title.setWordWrap(True)
        layout.addWidget(title)

        meta = QHBoxLayout()
        meta.setSpacing(4)
        if "priority" in fields and obj.priority:
            p = QLabel(f"P{obj.priority}")
            p.setProperty("class", f"priority-{obj.priority}")
            meta.addWidget(p)
        if "due_at" in fields and obj.due_at:
            d = QLabel(relative_date_label(obj.due_at))
            d.setProperty("class", "kanban-card-due")
            meta.addWidget(d)
        if "project" in fields and project_title:
            proj = QLabel(project_title)
            proj.setProperty("class", "kanban-card-due")
            meta.addWidget(proj)
        meta.addStretch()
        layout.addLayout(meta)

        if "tags" in fields and obj.tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(2)
            for t in obj.tags[:3]:
                chip = QLabel(t)
                chip.setProperty("class", "tag-chip")
                tag_row.addWidget(chip)
            if len(obj.tags) > 3:
                more = QLabel(f"+{len(obj.tags)-3}")
                more.setProperty("class", "kanban-card-due")
                tag_row.addWidget(more)
            tag_row.addStretch()
            layout.addLayout(tag_row)

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
        self.card_action.emit(self._object_id, "edit")
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setProperty("class", "object-context-menu")

        open_a = QAction("   Open", self)
        open_a.triggered.connect(lambda: self.card_action.emit(self._object_id, "edit"))
        menu.addAction(open_a)

        menu.addSeparator()

        status_menu = menu.addMenu("   Move to")
        statuses = [("Todo", "active"), ("In Progress", "in_progress"), ("Waiting", "waiting"), ("Done", "done")]
        for title, s in statuses:
            if s != self._obj.status:
                sa = QAction(title, self)
                sa.triggered.connect(lambda checked, v=s: self.card_action.emit(self._object_id, f"status:{v}"))
                status_menu.addAction(sa)

        dup_a = QAction("   Duplicate", self)
        dup_a.triggered.connect(lambda: self.card_action.emit(self._object_id, "duplicate"))
        menu.addAction(dup_a)

        menu.addSeparator()

        del_a = QAction("   Delete", self)
        del_a.triggered.connect(lambda: self.card_action.emit(self._object_id, "delete"))
        menu.addAction(del_a)

        menu.exec(event.globalPos())


class _KanbanColumn(QFrame):
    """A single kanban column: header + card list + add button."""

    def __init__(self, title: str, status: str, parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._status = status
        self.setProperty("class", "kanban-column")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._header = QLabel(f"{title}  (0)")
        self._header.setProperty("class", "kanban-column-header")
        # Fixed vertical policy is the actual fix for the "huge dead space
        # above the cards" bug: a plain QLabel's default vertical size
        # policy is Preferred, which *allows* it to grow past its own
        # sizeHint. In a QVBoxLayout with no explicit stretch item, Qt
        # hands leftover vertical space to whichever item's policy permits
        # growing -- here, with an empty/short card list and a QLineEdit
        # that's already Fixed, the header was the only candidate, so it
        # silently absorbed the *entire* unused column height (confirmed by
        # inspecting real geometry: the header's sizeHint was 17px tall but
        # its actual allocated rect was up to 549px). Capping it to Fixed
        # forces the explicit addStretch() below to claim that space
        # instead, which is where it visually belongs (below the cards,
        # above the add-card input) rather than as an invisible gap between
        # the header and the first card.
        self._header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._header)

        self._card_list = QVBoxLayout()
        self._card_list.setSpacing(3)
        layout.addLayout(self._card_list)
        layout.addStretch(1)

        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("+ Add card …")
        self._add_input.setProperty("class", "quick-add-input")
        self._add_input.returnPressed.connect(self._commit_add)
        layout.addWidget(self._add_input)

    @property
    def status(self) -> str:
        return self._status

    def set_cards(self, objects: list[Object]) -> None:
        while self._card_list.count():
            item = self._card_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parent_view = self._find_parent()
        fields = parent_view.card_fields() if parent_view else _load_card_fields()
        for obj in objects:
            project_title = parent_view.project_title(obj) if parent_view else ""
            card = _KanbanCard(obj, visible_fields=fields, project_title=project_title)
            if parent_view:
                card.card_action.connect(parent_view._on_card_action)
            self._card_list.addWidget(card)

        self._header.setText(f"{self._title}  ({len(objects)})")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        raw = event.mimeData().data(CARD_MIME).data()
        if not raw:
            return
        object_id = raw.decode("utf-8")
        parent_view = self._find_parent()
        if parent_view:
            parent_view._move_card(object_id, self._status)

    def _find_parent(self):
        p = self.parent()
        while p:
            if isinstance(p, KanbanBoard):
                return p
            p = p.parent()
        return None

    def _commit_add(self) -> None:
        text = self._add_input.text().strip()
        if not text:
            return
        self._add_input.clear()
        parent_view = self._find_parent()
        if parent_view:
            parent_view._add_card(text, self._status)


class KanbanBoard(QScrollArea):
    """Kanban board view — can be used standalone or as a task view."""

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "boards-view")
        self._all_objects: list[Object] = []
        self._card_fields: set[str] = _load_card_fields()

        container = QWidget()
        self.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QFrame()
        toolbar.setProperty("class", "cal-view-switcher")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.addStretch(1)
        self._fields_btn = QPushButton("⚙ Card fields")
        self._fields_btn.setProperty("class", "cal-view-btn")
        self._fields_btn.clicked.connect(self._show_card_fields_menu)
        tb_layout.addWidget(self._fields_btn)
        outer.addWidget(toolbar)

        columns_container = QWidget()
        columns_layout = QHBoxLayout(columns_container)
        columns_layout.setContentsMargins(8, 4, 8, 4)
        columns_layout.setSpacing(8)
        outer.addWidget(columns_container, 1)

        self._columns: list[_KanbanColumn] = []
        for title, status in BOARD_COLUMNS:
            col = _KanbanColumn(title, status)
            columns_layout.addWidget(col, 1)
            self._columns.append(col)

    def card_fields(self) -> set[str]:
        return self._card_fields

    def project_title(self, obj: Object) -> str:
        if not obj.parent_id:
            return ""
        parent = next((o for o in self._all_objects if o.id == obj.parent_id), None)
        return parent.title if parent else ""

    def _show_card_fields_menu(self) -> None:
        """Per-card "frontmatter" customization -- toggle which fields
        (priority/due date/project/tags) render on every kanban card,
        persisted so it survives a restart (2026-07-19 rework)."""
        menu = QMenu(self)
        for key, label, _default in CARD_FIELDS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key in self._card_fields)
            action.triggered.connect(lambda checked, k=key: self._toggle_card_field(k, checked))
        menu.exec(self._fields_btn.mapToGlobal(self._fields_btn.rect().bottomLeft()))

    def _toggle_card_field(self, key: str, visible: bool) -> None:
        if visible:
            self._card_fields.add(key)
        else:
            self._card_fields.discard(key)
        _save_card_fields(self._card_fields)
        self._refresh()

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = objects
        self._refresh()

    def _refresh(self) -> None:
        for col in self._columns:
            col_objs = [o for o in self._all_objects if o.type == ObjectType.task and o.status == col.status]
            col.set_cards(col_objs)

    def _move_card(self, object_id: str, new_status: str) -> None:
        """Persist a drag-between-columns status change.

        Previously only mutated the in-memory Object and re-rendered --
        never wrote to disk, so the status reverted on reindex/restart
        (same class of bug as the calendar week/day resize -- see
        STRESS_TEST_2026-07-17.md and calendar/widgets.py).
        """
        for o in self._all_objects:
            if o.id == object_id:
                o.status = new_status
                o.progress = progress_for_status(new_status)
                o.updated_at = datetime.now(timezone.utc).isoformat()
                FileRepository().write_object(o)
                break
        self._refresh()

    def _add_card(self, title: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        obj = Object(
            id=str(uuid.uuid4()),
            type=ObjectType.task,
            title=title,
            status=status,
            progress=progress_for_status(status),
            created_at=now,
            updated_at=now,
        )
        self._all_objects.append(obj)
        self._refresh()

    def _on_card_action(self, object_id: str, action: str) -> None:
        """2026-07-20 fix: duplicate/delete/status never wrote to disk --
        each branch only mutated `_all_objects` and re-rendered, so the
        change reverted on the next restart. Same bug, same fix, as
        `TasksView._on_task_context_action` in `widgets.py` (the drag
        handler `_move_card` above was already correct -- only these
        right-click-menu actions were missed)."""
        if action == "edit":
            self.open_object_requested.emit(object_id)
        elif action == "duplicate":
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
                self._refresh()
        elif action == "delete":
            FileRepository().delete_object(object_id)
            self._all_objects = [o for o in self._all_objects if o.id != object_id]
            self._refresh()
        elif action.startswith("status:"):
            new_status = action.split(":", 1)[1]
            for o in self._all_objects:
                if o.id == object_id:
                    o.status = new_status
                    o.progress = progress_for_status(new_status)
                    o.updated_at = datetime.now(timezone.utc).isoformat()
                    FileRepository().write_object(o)
                    break
            self._refresh()
