"""Preferences dialog.

A popup window with one scrollable page of titled sections (General,
Appearance, WebDAV, Syncthing, Calendar, Tags, About) -- not a sidebar
module, and (2026-07-19) not a QTabWidget either, see `PreferencesDialog`
below. Settings are stored as a local JSON file (per-device preferences,
not synced).

The old "Appearance" tab (Theme/Density/Shape/Accent/Qt Style) was removed
wholesale on 2026-07-17, which was a mistake corrected the next day: Theme,
Density, Shape, and Accent were genuinely dead (Density/Shape were saved and
never read back anywhere; Theme/Accent fed a stylesheet generator that
ignored them -- see `core/design/tokens.py`), but **Qt Style was not** --
`QStyleFactory.create(style_name)` + `QApplication.setStyle(...)` is a real,
working Qt mechanism, and it's how someone runs the app under a specific
installed style (e.g. Darkly) instead of whatever the desktop defaults to.
Native palette theming and an explicit style choice aren't in conflict:
picking a style applies that style's own palette, and the app's QSS reads
colors from `palette()` either way, so the two compose correctly. Restored
2026-07-18 as a slim Appearance section containing only the style picker.

2026-07-19: sections moved from QTabWidget pages to titled `QGroupBox`
widgets stacked on one scrolling page, matching the "ModernPlasma
Productivity" design doc's Settings screen (GroupBox sections, no tabs) and
needing zero custom QSS -- QGroupBox's border/title/rounding come from
whatever Qt style is active. See features/design-system.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

SETTINGS_PATH = Path.home() / ".command_center" / "settings.json"


def _default_settings() -> dict:
    return {
        "folder_path": str(Path.home() / "CommandCenter"),
        "language": "en",
        "autosave_interval": 30,
        "qt_style": "",
        "inspector_width": 380,
        "default_new_status": "active",
        "default_new_priority": None,
        "webdav_enabled": False,
        "webdav_port": 8080,
        "webdav_lan": False,
        "syncthing_enabled": False,
        "syncthing_api_key": "",
        "syncthing_url": "http://127.0.0.1:8384",
        "syncthing_folder_id": "",
        "calendar_default": "Personal",
        "calendar_week_start": "monday",
        "calendar_work_hours_start": 9,
        "calendar_work_hours_end": 17,
    }


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _default_settings()


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


class GeneralTab(QWidget):
    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._folder_path = QLineEdit(self._settings["folder_path"])
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self._folder_path, 1)
        folder_row.addWidget(browse_btn)
        form.addRow("Folder path:", folder_row)

        self._language = QComboBox()
        self._language.addItems(["en", "ro"])
        self._language.setCurrentText(self._settings.get("language", "en"))
        form.addRow("Language:", self._language)

        self._autosave = QSpinBox()
        self._autosave.setRange(5, 300)
        self._autosave.setValue(self._settings.get("autosave_interval", 30))
        self._autosave.setSuffix(" s")
        form.addRow("Autosave interval:", self._autosave)

        layout.addLayout(form)
        layout.addStretch(1)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Command Center folder", self._folder_path.text()
        )
        if path:
            self._folder_path.setText(path)
            self.changed.emit()

    def collect(self) -> dict:
        return {
            "folder_path": self._folder_path.text(),
            "language": self._language.currentText(),
            "autosave_interval": self._autosave.value(),
        }


class AppearanceTab(QWidget):
    """Just the Qt Style picker -- see module docstring for why this is
    slimmer than the tab of the same name that used to live here."""

    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._style = QComboBox()
        self._style.addItem("(system default)", "")
        app = QApplication.instance()
        if app is not None:
            for p in ["/usr/lib/qt6/plugins", "/usr/lib/x86_64-linux-gnu/qt6/plugins"]:
                if os.path.isdir(p):
                    QCoreApplication.addLibraryPath(p)
            for name in QStyleFactory.keys():
                s = QStyleFactory.create(name)
                if s is not None:
                    label = s.metaObject().className()
                    label = label.replace("Q", "", 1).replace("Style", "").replace("::", " ")
                    self._style.addItem(label.strip(), name)
                    del s
        current = self._settings.get("qt_style", "")
        idx = self._style.findData(current)
        if idx >= 0:
            self._style.setCurrentIndex(idx)
        layout.addRow("Qt Style:", self._style)

        note = QLabel(
            "Overrides the widget style Qt renders with (e.g. Darkly instead\n"
            "of the desktop default). Takes effect immediately; not all\n"
            "installed styles show up here if their plugin isn't discoverable."
        )
        note.setProperty("class", "settings-desc")
        layout.addRow(note)

        self._style.currentIndexChanged.connect(self.changed)

    def collect(self) -> dict:
        return {"qt_style": self._style.currentData()}


class InspectorTab(QWidget):
    """Defaults for the right-side object inspector.

    Panel width isn't a control here -- it's remembered automatically
    whenever you drag the splitter (see widgets/inspector.py / app.py),
    the same way most apps persist a resizable pane without a settings
    toggle for it. Default status/priority only apply to *new* tasks
    created via quick-add (an explicit `!1`-style token in the quick-add
    text still wins over the default) -- see features/shared/create.py.
    """

    changed = Signal()

    STATUS_CHOICES = ["active", "in_progress", "waiting", "done", "archived"]
    PRIORITY_CHOICES = [
        ("None", None), ("Urgent (P1)", 1), ("High (P2)", 2),
        ("Medium (P3)", 3), ("Low (P4)", 4),
    ]

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self._default_status = QComboBox()
        self._default_status.addItems(self.STATUS_CHOICES)
        current_status = self._settings.get("default_new_status", "active")
        idx = self._default_status.findText(current_status)
        self._default_status.setCurrentIndex(idx if idx >= 0 else 0)
        self._default_status.currentIndexChanged.connect(self.changed)
        form.addRow("Default status for new items:", self._default_status)

        self._default_priority = QComboBox()
        for label, data in self.PRIORITY_CHOICES:
            self._default_priority.addItem(label, data)
        p_idx = self._default_priority.findData(self._settings.get("default_new_priority"))
        self._default_priority.setCurrentIndex(p_idx if p_idx >= 0 else 0)
        self._default_priority.currentIndexChanged.connect(self.changed)
        form.addRow("Default priority for new items:", self._default_priority)

        layout.addLayout(form)

        note = QLabel(
            "Applies to tasks created via quick-add. An explicit priority\n"
            "token (e.g. !1) in the quick-add text still takes precedence.\n"
            "The inspector panel's width is remembered automatically."
        )
        note.setProperty("class", "settings-desc")
        layout.addWidget(note)

        layout.addStretch(1)

    def collect(self) -> dict:
        # Width isn't a control in this tab (see class docstring) -- read
        # it fresh from disk rather than the dict this tab was constructed
        # with, so a Preferences Save doesn't clobber a width written by
        # app.py's splitter-drag persistence *after* this dialog opened.
        width = load_settings().get("inspector_width", 380)
        return {
            "default_new_status": self._default_status.currentText(),
            "default_new_priority": self._default_priority.currentData(),
            "inspector_width": width,
        }


class WebDavTab(QWidget):
    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._enabled = QCheckBox("Enable WebDAV server")
        self._enabled.setChecked(self._settings.get("webdav_enabled", False))
        self._enabled.toggled.connect(self.changed)
        layout.addWidget(self._enabled)

        form = QFormLayout()
        self._port = QSpinBox()
        self._port.setRange(1024, 65535)
        self._port.setValue(self._settings.get("webdav_port", 8080))
        form.addRow("Port:", self._port)

        self._lan = QCheckBox("Allow LAN access (0.0.0.0)")
        self._lan.setChecked(self._settings.get("webdav_lan", False))
        form.addRow("", self._lan)
        layout.addLayout(form)

        self._url_label = QLabel()
        self._url_label.setProperty("class", "settings-url")
        layout.addWidget(self._url_label)

        self._update_url()

        self._port.valueChanged.connect(self.changed)
        self._lan.toggled.connect(self._update_url)

        layout.addStretch(1)

    def _update_url(self) -> None:
        host = "0.0.0.0" if self._lan.isChecked() else "127.0.0.1"
        self._url_label.setText(f"Connection URL: http://{host}:{self._port.value()}/")

    def collect(self) -> dict:
        return {
            "webdav_enabled": self._enabled.isChecked(),
            "webdav_port": self._port.value(),
            "webdav_lan": self._lan.isChecked(),
        }


class SyncthingTab(QWidget):
    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._enabled = QCheckBox("Enable P2P sync (Syncthing)")
        self._enabled.setChecked(self._settings.get("syncthing_enabled", False))
        self._enabled.toggled.connect(self.changed)
        layout.addWidget(self._enabled)

        form = QFormLayout()
        self._api_key = QLineEdit(self._settings.get("syncthing_api_key", ""))
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self._api_key)

        self._url = QLineEdit(
            self._settings.get("syncthing_url", "http://127.0.0.1:8384")
        )
        form.addRow("URL:", self._url)

        self._folder_id = QLineEdit(self._settings.get("syncthing_folder_id", ""))
        form.addRow("Folder ID:", self._folder_id)
        layout.addLayout(form)

        self._status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(self._status_group)
        self._status_label = QLabel("Not checked")
        self._status_label.setProperty("class", "sync-status-label")
        status_layout.addWidget(self._status_label)

        self._device_list = QListWidget()
        self._device_list.setMaximumHeight(120)
        status_layout.addWidget(self._device_list)

        check_btn = QPushButton("Check connection")
        check_btn.clicked.connect(self._check_connection)
        status_layout.addWidget(check_btn)
        layout.addWidget(self._status_group)

        layout.addStretch(1)

    def _check_connection(self) -> None:
        from ...core.sync.syncthing_client import SyncthingClient
        client = SyncthingClient(
            api_key=self._api_key.text(),
            base_url=self._url.text(),
        )
        if not client.ping():
            self._status_label.setText("Status: Disconnected — Syncthing not reachable")
            self._status_label.setProperty("class", "sync-status-disconnected")
            return

        try:
            st = client.status()
            self._status_label.setText(
                f"Status: Connected — {st.version} — Device: {st.my_id[:8]}…"
            )
            self._status_label.setProperty("class", "sync-status-connected")

            self._device_list.clear()
            for dev in client.connections():
                icon = "●" if dev.connected else "○"
                item = QListWidgetItem(f"{icon} {dev.name} ({dev.device_id[:8]}…)")
                self._device_list.addItem(item)
        except Exception as exc:
            self._status_label.setText(f"Status: Error — {exc}")

    def collect(self) -> dict:
        return {
            "syncthing_enabled": self._enabled.isChecked(),
            "syncthing_api_key": self._api_key.text(),
            "syncthing_url": self._url.text(),
            "syncthing_folder_id": self._folder_id.text(),
        }


class CalendarTab(QWidget):
    changed = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._default_cal = QLineEdit(
            self._settings.get("calendar_default", "Personal")
        )
        layout.addRow("Default calendar:", self._default_cal)

        self._week_start = QComboBox()
        for d in ["monday", "sunday", "saturday"]:
            self._week_start.addItem(d.capitalize(), d)
        self._week_start.setCurrentIndex(self._week_start.findData(
            self._settings.get("calendar_week_start", "monday")
        ))
        layout.addRow("Week starts on:", self._week_start)

        self._work_start = QSpinBox()
        self._work_start.setRange(0, 23)
        self._work_start.setValue(self._settings.get("calendar_work_hours_start", 9))
        layout.addRow("Working hours start:", self._work_start)

        self._work_end = QSpinBox()
        self._work_end.setRange(0, 23)
        self._work_end.setValue(self._settings.get("calendar_work_hours_end", 17))
        layout.addRow("Working hours end:", self._work_end)

        layout.addRow(QLabel(""))
        layout.addRow(QLabel("FIUB schedule overlay:"))
        self._fiub_enabled = QCheckBox("Show FIUB academic schedule")
        layout.addRow("", self._fiub_enabled)

        for w in [self._default_cal, self._week_start, self._work_start, self._work_end]:
            if hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self.changed)

    def collect(self) -> dict:
        return {
            "calendar_default": self._default_cal.text(),
            "calendar_week_start": self._week_start.currentData(),
            "calendar_work_hours_start": self._work_start.value(),
            "calendar_work_hours_end": self._work_end.value(),
        }


class AboutTab(QWidget):
    reindex_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.addRow("Version:", QLabel("0.1.0"))
        form.addRow("Python:", QLabel(__import__("sys").version))

        data_path = Path(self._settings.get("folder_path", ""))
        size_str = "—"
        if data_path.exists():
            total = sum(
                f.stat().st_size for f in data_path.rglob("*") if f.is_file()
            )
            if total > 1_000_000_000:
                size_str = f"{total / 1_000_000_000:.1f} GB"
            elif total > 1_000_000:
                size_str = f"{total / 1_000_000:.1f} MB"
            else:
                size_str = f"{total / 1_000:.0f} KB"

        self._size_label = QLabel(size_str)
        form.addRow("Data size:", self._size_label)
        layout.addLayout(form)

        reindex_btn = QPushButton("Reindex SQLite cache")
        reindex_btn.clicked.connect(self.reindex_requested)
        layout.addWidget(reindex_btn)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export data (JSON)")
        export_btn.clicked.connect(self.export_requested)
        btn_row.addWidget(export_btn)

        import_btn = QPushButton("Import data")
        import_btn.clicked.connect(self.import_requested)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)

        layout.addStretch(1)

    def collect(self) -> dict:
        return {}


class TagsTab(QWidget):
    """Tags manager tab — list, rename, recolor, merge, delete tags.

    2026-07-19: rename and the new merge action now rewrite every affected
    Object file's own `tags` list via `FileRepository`, not just the
    SQLite cache. `Database.rename_tag`/`.delete_tag` only ever touched
    the `tags`/`object_tags` cache tables -- those tables are themselves
    *rebuilt from* each object's `tags` field on reindex (see
    `Database.upsert_object`), so a rename or merge that stopped at the DB
    layer would look like it worked for the rest of the session and
    silently revert on the next reindex/restart. Same class of bug as the
    2026-07-18 Kanban/Timeline drag-persistence fixes (see
    `../tasks.md`/`../boards.md`) -- fixed the same way, by writing
    through to the actual source of truth.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._db = None
        self._build_ui()

    def set_db(self, db) -> None:
        self._db = db
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        desc = QLabel("Manage tags. Changes apply immediately.")
        desc.setProperty("class", "settings-desc")
        layout.addWidget(desc)

        self._list_layout = QVBoxLayout()
        layout.addLayout(self._list_layout)
        layout.addStretch(1)

    def _refresh(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._db:
            return

        tags = self._db.list_tags()
        if not tags:
            empty = QLabel("No tags yet. Add them from the inspector.")
            empty.setProperty("class", "settings-desc")
            self._list_layout.addWidget(empty)
            return

        for tag in tags:
            self._add_tag_row(tag, tags)

    def _add_tag_row(self, tag: dict, all_tags: list[dict]) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        color_btn = QPushButton("🎨")
        color_btn.setFixedWidth(32)
        current_color = tag.get("color") or ""
        if current_color:
            color_btn.setStyleSheet(f"background-color: {current_color};")
        color_btn.clicked.connect(lambda: self._pick_color(tag["id"], color_btn))
        row.addWidget(color_btn)

        name_edit = QLineEdit(tag["name"])
        name_edit.setProperty("class", "inspector-input")
        name_edit.editingFinished.connect(
            lambda e=name_edit, t=tag: self._rename(t, e.text())
        )
        row.addWidget(name_edit, 1)

        count = len(self._db.objects_by_tag(tag["name"])) if self._db else 0
        count_label = QLabel(f"{count}")
        count_label.setToolTip("Objects using this tag")
        count_label.setProperty("class", "settings-desc")
        row.addWidget(count_label)

        merge_btn = QPushButton("Merge into…")
        merge_btn.setProperty("class", "inspector-add-btn")
        others = [t for t in all_tags if t["id"] != tag["id"]]
        merge_btn.setEnabled(bool(others))
        merge_btn.clicked.connect(lambda: self._merge(tag, others))
        row.addWidget(merge_btn)

        del_btn = QPushButton("×")
        del_btn.setFixedWidth(28)
        del_btn.clicked.connect(lambda: self._delete(tag["id"]))
        row.addWidget(del_btn)

        container = QWidget()
        container.setProperty("class", "tag-manager-row")
        container.setLayout(row)
        self._list_layout.addWidget(container)

    def _pick_color(self, tag_id: str, btn: QPushButton) -> None:
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            btn.setStyleSheet(f"background-color: {hex_color};")
            if self._db:
                self._db.update_tag_color(tag_id, hex_color)

    def _rewrite_objects_tag(self, old_name: str, new_name: str | None) -> None:
        """Rewrite `old_name` to `new_name` (or drop it, if `new_name` is
        None) across every object file that actually has it -- the
        write-through half of rename/merge/delete. `new_name=None` isn't
        used by rename/merge (only conceptually by delete, which already
        has its own DB-cascade-only behavior kept as-is since "delete"
        removing the tag from objects was already the documented
        behavior, unlike rename/merge which is new)."""
        from ...core.filerepo.repository import FileRepository
        from datetime import datetime, timezone

        repo = FileRepository()
        for obj in repo.iter_objects():
            if old_name not in (obj.tags or []):
                continue
            new_tags = [t for t in obj.tags if t != old_name]
            if new_name and new_name not in new_tags:
                new_tags.append(new_name)
            obj.tags = new_tags
            obj.updated_at = datetime.now(timezone.utc).isoformat()
            repo.write_object(obj)
            if self._db:
                self._db.set_object_tags(obj.id, obj.tags)

    def _rename(self, tag: dict, new_name: str) -> None:
        new_name = new_name.strip()
        if not self._db or not new_name or new_name == tag["name"]:
            return
        self._rewrite_objects_tag(tag["name"], new_name)
        self._db.rename_tag(tag["id"], new_name)
        from ..shared.tag_names import add_known_tag
        add_known_tag(new_name)
        self._refresh()

    def _merge(self, src_tag: dict, others: list[dict]) -> None:
        """Merge `src_tag` into another existing tag: every object tagged
        `src_tag` gets the destination tag instead (deduped, not
        duplicated), and `src_tag` itself is deleted."""
        if not self._db or not others:
            return
        from PySide6.QtWidgets import QInputDialog
        names = [t["name"] for t in others]
        dest_name, ok = QInputDialog.getItem(
            self, "Merge tag",
            f"Merge “{src_tag['name']}” into:",
            names, 0, False,
        )
        if not ok or not dest_name:
            return
        self._rewrite_objects_tag(src_tag["name"], dest_name)
        self._db.delete_tag(src_tag["id"])
        self._refresh()

    def _delete(self, tag_id: str) -> None:
        reply = QMessageBox.question(
            self, "Delete tag",
            "Remove this tag from all objects?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes and self._db:
            tag = next((t for t in self._db.list_tags() if t["id"] == tag_id), None)
            if tag:
                self._rewrite_objects_tag(tag["name"], None)
            self._db.delete_tag(tag_id)
            self._refresh()


class PreferencesDialog(QDialog):
    """Preferences popup (General, WebDAV, Syncthing, Calendar, Tags, About).

    A window, not a sidebar module (2026-07-17) -- opened from the
    Settings menu / Ctrl+, rather than taking a slot in the main
    navigation. It's non-modal: `MainWindow` keeps one instance around and
    shows/raises it, so it behaves like every other desktop app's
    preferences window (comparable side-by-side with the app, not a
    blocking dialog you have to dismiss to keep working).
    """

    settings_changed = Signal(dict)
    reindex_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences — Command Center")
        self.setProperty("class", "settings-view")
        self.resize(560, 480)

        self._settings = load_settings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)

        desc = QLabel("Per-device preferences (not synced)")
        desc.setProperty("class", "settings-desc")
        layout.addWidget(desc)

        # A scrolling stack of titled QGroupBox sections -- not a QTabWidget.
        # Matches the design doc's Settings page (Appearance/Notifications/
        # Defaults/Account as GroupBox sections on one scrollable page, no
        # tabs) and needs zero custom QSS: QGroupBox's title/border/rounding
        # come straight from the active Qt style. Each section still owns
        # the same Tab widget class as before (GeneralTab, WebDavTab, ...)
        # -- only the container changed, not the field-collection logic.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        sections_container = QWidget()
        sections_layout = QVBoxLayout(sections_container)
        sections_layout.setContentsMargins(0, 4, 0, 4)
        sections_layout.setSpacing(14)
        self._scroll.setWidget(sections_container)
        layout.addWidget(self._scroll, 1)

        def section(title: str, widget: QWidget) -> QGroupBox:
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            box_layout.addWidget(widget)
            sections_layout.addWidget(box)
            return box

        self._general = GeneralTab(self._settings)
        section("General", self._general)

        self._appearance = AppearanceTab(self._settings)
        section("Appearance", self._appearance)

        self._inspector = InspectorTab(self._settings)
        section("Inspector", self._inspector)

        self._webdav = WebDavTab(self._settings)
        section("WebDAV", self._webdav)

        self._syncthing = SyncthingTab(self._settings)
        section("Syncthing", self._syncthing)

        self._calendar = CalendarTab(self._settings)
        section("Calendar", self._calendar)

        self._tags_tab = TagsTab()
        section("Tags", self._tags_tab)

        self._about = AboutTab(self._settings)
        self._about.reindex_requested.connect(self.reindex_requested)
        self._about.export_requested.connect(self.export_requested)
        self._about.import_requested.connect(self.import_requested)
        section("About", self._about)

        sections_layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

    def set_db(self, db) -> None:
        self._tags_tab.set_db(db)

    def _save(self) -> None:
        updated = {}
        for tab in [self._general, self._appearance, self._inspector, self._webdav,
                     self._syncthing, self._calendar, self._about]:
            updated.update(tab.collect())
        save_settings(updated)
        self._settings = updated
        self.settings_changed.emit(updated)

    def get_settings(self) -> dict:
        return self._settings

    def open_on_section(self, section_title: str) -> None:
        """Show the dialog raised/focused, scrolled to a named section.

        Renamed from the pre-2026-07-19 `open_on_tab` (there's no tab bar to
        select a page in anymore -- sections are QGroupBox widgets on one
        scrolling page, see class docstring).
        """
        self.show()
        self.raise_()
        self.activateWindow()
        box = next(
            (b for b in self.findChildren(QGroupBox) if b.title() == section_title),
            None,
        )
        if box is not None:
            self._scroll.ensureWidgetVisible(box)
