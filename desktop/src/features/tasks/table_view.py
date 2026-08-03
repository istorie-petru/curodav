"""TaskTableView — Notion-like editable database grid.

QTableView + QSortFilterProxyModel on top of a QAbstractTableModel.
Status/priority render as colored pills with formatted labels (not raw
enum text); project is a neutral badge. Progress is derived from status
(active=0%, in_progress=50%, waiting=90%, done/archived=100%) and is
display-only everywhere -- no manual progress editor exists anywhere in
the app anymore (see `core/models/object.py::progress_for_status`).
Column visibility/order is user-configurable (right-click a header, or
drag a header directly) and persisted. Deliberately does *not* open the
inspector/side panel from anywhere in this view -- editing happens only in
the table cells.

2026-07-19 rework: the Smart-list view's saved filters (Today/Upcoming/
All Open/High Priority/Waiting/Completed/Archived) moved here as a chip
filter bar (`TaskTableFilterBar`) above the grid, since the Smart view
itself was removed from the Tasks module (its "Today"/"Overdue" role went
to Dashboard instead -- see `features/tasks.md`).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QRectF, QTimer, Signal, QSortFilterProxyModel
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.design.tokens import is_dark, semantic_colors
from ...core.filerepo.repository import FileRepository
from ...core.models import Object, ObjectStatus, ObjectType, Priority, progress_for_status
from ...core.utils.date_utils import relative_date_label, today_str
from ...features.settings.widgets import load_settings, save_settings


# (key, header label, default-visible). "project" resolves to the parent
# task/project's title via TaskTableModel._project_title, not a raw field.
# "progress" is display-only (derived from status) -- see module docstring.
ALL_COLUMNS = [
    ("title", "Title", True),
    ("status", "Status", True),
    ("priority", "Priority", True),
    ("project", "Project", True),
    ("due_at", "Due date", True),
    ("progress", "Progress", True),
    ("tags", "Tags", True),
]
_COLUMN_KEYS = [c[0] for c in ALL_COLUMNS]
_COLUMN_LABELS = {c[0]: c[1] for c in ALL_COLUMNS}
SETTINGS_KEY = "tasks_table_columns"

STATUS_LABELS = {
    "active": "Active",
    "in_progress": "In Progress",
    "waiting": "Waiting",
    "done": "Done",
    "archived": "Archived",
}
PRIORITY_LABELS = {1: "P1 Urgent", 2: "P2 High", 3: "P3 Medium", 4: "P4 Low"}

# Smart filters, carried over from the old Tasks > Smart view (removed
# 2026-07-19) -- now a chip bar above this grid instead of a whole
# separate view. "Today"/"Overdue" also live on Dashboard now (that's the
# "integrated into Dashboard" half of the rework); the rest only exist here.
SMART_FILTERS = [
    ("Today", lambda o: o.due_at == today_str() and ObjectStatus.is_open(o.status)),
    ("Upcoming", lambda o: o.due_at and o.due_at > today_str() and ObjectStatus.is_open(o.status)),
    ("All Open", lambda o: ObjectStatus.is_open(o.status)),
    ("High Priority", lambda o: o.priority == Priority.urgent and ObjectStatus.is_open(o.status)),
    ("Waiting", lambda o: o.status == ObjectStatus.waiting),
    ("Completed", lambda o: o.status == ObjectStatus.done),
    ("Archived", lambda o: o.status == ObjectStatus.archived),
]
_DEFAULT_FILTER_INDEX = 2  # "All Open"


def _load_column_order() -> list[str]:
    """Persisted column key order (visible columns only, in display order).
    Falls back to every column, in ALL_COLUMNS' default order, if nothing's
    been customized yet or the saved value references columns that no
    longer exist."""
    settings = load_settings()
    saved = settings.get(SETTINGS_KEY)
    if isinstance(saved, list) and saved:
        valid = [k for k in saved if k in _COLUMN_KEYS]
        if valid:
            return valid
    return [c[0] for c in ALL_COLUMNS if c[2]]


def _save_column_order(keys: list[str]) -> None:
    settings = load_settings()
    settings[SETTINGS_KEY] = keys
    save_settings(settings)


class TaskTableFilterBar(QFrame):
    """Chip-style single-select filter row -- the Smart view's saved
    filters, relocated here (see module docstring). `filter_changed(idx)`
    emits an index into `SMART_FILTERS`."""

    filter_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "filter-bar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for idx, (name, _fn) in enumerate(SMART_FILTERS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(idx == _DEFAULT_FILTER_INDEX)
            btn.setProperty("class", "cal-view-btn")
            self._group.addButton(btn, idx)
            layout.addWidget(btn)
        layout.addStretch(1)
        self._group.idClicked.connect(self.filter_changed)

    def current_index(self) -> int:
        return self._group.checkedId()


class TaskTableModel(QAbstractTableModel):
    """Columns are dynamic (`self._columns`, a list of column keys in
    display order) rather than a fixed module-level list -- set by
    `TaskTableView` from the persisted column-order setting, and changed
    live from the header's right-click menu (show/hide/reorder) or by
    dragging a header directly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._objects: list[Object] = []
        self._all_objects: list[Object] = []  # for resolving "project" -> title
        self._columns: list[str] = [c[0] for c in ALL_COLUMNS if c[2]]

    def set_columns(self, keys: list[str]) -> None:
        self.beginResetModel()
        self._columns = [k for k in keys if k in _COLUMN_KEYS] or [c[0] for c in ALL_COLUMNS if c[2]]
        self.endResetModel()

    def columns(self) -> list[str]:
        return list(self._columns)

    def set_objects(self, objects: list[Object], all_objects: list[Object] | None = None) -> None:
        self.beginResetModel()
        self._objects = objects
        self._all_objects = all_objects if all_objects is not None else objects
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._objects)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def _col_key(self, col: int) -> str:
        if 0 <= col < len(self._columns):
            return self._columns[col]
        return ""

    def _project_title(self, obj: Object) -> str:
        if not obj.parent_id:
            return ""
        parent = next((o for o in self._all_objects if o.id == obj.parent_id), None)
        return parent.title if parent else ""

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        obj = self._objects[index.row()]
        key = self._col_key(index.column())

        if role == Qt.ItemDataRole.DisplayRole:
            if key == "project":
                return self._project_title(obj)
            if key == "status":
                return STATUS_LABELS.get(obj.status, obj.status)
            if key == "priority":
                return PRIORITY_LABELS.get(obj.priority, "") if obj.priority else ""
            if key == "due_at":
                return relative_date_label(obj.due_at)
            if key == "progress":
                # Always derived from status, never from a stored value the
                # user could edit directly -- see progress_for_status().
                return f"{int(progress_for_status(obj.status) * 100)}%"
            if key == "tags":
                return ", ".join(obj.tags) if obj.tags else ""
            return getattr(obj, key, None) or ""

        if role == Qt.ItemDataRole.EditRole:
            if key == "project":
                return self._project_title(obj)
            if key == "priority":
                return f"P{obj.priority}" if obj.priority else ""
            if key == "due_at":
                return obj.due_at or ""
            if key == "tags":
                return ", ".join(obj.tags) if obj.tags else ""
            val = getattr(obj, key, None)
            return val if val is not None else ""

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        obj = self._objects[index.row()]
        key = self._col_key(index.column())

        changed = False
        if key == "title":
            obj.title = str(value)
            changed = True
        elif key == "status" and value in ObjectStatus.core:
            obj.status = str(value)
            # Progress is derived from status, not independently editable
            # anywhere (table, kanban, inspector) -- see progress_for_status().
            obj.progress = progress_for_status(obj.status)
            changed = True
        elif key == "priority":
            try:
                p = int(value[-1]) if isinstance(value, str) and value.startswith("P") else int(value)
                if 1 <= p <= 4:
                    obj.priority = p
                    changed = True
                elif value in ("", None):
                    obj.priority = None
                    changed = True
            except (ValueError, TypeError):
                pass
        elif key == "project":
            match = next((o for o in self._all_objects if o.title == value and o.type == ObjectType.project), None)
            obj.parent_id = match.id if match else None
            changed = True
        elif key == "due_at":
            obj.due_at = str(value) if value else None
            changed = True
        elif key == "tags":
            obj.tags = [t.strip() for t in str(value).split(",") if t.strip()]
            changed = True

        if changed:
            from datetime import datetime, timezone
            obj.updated_at = datetime.now(timezone.utc).isoformat()
            FileRepository().write_object(obj)
            self.dataChanged.emit(index, index)
        return changed

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            key = self._col_key(section)
            return _COLUMN_LABELS.get(key, key)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        # Progress is read-only everywhere -- it's a pure function of
        # status, not a field the user edits (see progress_for_status()).
        if self._col_key(index.column()) == "progress":
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    def object_at(self, row: int) -> Object | None:
        if 0 <= row < len(self._objects):
            return self._objects[row]
        return None


