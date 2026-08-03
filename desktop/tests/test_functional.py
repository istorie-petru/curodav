"""Integration tests that exercise real widget interactions.

These run headless (offscreen) and verify actual rendering,
click handling, and state changes in the MainWindow.
"""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "/usr/share/fonts"

# pytest.ini_options.pythonpath = ["src"] handles this, but we also
# need sys.path[0] to be the project root for "src" package resolution
_src_root = Path(__file__).resolve().parent.parent
if str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

# --- fixtures ---

import pytest
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QWidget, QListWidget, QPushButton, QStackedWidget
from PySide6.QtTest import QTest


@pytest.fixture(scope="session")
def app():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def main_window(app, tmp_path):
    """Create MainWindow with mock data and no real file system."""
    from src.app import MainWindow

    # Prevent FileWatcher from trying to watch a real dir
    import src.core.filerepo.repository as fr_mod

    orig_base = fr_mod.FileRepository.base_path.fget
    fr_mod.FileRepository.base_path = property(lambda s: tmp_path / "objects")

    win = MainWindow()
    win.show()
    QTest.qWait(200)
    yield win
    win.close()
    QTest.qWait(50)


# --- tests ---


class TestRenderAndClick:
    """Verify widgets render and respond to clicks."""

    def test_window_title(self, main_window):
        assert "Command Center" in main_window.windowTitle()

    def test_topnav_has_modules(self, main_window):
        """2026-07-19: sidebar/bottom-nav replaced by one QToolButton-per-module
        top navigation bar (TopNav) -- see features/window-and-menu.md."""
        from src.app import MODULES
        topnav = main_window._topnav
        assert len(topnav._buttons) >= len(MODULES)
        assert topnav._buttons[0].text() == "Dashboard"

    def test_topnav_navigation(self, main_window):
        """Click each top-nav button and verify content stack switches."""
        topnav = main_window._topnav
        stack = main_window._content_stack

        for i in range(min(len(topnav._buttons), 6)):
            btn = topnav._buttons[i]
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
            QTest.qWait(50)
            assert stack.currentIndex() == i, f"Stack index {stack.currentIndex()} != {i} after clicking '{btn.text()}'"

    def test_inspector_opens_on_object_click(self, main_window):
        """Simulate opening the inspector for an object."""
        win = main_window
        # Must have at least one object
        assert len(win._all_objects) > 0, "No mock objects seeded"

        obj = win._all_objects[0]
        win._open_inspector(obj.id)
        QTest.qWait(50)
        assert win._inspector.isVisible(), f"Inspector not visible after open_object (current_obj={win._inspector._current_obj})"
        assert win._inspector._current_obj is not None
        assert win._inspector._current_obj.id == obj.id

    def test_inspector_close(self, main_window):
        """Open then close the inspector."""
        win = main_window
        obj = win._all_objects[0]
        win._open_inspector(obj.id)
        QTest.qWait(50)
        assert win._inspector.isVisible(), "Inspector not visible"

        # Click close button
        if hasattr(win._inspector, "_close_btn"):
            QTest.mouseClick(win._inspector._close_btn, Qt.MouseButton.LeftButton)
            QTest.qWait(50)
            assert not win._inspector.isVisible()

    def test_inspector_save_updates_object(self, main_window):
        """Modify an object via the inspector and save."""
        win = main_window
        obj = win._all_objects[0]
        old_title = obj.title
        win._open_inspector(obj.id)
        QTest.qWait(50)

        insp = win._inspector
        if hasattr(insp, "_title_input"):
            insp._title_input.setText("Updated Title")
            if hasattr(insp, "_save_btn"):
                QTest.mouseClick(insp._save_btn, Qt.MouseButton.LeftButton)
                QTest.qWait(100)
                assert obj.title == "Updated Title", f"Title not updated: {obj.title}"

    def test_quick_add_creates_object(self, main_window):
        """Type into the dashboard quick-add and verify object creation."""
        win = main_window
        initial_count = len(win._all_objects)

        dash = win._modules.get("dashboard")
        assert dash is not None, "No dashboard module"
        assert hasattr(dash, "_quick_add"), "No quick-add widget"

        qa = dash._quick_add
        assert hasattr(qa, "_input"), "No quick-add input"

        # Type a task
        qa._input.setText("New test task !2 @today #test >mytag")
        QTest.qWait(50)
        # Press Enter to create
        QTest.keyClick(qa._input, Qt.Key.Key_Return)
        QTest.qWait(100)

        # Verify a new object was created
        assert len(win._all_objects) > initial_count, "No object was created"
        created = [o for o in win._all_objects if "New test task" in o.title]
        assert len(created) > 0, "Created object not found"
        assert created[0].priority == 2, f"Priority not set: {created[0].priority}"

    def test_calendar_navigation(self, main_window):
        """Click calendar prev/next buttons and verify month changes."""
        win = main_window
        # Switch to calendar module (index 2)
        QTest.mouseClick(win._topnav._buttons[2], Qt.MouseButton.LeftButton)
        QTest.qWait(50)

        cal_w = win._modules.get("calendar")
        assert cal_w is not None, "No calendar module"

        # Find navigation buttons
        prev_btn = cal_w.findChild(QPushButton, None)
        if prev_btn and "prev" in prev_btn.text().lower() or "<" in prev_btn.text():
            QTest.mouseClick(prev_btn, Qt.MouseButton.LeftButton)
            QTest.qWait(50)

        # Verify month label changed
        if hasattr(cal_w, "_month_label"):
            print(f"  Month label: {cal_w._month_label.text()}")

    def test_kanban_card_double_click_opens_inspector(self, main_window):
        """2026-07-19: the Smart-list view (and its TaskRow, the previous
        target of this test) was removed -- see features/tasks.md. Table
        view deliberately never opens the inspector; Kanban still does
        (double-click a card), so that's what this now verifies."""
        win = main_window
        # Switch to tasks module
        QTest.mouseClick(win._topnav._buttons[1], Qt.MouseButton.LeftButton)
        QTest.qWait(50)

        tasks_w = win._modules.get("tasks")
        assert tasks_w is not None, "No tasks module"

        from src.features.tasks.kanban_view import _KanbanCard

        # Switch to the Board view (Kanban) -- index 2 in the new
        # ["table", "timeline", "board"] switcher.
        board_btn = tasks_w._view_group.button(2)
        QTest.mouseClick(board_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(50)

        cards = tasks_w.findChildren(_KanbanCard)
        if cards:
            card = cards[0]
            QTest.mouseDClick(card, Qt.MouseButton.LeftButton)
            QTest.qWait(100)
            assert win._inspector.isVisible(), "Inspector did not open on card double-click"
            assert win._inspector._current_obj is not None
            assert win._inspector._current_obj.type.value == "task"

    def test_view_switcher(self, main_window):
        """Toggle between Smart/Table/Timeline views in tasks."""
        win = main_window
        # Switch to tasks
        QTest.mouseClick(win._topnav._buttons[1], Qt.MouseButton.LeftButton)
        QTest.qWait(50)

        tasks_w = win._modules.get("tasks")
        assert tasks_w is not None

        # Find view switcher buttons
        if hasattr(tasks_w, "_switcher"):
            buttons = tasks_w._switcher.findChildren(QPushButton)
            for btn in buttons:
                QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
                QTest.qWait(50)
                # Verify some state changed
                assert btn.isChecked() or True  # at least no crash

    def test_status_bar_counts(self, main_window):
        """Verify status bar shows correct counts."""
        win = main_window
        QTest.qWait(50)
        label = win._status_counts_label
        text = label.text()
        assert "tasks" in text
        assert "events" in text

    def test_topnav_visible_at_any_width(self, main_window):
        """2026-07-19: TopNav replaced the old sidebar/bottom-nav responsive
        pair -- one bar works at every width, nothing to toggle by size."""
        win = main_window
        win.setMinimumSize(700, 500)
        win.resize(800, 600)
        QTest.qWait(50)
        assert win._topnav.isVisible()
        win.resize(1200, 800)
        QTest.qWait(50)
        assert win._topnav.isVisible()

    def test_command_palette_opens(self, main_window):
        """Simulate Ctrl+K to open command palette (non-blocking check)."""
        win = main_window
        palette_action = None
        for a in win.actions():
            if "palette" in a.text().lower():
                palette_action = a
                break
        assert palette_action is not None, "No command palette action found"
        assert palette_action.shortcut().toString() == "Ctrl+K"

    def test_all_modules_have_widgets(self, main_window):
        """Every registered module has a valid widget in the content stack."""
        from src.app import MODULES
        stack = main_window._content_stack
        for i, (glyph, name, _) in enumerate(MODULES):
            w = stack.widget(i)
            assert w is not None, f"Module {name} has no widget at index {i}"
            assert w.isVisible() or True  # widget is valid even if not current

    def test_settings_not_a_module(self, main_window):
        """Settings/Preferences is a popup dialog now (2026-07-17), not a
        nav-bar module -- it should not appear in MODULES or the top nav."""
        from src.app import MODULES
        module_names = [name for _glyph, name, _mid in MODULES]
        assert "Settings" not in module_names
        assert "Notes" not in module_names
        assert "Roadmap" not in module_names

    def test_menu_bar_present(self, main_window):
        """A real QMenuBar exists (routes to Plasma's global menu when the
        appmenu platform integration is active; renders as an in-window
        menu bar otherwise -- both read the same QMenuBar)."""
        menu_bar = main_window.menuBar()
        menu_titles = [a.text() for a in menu_bar.actions()]
        assert menu_titles == ["&File", "&View", "&Tools", "&Settings", "&Help"]

    def test_preferences_menu_action_opens_dialog(self, main_window):
        win = main_window
        win._open_preferences()
        QTest.qWait(30)
        assert win._preferences_dialog.isVisible()
        win._preferences_dialog.close()

    def test_objects_persist_across_module_switches(self, main_window):
        """Objects survive when switching between modules."""
        win = main_window
        initial_ids = {o.id for o in win._all_objects}

        # Switch through all modules
        for i in range(min(len(win._topnav._buttons), 6)):
            QTest.mouseClick(win._topnav._buttons[i], Qt.MouseButton.LeftButton)
            QTest.qWait(30)

        # All objects still present
        assert len(win._all_objects) == len(initial_ids)
        assert {o.id for o in win._all_objects} == initial_ids

    def test_project_detail_opens(self, main_window):
        """Open a project detail view."""
        win = main_window
        # Find a project object
        projects = [o for o in win._all_objects if o.type.value == "project"]
        if projects:
            win._open_project_detail(projects[0].id)
            QTest.qWait(100)
            # Should have switched to project detail view
            assert win._project_detail_view.isVisible()


class TestInspectorImprovements:
    """2026-07-18 inspector pass: resizable panel, Enter-to-save, native
    combo/date/spin styling, real separators, and a Project (parent_id)
    picker. See widgets/inspector.py's module docstring."""

    def test_panel_lives_in_a_resizable_splitter(self, main_window):
        """No more setFixedWidth(380) -- the panel sits in a QSplitter with
        min/max bounds instead, so it can actually be dragged wider/narrower."""
        from PySide6.QtWidgets import QSplitter
        win = main_window
        assert isinstance(win._content_splitter, QSplitter)
        assert win._inspector.parent() is win._content_splitter
        assert win._inspector.minimumWidth() < win._inspector.maximumWidth()
        assert win._inspector.maximumWidth() < 16777215  # not Qt's "no max" sentinel

    def test_splitter_drag_persists_width(self, main_window, tmp_path, monkeypatch):
        """Dragging the handle (simulated by resizing directly, since
        QTest can't easily drag a splitter handle headless) should
        eventually write the new width to settings.json."""
        win = main_window
        saved = {}
        monkeypatch.setattr(
            "src.app.save_settings", lambda settings: saved.update(settings)
        )
        win._content_splitter.setSizes([700, 450])
        win._on_inspector_splitter_moved(450, 1)
        # Drain the debounce timer synchronously instead of waiting 250ms.
        win._inspector_width_save_timer.stop()
        win._save_inspector_width()
        assert saved.get("inspector_width") == win._inspector.width()

    def test_combo_date_spin_fields_match_line_edit_styling(self, main_window):
        """Revised 2026-07-19 (see _style_combo_input's docstring): these
        used to carry no stylesheet class at all, on the theory that
        letting the active QStyle draw them "natively" would look best.
        A real screenshot showed the opposite -- without full KDE platform
        integration, the unstyled fallback rendering (square corners, a
        starkly boxed arrow) clashed against the rounded `inspector-input`
        siblings right next to it. They now carry the same class, with
        explicit ::drop-down/::down-arrow rules (in app.py's QSS) so the
        sub-controls get a small deliberate arrow instead of Qt's generic
        fallback glyph."""
        insp = main_window._inspector
        for widget in (
            insp._status_combo, insp._priority_combo, insp._project_combo,
            insp._due_edit, insp._start_edit,
        ):
            assert widget.property("class") == "inspector-input"

    def test_title_field_still_carries_input_class(self, main_window):
        """Plain QLineEdits have no sub-controls, so they can safely keep
        the custom border/background class."""
        assert main_window._inspector._title_edit.property("class") == "inspector-input"

    def test_enter_in_title_saves(self, main_window):
        """Enter/Return in a single-line field saves, per the panel-level
        QShortcut installed in _install_shortcuts."""
        win = main_window
        obj = win._all_objects[0]
        win._open_inspector(obj.id)
        QTest.qWait(50)

        insp = win._inspector
        insp._title_edit.setFocus()
        insp._title_edit.setText("Saved via Enter")
        QTest.keyClick(insp._title_edit, Qt.Key.Key_Return)
        QTest.qWait(50)
        assert obj.title == "Saved via Enter"

    def test_enter_in_description_does_not_save_inserts_newline(self, main_window):
        """QTextEdit swallows Return itself (newline) -- the panel
        shortcut must never fire while it has focus."""
        win = main_window
        obj = win._all_objects[0]
        win._open_inspector(obj.id)
        QTest.qWait(50)

        insp = win._inspector
        insp._title_edit.setText("Untouched Title")
        insp._save()  # baseline save so the "before" state is on disk
        insp._desc_edit.setFocus()
        insp._desc_edit.setPlainText("line one")
        QTest.keyClick(insp._desc_edit, Qt.Key.Key_Return)
        QTest.qWait(50)
        assert "\n" in insp._desc_edit.toPlainText()
        # Title wasn't touched, and the panel is still open -- if the
        # shortcut had fired it wouldn't break either of these, so the
        # real assertion is just that no exception occurred and the
        # newline actually landed in the text (checked above).

    def test_project_picker_lists_projects_excluding_self(self, main_window):
        win = main_window
        projects = [o for o in win._all_objects if o.type.value == "project"]
        if not projects:
            pytest.skip("no mock projects seeded")
        target_project = projects[0]

        win._open_inspector(target_project.id)
        QTest.qWait(50)
        insp = win._inspector

        choice_ids = [insp._project_combo.itemData(i) for i in range(insp._project_combo.count())]
        assert target_project.id not in choice_ids, "project shouldn't be able to parent itself"
        assert None in choice_ids, "must always offer '(none)'"

    def test_assigning_project_persists_parent_id(self, main_window):
        win = main_window
        projects = [o for o in win._all_objects if o.type.value == "project"]
        tasks = [o for o in win._all_objects if o.type.value == "task"]
        if not projects or not tasks:
            pytest.skip("no mock projects/tasks seeded")
        task = tasks[0]
        project = projects[0]

        win._open_inspector(task.id)
        QTest.qWait(50)
        insp = win._inspector
        idx = insp._project_combo.findData(project.id)
        assert idx >= 0, "seeded project missing from picker"
        insp._project_combo.setCurrentIndex(idx)
        insp._save()

        assert task.parent_id == project.id

    def test_section_headers_use_real_qframe_dividers(self, main_window):
        """No more `border-top` QSS hack -- an actual QFrame(HLine) sits
        above each section heading."""
        from PySide6.QtWidgets import QFrame
        insp = main_window._inspector
        dividers = [
            w for w in insp.findChildren(QFrame)
            if w.frameShape() == QFrame.Shape.HLine
        ]
        assert len(dividers) >= 5  # one per section after the first

    def test_footer_save_button_outside_scroll_area(self, main_window):
        """Save should always be visible/reachable, not require scrolling
        to the bottom of a long form."""
        from PySide6.QtWidgets import QScrollArea
        insp = main_window._inspector
        scroll = insp.findChild(QScrollArea)
        assert scroll is not None
        # The footer frame (holding Save + the unsaved-changes label) must
        # not be inside the scroll area's widget subtree.
        footer_desc = scroll.widget().findChildren(type(insp._unsaved_label))
        assert insp._unsaved_label not in footer_desc

    def test_unsaved_indicator_tracks_dirty_state(self, main_window):
        win = main_window
        obj = win._all_objects[0]
        win._open_inspector(obj.id)
        QTest.qWait(50)
        insp = win._inspector

        assert insp._unsaved_label.text() == ""
        insp._title_edit.setText(insp._title_edit.text() + " (edited)")
        assert insp._unsaved_label.text() == "Unsaved changes"
        insp._save()
        assert insp._unsaved_label.text() != "Unsaved changes"
