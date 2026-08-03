"""Main window and application setup.

QMainWindow with top navigation bar (icon-over-label module buttons, see
TopNav), a per-module title bar, content area, status bar, system tray,
WebDAV server, and Syncthing integration.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyleFactory,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .core.attachments import AttachmentStore
from .core.dav.server import WebDavServer
from .core.db.database import Database
from .core.design.tokens import is_dark, semantic_colors
from .core.export import (
    export_all_markdown,
    export_json,
    import_json,
    import_obsidian_vault,
)
from .core.filerepo.repository import FileRepository
from .core.models import Object, ObjectType
from .core.notifications import NotificationEngine
from .core.sync.syncthing_client import SyncthingClient
from .core.sync.watcher import FileWatcher
from .features.calendar import CalendarView
from .features.dashboard import DashboardView
from .features.tasks import TasksView
from .features.projects import ProjectDetailView, ProjectOverview
from .features.search import SearchView
from .features.search.command_palette import CommandPalette
from .features.settings import PreferencesDialog, load_settings, save_settings
from .widgets import InspectorPanel

MODULES = [
    ("DB", "Dashboard", "dashboard"),
    ("TK", "Tasks", "tasks"),
    ("CA", "Calendar", "calendar"),
    ("SR", "Search", "search"),
]


def _module_index(module_id: str) -> int:
    """Look up a module's position in MODULES by id, instead of a magic number.

    Several call sites used to hardcode an index (`_on_module_changed(4)` for
    "Notes") that drifted out of sync with MODULES and silently opened the
    wrong module. Looking it up by id makes that class of bug impossible.
    """
    for i, (_glyph, _name, mid) in enumerate(MODULES):
        if mid == module_id:
            return i
    raise ValueError(f"Unknown module id: {module_id}")


def _themed_icon(theme_name: str, fallback) -> QIcon:
    """A named icon from the desktop's icon theme (Breeze on Plasma, etc.),
    falling back to a Qt standard pixmap if the theme doesn't have it or no
    icon theme is available at all (e.g. headless/non-Linux). This is the
    native mechanism for "use the system's icons" -- no bundled icon assets."""
    style = QApplication.style()
    fallback_icon = style.standardIcon(fallback) if style else QIcon()
    return QIcon.fromTheme(theme_name, fallback_icon)


_MODULE_ICONS = {
    "dashboard": ("go-home", QStyle.StandardPixmap.SP_DirHomeIcon),
    "tasks": ("view-task", QStyle.StandardPixmap.SP_FileDialogDetailedView),
    "calendar": ("view-calendar", QStyle.StandardPixmap.SP_FileDialogContentsView),
    "search": ("edit-find", QStyle.StandardPixmap.SP_FileDialogContentsView),
    "projects": ("folder", QStyle.StandardPixmap.SP_DirIcon),
}


class TopNav(QWidget):
    """Horizontal top navigation: one QToolButton per module, icon over
    label (`ToolButtonTextUnderIcon`), icons from the system icon theme.

    Replaces the old Sidebar + BottomNav pair (2026-07-19) -- a single bar
    works at every window width, so there's no responsive sidebar/bottom-nav
    switch to maintain, and `ToolButtonTextUnderIcon` is a real, native Qt
    toolbar style (this is literally how Calibre's own toolbar renders)
    rather than a custom-drawn nav rail.
    """

    module_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "topnav")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        self._buttons: list[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        def add_button(module_id: str, name: str) -> None:
            theme_name, fallback = _MODULE_ICONS.get(
                module_id, ("application-x-executable", QStyle.StandardPixmap.SP_FileIcon)
            )
            btn = QToolButton()
            btn.setText(name)
            btn.setIcon(_themed_icon(theme_name, fallback))
            btn.setIconSize(QSize(22, 22))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            btn.setProperty("class", "topnav-btn")
            idx = len(self._buttons)
            btn.clicked.connect(lambda checked, i=idx: self.module_selected.emit(i))
            layout.addWidget(btn)
            self._buttons.append(btn)
            self._group.addButton(btn)

        for _glyph, name, module_id in MODULES:
            add_button(module_id, name)
        add_button("projects", "Projects")  # not in MODULES, appended after

        layout.addStretch(1)

        self._sync_indicator = QLabel("Local only")
        self._sync_indicator.setProperty("class", "sync-indicator")
        layout.addWidget(self._sync_indicator)

        self._clock_label = QLabel()
        self._clock_label.setProperty("class", "topnav-clock")
        layout.addWidget(self._clock_label)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

        self._buttons[0].setChecked(True)

    def _update_clock(self) -> None:
        self._clock_label.setText(datetime.now().strftime("%H:%M"))

    def set_active(self, idx: int) -> None:
        if 0 <= idx < len(self._buttons):
            self._buttons[idx].setChecked(True)

    def set_sync_status(self, text: str, connected: bool = False) -> None:
        mark = "Connected" if connected else "Local only"
        self._sync_indicator.setText(f"{mark} — {text}" if text else mark)


class TopBar(QWidget):
    """Module title + toolbar items (REWORK_PLAN §7.1)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "topbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)

        self._title_label = QLabel("Dashboard")
        self._title_label.setProperty("class", "topbar-title")
        layout.addWidget(self._title_label)

        layout.addStretch(1)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self) -> None:
        super().__init__()
        import locale
        try:
            locale.setlocale(locale.LC_TIME, "en_US.UTF-8")
        except locale.Error:
            try:
                locale.setlocale(locale.LC_TIME, "C")
            except locale.Error:
                pass
        self.setWindowTitle("Command Center")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

        self._all_objects: list[Object] = []
        self._settings: dict = {}
        self._webdav = WebDavServer()
        self._syncthing: SyncthingClient | None = None
        self._syncthing_timer = QTimer(self)
        self._syncthing_timer.timeout.connect(self._poll_syncthing)

        self._setup_ui()
        self._setup_actions()
        self._setup_menu_bar()
        self._attachments = AttachmentStore()
        self._notifications = NotificationEngine(tray_icon=None)
        self._setup_system_tray()
        self._seed_mock_data()
        self._init_data_pipeline()

        # Follow the system theme live -- Plasma (and GNOME/etc. via the Qt
        # platform theme plugin) reports color-scheme changes here without
        # needing a restart.
        style_hints = QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(lambda _scheme: self._apply_appearance())

    def _init_data_pipeline(self) -> None:
        # FileRepository()'s default base_path now reads Settings -> General
        # -> Folder path itself (core/filerepo/repository.py), so this
        # naturally picks up whatever the user configured -- that setting
        # used to be a no-op (STRESS_TEST_2026-07-17.md).
        self._file_repo = FileRepository()
        self._db = Database()
        self._db.open()
        self._db.rebuild_from_path(self._file_repo.base_path)

        # Bug (2026-07-18): _seed_mock_data() (called just before this, in
        # __init__) unconditionally set self._all_objects to a hardcoded
        # demo list. Nothing ever replaced it with what's actually on disk --
        # rebuild_from_path above only populates the SQLite *cache*, and nothing
        # in this file called FileRepository.iter_objects(). So every launch
        # silently discarded any real, previously-saved data and rendered the
        # same mock objects again, which is exactly why edits appeared to
        # "not save": they were written to object.json correctly, but the next
        # launch never read them back. Only load real objects if the folder
        # actually has any; otherwise keep the mock seed for a first-run/empty
        # folder.
        real_objects = self._file_repo.iter_objects()
        if real_objects:
            self._all_objects = real_objects

        self._file_watcher = FileWatcher(self._file_repo.base_path)
        self._file_watcher.start(
            on_modified=self._on_file_modified,
            on_created=self._on_file_created,
            on_deleted=self._on_file_deleted,
        )

        for module_id in ("dashboard", "tasks"):
            w = self._modules.get(module_id)
            if hasattr(w, "set_file_repo"):
                w.set_file_repo(self._file_repo)

        self._project_detail_view.set_file_repo(self._file_repo)

        self._modules["dashboard"]._quick_add.object_created.connect(self._on_object_created)
        tasks_w = self._modules.get("tasks")
        if hasattr(tasks_w, "_quick_add"):
            tasks_w._quick_add.task_created.connect(self._on_object_created)
        # Feature (2026-07-18): click-and-drag an empty Timeline cell to
        # create a task there. Unlike the quick-add path above, the new
        # task also needs its Inspector opened immediately -- see
        # _on_timeline_task_created.
        if hasattr(tasks_w, "_timeline_view"):
            tasks_w._timeline_view.task_created.connect(self._on_timeline_task_created)

        # Inspector
        self._inspector.set_file_repo(self._file_repo)
        self._inspector.set_db(self._db)
        self._inspector.object_saved.connect(self._on_inspector_saved)
        self._inspector.project_open_requested.connect(self._open_project_detail)

        # Tags tab (inside Preferences)
        self._preferences_dialog.set_db(self._db)

        # Wire open_object_requested from each module
        for module_id, w in self._modules.items():
            if hasattr(w, "open_object_requested"):
                w.open_object_requested.connect(self._open_inspector)

        # Whatever module rendered first did so with self._all_objects as it
        # stood before real_objects (above) replaced it -- push the final
        # list out now so the initial view reflects disk, not the mock seed.
        self._refresh_current_module()

    def _open_inspector(self, object_id: str) -> None:
        for obj in self._all_objects:
            if obj.id == object_id:
                self._inspector.open_object(obj)
                break

    def _on_inspector_saved(self, obj: Object) -> None:
        for i, o in enumerate(self._all_objects):
            if o.id == obj.id:
                self._all_objects[i] = obj
                break
        self._db.upsert_object(obj)
        self._status_bar.showMessage(f"Saved {obj.title}", 3000)
        self._refresh_current_module()

    def _on_object_created(self, obj: Object) -> None:
        if any(o.id == obj.id for o in self._all_objects):
            return
        self._all_objects.append(obj)
        self._db.upsert_object(obj)
        self._status_bar.showMessage(f"Created {obj.title}", 3000)
        self._update_status_counts()
        self._refresh_current_module()

    def _on_timeline_task_created(self, obj: Object) -> None:
        """Feature (2026-07-18): click-and-drag an empty Timeline cell to
        create a task there (TimelineCanvas._finish_create_drag). Reuses
        _on_object_created for the actual bookkeeping (append to
        _all_objects, upsert the SQLite cache, refresh the current
        module), then immediately opens the Inspector for it -- the whole
        point of this gesture is to jump straight into filling in the new
        task's details, not to leave a bare "New task" bar sitting there.
        _on_object_created must run first so _open_inspector can actually
        find the object by id in _all_objects."""
        self._on_object_created(obj)
        self._open_inspector(obj.id)

    def _update_status_counts(self) -> None:
        tasks = sum(1 for o in self._all_objects if o.type == ObjectType.task)
        events = sum(1 for o in self._all_objects if o.type == ObjectType.event)
        notes = sum(1 for o in self._all_objects if o.type == ObjectType.note)
        projects = sum(1 for o in self._all_objects if o.type == ObjectType.project)
        self._status_counts_label.setText(f"{tasks} tasks · {events} events · {notes} notes · {projects} projects")
        idx = self._content_stack.currentIndex()
        name = "Projects" if idx >= len(MODULES) else MODULES[idx][1]
        self.setWindowTitle(f"{name} — Command Center ({len(self._all_objects)} objects)")

    def _on_file_created(self, object_id: str) -> None:
        QTimer.singleShot(0, lambda oid=object_id: self._handle_file_created(oid))

    def _on_file_modified(self, object_id: str) -> None:
        QTimer.singleShot(0, lambda oid=object_id: self._handle_file_modified(oid))

    def _on_file_deleted(self, object_id: str) -> None:
        QTimer.singleShot(0, lambda oid=object_id: self._handle_file_deleted(oid))

    def _handle_file_created(self, object_id: str) -> None:
        obj = self._file_repo.read_object(object_id)
        if obj is not None:
            self._db.upsert_object(obj)
            if not any(o.id == obj.id for o in self._all_objects):
                self._all_objects.append(obj)
                self._refresh_current_module()

    def _handle_file_modified(self, object_id: str) -> None:
        obj = self._file_repo.read_object(object_id)
        if obj is not None:
            self._db.upsert_object(obj)
            for i, o in enumerate(self._all_objects):
                if o.id == obj.id:
                    self._all_objects[i] = obj
                    break
            self._refresh_current_module()

    def _handle_file_deleted(self, object_id: str) -> None:
        self._db.delete_object(object_id)
        self._all_objects = [o for o in self._all_objects if o.id != object_id]
        self._refresh_current_module()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        # Top-to-bottom: TopNav (full-width, module switcher) above
        # everything else, not a side rail -- this used to be a QHBoxLayout
        # with TopNav as the first item alongside the rest of the window,
        # which put it in the *sidebar* position even though TopNav's own
        # internal layout is horizontal (its buttons sit side by side, but
        # the widget itself was still being placed to the left of the
        # content rather than above it).
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._topnav = TopNav()
        root_layout.addWidget(self._topnav)

        self._topbar = TopBar()
        root_layout.addWidget(self._topbar)

        self._content_stack = QStackedWidget()
        self._content_stack.setProperty("class", "content-area")

        # QSplitter (not a plain QHBoxLayout) so the inspector panel is
        # user-resizable via a drag handle -- it previously had a hard
        # setFixedWidth(380) with no way to make it wider/narrower.
        # Width is remembered across restarts (settings.json
        # "inspector_width", see _on_inspector_splitter_moved below and
        # Settings -> Inspector).
        self._content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._content_splitter.setChildrenCollapsible(False)
        self._content_splitter.setHandleWidth(4)
        self._content_splitter.addWidget(self._content_stack)
        self._inspector = InspectorPanel()
        self._content_splitter.addWidget(self._inspector)
        self._content_splitter.setStretchFactor(0, 1)
        self._content_splitter.setStretchFactor(1, 0)
        saved_width = load_settings().get("inspector_width", 380)
        self._inspector.setMinimumWidth(280)
        self._inspector.setMaximumWidth(640)
        # Give the splitter an initial split; content_stack gets whatever's
        # left. Actual pixel sizes are only meaningful once the window has
        # a real geometry, so this is a reasonable starting guess -- Qt
        # clamps to available space on first show regardless.
        self._content_splitter.setSizes([1000, saved_width])
        self._content_splitter.splitterMoved.connect(self._on_inspector_splitter_moved)
        root_layout.addWidget(self._content_splitter, 1)

        self._status_bar = QStatusBar()
        self._status_bar.setProperty("class", "status-bar")
        self._status_bar.showMessage("Ready")
        self._status_counts_label = QLabel("")
        self._status_counts_label.setProperty("class", "inspector-field-label")
        self._status_bar.addPermanentWidget(self._status_counts_label)
        self._status_shortcuts_label = QLabel("Ctrl+K palette \u00b7 Alt+1 task \u00b7 Alt+3 event \u00b7 Ctrl+F search")
        self._status_shortcuts_label.setProperty("class", "inspector-field-label")
        self._status_bar.addPermanentWidget(self._status_shortcuts_label)
        root_layout.addWidget(self._status_bar)

        self._modules: dict[str, QWidget] = {}
        self._module_widgets: list[QWidget] = []

        dashboard = DashboardView()
        self._modules["dashboard"] = dashboard
        self._module_widgets.append(dashboard)

        tasks = TasksView()
        self._modules["tasks"] = tasks
        self._module_widgets.append(tasks)

        calendar = CalendarView()
        self._modules["calendar"] = calendar
        self._module_widgets.append(calendar)

        search = SearchView()
        self._modules["search"] = search
        self._module_widgets.append(search)

        # Preferences is a popup window, not a module in the content stack --
        # see PreferencesDialog docstring. Created here (not lazily) so its
        # settings_changed/reindex_requested/etc. signals are wired up from
        # app start, same as before.
        self._preferences_dialog = PreferencesDialog(self)
        self._preferences_dialog.settings_changed.connect(self._on_settings_changed)
        self._preferences_dialog.reindex_requested.connect(self._on_reindex)
        self._preferences_dialog.export_requested.connect(self._on_export)
        self._preferences_dialog.import_requested.connect(self._on_import)

        project_overview = ProjectOverview()
        self._modules["projects"] = project_overview
        self._module_widgets.append(project_overview)

        self._project_detail_view = ProjectDetailView()
        self._project_detail_view.open_object_requested.connect(self._open_inspector)
        self._project_detail_view.set_go_back_callback(self._on_project_back)

        for w in self._module_widgets:
            self._content_stack.addWidget(w)
        self._content_stack.addWidget(self._project_detail_view)

        project_overview.open_project_requested.connect(self._open_project_detail)
        project_overview.open_object_requested.connect(self._open_inspector)

        self._topnav.module_selected.connect(self._on_module_changed)

        self._apply_stored_settings()

    def _setup_actions(self) -> None:
        """Create every QAction once, as attributes, so both global keyboard
        shortcuts (`self.addAction`) and the menu bar (`_setup_menu_bar`)
        share the same instances -- one shortcut definition per action,
        shown correctly in whichever menu ends up hosting it (including
        Plasma's global menu, which reads the actions straight off the
        QMenuBar)."""

        def make(text: str, shortcut: str | None, slot) -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)
            return action

        self._action_palette = make("Command Palette…", "Ctrl+K", self._open_command_palette)
        self._action_new_task = make("New Task", "Alt+1", self._focus_quick_add)
        self._action_new_event = make("New Event", "Alt+3", self._new_event)
        self._action_focus_search = make("Focus Search", "Ctrl+F", self._focus_search)
        self._action_import = make("Import…", None, self._on_import)
        self._action_export = make("Export…", None, self._on_export)
        self._action_quit = make("Quit", "Ctrl+Q", self.close)
        self._action_reindex = make("Reindex SQLite Cache", None, self._on_reindex)
        self._action_toggle_topnav = make("Toggle Navigation Bar", "Ctrl+B", self._toggle_topnav)
        self._action_preferences = make("Preferences…", "Ctrl+,", self._open_preferences)
        self._action_about = make("About Command Center", None, self._show_about)

        self._module_actions: dict[str, QAction] = {}
        for _glyph, name, module_id in MODULES:
            act = make(name, None, lambda checked=False, mid=module_id: self._on_module_changed(_module_index(mid)))
            self._module_actions[module_id] = act
        self._action_projects = make("Projects", None, lambda: self._on_module_changed(len(MODULES)))

    def _setup_menu_bar(self) -> None:
        """A real QMenuBar -- on Plasma (with appmenu-qt6/kf6 and the global
        menu widget enabled) Qt routes this into the global menu bar
        automatically; there's no separate "global menu" API to call. This
        also gives every action above a discoverable home, not just a
        keyboard shortcut."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._action_new_task)
        file_menu.addAction(self._action_new_event)
        file_menu.addSeparator()
        file_menu.addAction(self._action_import)
        file_menu.addAction(self._action_export)
        file_menu.addSeparator()
        file_menu.addAction(self._action_quit)

        view_menu = menu_bar.addMenu("&View")
        for _glyph, _name, module_id in MODULES:
            view_menu.addAction(self._module_actions[module_id])
        view_menu.addAction(self._action_projects)
        view_menu.addSeparator()
        view_menu.addAction(self._action_focus_search)
        view_menu.addAction(self._action_palette)
        view_menu.addAction(self._action_toggle_topnav)

        tools_menu = menu_bar.addMenu("&Tools")
        tools_menu.addAction(self._action_reindex)

        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self._action_preferences)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self._action_about)

    def _toggle_topnav(self) -> None:
        self._topnav.setVisible(not self._topnav.isVisible())

    def _open_preferences(self) -> None:
        self._preferences_dialog.open_on_section("General")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Command Center",
            "<b>Command Center</b><br>"
            "Personal command center — unified object model, offline-first.<br><br>"
            "Version 0.1.0",
        )

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setToolTip("Command Center")
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

        self._notifications = NotificationEngine(tray_icon=self._tray_icon)
        self._notifications.start()

    def _on_tray_activated(self, reason: int) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()

    def _on_module_changed(self, row: int) -> None:
        if 0 <= row < len(MODULES):
            _glyph, name, _ = MODULES[row]
            self._topbar.set_title(name)
            self._content_stack.setCurrentIndex(row)
            self._refresh_current_module()
            self._topnav.set_active(row)
        elif row == len(MODULES):
            self._topbar.set_title("Projects")
            self._content_stack.setCurrentIndex(row)
            self._refresh_current_module()
            self._topnav.set_active(row)

    def _open_project_detail(self, project_id: str) -> None:
        idx = len(MODULES) + 1
        self._content_stack.setCurrentIndex(idx)
        self._project_detail_view.load_project(project_id, self._all_objects)
        self._project_detail_view.show()

    def _on_project_back(self) -> None:
        self._content_stack.setCurrentIndex(len(MODULES))
        self._topbar.set_title("Projects")
        self._refresh_current_module()

    def _refresh_current_module(self) -> None:
        from .features.shared.tag_names import refresh_known_tags
        refresh_known_tags(self._all_objects)

        idx = self._content_stack.currentIndex()
        if idx < 0 or idx >= len(self._module_widgets):
            return
        if idx < len(MODULES):
            _, _, module_id = MODULES[idx]
            w = self._modules.get(module_id)
        else:
            w = self._module_widgets[idx] if idx < len(self._module_widgets) else None
        if hasattr(w, "set_objects"):
            w.set_objects(self._all_objects)
        if hasattr(self, "_notifications"):
            self._notifications.check_now(self._all_objects)
        self._update_status_counts()

    def _seed_mock_data(self) -> None:
        today = date.today().isoformat()

        def iso(n: int) -> str:
            return (date.today() + timedelta(days=n)).isoformat()

        self._all_objects = [
            Object(id="1", type=ObjectType.task, title="Review BAC submission",
                   status="active", priority=1, due_at=today,
                   created_at=iso(-5), updated_at=iso(-1)),
            Object(id="2", type=ObjectType.task, title="Prepare FIUB slides",
                   status="in_progress", priority=2, due_at=iso(1),
                   created_at=iso(-3), updated_at=today),
            Object(id="3", type=ObjectType.task, title="Order lab supplies",
                   status="waiting", priority=3, due_at=iso(-2),
                   created_at=iso(-10), updated_at=iso(-2)),
            Object(id="4", type=ObjectType.task, title="Update CV",
                   status="active", due_at=iso(5),
                   created_at=iso(-20), updated_at=iso(-1)),
            Object(id="5", type=ObjectType.task, title="Fix CI pipeline",
                   status="done", priority=1, due_at=iso(-1),
                   created_at=iso(-7), updated_at=iso(-1)),
            Object(id="6", type=ObjectType.task, title="Write meeting notes",
                   status="active", due_at=iso(3), pinned=True,
                   created_at=today, updated_at=today),
            Object(id="7", type=ObjectType.event, title="Team standup",
                   status="active", due_at=today, start_at=f"{today}T09:30:00",
                   created_at=iso(-30), updated_at=today,
                   details={"end_at": f"{today}T10:00:00"}),
            Object(id="8", type=ObjectType.event, title="Dentist appointment",
                   status="done", due_at=iso(-3),
                   created_at=iso(-60), updated_at=iso(-3)),
            Object(id="19", type=ObjectType.event, title="Lunch with team",
                   status="active", due_at=today, start_at=f"{today}T12:00:00",
                   created_at=iso(-5), updated_at=today,
                   details={"end_at": f"{today}T13:30:00"}),
            Object(id="20", type=ObjectType.event, title="Project review",
                   status="active", due_at=iso(1), start_at=f"{iso(1)}T14:00:00",
                   created_at=iso(-10), updated_at=today,
                   details={"end_at": f"{iso(1)}T15:30:00"}),
            Object(id="9", type=ObjectType.project, title="Command Center",
                   status="in_progress",
                   created_at=iso(-90), updated_at=today,
                   description="Personal command center app"),
            Object(id="11", type=ObjectType.task, title="Prepare annual review",
                   status="active", priority=2, due_at=iso(14),
                   created_at=iso(-2), updated_at=today),
            Object(id="12", type=ObjectType.task, title="Read Pragmatic Programmer",
                   status="active", progress=0.3,
                   created_at=iso(-30), updated_at=iso(-5)),
            Object(id="16", type=ObjectType.goal, title="Ship v1.0",
                   status="active", progress=0.45,
                   created_at=iso(-60), updated_at=iso(-5)),
            Object(id="17", type=ObjectType.goal, title="10 active users",
                   status="in_progress", progress=0.2,
                   created_at=iso(-30), updated_at=today),
            Object(id="18", type=ObjectType.goal, title="Zero data loss incidents",
                   status="active", progress=0.8,
                   created_at=iso(-90), updated_at=iso(-10)),
        ]
        self._refresh_current_module()

    def _apply_stored_settings(self) -> None:
        if hasattr(self, "_preferences_dialog"):
            self._settings = self._preferences_dialog.get_settings()
            self._apply_appearance(self._settings)
            self._apply_webdav(self._settings)
            self._apply_syncthing(self._settings)

    def _on_settings_changed(self, settings: dict) -> None:
        folder_changed = (
            hasattr(self, "_file_repo")
            and settings.get("folder_path")
            and Path(settings["folder_path"]) != self._file_repo.base_path
        )
        self._settings = settings
        self._apply_appearance(settings)
        restart_webdav = (
            settings.get("webdav_enabled") != self._webdav.is_running
            or settings.get("webdav_port") != self._webdav.port
            or settings.get("webdav_lan") != self._webdav.lan_mode
        )
        if restart_webdav:
            self._apply_webdav(settings)
        self._apply_syncthing(settings)
        if folder_changed:
            self._status_bar.showMessage(
                "Settings saved — restart Command Center to switch to the new data folder", 8000
            )
        else:
            self._status_bar.showMessage("Settings saved", 3000)

    def _apply_appearance(self, settings: dict | None = None) -> None:
        """Apply the chosen Qt Style (if any), then rebuild the stylesheet
        from the live palette.

        Color/theme itself is not a setting on purpose -- it follows the
        desktop (Plasma/GNOME/etc.) automatically, including live updates
        via QGuiApplication's colorSchemeChanged signal. Qt Style *is*
        still a setting (restored 2026-07-18 after being wrongly removed
        alongside the dead Theme/Density/Shape/Accent controls the day
        before -- see features/settings.md): it's how someone runs the app
        under a specific installed style, e.g. Darkly, instead of whatever
        the platform default is. The two compose correctly -- setStyle
        applies that style's own palette, and _generate_qss reads colors
        via palette() regardless of which style is active.
        """
        settings = settings or {}
        style_name = settings.get("qt_style", "")
        app = QApplication.instance()
        if app is not None and style_name:
            try:
                style = QStyleFactory.create(style_name)
                if style is not None:
                    app.setStyle(style)
            except Exception:
                pass
        self.setStyleSheet(self._generate_qss())

    def _on_inspector_splitter_moved(self, pos: int, index: int) -> None:
        """Persist the inspector panel's width whenever the user drags the
        splitter handle. Debounced via a single-shot timer restarted on
        every call, so a drag that fires this dozens of times only writes
        to disk once, ~250ms after the user stops moving the handle."""
        if not hasattr(self, "_inspector_width_save_timer"):
            self._inspector_width_save_timer = QTimer(self)
            self._inspector_width_save_timer.setSingleShot(True)
            self._inspector_width_save_timer.timeout.connect(self._save_inspector_width)
        self._inspector_width_save_timer.start(250)

    def _save_inspector_width(self) -> None:
        width = self._inspector.width()
        if width <= 0:
            return
        settings = load_settings()
        settings["inspector_width"] = width
        save_settings(settings)

    def _apply_webdav(self, settings: dict) -> None:
        if settings.get("webdav_enabled", False):
            self._webdav.port = settings.get("webdav_port", 8080)
            self._webdav.lan_mode = settings.get("webdav_lan", False)
            try:
                self._webdav.start()
            except OSError as exc:
                # e.g. port already in use -- start() now actually binds a
                # socket (see core/dav/server.py), so this is a real failure
                # mode worth surfacing instead of crashing app startup.
                self._status_bar.showMessage(
                    f"WebDAV failed to start on port {self._webdav.port}: {exc}", 8000
                )
                return
            self._status_bar.showMessage(
                f"WebDAV: {self._webdav.connection_url}", 5000
            )
        else:
            self._webdav.stop()
            self._status_bar.showMessage("WebDAV stopped", 3000)

    def _apply_syncthing(self, settings: dict) -> None:
        if settings.get("syncthing_enabled", False):
            self._syncthing = SyncthingClient(
                api_key=settings.get("syncthing_api_key", ""),
                base_url=settings.get("syncthing_url", "http://127.0.0.1:8384"),
            )
            self._poll_syncthing()
            self._syncthing_timer.start(15000)
        else:
            self._syncthing = None
            self._syncthing_timer.stop()
            self._topnav.set_sync_status("P2P disabled")

    def _poll_syncthing(self) -> None:
        if not self._syncthing:
            return
        try:
            st = self._syncthing.status()
            if st.running:
                self._topnav.set_sync_status(
                    f"Syncthing • {st.version.split()[0]}", connected=True
                )
                self._status_bar.showMessage(
                    f"Syncthing: {st.device_count or '?'} devices, uptime {st.uptime}s",
                    5000,
                )
            else:
                self._topnav.set_sync_status("Syncthing not running")
        except Exception:
            self._topnav.set_sync_status("Syncthing not reachable")

    def _on_reindex(self) -> None:
        self._status_bar.showMessage("Reindexing SQLite cache…")
        count = self._db.rebuild_from_path(self._file_repo.base_path)
        self._status_bar.showMessage(f"Reindex complete — {count} objects cached", 3000)
        self._refresh_current_module()

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export data", "command_center_export.json", "JSON (*.json)"
        )
        if path:
            export_json(self._all_objects, Path(path))
            self._status_bar.showMessage(f"Exported {len(self._all_objects)} objects to {path}", 3000)

    def _on_import(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import data", "", "JSON (*.json)"
        )
        if path:
            imported = import_json(Path(path))
            existing_ids = {o.id for o in self._all_objects}
            new_count = 0
            for obj in imported:
                if obj.id not in existing_ids:
                    self._all_objects.append(obj)
                    existing_ids.add(obj.id)
                    new_count += 1
            self._refresh_current_module()
            self._status_bar.showMessage(f"Imported {new_count} new objects from {path}", 3000)

    def _open_command_palette(self) -> None:
        palette = CommandPalette(self)
        palette.exec()

    def _focus_quick_add(self) -> None:
        """Focus the dashboard quick-add input."""
        dw = self._modules.get("dashboard")
        if dw and hasattr(dw, "_quick_add") and hasattr(dw._quick_add, "_input"):
            dw._quick_add._input.setFocus()
            self._on_module_changed(_module_index("dashboard"))

    def _new_event(self) -> None:
        """Create a new event with today's date."""
        now_iso = datetime.now(timezone.utc).isoformat()
        obj = Object(
            id=str(uuid.uuid4()),
            type=ObjectType.event,
            title="New event",
            status="active",
            due_at=date.today().isoformat(),
            created_at=now_iso,
            updated_at=now_iso,
        )
        if hasattr(self, "_file_repo"):
            self._file_repo.write_object(obj)
        self._on_object_created(obj)
        self._on_module_changed(_module_index("calendar"))

    def _focus_search(self) -> None:
        """Switch to search module and focus its input."""
        self._on_module_changed(_module_index("search"))
        sw = self._modules.get("search")
        if sw and hasattr(sw, "_input"):
            sw._input.setFocus()
            sw._input.selectAll()

    def closeEvent(self, event) -> None:
        self._webdav.stop()
        self._syncthing_timer.stop()
        if hasattr(self, "_file_watcher"):
            self._file_watcher.stop()
        if hasattr(self, "_db"):
            self._db.close()
        if hasattr(self, "_notifications"):
            self._notifications.stop()
        super().closeEvent(event)

    def _arrow_icon_path(self, direction: str) -> str:
        """Render a small filled triangle to a PNG on disk and return its
        path, for QComboBox/QDateEdit/QSpinBox's `::down-arrow`/
        `::up-arrow` to reference via `image: url(...)`.

        Second revision (2026-07-19). The first version asked the *live*
        QStyle to paint its own `PE_IndicatorArrowDown`/`PE_IndicatorArrowUp`
        primitive, on the theory that would look genuinely native under
        whatever style is active. In practice, on a real user's system,
        that primitive rendered as something else entirely -- not a
        triangle at all. Different styles interpret a bare, minimally
        populated `QStyleOption` differently (some primitive
        implementations branch on the option's concrete subclass, e.g.
        `QStyleOptionButton` vs a plain `QStyleOption`, and clearly at
        least one real style's fallback path for "wrong option type" is
        not "draw a plain arrow"). That's not a fixable QSS tweak, it's
        the whole approach being unreliable across styles -- so this
        stops asking the active style to improvise and draws the triangle
        directly instead: three explicit points, no ambiguity about what
        primitive gets invoked or how a given style chooses to interpret
        it. Still theme-reactive (color comes from the live palette, not
        a hardcoded hex), just not "native" in the sense of delegating the
        actual paint call -- delegating that call is exactly what broke.
        """
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPainter, QPolygonF, QPixmap
        from PySide6.QtGui import QPalette

        size = 10
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))

        color = self.palette().color(QPalette.ColorRole.WindowText)
        # A little transparency so it reads as a subtle indicator, not a
        # bold graphic element competing with the field's actual text.
        color.setAlphaF(0.65)

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        margin_x, top, bottom = 1.5, 3.0, 7.0
        if direction == "down":
            points = [
                QPointF(margin_x, top),
                QPointF(size - margin_x, top),
                QPointF(size / 2, bottom),
            ]
        else:  # "up"
            points = [
                QPointF(margin_x, bottom),
                QPointF(size - margin_x, bottom),
                QPointF(size / 2, top),
            ]
        painter.drawPolygon(QPolygonF(points))
        painter.end()

        cache_dir = Path.home() / ".command_center" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"arrow-{direction}.png"
        pix.save(str(path))
        return path.as_posix()

    def _generate_qss(self) -> str:
        """Build the stylesheet from the live QPalette (Plasma/GNOME/etc.).

        Structural rules only (spacing, radii, font sizes) plus `palette()`
        lookups for color -- no hardcoded hex palette. See
        `core/design/tokens.py` for why this replaced the old OKLCH/macOS
        theme (2026-07-17).
        """
        C = lambda name: f'*[class="{name}"]'
        arrow_down = self._arrow_icon_path("down")
        arrow_up = self._arrow_icon_path("up")

        dark = is_dark(self)
        sem = semantic_colors(dark)
        danger, warning, success = sem["danger"], sem["warning"], sem["success"]

        win = "palette(window)"
        win_text = "palette(window-text)"
        base = "palette(base)"
        text = "palette(text)"
        muted = "palette(placeholder-text)"
        border = "palette(mid)"
        hover = "palette(alternate-base)"
        accent = "palette(highlight)"
        accent_text = "palette(highlighted-text)"
        mono = "'IBM Plex Mono', 'Cascadia Code', 'Fira Code', monospace"

        return f"""
        {C('topnav')} {{
            background-color: {win}; border-bottom: 1px solid {border};
        }}
        {C('topnav-btn')} {{
            padding: 4px 8px; font-size: 11px; border-radius: 4px;
        }}
        {C('sync-indicator')} {{
            color: {muted}; font-size: 10px; padding: 0 8px;
        }}
        {C('topnav-clock')} {{
            color: {muted}; font-size: 10px; padding: 0 6px; font-family: {mono};
        }}

        {C('topbar')} {{
            background: {win}; border-bottom: 1px solid {border}; min-height: 32px;
        }}
        {C('topbar-title')} {{
            font-size: 16px; font-weight: 600; color: {win_text}; padding: 0 8px;
        }}
        {C('content-area')} {{ background: {win}; }}

        {C('cal-view-switcher')} {{
            background: {win}; border-bottom: 1px solid {border}; padding: 2px 0;
        }}
        {C('cal-view-btn')}, {C('cal-view-btn')}:checked {{
            font-size: 11px; font-weight: 600; border: none; border-radius: 4px;
            padding: 4px 12px; margin: 0 1px;
        }}
        {C('cal-view-btn')} {{ background: transparent; color: {muted}; }}
        {C('cal-view-btn')}:hover {{ background: {hover}; }}
        {C('cal-view-btn')}:checked {{ background: {accent}; color: {accent_text}; }}

        {C('status-bar')} {{
            background: {win}; border-top: 1px solid {border};
            color: {muted}; font-size: 10px;
        }}

        {C('command-palette-input')} {{
            background: {base}; color: {text};
            border: 1px solid {border}; border-radius: 6px;
            padding: 8px 12px; font-size: 13px;
        }}
        {C('command-palette-results')} {{
            background: {base}; color: {text};
            border: 1px solid {border}; border-radius: 6px; font-size: 12px;
        }}

        {C('object-card')} {{
            background: {base}; border: 1px solid {border}; border-radius: 6px; padding: 6px 10px;
        }}
        {C('section-list-box')} {{
            background: {base}; border: 1px solid {border}; border-radius: 6px;
        }}
        {C('object-card-flush')} {{
            background: transparent; border: none; border-bottom: 1px solid {border};
        }}
        {C('object-card-flush')}:hover {{ background: {hover}; }}
        {C('object-card-flush-last')} {{
            background: transparent; border: none;
        }}
        {C('object-card-flush-last')}:hover {{ background: {hover}; }}
        {C('card-title')} {{ color: {text}; font-size: 12px; font-weight: 500; }}
        {C('card-meta')} {{ color: {muted}; font-size: 10px; }}

        {C('section-title')} {{ font-size: 10px; color: {muted}; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 0; }}
        {C('section-empty')} {{ color: {muted}; font-size: 11px; font-style: italic; padding: 8px; }}
        {C('quick-add-row')} {{ border-top: 1px solid {border}; margin-top: 4px; }}
        {C('quick-add-input')} {{
            font-size: 12px;
        }}

        {C('task-row')} {{
            border: none; border-bottom: 1px solid {border};
            padding: 3px 6px; border-radius: 4px;
        }}
        {C('task-row')}:hover {{ background: {hover}; }}
        {C('task-title')} {{ color: {text}; font-size: 12px; font-weight: 500; }}
        {C('task-due')} {{ color: {muted}; font-size: 10px; }}
        {C('task-progress')} {{ max-height: 3px; }}

        {C('priority-1')} {{ color: {danger}; font-size: 10px; font-weight: 700; }}
        {C('priority-2')} {{ color: {warning}; font-size: 10px; font-weight: 600; }}
        {C('priority-3')} {{ color: {text}; font-size: 10px; }}
        {C('priority-4')} {{ color: {muted}; font-size: 10px; }}

        {C('cal-nav-btn')} {{
            font-size: 12px; font-weight: 600; padding: 3px 12px;
        }}
        {C('cal-month-label')} {{ font-size: 15px; font-weight: 700; color: {text}; }}
        {C('cal-dow')} {{ color: {muted}; font-size: 9px; font-weight: 600; text-transform: uppercase; padding: 2px; font-family: {mono}; border-right: 1px solid {border}; }}
        {C('cal-day')} {{
            background: transparent; border: 1px solid {border}; border-radius: 4px;
            min-height: 48px; margin: 1px;
        }}
        {C('cal-day')}:hover {{ background: {hover}; }}
        {C('cal-day-today')} {{ background: {hover}; border: 1px solid {accent}; border-radius: 4px; min-height: 48px; margin: 0; }}
        {C('cal-day-past')} {{ background: transparent; border: 1px solid {border}; border-radius: 4px; min-height: 48px; margin: 1px; }}
        {C('cal-day-number')} {{ color: {text}; font-size: 11px; font-weight: 500; padding: 1px 0; font-family: {mono}; }}
        {C('cal-event-chip')} {{
            background: {accent}; color: {accent_text}; font-size: 9px; font-weight: 500;
            border-radius: 3px; padding: 1px 4px; margin: 1px 0;
        }}
        {C('cal-event-chip')}:hover {{ background: {accent}; }}
        {C('cal-all-day')} {{
            background: {base}; border-bottom: 1px solid {border}; min-height: 22px;
        }}
        {C('cal-time-label')} {{
            color: {muted}; font-size: 9px; padding: 1px 4px 0 0; min-width: 40px; max-width: 40px; font-family: {mono};
        }}
        {C('cal-hour-cell')} {{
            background: transparent; border-bottom: 1px solid {border}; border-right: 1px solid {border};
        }}
        {C('cal-event-block')} {{
            background: {accent}; color: {accent_text}; border-radius: 4px; font-size: 9px; font-weight: 500;
        }}
        {C('cal-event-block-title')} {{ padding: 2px 4px; }}
        {C('cal-now-line')} {{ background: {danger}; border: none; }}
        {C('agenda-day-label')} {{ font-size: 13px; font-weight: 700; color: {text}; }}
        {C('agenda-entry')} {{ border: none; padding: 2px 0; }}
        {C('agenda-entry-title')} {{ color: {text}; font-size: 12px; }}
        {C('agenda-entry-time')} {{ color: {muted}; font-size: 10px; font-family: {mono}; }}

        {C('kanban-column')} {{ background: {base}; border: 1px solid {border}; border-radius: 6px; }}
        {C('kanban-column-header')} {{ font-size: 10px; font-weight: 600; color: {muted}; text-transform: uppercase; padding: 6px 8px; border-bottom: 1px solid {border}; }}
        {C('kanban-card')} {{
            background: {win}; border: 1px solid {border}; border-radius: 4px;
            margin: 1px 4px; padding: 4px 6px;
        }}
        {C('kanban-card')}:hover {{ background: {hover}; border-color: {accent}; }}
        {C('kanban-card-title')} {{ color: {text}; font-size: 11px; font-weight: 500; }}
        {C('kanban-card-due')} {{ color: {muted}; font-size: 9px; font-family: {mono}; }}

        {C('md-source')}, {C('md-preview')} {{
            font-size: 12px; padding: 8px;
        }}

        {C('era-header')} {{ font-size: 14px; font-weight: 700; color: {text}; padding: 4px 0; }}
        {C('timeline-title')} {{ color: {text}; font-size: 12px; }}

        {C('inspector-panel')} {{ background: {base}; border-left: 1px solid {border}; }}
        {C('inspector-header')} {{
            background: {win}; border-bottom: 1px solid {border};
        }}
        {C('inspector-type-badge')} {{
            background: {accent}; color: {accent_text}; font-size: 10px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.4px; border-radius: 3px; padding: 2px 8px;
        }}
        {C('inspector-close-btn')} {{
            background: transparent; color: {muted}; border: none; border-radius: 4px;
            font-size: 14px; font-weight: 600; padding: 0px 6px;
        }}
        {C('inspector-close-btn')}:hover {{ background: {hover}; color: {text}; }}
        {C('inspector-section-header')} {{
            color: {muted}; font-size: 10px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.5px; font-family: {mono};
        }}
        /* No border-top here anymore -- widgets/inspector.py's _add_section
        puts a real QFrame(HLine/Sunken) above each heading instead, a
        native Qt separator the active style draws consistently with every
        other divider in the app. */
        {C('inspector-field-label')} {{
            color: {muted}; font-size: 9px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.3px; margin-top: 2px; font-family: {mono};
        }}
        {C('inspector-placeholder')} {{ color: {muted}; font-size: 11px; font-style: italic; }}
        {C('inspector-add-btn')} {{
            background: transparent; color: {accent}; border: 1px solid {border};
            border-radius: 4px; font-size: 10px; font-weight: 600; padding: 3px 8px;
        }}
        {C('inspector-add-btn')}:hover {{ background: {hover}; }}
        {C('inspector-input')}, {C('inspector-textarea')}, {C('inspector-checklist-input')} {{
            background: {win}; color: {text};
            border: 1px solid {border}; border-radius: 4px;
            padding: 4px 8px; font-size: 12px;
        }}
        {C('inspector-input')}:focus, {C('inspector-textarea')}:focus {{
            border: 1px solid {accent};
        }}
        QComboBox[class="inspector-input"], QDateEdit[class="inspector-input"] {{
            padding-right: 24px;
        }}
        QComboBox[class="inspector-input"]::drop-down,
        QDateEdit[class="inspector-input"]::drop-down {{
            subcontrol-origin: padding; subcontrol-position: center right;
            width: 22px; border: none;
        }}
        QComboBox[class="inspector-input"]::down-arrow,
        QDateEdit[class="inspector-input"]::down-arrow {{
            image: url({arrow_down}); width: 10px; height: 10px;
        }}
        QSpinBox[class="inspector-input"] {{
            padding-right: 20px;
        }}
        QSpinBox[class="inspector-input"]::up-button,
        QSpinBox[class="inspector-input"]::down-button {{
            width: 16px; border: none; background: transparent;
            subcontrol-origin: border;
        }}
        QSpinBox[class="inspector-input"]::up-button {{ subcontrol-position: top right; }}
        QSpinBox[class="inspector-input"]::down-button {{ subcontrol-position: bottom right; }}
        QSpinBox[class="inspector-input"]::up-arrow {{ image: url({arrow_up}); width: 8px; height: 8px; }}
        QSpinBox[class="inspector-input"]::down-arrow {{ image: url({arrow_down}); width: 8px; height: 8px; }}
        /* Revised 2026-07-19 (twice). First pass: gave combo/date/spin
        the same class as QLineEdit siblings but left `::down-arrow`/
        `::up-arrow` untouched, on the theory the active QStyle would
        keep drawing its own -- it did in offscreen testing (Fusion) but
        rendered *nothing* on a real user's system, confirmed from their
        screenshot. Second pass, this one: draw the arrow explicitly, but
        from a real file, not a hand-coded shape -- `_arrow_icon_path`
        above asks the live QStyle to paint its own arrow primitive
        (genuinely native to whatever style/theme is active) to a small
        PNG, because Qt Style Sheets' `url()` doesn't accept `data:` URIs
        (tested both ways; only the file path version drew anything) and
        an inline CSS-triangle-via-borders hack doesn't render correctly
        in Qt's box model (tested that too, in the first pass). */
        {C('inspector-slider')} {{ max-height: 18px; }}
        {C('inspector-footer')} {{
            background: {win}; border-top: 1px solid {border};
        }}
        {C('inspector-unsaved-label')} {{
            color: {muted}; font-size: 10px; font-style: italic;
        }}
        {C('inspector-save-btn')} {{
            background: {accent}; color: {accent_text}; font-size: 11px;
            font-weight: 600; border: none; border-radius: 6px; padding: 6px 16px;
        }}
        {C('inspector-save-btn')}:hover {{ background: {accent}; }}

        QComboBox QAbstractItemView {{
            background: {base}; color: {text};
            border: 1px solid {border}; border-radius: 4px;
            padding: 4px; outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 5px 10px; min-height: 20px; border-radius: 3px;
        }}
        QComboBox QAbstractItemView::item:selected {{
            background: {accent}; color: {accent_text};
        }}
        /* Targets the popup's item list (a plain QListView), giving the
        dropdown's rows breathing room instead of sitting flush against
        each other and the popup's edges. */

        QCalendarWidget {{
            background: {base}; border: 1px solid {border}; border-radius: 6px;
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: {win}; border-bottom: 1px solid {border};
            border-top-left-radius: 6px; border-top-right-radius: 6px;
        }}
        QCalendarWidget QToolButton {{
            background: transparent; color: {text}; font-size: 12px; font-weight: 600;
            border: none; border-radius: 4px; padding: 4px 10px; margin: 2px;
        }}
        QCalendarWidget QToolButton:hover {{ background: {hover}; }}
        QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
        QCalendarWidget QSpinBox {{
            background: {win}; color: {text};
            border: 1px solid {border}; border-radius: 4px; padding: 2px 4px;
        }}
        QCalendarWidget QAbstractItemView:enabled {{
            background: {base}; color: {text}; outline: none;
            selection-background-color: {accent}; selection-color: {accent_text};
            gridline-color: transparent; font-size: 12px;
        }}
        QCalendarWidget QAbstractItemView:disabled {{ color: {muted}; }}
        QCalendarWidget QMenu {{
            background: {base}; color: {text}; border: 1px solid {border}; border-radius: 4px;
        }}
        /* The weekday-name row (Mon/Tue/.../Sun) used to be targeted here
        via `QCalendarWidget QAbstractItemView QHeaderView::section` -- a
        type-based descendant selector that depends on Qt's internal
        composition of QCalendarWidget matching what the selector assumes.
        Removed: that's unreliable across environments (confirmed the hard
        way -- the same class of bug broke the dropdown arrows elsewhere
        in this file). It's now styled by reaching directly into the real
        header widget instance, found by its stable internal object name,
        in widgets/inspector.py's `_style_calendar_popup` -- an object
        reference can't fail to match the way a guessed selector can. */

        /* The date-picker popup QDateEdit opens (a bare QCalendarWidget)
        previously had zero styling -- it rendered with Qt's plain default
        look (flat white page, no border/frame of its own), which read as
        unfinished/thin next to the rest of the app's deliberately-styled
        chrome. This gives it an actual frame, a distinct navigation bar,
        and palette-driven (not hardcoded) colors for the nav buttons, the
        year spinbox, and the date grid's selection/disabled states, so it
        reads as one consistent piece of the app rather than a bare Qt
        default dropped in. `QAbstractItemView:enabled`/`:disabled` (not
        just plain `QAbstractItemView`) is required here -- undocumented
        outside Qt's own example, but the calendar grid won't pick up
        selection/text colors without the pseudo-state qualifier. */

        {C('tag-chip')} {{
            background: {hover}; color: {text};
            font-size: 9px; font-weight: 500; border-radius: 3px; padding: 1px 5px;
        }}
        {C('tag-chip-active')} {{
            background: {accent}; color: {accent_text}; font-size: 9px; font-weight: 600; border-radius: 3px; padding: 1px 5px;
        }}
        {C('filter-bar')} {{
            background: {base}; border-bottom: 1px solid {border}; padding: 2px 6px;
        }}

        {C('dashboard-view')}, {C('calendar-view')},
        {C('tasks-view')}, {C('settings-view')},
        {C('search-view')} {{ background: {win}; }}
        """