_PILL_COLUMNS = ("status", "priority", "project")


class TaskTableDelegate(QStyledItemDelegate):
    """Dropdown-in-place-of-typing for the fixed-vocabulary columns
    (status/priority/project), and Notion-style colored pill rendering for
    those same three columns plus a colored badge for the (derived,
    read-only) progress column -- the "look like an actual Notion-style
    database, not raw enum text" rework (2026-07-19).

    `_resolve_key` maps through the `QSortFilterProxyModel` before asking
    for the column key -- `index.model()` on a row in a `QTableView` backed
    by a proxy returns the *proxy*, which has no `_col_key` method.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._available_projects: list[str] = []

    def set_available_projects(self, titles: list[str]) -> None:
        self._available_projects = titles

    def _resolve_key(self, index: QModelIndex) -> str:
        model = index.model()
        if isinstance(model, QSortFilterProxyModel):
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()
        else:
            source_index = index
            source_model = model
        if source_model is not None and hasattr(source_model, "_col_key"):
            return source_model._col_key(source_index.column())
        return ""

    def _resolve_object(self, index: QModelIndex) -> Object | None:
        model = index.model()
        if isinstance(model, QSortFilterProxyModel):
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()
        else:
            source_index = index
            source_model = model
        if source_model is not None and hasattr(source_model, "object_at"):
            return source_model.object_at(source_index.row())
        return None

    # ------------------------------------------------------------------ #
    # Pill colors -- reuses the same danger/warning/success tuning as the
    # rest of the app (core/design/tokens.py) rather than a separate
    # hardcoded palette, so pills stay legible in both light and dark mode.

    def _pill_color(self, key: str, obj: Object, widget: QWidget | None) -> QColor:
        dark = is_dark(widget) if widget is not None else False
        sem = semantic_colors(dark)
        if key == "status":
            return QColor({
                "active": "#8E8E93" if not dark else "#9A9AA0",
                "in_progress": "#3B82F6",
                "waiting": sem["warning"],
                "done": sem["success"],
                "archived": "#8E8E93",
            }.get(obj.status, "#8E8E93"))
        if key == "priority":
            return QColor({
                1: sem["danger"],
                2: sem["warning"],
                3: "#3B82F6",
                4: "#8E8E93",
            }.get(obj.priority, "#8E8E93"))
        if key == "project":
            return QColor("#8E8E93")
        if key == "progress":
            pct = progress_for_status(obj.status)
            if pct >= 1.0:
                return QColor(sem["success"])
            if pct >= 0.5:
                return QColor("#3B82F6")
            return QColor("#8E8E93")
        return QColor("#8E8E93")

    @staticmethod
    def _readable_text_color(bg: QColor) -> QColor:
        # Perceived luminance -- white text on dark/saturated pill colors,
        # dark text on pale ones. All the pill colors used here are
        # mid-to-dark, so this almost always resolves to white, but stays
        # correct if a paler color is ever added.
        luminance = 0.299 * bg.redF() + 0.587 * bg.greenF() + 0.114 * bg.blueF()
        return QColor("#1a1a1a") if luminance > 0.6 else QColor("#ffffff")

    def _paint_pill(self, painter, option, text: str, color: QColor) -> None:
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        fm = QFontMetrics(option.font)
        text_w = fm.horizontalAdvance(text)
        pad_h, pad_v = 10, 3
        pill_w = min(text_w + pad_h * 2, option.rect.width() - 8)
        pill_h = fm.height() + pad_v * 2
        rect = QRectF(
            option.rect.left() + 4,
            option.rect.center().y() - pill_h / 2,
            max(pill_w, 0),
            pill_h,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, pill_h / 2, pill_h / 2)
        painter.setPen(self._readable_text_color(color))
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - pad_h))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.restore()

    def paint(self, painter, option, index) -> None:
        key = self._resolve_key(index)
        obj = self._resolve_object(index)

        if key in _PILL_COLUMNS and obj is not None:
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            if text:
                color = self._pill_color(key, obj, option.widget)
                self._paint_pill(painter, option, str(text), color)
            return

        if key == "progress" and obj is not None:
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            color = self._pill_color("progress", obj, option.widget)
            self._paint_pill(painter, option, str(text), color)
            return

        super().paint(painter, option, index)
        if key in ("status", "priority", "project") and (option.state & QStyle.StateFlag.State_MouseOver):
            self._draw_dropdown_arrow(painter, option)

    def _draw_dropdown_arrow(self, painter, option) -> None:
        size = 12
        rect = option.rect
        arrow_rect = option.rect.__class__(rect.right() - size - 6, rect.center().y() - size // 2, size, size)
        arrow_opt = QStyleOptionViewItem(option)
        arrow_opt.rect = arrow_rect
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowDown, arrow_opt, painter, option.widget)

    def createEditor(self, parent, option, index):
        key = self._resolve_key(index)
        if key == "status":
            c = QComboBox(parent)
            c.addItems(["active", "in_progress", "waiting", "done", "archived"])
            QTimer.singleShot(0, c.showPopup)
            return c
        if key == "priority":
            c = QComboBox(parent)
            c.addItems(["", "P1", "P2", "P3", "P4"])
            QTimer.singleShot(0, c.showPopup)
            return c
        if key == "project":
            c = QComboBox(parent)
            c.setEditable(False)
            c.addItem("")
            c.addItems(self._available_projects)
            QTimer.singleShot(0, c.showPopup)
            return c
        if key == "tags":
            e = QLineEdit(parent)
            e.setPlaceholderText("tag1, tag2")
            from .tag_autocomplete import install_tag_completer
            install_tag_completer(e)
            return e
        return QLineEdit(parent)

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.EditRole) or ""
        if isinstance(editor, QComboBox):
            editor.setCurrentText(str(val) if val else "")
        else:
            editor.setText(str(val))

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        else:
            model.setData(index, editor.text())


class TaskTableView(QWidget):
    """Notion-like editable task grid: every field edits in place (dropdowns
    for status/priority/project, colored pills for their display), a
    Smart-filter chip bar up top, columns are user-configurable both via
    the header's right-click menu and by dragging a header directly, and
    both are persisted (`_load_column_order`/`_save_column_order`).

    Deliberately does **not** emit `open_object_requested` from anywhere
    in this view -- the signal is kept on the class only because
    `TasksView` still connects it for API-compatibility with the other
    views; the connection is simply never triggered from here.
    """

    open_object_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._filter_bar = TaskTableFilterBar()
        self._filter_bar.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self._filter_bar)

        self._model = TaskTableModel()
        self._model.set_columns(_load_column_order())
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setSortRole(Qt.ItemDataRole.DisplayRole)

        self._delegate = TaskTableDelegate(self)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setItemDelegate(self._delegate)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self._table.clicked.connect(self._table.edit)
        self._table.setMouseTracking(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_context_menu)

        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)
        # Notion-style drag-to-reorder columns, in addition to the
        # right-click "move left"/"move right" menu actions below.
        header.setSectionsMovable(True)
        header.sectionMoved.connect(self._on_section_dragged)

        layout.addWidget(self._table)

        self._all_tasks: list[Object] = []
        self._all_objects: list[Object] = []
        self._filter_idx = _DEFAULT_FILTER_INDEX

    def set_objects(self, objects: list[Object]) -> None:
        self._all_objects = objects
        self._all_tasks = [o for o in objects if o.type == ObjectType.task]
        project_titles = sorted(
            {o.title for o in objects if o.type == ObjectType.project and o.title}
        )
        self._delegate.set_available_projects(project_titles)
        self._apply_filter()

    def _apply_filter(self) -> None:
        _, smart_fn = SMART_FILTERS[self._filter_idx]
        filtered = [o for o in self._all_tasks if smart_fn(o)]
        self._model.set_objects(filtered, all_objects=self._all_objects)

    def _on_filter_changed(self, idx: int) -> None:
        self._filter_idx = idx
        self._apply_filter()

    def _on_section_dragged(self, logical_index: int, old_visual: int, new_visual: int) -> None:
        """Persist a drag-reordered header the same way the right-click
        "move left"/"move right" menu actions do -- resolve the header's
        current *visual* order back to column keys and hand it to
        `_apply_column_order`, which resets the model (making the new
        order the model's logical order too, so it survives a restart)."""
        header = self._table.horizontalHeader()
        new_order = []
        for visual in range(header.count()):
            logical = header.logicalIndex(visual)
            key = self._model._col_key(logical)
            if key:
                new_order.append(key)
        if new_order and new_order != self._model.columns():
            self._apply_column_order(new_order)

    def _show_column_menu(self, pos) -> None:
        """Right-click a header: toggle column visibility, or move a
        column left/right -- the customizable-columns half of the ask."""
        menu = QMenu(self)
        current = self._model.columns()
        clicked_col = self._table.horizontalHeader().logicalIndexAt(pos)
        clicked_key = self._model._col_key(clicked_col) if clicked_col >= 0 else None

        for key, label, _default in ALL_COLUMNS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key in current)
            action.triggered.connect(lambda checked, k=key: self._toggle_column(k, checked))

        if clicked_key:
            menu.addSeparator()
            idx = current.index(clicked_key)
            if idx > 0:
                left = menu.addAction(f"Move “{_COLUMN_LABELS[clicked_key]}” left")
                left.triggered.connect(lambda: self._move_column(clicked_key, -1))
            if idx < len(current) - 1:
                right = menu.addAction(f"Move “{_COLUMN_LABELS[clicked_key]}” right")
                right.triggered.connect(lambda: self._move_column(clicked_key, 1))

        menu.exec(self._table.horizontalHeader().viewport().mapToGlobal(pos))

    def _toggle_column(self, key: str, visible: bool) -> None:
        current = self._model.columns()
        if visible and key not in current:
            current.append(key)
        elif not visible and key in current:
            if len(current) == 1:
                return  # never hide the last visible column
            current.remove(key)
        self._apply_column_order(current)

    def _move_column(self, key: str, direction: int) -> None:
        current = self._model.columns()
        idx = current.index(key)
        new_idx = idx + direction
        if 0 <= new_idx < len(current):
            current[idx], current[new_idx] = current[new_idx], current[idx]
            self._apply_column_order(current)

    def _apply_column_order(self, keys: list[str]) -> None:
        self._model.set_columns(keys)
        _save_column_order(keys)

    def _show_row_context_menu(self, pos) -> None:
        from PySide6.QtGui import QAction

        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        src = self._proxy.mapToSource(index)
        obj = self._model.object_at(src.row())
        if not obj:
            return

        menu = QMenu(self)
        dup_a = QAction("Duplicate", self)
        dup_a.triggered.connect(self._duplicate_row)
        menu.addAction(dup_a)

        del_a = QAction("Delete", self)
        del_a.triggered.connect(lambda: self._delete_row(src.row()))
        menu.addAction(del_a)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _duplicate_row(self) -> None:
        import uuid, copy
        from datetime import datetime, timezone
        idx = self._table.currentIndex()
        src = self._proxy.mapToSource(idx)
        obj = self._model.object_at(src.row())
        if obj:
            dup = copy.deepcopy(obj)
            dup.id = str(uuid.uuid4())
            dup.title = f"{dup.title} (copy)"
            now = datetime.now(timezone.utc).isoformat()
            dup.created_at = now
            dup.updated_at = now
            FileRepository().write_object(dup)

    def _delete_row(self, row: int) -> None:
        obj = self._model.object_at(row)
        if obj:
            FileRepository().delete_object(obj.id)
