"""InspectorPanel — right-side detail/editor panel (PHASE 2).

Click any ObjectCard → opens a scrollable form where the user can view
and edit all fields. Type-aware: shows different fields for task vs. event.

Layout is grouped into labeled sections (Details / Schedule / Tags /
Description / Checklist / Relationships) with related fields paired
side-by-side (Status+Priority, Due+Start) to keep the form compact. The
Save button lives in a footer outside the scroll area so it's always
visible, and a small status label next to it reflects unsaved changes.

The Progress section (a slider) that used to live here was removed
2026-07-19 -- progress is now purely derived from status everywhere in
the app (active=0%, in_progress=50%, waiting=90%, done/archived=100%),
not an independently editable field. See
`core/models/object.py::progress_for_status`.

Keyboard: Enter/Return saves from any single-line field (title, tag input,
combo boxes, date/spin fields, checklist rows) -- QTextEdit keeps Enter as
a normal newline (this falls out of how Qt's shortcut-override mechanism
works: QTextEdit swallows Return itself to insert a paragraph, so the
panel-level shortcut below never sees it). Ctrl+Return saves from anywhere,
including inside the description text area. Escape closes the panel.
"""

from __future__ import annotations

from datetime import date as Date

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut, QTextCharFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.db.database import Database
from ..core.filerepo.repository import FileRepository
from ..core.models import Object, ObjectStatus, ObjectType, progress_for_status
from ..core.recurrence import RecurrenceRule, WEEKDAY_CODES


class InspectorPanel(QFrame):
    """Right-side inspector panel for viewing/editing objects."""

    object_saved = Signal(Object)
    project_open_requested = Signal(str)  # emitted with a project's object id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Width used to be fixed (setFixedWidth(380)) with no way to make
        # the panel wider or narrower. It now lives inside a QSplitter
        # (see app.py) which owns sizing; min/max bounds are also set
        # there so the splitter has something sane to clamp to.
        self.setProperty("class", "inspector-panel")
        self._file_repo: FileRepository | None = None
        self._db: Database | None = None
        self._current_obj: Object | None = None
        self._tag_chip_widgets: list[QLabel] = []
        self._dirty = False
        # Guards dirty-tracking while fields are being populated
        # programmatically (initial construction and _populate), so we
        # only flag "unsaved changes" for edits the user actually made.
        self._populating = True
        self._build_ui()
        self._install_shortcuts()
        self._populating = False
        self.hide()

    def set_file_repo(self, repo: FileRepository) -> None:
        self._file_repo = repo

    def set_db(self, db: Database) -> None:
        self._db = db

    def open_object(self, obj: Object) -> None:
        self._current_obj = obj
        self._populating = True
        self._populate(obj)
        self._populating = False
        self._clear_dirty()
        self.show()
        self.setFocus()

    def close(self) -> None:
        self._current_obj = None
        self.hide()

    # ------------------------------------------------------------------ #
    # Keyboard shortcuts

    def _install_shortcuts(self) -> None:
        """Enter-to-save (respecting QTextEdit's own newline handling),
        Ctrl+Return to save from anywhere, Escape to close."""

        def _shortcut(seq: str) -> QShortcut:
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            return sc

        _shortcut("Return").activated.connect(self._save)
        _shortcut("Enter").activated.connect(self._save)
        _shortcut("Ctrl+Return").activated.connect(self._save)
        _shortcut("Ctrl+Enter").activated.connect(self._save)
        _shortcut("Escape").activated.connect(self.close)

    # ------------------------------------------------------------------ #
    # Dirty-state tracking (drives the footer's "Unsaved changes" hint)

    def _mark_dirty(self, *_args) -> None:
        if self._populating:
            return
        if not self._dirty:
            self._dirty = True
            self._update_footer_state()

    def _clear_dirty(self) -> None:
        self._dirty = False
        self._update_footer_state()

    def _update_footer_state(self) -> None:
        self._unsaved_label.setText("Unsaved changes" if self._dirty else "")

    def _flash_saved(self) -> None:
        self._unsaved_label.setText("Saved")
        QTimer.singleShot(1200, lambda: None if self._dirty else self._unsaved_label.setText(""))

    # ------------------------------------------------------------------ #
    # UI construction

    def _add_section(self, text: str, trailing: QWidget | None = None, first: bool = False) -> None:
        """Add a section heading, with a real divider above it (except the
        very first section).

        Previously the "divider" was a `border-top` QSS rule painted on the
        label itself -- a fake line drawn under text, not a real widget.
        This uses an actual `QFrame` configured as `HLine`/`Sunken`, Qt's
        native separator: the active QStyle draws it (bevel, color, weight)
        the same way it draws every other separator in the app, so it needs
        zero QSS and stays visually consistent if the Qt Style changes.
        `trailing`, if given, sits right-aligned on the same row as the
        heading (used for Checklist/Relationships' "+" buttons).
        """
        if not first:
            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setFrameShadow(QFrame.Shadow.Sunken)
            self._form_layout.addSpacing(4)
            self._form_layout.addWidget(divider)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 4, 0, 2)
        label = QLabel(text)
        label.setProperty("class", "inspector-section-header")
        header_row.addWidget(label, 1)
        if trailing is not None:
            header_row.addWidget(trailing)
        self._form_layout.addLayout(header_row)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setProperty("class", "inspector-header")
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(12, 8, 12, 8)

        self._type_badge = QLabel("task")
        self._type_badge.setProperty("class", "inspector-type-badge")
        hdr_layout.addWidget(self._type_badge)

        hdr_layout.addStretch(1)

        close_btn = QPushButton("×")
        close_btn.setProperty("class", "inspector-close-btn")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.close)
        hdr_layout.addWidget(close_btn)

        layout.addWidget(header)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setProperty("class", "inspector-scroll")
        form_container = QWidget()
        self._form_layout = QVBoxLayout(form_container)
        self._form_layout.setContentsMargins(16, 10, 16, 12)
        self._form_layout.setSpacing(8)

        # ============================================================== #
        # Section: Details (title, status, priority)
        self._add_section("Details", first=True)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Title")
        self._title_edit.setProperty("class", "inspector-input")
        self._title_edit.textChanged.connect(self._mark_dirty)
        self._form_layout.addWidget(self._title_edit)

        status_col = QVBoxLayout()
        status_col.setSpacing(2)
        status_col.addWidget(self._field_label("Status"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["active", "in_progress", "waiting", "done", "archived"])
        self._style_combo_input(self._status_combo)
        self._status_combo.currentIndexChanged.connect(self._mark_dirty)
        status_col.addWidget(self._status_combo)

        priority_col = QVBoxLayout()
        priority_col.setSpacing(2)
        priority_col.addWidget(self._field_label("Priority"))
        self._priority_combo = QComboBox()
        self._priority_combo.addItem("None", None)
        self._priority_combo.addItem("Urgent (P1)", 1)
        self._priority_combo.addItem("High (P2)", 2)
        self._priority_combo.addItem("Medium (P3)", 3)
        self._priority_combo.addItem("Low (P4)", 4)
        self._style_combo_input(self._priority_combo)
        self._priority_combo.currentIndexChanged.connect(self._mark_dirty)
        priority_col.addWidget(self._priority_combo)

        status_priority_row = QHBoxLayout()
        status_priority_row.setSpacing(10)
        status_priority_row.addLayout(status_col, 1)
        status_priority_row.addLayout(priority_col, 1)
        self._form_layout.addLayout(status_priority_row)

        # --- Project (parent_id) ---
        # Previously there was no way to assign or change an object's
        # parent project from the inspector at all -- only via typing
        # "#project-name" in quick-add (features/shared/create.py) or from
        # inside a project's own task list. This makes it a first-class
        # editable field like everything else here.
        self._form_layout.addWidget(self._field_label("Project"))
        project_row = QHBoxLayout()
        project_row.setSpacing(6)
        self._project_combo = QComboBox()
        self._project_combo.addItem("(none)", None)
        self._style_combo_input(self._project_combo)
        self._project_combo.currentIndexChanged.connect(self._mark_dirty)
        project_row.addWidget(self._project_combo, 1)
        self._open_project_btn = QPushButton("Open →")
        self._open_project_btn.setProperty("class", "inspector-add-btn")
        self._open_project_btn.setToolTip("Jump to this project")
        self._open_project_btn.clicked.connect(self._on_open_project_clicked)
        self._open_project_btn.setEnabled(False)
        project_row.addWidget(self._open_project_btn)
        self._form_layout.addLayout(project_row)
        self._project_combo.currentIndexChanged.connect(self._update_open_project_btn)

        # ============================================================== #
        # Section: Schedule (due/start dates + recurrence)
        self._add_section("Schedule")

        due_col = QVBoxLayout()
        due_col.setSpacing(2)
        due_col.addWidget(self._field_label("Due date"))
        self._due_edit = QDateEdit()
        self._due_edit.setCalendarPopup(True)
        self._style_calendar_popup(self._due_edit)
        self._due_edit.setSpecialValueText("Not set")
        self._due_edit.setDate(self._due_edit.minimumDate())
        self._style_combo_input(self._due_edit)
        self._due_edit.dateChanged.connect(self._mark_dirty)
        due_col.addWidget(self._due_edit)

        start_col = QVBoxLayout()
        start_col.setSpacing(2)
        start_col.addWidget(self._field_label("Start date"))
        self._start_edit = QDateEdit()
        self._start_edit.setCalendarPopup(True)
        self._style_calendar_popup(self._start_edit)
        self._start_edit.setSpecialValueText("Not set")
        self._start_edit.setDate(self._start_edit.minimumDate())
        self._style_combo_input(self._start_edit)
        self._start_edit.dateChanged.connect(self._mark_dirty)
        start_col.addWidget(self._start_edit)

        due_start_row = QHBoxLayout()
        due_start_row.setSpacing(10)
        due_start_row.addLayout(due_col, 1)
        due_start_row.addLayout(start_col, 1)
        self._form_layout.addLayout(due_start_row)

        # --- Recurrence ("schedule list": repeats + exception dates) ---
        # See core/recurrence.py -- a purpose-built repeat rule (daily/
        # weekly, interval, weekdays, until/count, exception dates), not
        # full RRULE. This is the only place a rule gets edited; calendar
        # views only ever read/expand it.
        self._recur_enabled = QCheckBox("Repeats")
        self._recur_enabled.toggled.connect(self._on_recur_toggled)
        self._recur_enabled.toggled.connect(self._mark_dirty)
        self._form_layout.addWidget(self._recur_enabled)

        self._recur_box = QWidget()
        recur_layout = QVBoxLayout(self._recur_box)
        recur_layout.setContentsMargins(12, 4, 0, 4)
        recur_layout.setSpacing(6)

        freq_row = QHBoxLayout()
        self._recur_freq = QComboBox()
        self._recur_freq.addItem("Daily", "daily")
        self._recur_freq.addItem("Weekly", "weekly")
        self._style_combo_input(self._recur_freq)
        self._recur_freq.currentIndexChanged.connect(self._on_recur_freq_changed)
        self._recur_freq.currentIndexChanged.connect(self._mark_dirty)
        freq_row.addWidget(QLabel("Every"))
        self._recur_interval = QSpinBox()
        self._recur_interval.setRange(1, 52)
        self._style_combo_input(self._recur_interval)
        self._recur_interval.valueChanged.connect(self._mark_dirty)
        freq_row.addWidget(self._recur_interval)
        freq_row.addWidget(self._recur_freq)
        recur_layout.addLayout(freq_row)

        self._recur_weekday_widget = QWidget()
        weekday_grid = QGridLayout(self._recur_weekday_widget)
        weekday_grid.setContentsMargins(0, 0, 0, 0)
        weekday_grid.setSpacing(2)
        self._recur_weekday_checks: list[QCheckBox] = []
        weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, wd_label in enumerate(weekday_labels):
            cb = QCheckBox(wd_label)
            cb.toggled.connect(self._mark_dirty)
            weekday_grid.addWidget(cb, 0, i)
            self._recur_weekday_checks.append(cb)
        recur_layout.addWidget(self._recur_weekday_widget)

        end_row = QHBoxLayout()
        self._recur_end_combo = QComboBox()
        self._recur_end_combo.addItem("Never ends", "never")
        self._recur_end_combo.addItem("Until date", "until")
        self._recur_end_combo.addItem("After N times", "count")
        self._style_combo_input(self._recur_end_combo)
        self._recur_end_combo.currentIndexChanged.connect(self._on_recur_end_changed)
        self._recur_end_combo.currentIndexChanged.connect(self._mark_dirty)
        end_row.addWidget(self._recur_end_combo)
        self._recur_until = QDateEdit()
        self._recur_until.setCalendarPopup(True)
        self._style_calendar_popup(self._recur_until)
        self._style_combo_input(self._recur_until)
        self._recur_until.dateChanged.connect(self._mark_dirty)
        end_row.addWidget(self._recur_until)
        self._recur_count = QSpinBox()
        self._recur_count.setRange(1, 999)
        self._recur_count.setValue(10)
        self._style_combo_input(self._recur_count)
        self._recur_count.valueChanged.connect(self._mark_dirty)
        end_row.addWidget(self._recur_count)
        recur_layout.addLayout(end_row)

        exceptions_row = QHBoxLayout()
        self._recur_exceptions_label = QLabel("No exceptions")
        self._recur_exceptions_label.setProperty("class", "inspector-placeholder")
        exceptions_row.addWidget(self._recur_exceptions_label, 1)
        add_exc_btn = QPushButton("Except due date")
        add_exc_btn.setProperty("class", "inspector-add-btn")
        add_exc_btn.setToolTip("Skip the occurrence currently on the Due date field above")
        add_exc_btn.clicked.connect(self._add_recur_exception)
        exceptions_row.addWidget(add_exc_btn)
        clear_exc_btn = QPushButton("Clear")
        clear_exc_btn.setProperty("class", "inspector-add-btn")
        clear_exc_btn.clicked.connect(self._clear_recur_exceptions)
        exceptions_row.addWidget(clear_exc_btn)
        recur_layout.addLayout(exceptions_row)

        self._form_layout.addWidget(self._recur_box)
        self._recur_exceptions: list[Date] = []
        self._recur_box.setVisible(False)
        self._on_recur_freq_changed()
        self._on_recur_end_changed()

        # ============================================================== #
        # Section: Tags
        # (The Progress section that used to live here was removed
        # 2026-07-19 -- progress is now purely derived from status
        # everywhere in the app, not an independently editable field. See
        # core/models/object.py::progress_for_status.)
        self._add_section("Tags")

        self._tag_container = QWidget()
        self._tag_container_layout = QHBoxLayout(self._tag_container)
        self._tag_container_layout.setContentsMargins(0, 0, 0, 0)
        self._tag_container_layout.setSpacing(4)
        self._tag_container_layout.addStretch(1)
        self._form_layout.addWidget(self._tag_container)

        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Type tag name + Enter to add")
        self._tag_input.setProperty("class", "inspector-input")
        self._tag_input.returnPressed.connect(self._add_tag_from_input)
        from ..features.tasks.tag_autocomplete import install_tag_completer
        install_tag_completer(self._tag_input, multi=False)
        self._form_layout.addWidget(self._tag_input)

        # ============================================================== #
        # Section: Description
        self._add_section("Description")
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("Markdown description… (Ctrl+Enter to save)")
        self._desc_edit.setMaximumHeight(140)
        self._desc_edit.setProperty("class", "inspector-textarea")
        self._desc_edit.textChanged.connect(self._mark_dirty)
        self._form_layout.addWidget(self._desc_edit)

        # ============================================================== #
        # Section: Checklist
        self._add_checklist_btn = QPushButton("+ Add item")
        self._add_checklist_btn.setProperty("class", "inspector-add-btn")
        self._add_checklist_btn.clicked.connect(self._add_checklist_item)
        self._add_section("Checklist", trailing=self._add_checklist_btn)

        self._checklist_widget = QWidget()
        self._checklist_layout = QVBoxLayout(self._checklist_widget)
        self._checklist_layout.setContentsMargins(0, 0, 0, 0)
        self._checklist_layout.setSpacing(4)
        self._form_layout.addWidget(self._checklist_widget)

        # ============================================================== #
        # Section: Relationships (linked items + backlinks)
        add_link_btn = QPushButton("+ Link")
        add_link_btn.setProperty("class", "inspector-add-btn")
        add_link_btn.clicked.connect(self._open_link_picker)
        self._add_section("Relationships", trailing=add_link_btn)

        self._links_label = QLabel("Linked items")
        self._links_label.setProperty("class", "inspector-field-label")
        self._form_layout.addWidget(self._links_label)
        self._links_container = QVBoxLayout()
        self._links_container.setSpacing(4)
        self._form_layout.addLayout(self._links_container)

        self._backlinks_label = QLabel("Backlinks")
        self._backlinks_label.setProperty("class", "inspector-field-label")
        self._form_layout.addWidget(self._backlinks_label)
        self._backlinks_container = QVBoxLayout()
        self._backlinks_container.setSpacing(4)
        self._form_layout.addLayout(self._backlinks_container)

        self._form_layout.addStretch(1)

        scroll.setWidget(form_container)
        layout.addWidget(scroll, 1)

        # Footer -- outside the scroll area so Save is always visible and
        # reachable without scrolling, with a small live "unsaved" hint.
        footer = QFrame()
        footer.setProperty("class", "inspector-footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 8, 16, 8)
        footer_layout.setSpacing(8)

        self._unsaved_label = QLabel("")
        self._unsaved_label.setProperty("class", "inspector-unsaved-label")
        footer_layout.addWidget(self._unsaved_label, 1)

        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save (Enter)")
        save_btn.setProperty("class", "inspector-save-btn")
        save_btn.clicked.connect(self._save)
        footer_layout.addWidget(save_btn)

        layout.addWidget(footer)

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", "inspector-field-label")
        return label

    def _style_combo_input(self, widget: QWidget) -> None:
        """Style combo/date/spin controls to match their QLineEdit siblings.

        Revised 2026-07-19. The previous approach here left these widgets
        completely unstyled (no class at all) on the theory that any QSS
        match forces Qt to stop delegating to the active native QStyle for
        the whole control, sub-controls included, which is true -- but it
        assumed the payoff was "looks like a proper native Breeze/Fusion/
        whatever control," and in practice, without a fully KDE-integrated
        QPA platform theme, the fallback is Qt's bare-bones default
        rendering: a flat, square-cornered box with a stark, separately
        boxed arrow segment that clashes hard against this app's actual
        rounded, palette-driven `inspector-input` siblings right next to
        it -- confirmed from an actual screenshot, not a theory. This app's
        visual language was never "untouched OS chrome" to begin with (the
        whole rest of the stylesheet -- panels, buttons, cards -- is
        custom-drawn with colors pulled from `palette()`, see
        `core/design/tokens.py`); a combo box that opts out of that is the
        outlier, not the norm. So: same `inspector-input` class as
        QLineEdit (background/border/radius from the live palette, not
        hardcoded), plus explicit `::drop-down`/`::down-arrow` /
        `::up-button`/`::down-button` rules in app.py so the sub-controls
        get a small, deliberate arrow instead of Qt's generic fallback
        glyph -- still theme-reactive (palette-based), just not delegated
        to whatever base QStyle happens to be active.
        """
        widget.setMinimumHeight(26)
        widget.setProperty("class", "inspector-input")

    def _style_calendar_popup(self, date_edit: QDateEdit) -> None:
        """Flatten the weekday header row (Mon/Tue/.../Sun) in the popup
        calendar QDateEdit opens: no colored text, square corners.

        Revised 2026-07-19 (third pass). Previously only Saturday/Sunday
        got an explicit neutral `QTextCharFormat` -- Qt's default red is
        specifically a weekend thing, so that looked sufficient when
        tested here. Still came back as "not fixed, needs not colors" --
        so this now sets the *same* explicit format on all seven days
        (`Qt.DayOfWeek.Monday` through `.Sunday`), not just the two that
        default to red, in case what's actually showing on the real
        system isn't Qt's stock red-weekend behavior but something else
        (a style/theme applying its own per-column color Qt's own
        defaults wouldn't). Also switched the color source from
        `cal.palette().text()` to `QPalette.ColorRole.PlaceholderText`
        explicitly -- the exact role `app.py`'s QSS calls `muted`
        everywhere else -- rather than trusting `.text()` to already be
        neutral.

        The header's background/border-radius (the "square corners" part)
        is handled separately below by reaching into the real header
        widget instance (found by its stable internal object name,
        `qt_calendar_calendarview`) and styling that instance directly --
        not a type-based QSS selector, which is the same class of bug
        that broke the dropdown arrows elsewhere in this app (unreliable
        across environments).

        Must run after `setCalendarPopup(True)` -- that's what lazily
        creates the QCalendarWidget this reaches into.
        """
        cal = date_edit.calendarWidget()
        if cal is None:
            return

        # `setWeekdayTextFormat` colors both the header label *and* every
        # date number of that weekday in the grid -- there's no separate
        # hook for "just the header row." Using PlaceholderText (a
        # deliberately dim, low-contrast tone meant for hint text) washed
        # out all 28-31 date numbers, not just the seven header labels --
        # confirmed by rendering it, and it undercut the earlier "make the
        # calendar look more solid" request. Text (full contrast, the same
        # color every date number already used before any of this) is the
        # right role: every weekday reads identically, nothing is
        # color-coded by day, and the numbers stay legible.
        neutral_color = cal.palette().color(QPalette.ColorRole.Text)
        neutral = QTextCharFormat()
        neutral.setForeground(neutral_color)
        for day in (
            Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday, Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday, Qt.DayOfWeek.Friday,
            Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday,
        ):
            cal.setWeekdayTextFormat(day, neutral)

        table = cal.findChild(QTableView, "qt_calendar_calendarview")
        header = table.horizontalHeader() if table is not None else None
        if header is not None:
            header.setStyleSheet(
                "QHeaderView::section {"
                " border-radius: 0px; border: none;"
                " background: palette(window); color: palette(placeholder-text);"
                " font-weight: 600; padding: 4px 0px;"
                "}"
            )

    # ------------------------------------------------------------------ #
    # Project (parent_id)

    def _refresh_project_choices(self) -> None:
        """Rebuild the Project combo from every `type=project` object,
        excluding the object currently open (it can't be its own parent).
        Doesn't attempt deeper cycle detection (e.g. project B parented to
        project A parented to project B) -- projects are a flat top-level
        concept in practice (see features/projects.md); worth revisiting
        if that ever changes.
        """
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        self._project_combo.addItem("(none)", None)
        if self._file_repo:
            current_id = self._current_obj.id if self._current_obj else None
            projects = sorted(
                (o for o in self._file_repo.iter_objects()
                 if o.type == ObjectType.project and o.id != current_id),
                key=lambda o: o.title.lower(),
            )
            for p in projects:
                self._project_combo.addItem(p.title, p.id)
        self._project_combo.blockSignals(False)

    def _on_open_project_clicked(self) -> None:
        project_id = self._project_combo.currentData()
        if project_id:
            self.project_open_requested.emit(project_id)

    def _update_open_project_btn(self) -> None:
        self._open_project_btn.setEnabled(self._project_combo.currentData() is not None)

    # ------------------------------------------------------------------ #
    # Populate from object

    def _populate(self, obj: Object) -> None:
        self._type_badge.setText(obj.type.value)
        self._title_edit.setText(obj.title)

        idx = self._status_combo.findText(obj.status)
        if idx >= 0:
            self._status_combo.setCurrentIndex(idx)

        p_idx = self._priority_combo.findData(obj.priority)
        self._priority_combo.setCurrentIndex(p_idx if p_idx >= 0 else 0)

        self._refresh_project_choices()
        proj_idx = self._project_combo.findData(obj.parent_id)
        self._project_combo.setCurrentIndex(proj_idx if proj_idx >= 0 else 0)
        self._update_open_project_btn()

        if obj.due_at:
            try:
                d = Date.fromisoformat(obj.due_at)
                self._due_edit.setDate(d)
                self._due_edit.setSpecialValueText("")  # remove "Not set"
            except (ValueError, TypeError):
                self._due_edit.setDate(self._due_edit.minimumDate())
        else:
            self._due_edit.clear()
            self._due_edit.setSpecialValueText("Not set")

        if obj.start_at:
            try:
                d = Date.fromisoformat(obj.start_at[:10])
                self._start_edit.setDate(d)
                self._start_edit.setSpecialValueText("")
            except (ValueError, TypeError):
                self._start_edit.setDate(self._start_edit.minimumDate())
        else:
            self._start_edit.clear()
            self._start_edit.setSpecialValueText("Not set")

        self._render_tag_chips(obj.tags)

        self._desc_edit.setText(obj.description)

        # Recurrence
        self._populate_recurrence(obj)

        # Checklist
        self._load_checklist(obj.id)

        # Links
        self._load_links()

    def _populate_recurrence(self, obj: Object) -> None:
        rule = RecurrenceRule.from_rule_string(
            obj.details.get("recurrence") if obj.details else None
        )
        self._recur_enabled.setChecked(rule is not None)
        self._recur_exceptions = list(rule.exceptions) if rule else []
        self._update_exceptions_label()

        if rule is None:
            self._recur_freq.setCurrentIndex(self._recur_freq.findData("weekly"))
            self._recur_interval.setValue(1)
            for cb in self._recur_weekday_checks:
                cb.setChecked(False)
            self._recur_end_combo.setCurrentIndex(0)
            self._recur_until.setDate(self._recur_until.minimumDate())
            self._recur_count.setValue(10)
            return

        self._recur_freq.setCurrentIndex(self._recur_freq.findData(rule.freq))
        self._recur_interval.setValue(rule.interval)
        for i, cb in enumerate(self._recur_weekday_checks):
            cb.setChecked(i in rule.weekdays)
        if rule.until is not None:
            self._recur_end_combo.setCurrentIndex(self._recur_end_combo.findData("until"))
            self._recur_until.setDate(rule.until)
        elif rule.count is not None:
            self._recur_end_combo.setCurrentIndex(self._recur_end_combo.findData("count"))
            self._recur_count.setValue(rule.count)
        else:
            self._recur_end_combo.setCurrentIndex(self._recur_end_combo.findData("never"))

    def _on_recur_toggled(self, checked: bool) -> None:
        self._recur_box.setVisible(checked)

    def _on_recur_freq_changed(self) -> None:
        is_weekly = self._recur_freq.currentData() == "weekly"
        self._recur_weekday_widget.setVisible(is_weekly)

    def _on_recur_end_changed(self) -> None:
        mode = self._recur_end_combo.currentData()
        self._recur_until.setVisible(mode == "until")
        self._recur_count.setVisible(mode == "count")

    def _add_recur_exception(self) -> None:
        d = self._due_edit.date()
        if not d.isValid() or d == self._due_edit.minimumDate():
            return
        py_date = Date(d.year(), d.month(), d.day())
        if py_date not in self._recur_exceptions:
            self._recur_exceptions.append(py_date)
            self._update_exceptions_label()
            self._mark_dirty()

    def _clear_recur_exceptions(self) -> None:
        self._recur_exceptions = []
        self._update_exceptions_label()
        self._mark_dirty()

    def _update_exceptions_label(self) -> None:
        n = len(self._recur_exceptions)
        self._recur_exceptions_label.setText(
            "No exceptions" if n == 0 else f"{n} exception date{'s' if n != 1 else ''}"
        )

    def _collect_recurrence_string(self) -> str | None:
        """Build the RRULE-subset string from the recurrence controls, or
        None if "Repeats" isn't checked -- the inverse of `_populate_recurrence`."""
        if not self._recur_enabled.isChecked():
            return None
        weekdays = frozenset(
            i for i, cb in enumerate(self._recur_weekday_checks) if cb.isChecked()
        )
        mode = self._recur_end_combo.currentData()
        until = None
        count = None
        if mode == "until":
            d = self._recur_until.date()
            if d.isValid():
                until = Date(d.year(), d.month(), d.day())
        elif mode == "count":
            count = self._recur_count.value()
        rule = RecurrenceRule(
            freq=self._recur_freq.currentData(),
            interval=self._recur_interval.value(),
            weekdays=weekdays,
            until=until,
            count=count,
            exceptions=frozenset(self._recur_exceptions),
        )
        return rule.to_rule_string()

    def _load_checklist(self, object_id: str) -> None:
        while self._checklist_layout.count():
            item = self._checklist_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._file_repo:
            return
        items = self._file_repo.read_checklist(object_id) or []
        for ci in items:
            self._add_checklist_row(ci.get("text", ""), ci.get("done", False))

    def _add_checklist_item(self) -> None:
        self._add_checklist_row("", False)
        self._mark_dirty()

    def _add_checklist_row(self, text: str, done: bool) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(done)
        cb.toggled.connect(self._mark_dirty)
        row.addWidget(cb)
        edit = QLineEdit(text)
        edit.setProperty("class", "inspector-checklist-input")
        edit.textChanged.connect(self._mark_dirty)
        row.addWidget(edit, 1)
        del_btn = QPushButton("×")
        del_btn.setFixedWidth(24)
        del_btn.setProperty("class", "inspector-close-btn")
        del_btn.clicked.connect(lambda: self._remove_checklist_row(row))
        row.addWidget(del_btn)
        container = QWidget()
        container.setLayout(row)
        self._checklist_layout.addWidget(container)

    def _remove_checklist_row(self, row_layout: QHBoxLayout) -> None:
        for i in range(self._checklist_layout.count()):
            item = self._checklist_layout.itemAt(i)
            if item and item.widget() and item.widget().layout() is row_layout:
                item.widget().deleteLater()
                break
        self._mark_dirty()

    # ------------------------------------------------------------------ #
    # Tag chips

    def _render_tag_chips(self, tags: list[str]) -> None:
        for w in self._tag_chip_widgets:
            w.deleteLater()
        self._tag_chip_widgets.clear()

        # Remove all widgets from container except the stretch
        while self._tag_container_layout.count():
            item = self._tag_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for t in tags:
            chip = QLabel(t)
            chip.setProperty("class", "tag-chip-removable")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Click to remove")
            chip.mousePressEvent = lambda e, n=t: self._remove_tag(n)
            self._tag_container_layout.addWidget(chip)
            self._tag_chip_widgets.append(chip)

        self._tag_container_layout.addStretch(1)

    def _add_tag_from_input(self) -> None:
        name = self._tag_input.text().strip()
        if not name:
            return
        self._tag_input.clear()
        current = self._collect_tag_names()
        if name not in current:
            current.append(name)
            self._render_tag_chips(current)
            self._mark_dirty()

    def _remove_tag(self, name: str) -> None:
        current = self._collect_tag_names()
        if name in current:
            current.remove(name)
            self._render_tag_chips(current)
            self._mark_dirty()

    def _collect_tag_names(self) -> list[str]:
        return [chip.text() for chip in self._tag_chip_widgets]

    # ------------------------------------------------------------------ #
    # Links / Backlinks

    def _open_link_picker(self) -> None:
        if not self._db or not self._current_obj:
            return
        from ..features.shared.link_picker import LinkPicker
        picker = LinkPicker(self._db, self._current_obj.id, self)
        if picker.exec():
            self._load_links()

    def _load_links(self) -> None:
        # Clear link rows
        while self._links_container.count():
            item = self._links_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self._backlinks_container.count():
            item = self._backlinks_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._db or not self._current_obj:
            return

        oid = self._current_obj.id

        # Outgoing links
        outgoing = self._db.get_outgoing_links(oid)
        if outgoing:
            for link in outgoing:
                row = self._build_link_row(link, outgoing=True)
                self._links_container.addWidget(row)
        else:
            empty = QLabel("No linked items")
            empty.setProperty("class", "inspector-placeholder")
            self._links_container.addWidget(empty)

        # Incoming (backlinks)
        incoming = self._db.get_incoming_links(oid)
        if incoming:
            for link in incoming:
                row = self._build_link_row(link, outgoing=False)
                self._backlinks_container.addWidget(row)
        else:
            empty = QLabel("No backlinks")
            empty.setProperty("class", "inspector-placeholder")
            self._backlinks_container.addWidget(empty)

    def _build_link_row(self, link: dict, outgoing: bool = True) -> QWidget:
        from ..widgets import ObjectCard

        target_id = link["to_id"] if outgoing else link["from_id"]
        obj = None
        if self._file_repo:
            obj = self._file_repo.read_object(target_id)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        type_label = QLabel(link["link_type"])
        type_cls = {
            "blocks": "link-type-blocks",
            "references": "link-type-references",
            "mentions": "link-type-mentions",
        }.get(link["link_type"], "link-type-related")
        type_label.setProperty("class", type_cls)
        type_label.setFixedWidth(60)
        row.addWidget(type_label)

        if obj:
            title = QLabel(obj.title)
            title.setProperty("class", "card-title")
            title.setWordWrap(True)
        else:
            title = QLabel(target_id)
            title.setProperty("class", "inspector-placeholder")
        row.addWidget(title, 1)

        if outgoing:
            del_btn = QPushButton("×")
            del_btn.setFixedWidth(22)
            del_btn.setProperty("class", "inspector-close-btn")
            del_btn.clicked.connect(lambda checked, lid=link["id"]: self._delete_link(lid))
            row.addWidget(del_btn)

        container = QWidget()
        container.setLayout(row)
        return container

    def _delete_link(self, link_id: str) -> None:
        if self._db:
            self._db.delete_link(link_id)
            self._load_links()
            self._mark_dirty()

    # ------------------------------------------------------------------ #
    # Save

    def _save(self) -> None:
        obj = self._current_obj
        if obj is None or not self._file_repo:
            return

        obj.title = self._title_edit.text()

        status_text = self._status_combo.currentText()
        if status_text in ObjectStatus.core:
            obj.status = status_text

        obj.priority = self._priority_combo.currentData()
        obj.parent_id = self._project_combo.currentData()

        due_date = self._due_edit.date()
        if due_date.isValid() and due_date != self._due_edit.minimumDate():
            obj.due_at = due_date.toString(Qt.DateFormat.ISODate)
        else:
            obj.due_at = None

        start_date = self._start_edit.date()
        if start_date.isValid() and start_date != self._start_edit.minimumDate():
            new_date_str = start_date.toString(Qt.DateFormat.ISODate)
            # Preserve the time-of-day if there was already one -- this
            # QDateEdit is date-only, and unconditionally overwriting
            # start_at with just the date used to silently strip an
            # event's time on every inspector save (found while wiring up
            # recurrence, which depends on start_at's time surviving).
            if obj.start_at and "T" in obj.start_at:
                time_part = obj.start_at.split("T", 1)[1]
                obj.start_at = f"{new_date_str}T{time_part}"
            else:
                obj.start_at = new_date_str
        else:
            obj.start_at = None

        # Progress is derived from status, not independently editable (the
        # Progress slider was removed 2026-07-19) -- see progress_for_status().
        obj.progress = progress_for_status(obj.status)
        obj.description = self._desc_edit.toPlainText()
        obj.tags = self._collect_tag_names()

        if obj.details is None:
            obj.details = {}
        recurrence_str = self._collect_recurrence_string()
        if recurrence_str:
            obj.details["recurrence"] = recurrence_str
        else:
            obj.details.pop("recurrence", None)

        from datetime import datetime, timezone
        obj.updated_at = datetime.now(timezone.utc).isoformat()

        self._file_repo.write_object(obj)
        if self._db:
            self._db.upsert_object(obj)
            self._db.set_object_tags(obj.id, obj.tags)

        # Save checklist
        checklist = []
        for i in range(self._checklist_layout.count()):
            item = self._checklist_layout.itemAt(i)
            if item and item.widget():
                row_widget = item.widget()
                row_layout = row_widget.layout()
                if row_layout and row_layout.count() >= 2:
                    cb = row_layout.itemAt(0).widget()
                    edit = row_layout.itemAt(1).widget()
                    if isinstance(cb, QCheckBox) and isinstance(edit, QLineEdit):
                        checklist.append({
                            "text": edit.text(),
                            "done": cb.isChecked(),
                        })
        self._file_repo.write_checklist(obj.id, checklist)

        self._clear_dirty()
        self._flash_saved()
        self.object_saved.emit(obj)
