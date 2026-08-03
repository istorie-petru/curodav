"""View tests — verify widgets render and respond correctly.

Uses QT_QPA_PLATFORM=offscreen (set in pyproject.toml or via env).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QPushButton, QSizePolicy

from src.core.filerepo.repository import FileRepository
from src.core.models import Object, ObjectStatus, ObjectType
from src.features.calendar import CalendarView
from src.features.tasks.kanban_view import KanbanBoard, _KanbanColumn
from src.features.tasks.timeline_view import GUTTER_WIDTH, MAX_GUTTER_WIDTH, MIN_GUTTER_WIDTH, TimelineView
from src.features.tasks.table_view import TaskTableView
from src.features.dashboard import DashboardView
from src.features.projects import ProjectDetailView, ProjectOverview
from src.features.search import SearchView
from src.features.settings import PreferencesDialog
from src.features.tasks import TasksView


def _make_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_objects() -> list[Object]:
    today = date.today().isoformat()
    return [
        Object(id="v1", type=ObjectType.task, title="Task 1",
               status=ObjectStatus.active, due_at=today,
               created_at="2026-01-01", updated_at="2026-01-02"),
        Object(id="v2", type=ObjectType.task, title="Task 2",
               status=ObjectStatus.in_progress, priority=2,
               created_at="2026-01-01", updated_at="2026-01-02"),
        Object(id="v3", type=ObjectType.task, title="Task 3",
               status=ObjectStatus.done, due_at=today,
               created_at="2026-01-01", updated_at="2026-01-02"),
        Object(id="v4", type=ObjectType.note, title="Note A",
               status=ObjectStatus.active,
               created_at="2026-01-01", updated_at="2026-01-02"),
        Object(id="v5", type=ObjectType.event, title="Event A",
               status=ObjectStatus.active, due_at=today,
               created_at="2026-01-01", updated_at="2026-01-02"),
        Object(id="v6", type=ObjectType.project, title="Proj X",
               status=ObjectStatus.active,
               created_at="2026-01-01", updated_at="2026-01-02"),
    ]


class TestDashboard:
    def test_stats(self):
        _make_app()
        view = DashboardView()
        view.set_objects(_make_objects())
        assert view._stats is not None

    def test_quick_add(self):
        _make_app()
        view = DashboardView()
        assert view._quick_add is not None


class TestTasks:
    def test_view_switcher(self):
        """2026-07-19: the Smart-list view was removed (see
        features/tasks.md) -- Table/Timeline/Board are the only three
        views left, and Table is now the default (index 0)."""
        _make_app()
        view = TasksView()
        assert view._stack.count() == 3
        assert view._view_names == ["table", "timeline", "board"]

    def test_set_objects(self):
        _make_app()
        view = TasksView()
        view.set_objects(_make_objects())
        assert view._all_objects is not None
        assert view._table_view is not None

    def test_smart_filters_live_on_table_view(self):
        """The old Smart view's saved filters moved to a chip bar above
        the Table view -- see table_view.py::SMART_FILTERS."""
        _make_app()
        view = TasksView()
        view.set_objects(_make_objects())
        from src.features.tasks.table_view import SMART_FILTERS
        assert len(SMART_FILTERS) == 7
        assert view._table_view._filter_bar is not None


class TestTaskTimelineSwimlanes:
    """2026-07-19: timeline rows are grouped by project, with a project's
    own overlapping tasks bin-packed into extra rows -- tasks from
    different projects never share a row. See features/tasks.md and
    core/utils/interval_packing.py."""

    def test_overlapping_tasks_in_same_project_get_different_rows(self):
        from datetime import timedelta
        from src.features.tasks.timeline_view import TimelineCanvas

        _make_app()
        today = date.today()
        proj = Object(id="pA", type=ObjectType.project, title="Website",
                      status=ObjectStatus.active, created_at="2026-01-01")
        a1 = Object(id="a1", type=ObjectType.task, title="Design", status=ObjectStatus.active,
                    parent_id="pA", start_at=today.isoformat(),
                    due_at=(today + timedelta(days=5)).isoformat(), created_at="2026-01-01")
        a2 = Object(id="a2", type=ObjectType.task, title="Copy", status=ObjectStatus.active,
                    parent_id="pA", start_at=(today + timedelta(days=2)).isoformat(),
                    due_at=(today + timedelta(days=4)).isoformat(), created_at="2026-01-01")

        canvas = TimelineCanvas()
        canvas.set_objects([proj, a1, a2])
        assert canvas._row_of["a1"] != canvas._row_of["a2"]
        assert any(label == "Website" and count == 2 for _s, count, label, _pid in canvas._project_labels)

    def test_different_projects_never_share_a_row(self):
        from datetime import timedelta
        from src.features.tasks.timeline_view import TimelineCanvas

        _make_app()
        today = date.today()
        proj_a = Object(id="pA", type=ObjectType.project, title="Alpha",
                        status=ObjectStatus.active, created_at="2026-01-01")
        proj_b = Object(id="pB", type=ObjectType.project, title="Beta",
                        status=ObjectStatus.active, created_at="2026-01-01")
        a1 = Object(id="a1", type=ObjectType.task, title="A task", status=ObjectStatus.active,
                    parent_id="pA", due_at=today.isoformat(), created_at="2026-01-01")
        b1 = Object(id="b1", type=ObjectType.task, title="B task", status=ObjectStatus.active,
                    parent_id="pB", due_at=today.isoformat(), created_at="2026-01-01")

        canvas = TimelineCanvas()
        canvas.set_objects([proj_a, proj_b, a1, b1])
        assert canvas._row_of["a1"] != canvas._row_of["b1"]
        # each project's row range must be disjoint from the other's
        a_ranges = [(s, s + c) for s, c, label, _pid in canvas._project_labels if label == "Alpha"]
        b_ranges = [(s, s + c) for s, c, label, _pid in canvas._project_labels if label == "Beta"]
        (a_start, a_end), (b_start, b_end) = a_ranges[0], b_ranges[0]
        assert a_end <= b_start or b_end <= a_start


class TestTimelinePerRowGutterLabels:
    """Feature (2026-07-18): the gutter used to show one label per project,
    vertically centered across that project's whole swimlane block --
    telling you a block of rows belonged to some project, but not which
    row was which once a project needed more than one row. Now row 0 of
    each block is the project's own name and every row after it gets a
    "Row N" label, customizable per project via `_set_row_name`
    (persisted to the project's own `details["timeline_row_names"]`, the
    same pattern used for a task's manually-placed `timeline_lane`)."""

    def _two_row_project(self):
        from src.features.tasks.timeline_view import TimelineCanvas

        today = date.today()
        proj = Object(id="pA", type=ObjectType.project, title="Website",
                      status=ObjectStatus.active, created_at="2026-01-01")
        a1 = Object(id="a1", type=ObjectType.task, title="Design", status=ObjectStatus.active,
                    parent_id="pA", start_at=today.isoformat(),
                    due_at=(today + timedelta(days=5)).isoformat(), created_at="2026-01-01")
        a2 = Object(id="a2", type=ObjectType.task, title="Copy", status=ObjectStatus.active,
                    parent_id="pA", start_at=(today + timedelta(days=2)).isoformat(),
                    due_at=(today + timedelta(days=4)).isoformat(), created_at="2026-01-01")
        canvas = TimelineCanvas()
        canvas.set_objects([proj, a1, a2])
        return canvas, proj

    def test_first_row_is_project_name_second_row_defaults_to_row_1(self):
        _make_app()
        canvas, proj = self._two_row_project()
        assert canvas._row_label("pA", 0) == "Website"
        assert canvas._row_label("pA", 1) == "Row 1"

    def test_renaming_a_row_persists_on_the_project_and_survives_reload(self, tmp_path):
        _make_app()
        canvas, proj = self._two_row_project()

        canvas._set_row_name("pA", 1, "Design track")
        assert canvas._row_label("pA", 1) == "Design track"
        assert canvas._project_objects["pA"].details["timeline_row_names"] == {"1": "Design track"}

        repo = FileRepository(base_path=tmp_path)
        repo.write_object(canvas._project_objects["pA"])
        reloaded_proj = repo.read_object("pA")
        assert reloaded_proj.details.get("timeline_row_names") == {"1": "Design track"}

        from src.features.tasks.timeline_view import TimelineCanvas
        canvas2 = TimelineCanvas()
        canvas2.set_objects([reloaded_proj])
        assert canvas2._row_label("pA", 1) == "Design track"

    def test_typing_back_the_default_name_clears_the_override(self):
        _make_app()
        canvas, proj = self._two_row_project()
        canvas._set_row_name("pA", 1, "Design track")
        assert "timeline_row_names" in canvas._project_objects["pA"].details

        canvas._set_row_name("pA", 1, "Row 1")
        assert "timeline_row_names" not in canvas._project_objects["pA"].details
        assert canvas._row_label("pA", 1) == "Row 1"

    def test_renaming_the_header_row_changes_display_only_not_the_project_title(self):
        """Feature (2026-07-18): row 0 (the project's own row) can now be
        given a custom *display* label too, same as any other row -- but
        this must only ever touch the project's `details`, never its
        actual `title`, since that title is used everywhere else in the
        app (project list, task cards, etc.)."""
        _make_app()
        canvas, proj = self._two_row_project()

        canvas._set_row_name("pA", 0, "Site Redesign Q3")
        assert canvas._row_label("pA", 0) == "Site Redesign Q3"
        assert proj.title == "Website", "the project's real title must be untouched"
        assert canvas._project_objects["pA"].details["timeline_row_names"] == {"0": "Site Redesign Q3"}

        # Typing the real project title back in clears the override, same
        # as any other row reverting to its default.
        canvas._set_row_name("pA", 0, "Website")
        assert "timeline_row_names" not in canvas._project_objects["pA"].details
        assert canvas._row_label("pA", 0) == "Website"

    def test_gutter_row_hit_maps_pixel_position_to_project_and_local_row(self):
        from PySide6.QtCore import QPointF
        _make_app()
        canvas, proj = self._two_row_project()

        header_hit = canvas._gutter_row_hit(QPointF(10, canvas._header_height + 5))
        assert header_hit == ("pA", 0)

        second_row_hit = canvas._gutter_row_hit(
            QPointF(10, canvas._header_height + canvas._row_height + 5)
        )
        assert second_row_hit == ("pA", 1)

        # Past the right edge of the gutter (over the bars/date grid) isn't a gutter hit.
        assert canvas._gutter_row_hit(QPointF(GUTTER_WIDTH + 10, canvas._header_height + 5)) is None


class TestTimelineGutterResize:
    """Feature (2026-07-18): the gutter/project-label column can be
    resized by dragging the boundary between it and the date grid, same
    interaction as a spreadsheet column resize. Session-only (not
    persisted to disk) -- clamped to [MIN_GUTTER_WIDTH, MAX_GUTTER_WIDTH]
    so it can't be dragged down to unreadable or up to swallowing the
    whole view."""

    def _canvas(self):
        tv = TimelineView()
        tv.set_objects([])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        self._tv = tv
        return tv._canvas

    def _drag_boundary(self, canvas, to_x: int):
        start_pos = QPoint(int(canvas._gutter_width), 20)
        end_pos = QPoint(to_x, 20)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pos)
        QApplication.instance().processEvents()
        QTest.mouseMove(canvas, end_pos)
        QApplication.instance().processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_pos)
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

    def test_dragging_the_boundary_widens_the_column(self):
        _make_app()
        canvas = self._canvas()
        assert canvas._gutter_width == GUTTER_WIDTH
        self._drag_boundary(canvas, GUTTER_WIDTH + 60)
        assert canvas._gutter_width == GUTTER_WIDTH + 60

    def test_resize_is_clamped_to_a_minimum(self):
        _make_app()
        canvas = self._canvas()
        self._drag_boundary(canvas, 0)
        assert canvas._gutter_width == MIN_GUTTER_WIDTH

    def test_resize_is_clamped_to_a_maximum(self):
        _make_app()
        canvas = self._canvas()
        self._drag_boundary(canvas, 5000)
        assert canvas._gutter_width == MAX_GUTTER_WIDTH

    def test_clicking_well_away_from_the_boundary_does_not_resize(self):
        """A click deep in the date grid shouldn't be misread as grabbing
        the (much narrower) resize hot zone."""
        _make_app()
        canvas = self._canvas()
        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(int(canvas._gutter_width) + 200, 20),
        )
        QApplication.instance().processEvents()
        assert canvas._gutter_width == GUTTER_WIDTH


class TestTimelineClickCreateTask:
    """Feature (2026-07-18): click-and-drag an empty grid cell to create
    a new task spanning the selected date range, in the exact row that
    was clicked -- a plain click with no drag at all still creates a
    1-day task (start == end). Emits task_created (a new Object,
    write_object'd to disk already) rather than mutating self._objects
    directly; the app is expected to persist it into its own list and
    round-trip back through set_objects, the same pattern every other
    creation path already uses (see app.py's _on_timeline_task_created)."""

    def _canvas_with_project(self):
        today = date.today()
        proj = Object(id="pA", type=ObjectType.project, title="Website",
                      status=ObjectStatus.active, created_at="2026-01-01")
        existing = Object(id="a1", type=ObjectType.task, title="Existing", status=ObjectStatus.active,
                          parent_id="pA", start_at=today.isoformat(),
                          due_at=(today + timedelta(days=1)).isoformat(), created_at="2026-01-01")
        tv = TimelineView()
        created = []
        tv.task_created.connect(created.append)
        tv.set_objects([proj, existing])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        self._tv = tv
        return tv._canvas, created

    def _day_x(self, canvas, d: date) -> int:
        return int((d - canvas._start).days * canvas._day_width + canvas._gutter_width)

    def test_drag_creates_a_task_spanning_the_selected_range_in_the_clicked_row(self):
        _make_app()
        canvas, created = self._canvas_with_project()
        today = date.today()
        start_day = today + timedelta(days=10)
        end_day = today + timedelta(days=12)
        y = canvas._header_height + canvas._row_height // 2

        QTest.mousePress(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(self._day_x(canvas, start_day), y),
        )
        QApplication.instance().processEvents()
        QTest.mouseMove(canvas, QPoint(self._day_x(canvas, end_day), y))
        QApplication.instance().processEvents()
        QTest.mouseRelease(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(self._day_x(canvas, end_day), y),
        )
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

        assert len(created) == 1
        new_obj = created[0]
        assert new_obj.type == ObjectType.task
        assert new_obj.parent_id == "pA"
        assert new_obj.start_at == start_day.isoformat()
        assert new_obj.due_at == end_day.isoformat()
        assert new_obj.details.get("timeline_lane") == 0

    def test_plain_click_with_no_drag_creates_a_one_day_task(self):
        _make_app()
        canvas, created = self._canvas_with_project()
        today = date.today()
        click_day = today + timedelta(days=5)
        y = canvas._header_height + canvas._row_height // 2

        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(self._day_x(canvas, click_day), y),
        )
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

        assert len(created) == 1
        assert created[0].start_at == created[0].due_at == click_day.isoformat()

    def test_clicking_on_an_existing_bar_does_not_create_a_task(self):
        _make_app()
        canvas, created = self._canvas_with_project()
        rect = canvas._bar_rect(0)
        assert rect is not None
        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(int(rect.center().x()), int(rect.center().y())),
        )
        QApplication.instance().processEvents()
        assert created == []

    def test_clicking_the_gutter_does_not_create_a_task(self):
        _make_app()
        canvas, created = self._canvas_with_project()
        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPoint(10, canvas._header_height + 5),
        )
        QApplication.instance().processEvents()
        assert created == []

    def test_selection_snaps_to_the_actual_grid_column_under_the_cursor(self):
        """Bug (2026-07-18): the live selection used _x_to_date
        (round-to-nearest-day-*boundary*) rather than a floor-based day-
        *column* lookup, so clicking anywhere past the midpoint of a
        column rounded up into the neighboring one -- the highlighted
        cell didn't line up with the column actually under the pointer.
        Clicking near the right edge of day-column N (but still inside
        it) must resolve to N, not N+1."""
        _make_app()
        canvas, created = self._canvas_with_project()
        day_idx = 5
        col_x = day_idx * canvas._day_width + canvas._gutter_width
        near_right_edge_x = col_x + canvas._day_width * 0.9
        assert canvas._x_to_day_index(near_right_edge_x) == day_idx

    def test_drag_selection_is_grid_aligned_edge_to_edge(self):
        """The selected range must cover whole day-columns exactly --
        starting flush on a gridline and ending flush on the next one,
        not inset or fractionally offset from the actual grid."""
        _make_app()
        canvas, created = self._canvas_with_project()
        today = date.today()
        y = canvas._header_height + canvas._row_height // 2

        start_day = today + timedelta(days=5)
        # Click partway through the start day's column, not at its left edge.
        start_x = self._day_x(canvas, start_day) + canvas._day_width * 0.6
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                          QPoint(int(start_x), y))
        QApplication.instance().processEvents()
        end_day = today + timedelta(days=7)
        QTest.mouseMove(canvas, QPoint(self._day_x(canvas, end_day) + 5, y))
        QApplication.instance().processEvents()

        assert min(canvas._create_start_day, canvas._create_end_day) == start_day
        assert max(canvas._create_start_day, canvas._create_end_day) == end_day

        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                            QPoint(self._day_x(canvas, end_day) + 5, y))
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()
        assert created[0].start_at == start_day.isoformat()
        assert created[0].due_at == end_day.isoformat()


class TestTaskTableView:
    """2026-07-19 rework: Notion-like editable table -- dropdown editors
    for status/priority/project, customizable+persisted columns, no
    inspector activation from this view. See features/tasks.md."""

    def test_status_delegate_resolves_through_proxy(self):
        """The bug that made every dropdown editor silently fall back to a
        plain QLineEdit: `index.model()` on a QTableView backed by a
        QSortFilterProxyModel is the *proxy*, which has no `_col_key`."""
        from PySide6.QtWidgets import QComboBox
        from src.features.tasks.table_view import TaskTableView

        _make_app()
        view = TaskTableView()
        view.set_objects(_make_objects())
        status_col = view._model.columns().index("status")
        proxy_index = view._proxy.index(0, status_col)
        assert view._delegate._resolve_key(proxy_index) == "status"
        editor = view._delegate.createEditor(None, None, proxy_index)
        assert isinstance(editor, QComboBox)

    def test_project_column_resolves_title_to_parent_id(self, monkeypatch, tmp_path: Path) -> None:
        """`TaskTableModel.setData()` writes via a bare `FileRepository()`,
        not whatever repo the caller passed in (a pre-existing pattern,
        not introduced by the 2026-07-19 rework -- see features/tasks.md).
        It resolves its base_path from settings.json's folder_path, so
        this test points that at the same temp folder the assertions read
        from, rather than the real ~/CommandCenter."""
        import src.core.filerepo.repository as repo_module
        from src.features.tasks.table_view import TaskTableView

        _make_app()
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True)
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(f'{{"folder_path": "{base}"}}')
        monkeypatch.setattr(repo_module, "_SETTINGS_PATH", settings_path)

        repo = FileRepository(base_path=base)
        now = "2026-07-19T00:00:00"
        proj = Object(id="p1", type=ObjectType.project, title="Website Relaunch",
                      status=ObjectStatus.active, created_at=now)
        task = Object(id="t1", type=ObjectType.task, title="Design homepage",
                      status=ObjectStatus.active, created_at=now)
        repo.write_object(proj)
        repo.write_object(task)

        view = TaskTableView()
        view.set_objects([proj, task])
        assert "Website Relaunch" in view._delegate._available_projects

        proj_col = view._model.columns().index("project")
        row = next(r for r in range(view._model.rowCount()) if view._model.object_at(r).id == "t1")
        view._model.setData(view._model.index(row, proj_col), "Website Relaunch")
        assert repo.read_object("t1").parent_id == "p1"

    def test_column_visibility_and_order_persist(self, monkeypatch, tmp_path: Path) -> None:
        import src.features.tasks.table_view as tv

        _make_app()
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr(tv, "SETTINGS_KEY", "tasks_table_columns")
        monkeypatch.setattr("src.features.settings.widgets.SETTINGS_PATH", settings_path)

        view = tv.TaskTableView()
        view.set_objects(_make_objects())
        view._toggle_column("tags", False)
        assert "tags" not in view._model.columns()
        assert "tags" not in tv._load_column_order()

        # a fresh instance picks up the persisted layout
        view2 = tv.TaskTableView()
        assert view2._model.columns() == view._model.columns()

    def test_no_inspector_activation_from_table_view(self) -> None:
        import inspect
        from src.features.tasks.table_view import TaskTableView

        src = inspect.getsource(TaskTableView)
        assert "open_object_requested.emit" not in src
        assert "doubleClicked.connect" not in src


class TestCalendar:
    def test_view_switcher(self):
        _make_app()
        view = CalendarView()
        assert view._stack.count() == 4

    def test_month_grid_objects(self):
        _make_app()
        view = CalendarView()
        view.set_objects(_make_objects())
        assert view._month_grid is not None

    def test_overlapping_events_get_separate_columns(self):
        """2026-07-19: week/day grids used to render every event at full
        column width regardless of what else was happening at the same
        time, so two overlapping events landed directly on top of each
        other with no visual indication anything was hidden. Verify the
        packing algorithm actually separates them (see _pack_overlaps)."""
        from datetime import datetime
        from src.features.calendar.widgets import _pack_overlaps

        def dt(h, m=0):
            return datetime(2026, 7, 20, h, m)

        overlapping = _pack_overlaps([
            (dt(9), dt(10), "a"), (dt(9), dt(10), "b"), (dt(9), dt(10), "c"),
        ])
        assert len({col for col, _total in overlapping.values()}) == 3
        assert all(total == 3 for _col, total in overlapping.values())

        sequential = _pack_overlaps([
            (dt(9), dt(10), "a"), (dt(10), dt(11), "b"),
        ])
        assert all(v == (0, 1) for v in sequential.values())


class TestBoards:
    def test_kanban_columns(self):
        _make_app()
        view = KanbanBoard()
        view.set_objects(_make_objects())
        assert view._columns is not None
        assert len(view._columns) == 4


class TestSearch:
    def test_empty_state(self):
        _make_app()
        view = SearchView()
        assert view._empty_state is not None

    def test_search_results(self):
        _make_app()
        view = SearchView()
        view.set_objects(_make_objects())
        view._input.setText("Task")
        view._execute_search()
        # Should find Task 1, 2, 3
        tasks_group = view._groups["Tasks"]
        assert tasks_group is not None


class TestProjects:
    def test_overview(self):
        _make_app()
        view = ProjectOverview()
        view.set_objects(_make_objects())
        assert view._empty_label is not None

    def test_detail_view(self):
        _make_app()
        view = ProjectDetailView()
        objects = _make_objects()
        view.load_project("v6", objects)
        assert view._title_edit.text() == "Proj X"


class TestSettings:
    def test_instantiate(self):
        _make_app()
        dialog = PreferencesDialog()
        assert dialog is not None

    def test_sections_are_groupboxes_not_tabs(self):
        """2026-07-19: sections moved from QTabWidget pages to titled
        QGroupBox widgets on one scrolling page (matches the design doc's
        Settings screen, needs no custom QSS). No more ._tabs.

        "Inspector" added 2026-07-18: defaults for the object inspector
        (default status/priority for new quick-add items) -- see
        InspectorTab in features/settings/widgets.py."""
        _make_app()
        dialog = PreferencesDialog()
        assert not hasattr(dialog, "_tabs")
        # top-level sections only -- SyncthingTab nests its own "Status"
        # QGroupBox internally, which findChildren() would also pick up
        top_level = [b for b in dialog.findChildren(QGroupBox) if b.parent() is dialog._scroll.widget()]
        titles = [b.title() for b in top_level]
        assert titles == [
            "General", "Appearance", "Inspector", "WebDAV", "Syncthing", "Calendar", "Tags", "About",
        ]

    def test_appearance_section_is_style_only(self):
        """Theme/Density/Shape/Accent are gone for good (2026-07-17) -- they
        never did anything. Qt Style is back (2026-07-18, restored after
        being wrongly removed alongside those) since it's a real, working
        setting (QStyleFactory + QApplication.setStyle), unlike the rest."""
        _make_app()
        dialog = PreferencesDialog()
        assert hasattr(dialog._appearance, "_style")
        assert not hasattr(dialog._appearance, "_theme")
        assert not hasattr(dialog._appearance, "_density")
        assert not hasattr(dialog._appearance, "_shape")
        assert not hasattr(dialog._appearance, "_accent")


class TestKanbanGeometry:
    """Regression test for the 2026-07-20 dead-space-above-cards fix:
    the column header's QLabel must stay pinned to its sizeHint height
    instead of absorbing leftover vertical space (see _KanbanColumn's
    __init__ comment for the full root-cause writeup)."""

    def test_header_is_fixed_vertical_policy(self):
        _make_app()
        col = _KanbanColumn("Todo", ObjectStatus.active)
        assert col._header.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed

    def test_header_height_matches_sizehint_after_layout(self):
        _make_app()
        board = KanbanBoard()
        board.set_objects(_make_objects())
        board.resize(1000, 700)
        board.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        for col in board._columns:
            hint_h = col._header.sizeHint().height()
            actual_h = col._header.height()
            # allow a couple px of style/font rounding, but the header
            # must not be absorbing large amounts of leftover space
            assert actual_h <= hint_h + 4, f"header grew to {actual_h}px (sizeHint {hint_h}px)"


class TestTimelineToolbar:
    """2026-07-18: the zoom toggle itself (Day/Week buttons) was removed
    entirely once Day zoom went away, leaving nothing left to toggle --
    so the old "buttons stay fixed while scrolling" regression test no
    longer applies (there's no toolbar row above the canvas to test).
    What's still worth guarding is the underlying structural fix it was
    testing: the canvas is independently scrollable, nested by itself
    inside the QScrollArea, not sharing scroll state with anything else
    that might someday sit above it again."""

    def test_only_canvas_is_inside_the_scroll_area(self):
        """Structural check that the toolbar isn't nested inside the
        QScrollArea at all (the actual 2026-07-19 bug), not just that it
        happens not to move in this one scenario."""
        _make_app()
        tv = TimelineView()
        assert tv._scroll.widget() is tv._canvas


class TestTimelineZoomScaling:
    """Regression tests for the 2026-07-20 rework of Week zoom.

    Went through several intermediate designs before landing here (none
    worth re-testing individually): a first pass gave Week and Month
    zoom wider rolling default windows and week-boundary-only gridlines;
    a correction reverted Week zoom to per-day gridlines/labels since
    showing days as the actual interval is the whole point of Week zoom;
    Month zoom itself was removed entirely, and then Day zoom was too
    (2026-07-18) -- this view is Week-only now, with no toggle. Final
    date-range design: the rolling today-N..today+M window was replaced
    with calendar-aligned months -- the previous, current, and next
    month.
    """

    def _canvas_at(self, objects=None):
        tv = TimelineView()
        tv.set_objects(objects or [])
        tv.resize(900, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        self._tv = tv  # keep a Python reference alive so Qt doesn't GC the canvas out from under the test
        return tv._canvas

    def test_no_zoom_toggle_exists(self):
        _make_app()
        tv = TimelineView()
        assert not hasattr(tv, "_zoom_group"), "Day zoom was removed 2026-07-18 -- there's nothing left to toggle"

    def test_shows_previous_current_and_next_month(self):
        _make_app()
        import calendar as _calendar
        today = date.today()
        canvas = self._canvas_at()
        prev_month_index = today.month - 2  # 0-based, one month back
        prev_year = today.year + prev_month_index // 12
        prev_month = prev_month_index % 12 + 1
        expected_start = date(prev_year, prev_month, 1)

        next_month_index = today.month  # 0-based, one month forward
        next_year = today.year + next_month_index // 12
        next_month = next_month_index % 12 + 1
        expected_end = date(next_year, next_month, _calendar.monthrange(next_year, next_month)[1])

        assert canvas._start == expected_start
        assert canvas._end == expected_end

    def test_marks_every_day(self):
        """Shows days as the actual interval -- every day gets a
        gridline, not just week boundaries."""
        _make_app()
        canvas = self._canvas_at()
        assert canvas._grid_line_day_indices() == list(range(canvas._total_days + 1))


class TestTimelineWeekHeading:
    """Regression tests for the 2026-07-20 fix: Week zoom's header used to
    be a single row where a Monday's label used "%b %d" (e.g. "Jul 06",
    ~6 characters) squeezed into a single 24px-wide day column -- the
    text overflowed past its own column and visually overlapped the
    following days' bare-number labels. Week zoom now has a two-row
    header: a "Week NN" heading drawn once per week (spanning that whole
    week's ~168px, not fighting a single day's 24px), and a plain day
    number per day underneath it, on its own row so it never collides
    with the week heading regardless of how wide "Week NN" renders.

    A second, related overlap was caught visually (via a real rendered
    screenshot, not just geometry) after switching to calendar-aligned
    months the same day: when the visible range doesn't start on a
    Monday, the leading partial week can be only a couple of days wide --
    narrower than "Week NN" itself -- and the label bled into the very
    next week's label with no gap. Fixed by clipping each week label to
    a QRectF bounded by the *next* label's x-position (Qt clips
    rect-based drawText calls to the rect by default), instead of
    drawing at a bare unbounded (x, y) point."""

    def _canvas(self, objects=None):
        tv = TimelineView()
        tv.set_objects(objects or [])
        tv.resize(900, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        self._tv = tv  # keep a Python reference alive so Qt doesn't GC the canvas out from under the test
        return tv._canvas

    def test_week_start_indices_are_mondays(self):
        _make_app()
        canvas = self._canvas()
        indices = canvas._week_start_indices()
        # every index past the first should land on a Monday; the first
        # may be a leading partial week that isn't
        for i in indices[1:]:
            d = canvas._start + timedelta(days=i)
            assert d.weekday() == 0, f"non-Monday week-start index {i} ({d})"

    def test_leading_partial_week_still_gets_a_heading(self):
        """If the visible range doesn't happen to start on a Monday, day
        0 should still get a week-number heading rather than showing no
        heading at all for that first, partial week."""
        _make_app()
        canvas = self._canvas()
        if canvas._start.weekday() != 0:
            assert canvas._week_start_indices()[0] == 0

    def test_isocalendar_week_number_is_correct(self):
        _make_app()
        canvas = self._canvas()
        i = canvas._week_start_indices()[-1]
        d = canvas._start + timedelta(days=i)
        assert d.isocalendar()[1] == d.isocalendar().week

    def test_week_header_renders_without_error(self):
        _make_app()
        canvas = self._canvas()
        canvas.repaint()  # would raise if _draw_header's week branch had a bug
        QApplication.instance().processEvents()

    def test_leading_partial_week_label_is_clipped_not_overlapping(self):
        """Reproduce the exact geometry that caused the visual overlap:
        a leading partial week narrower than a full week's ~168px. The
        available width for that label (up to the next week's x
        position) must be strictly less than a full week's width, and
        never negative -- confirming the label is actually bounded to a
        narrower rect rather than drawn unclipped."""
        _make_app()
        canvas = self._canvas()
        week_indices = canvas._week_start_indices()
        if canvas._start.weekday() == 0:
            return  # range happens to start on a Monday this month -- no partial week to check
        assert len(week_indices) >= 2
        first_x = week_indices[0] * canvas._day_width + GUTTER_WIDTH
        next_x = week_indices[1] * canvas._day_width + GUTTER_WIDTH
        available_width = next_x - first_x
        assert 0 <= available_width < 7 * canvas._day_width


class TestTimelineNoOverlappingTasksInARow:
    """Explicit regression coverage (2026-07-20) that two overlapping
    tasks in the same project never land on the same swimlane row, at
    either remaining zoom level (Day, Week). The bin-packing itself
    (`_assign_swimlanes` / `core/utils/interval_packing.pack_intervals`)
    predates this date -- it shipped with project swimlanes on
    2026-07-19 -- but wasn't previously exercised as its own explicit
    "does this actually prevent overlap" test per zoom, and was
    re-verified here after the Month-zoom-only visibility filtering that
    briefly wrapped `_assign_swimlanes` was removed."""

    def _canvas_at(self, objects):
        tv = TimelineView()
        tv.set_objects(objects)
        tv.resize(900, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
        self._tv = tv  # keep a Python reference alive so Qt doesn't GC the canvas out from under the test
        return tv._canvas

    def _overlapping_same_project_objects(self):
        today = date.today()
        project = Object(id="p1", type=ObjectType.project, title="ProjectA", status="active",
                          created_at="2026-01-01", updated_at="2026-01-02")
        t1 = Object(id="t1", type=ObjectType.task, title="TaskA", status="active", parent_id="p1",
                    start_at=today.isoformat(), due_at=(today + timedelta(days=5)).isoformat(),
                    created_at="2026-01-01", updated_at="2026-01-02")
        t2 = Object(id="t2", type=ObjectType.task, title="TaskB", status="active", parent_id="p1",
                    start_at=(today + timedelta(days=2)).isoformat(),
                    due_at=(today + timedelta(days=8)).isoformat(),
                    created_at="2026-01-01", updated_at="2026-01-02")
        return [project, t1, t2]

    def test_no_overlap(self):
        _make_app()
        objects = self._overlapping_same_project_objects()
        canvas = self._canvas_at(objects)
        # canvas._objects filters out the project object (set_objects
        # keeps tasks only), so within the canvas the two tasks are
        # indices 0 and 1, not 1 and 2 as in the `objects` list passed
        # in above -- get the real indices by id rather than assuming
        # position, so this can't silently drift out of sync again.
        ids = [o.id for o in canvas._objects]
        idx_t1 = ids.index("t1")
        idx_t2 = ids.index("t2")
        row1 = canvas._row_for(idx_t1)
        row2 = canvas._row_for(idx_t2)
        assert row1 != row2, "overlapping same-project tasks landed on the same row"
        assert canvas._total_rows >= 2

    def test_bar_rects_do_not_visually_overlap(self):
        """Beyond just "different row number" -- confirm the actual
        painted rectangles don't intersect."""
        _make_app()
        objects = self._overlapping_same_project_objects()
        canvas = self._canvas_at(objects)
        ids = [o.id for o in canvas._objects]
        rect1 = canvas._bar_rect(ids.index("t1"))
        rect2 = canvas._bar_rect(ids.index("t2"))
        assert rect1 is not None and rect2 is not None
        assert not rect1.intersects(rect2)


class TestTimelineRowsMergeAfterDragEndsOverlap:
    """Regression test (2026-07-18): _assign_swimlanes only ran inside
    set_objects(). mouseMoveEvent mutated the dragged task's dates in
    place and just repainted; mouseReleaseEvent persisted to disk but
    never recomputed row packing. So a task dragged apart from another
    (no longer overlapping) kept whatever row it was packed into
    *before* the drag, until the next full set_objects() refresh -- which
    for the Timeline specifically never even happened after a
    reschedule, since _on_timeline_rescheduled in widgets.py only
    refreshed the task list and table view. Fixed by calling
    _assign_swimlanes()/_compute_range() directly in mouseReleaseEvent.
    """

    def test_rows_merge_once_dragged_apart_no_longer_overlap(self):
        _make_app()
        today = date.today()
        o1 = Object(id="a", type=ObjectType.task, title="A", status="active",
                     start_at=today.isoformat(), due_at=(today + timedelta(days=3)).isoformat(),
                     created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")
        o2 = Object(id="b", type=ObjectType.task, title="B", status="active",
                     start_at=today.isoformat(), due_at=(today + timedelta(days=3)).isoformat(),
                     created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")

        tv = TimelineView()
        tv.set_objects([o1, o2])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        assert canvas._row_of["a"] != canvas._row_of["b"], "sanity: should start out overlapping in different rows"

        rect = canvas._bar_rect(1)
        start_pos = QPoint(int(rect.center().x()), int(rect.center().y()))
        end_pos = QPoint(start_pos.x() + canvas._day_width * 10, start_pos.y())
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pos)
        app.processEvents()
        QTest.mouseMove(canvas, end_pos)
        app.processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_pos)
        app.processEvents()
        app.processEvents()

        assert canvas._row_of["a"] == canvas._row_of["b"], \
            "rows should merge back once the dragged task no longer overlaps"


class TestTimelineManualVerticalPlacement:
    """Feature (2026-07-18): a "move" drag can now reposition a task
    vertically, not just reschedule it -- letting the user park a task on
    any row within its own project's swimlane block for deliberate visual
    grouping/spacing, on top of (not instead of) the existing automatic
    no-overlap packing. The target row is persisted to
    `details["timeline_lane"]` (write_object already serializes any
    truthy `details` dict) so it survives a restart, and _assign_swimlanes
    treats it as an unclamped `preferred` lane -- unlike the ordinary
    stability preference, it's allowed to leave empty rows on purpose.
    pack_intervals' own "preferred lane if free, else lowest free"
    fallback is what guarantees this can never actually create an
    overlap: requesting an occupied row just quietly resolves to the
    nearest free one instead of being honored literally.
    """

    def _drag_vertically(self, canvas, idx: int, row_delta: int):
        rect = canvas._bar_rect(idx)
        start_pos = QPoint(int(rect.center().x()), int(rect.center().y()))
        end_pos = QPoint(start_pos.x(), start_pos.y() + canvas._row_height * row_delta)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pos)
        QApplication.instance().processEvents()
        QTest.mouseMove(canvas, end_pos)
        QApplication.instance().processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_pos)
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

    def test_dragging_straight_down_pins_task_to_a_lower_empty_row(self):
        _make_app()
        today = date.today()
        a = Object(id="a", type=ObjectType.task, title="A", status="active",
                   start_at=today.isoformat(), due_at=(today + timedelta(days=2)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")
        b = Object(id="b", type=ObjectType.task, title="B", status="active",
                   start_at=(today + timedelta(days=10)).isoformat(),
                   due_at=(today + timedelta(days=12)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")

        tv = TimelineView()
        tv.set_objects([a, b])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        assert canvas._row_of["a"] == canvas._row_of["b"] == 0, \
            "sanity: non-overlapping tasks should both start on lane 0"

        b_idx = [o.id for o in canvas._objects].index("b")
        self._drag_vertically(canvas, b_idx, row_delta=2)

        assert canvas._row_of["b"] == 2, f"expected b pinned to row 2, got {canvas._row_of['b']}"
        assert canvas._row_of["a"] == 0, "untouched task should stay put"
        assert canvas._objects[b_idx].details.get("timeline_lane") == 2
        # Dates must be untouched by a purely-vertical drag.
        assert canvas._objects[b_idx].start_at == (today + timedelta(days=10)).isoformat()
        assert canvas._objects[b_idx].due_at == (today + timedelta(days=12)).isoformat()

    def test_manual_placement_survives_a_fresh_reload_from_disk(self, tmp_path):
        _make_app()
        today = date.today()
        a = Object(id="a", type=ObjectType.task, title="A", status="active",
                   start_at=today.isoformat(), due_at=(today + timedelta(days=2)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")
        b = Object(id="b", type=ObjectType.task, title="B", status="active",
                   start_at=(today + timedelta(days=10)).isoformat(),
                   due_at=(today + timedelta(days=12)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")

        tv = TimelineView()
        tv.set_objects([a, b])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        b_idx = [o.id for o in canvas._objects].index("b")
        self._drag_vertically(canvas, b_idx, row_delta=2)
        assert canvas._row_of["b"] == 2

        repo = FileRepository(base_path=tmp_path)
        repo.write_object(canvas._objects[0])
        repo.write_object(canvas._objects[1])
        reloaded_a = repo.read_object("a")
        reloaded_b = repo.read_object("b")
        assert reloaded_b.details.get("timeline_lane") == 2

        tv2 = TimelineView()
        tv2.set_objects([reloaded_a, reloaded_b])
        tv2.resize(1200, 500)
        tv2.show()
        app.processEvents()
        app.processEvents()
        assert tv2._canvas._row_of["b"] == 2, "manual placement should survive a fresh load from disk"

    def test_dragging_onto_an_occupied_row_never_creates_a_collision(self):
        _make_app()
        today = date.today()
        a = Object(id="a", type=ObjectType.task, title="A", status="active",
                   start_at=today.isoformat(), due_at=(today + timedelta(days=5)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")
        b = Object(id="b", type=ObjectType.task, title="B", status="active",
                   start_at=(today + timedelta(days=1)).isoformat(),
                   due_at=(today + timedelta(days=6)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")

        tv = TimelineView()
        tv.set_objects([a, b])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        assert canvas._row_of["a"] != canvas._row_of["b"], "sanity: a and b overlap in time"

        b_idx = [o.id for o in canvas._objects].index("b")
        a_row, b_row = canvas._row_of["a"], canvas._row_of["b"]
        self._drag_vertically(canvas, b_idx, row_delta=(a_row - b_row))

        assert canvas._row_of["a"] != canvas._row_of["b"], \
            "must never let two time-overlapping tasks land on the same row"
        rect_a = canvas._bar_rect([o.id for o in canvas._objects].index("a"))
        rect_b = canvas._bar_rect(b_idx)
        assert not rect_a.intersects(rect_b)


class TestTimelineResizeKeepsOwnRowInsteadOfBumpingToTheBottom:
    """Regression test (2026-07-18): pack_intervals sorts by (start, end)
    and assigns lowest-free-lane in that order. Resizing a task changes
    its own sort key, which can reorder it relative to its neighbors
    within the same overlap cluster -- so even a resize that leaves a
    genuine, unavoidable conflict could land the *resized* task itself in
    a new (often the highest/bottom) lane, rather than the lane it
    already occupied, purely as a side effect of re-sorting -- not because
    it actually needed to move. Fixed by preferring each task's previous
    lane (see pack_intervals' `preferred` param), clamped to never exceed
    the natural (preference-free) minimum lane count for its cluster, so
    a resize that creates a real conflict still bumps *something* -- just
    not necessarily the task that was resized.
    """

    def test_resized_task_keeps_its_lane_when_new_overlap_appears(self):
        _make_app()
        today = date.today()
        a = Object(id="a", type=ObjectType.task, title="A", status="active",
                   start_at=today.isoformat(), due_at=(today + timedelta(days=2)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")
        b = Object(id="b", type=ObjectType.task, title="B", status="active",
                   start_at=(today + timedelta(days=3)).isoformat(),
                   due_at=(today + timedelta(days=5)).isoformat(),
                   created_at="2026-01-01", updated_at="2026-01-01", parent_id="p1")

        tv = TimelineView()
        tv.set_objects([a, b])
        tv.resize(1200, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        assert canvas._row_of["a"] == canvas._row_of["b"] == 0, \
            "sanity: non-overlapping tasks should both start on lane 0"

        # Drag a's right edge out far enough to genuinely overlap b.
        rect = canvas._bar_rect(0)
        start_pos = QPoint(int(rect.right()) - 1, int(rect.center().y()))
        end_pos = QPoint(start_pos.x() + canvas._day_width * 4, start_pos.y())
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pos)
        app.processEvents()
        QTest.mouseMove(canvas, end_pos)
        app.processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_pos)
        app.processEvents()
        app.processEvents()

        assert canvas._row_of["a"] == 0, \
            f"the resized task should keep its own row, got {canvas._row_of['a']}"
        assert canvas._row_of["b"] == 1, \
            "the *other*, untouched task should be the one bumped to a new row"


class TestTimelineResizeRightSingleDayTask:
    """Regression test for the 2026-07-20 fix: dragging a single-day
    (no explicit start_at) task's *right* edge visibly just moved the
    whole bar instead of growing it, while the left edge worked fine.

    Root cause: with no explicit start_at, both `_bar_rect` and
    `mousePressEvent` fell back to using due_at as the display start. A
    right-resize only ever wrote due_at, so on the next repaint the
    still-unset start_at re-resolved to that same (just-moved) due_at --
    both edges walked forward together. Left-resize never showed this
    because it writes start_at explicitly on the very first drag,
    permanently escaping the fallback. Fixed by freezing start_at to its
    resolved value the moment *any* resize drag begins.

    A second, related bug surfaced while writing this test: at Month
    zoom a single-day bar is only 8px wide -- narrower than the 20px
    combined width of both resize handles -- so the old "check left
    handle first" hit-test always classified clicks on such a bar as
    resize_left regardless of which edge was actually clicked, silently
    no-opping right-edge drags (resize_left's own guard rejects moving
    start past due). Fixed by splitting narrow bars at their visual
    midpoint instead of a fixed handle-check order.
    """

    def _drag_right_edge(self, canvas, day_delta: int):
        rect = canvas._bar_rect(0)
        start_pos = QPoint(int(rect.right()) - 1, int(rect.center().y()))
        end_pos = QPoint(start_pos.x() + canvas._day_width * day_delta, start_pos.y())
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pos)
        QApplication.instance().processEvents()
        QTest.mouseMove(canvas, end_pos)
        QApplication.instance().processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_pos)
        QApplication.instance().processEvents()
        QApplication.instance().processEvents()

    def test_right_resize_grows_due_without_moving_start(self):
        _make_app()
        due = date.today().replace(day=min(date.today().day + 3, 28))
        obj = Object(id="tr1", type=ObjectType.task, title="OneDay", status="active",
                     start_at=None, due_at=due.isoformat(),
                     created_at="2026-01-01", updated_at="2026-01-02")
        tv = TimelineView()
        tv.set_objects([obj])
        tv.resize(900, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        before_due = canvas._objects[0].due_at
        self._drag_right_edge(canvas, day_delta=3)

        after_start = canvas._objects[0].start_at
        after_due = canvas._objects[0].due_at
        assert after_start == before_due, "start should freeze at the original due date, not drift with it"
        assert after_due != before_due, "due date should have grown"

    def test_right_resize_works_when_bar_is_narrower_than_both_handles(self):
        """The hit-test-ambiguity bug only showed up when the bar was
        narrower than both handle zones combined (HANDLE_WIDTH*2 = 20px).

        This used to be reachable at Month zoom with a single-day task
        (8px bar), which was the scenario that originally exposed the
        bug. As of the 2026-07-20 Month-zoom-hides-short-tasks change,
        that specific combination can no longer occur through the UI --
        the shortest task visible at Month zoom is >= 7 days, which even
        at 8px/day is 56px wide, comfortably past the ambiguous case. The
        hit-test's midpoint-split fix is still real and still worth
        covering, so this exercises `_hit_test` directly with an
        artificially tiny day_width (bypassing the zoom/visibility
        system entirely) to reproduce the exact narrow-bar geometry.
        """
        _make_app()
        due = date.today().replace(day=min(date.today().day + 3, 28))
        obj = Object(id="tr2", type=ObjectType.task, title="OneDay", status="active",
                     start_at=None, due_at=due.isoformat(),
                     created_at="2026-01-01", updated_at="2026-01-02")
        tv = TimelineView()
        tv.set_objects([obj])
        tv.resize(900, 500)
        tv.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        canvas = tv._canvas
        canvas._day_width = 2  # artificially force a bar narrower than HANDLE_WIDTH*2 (20px)
        assert canvas._bar_rect(0).width() <= 10  # sanity: this is the narrow-bar case
        before_due = canvas._objects[0].due_at
        self._drag_right_edge(canvas, day_delta=3)
        assert canvas._objects[0].due_at != before_due


class TestTaskTableSingleClickEdit:
    """Regression test for the 2026-07-20 fix: a single click on a
    dropdown cell (status/priority/project) must open its editor with
    the popup already showing, instead of requiring a double-click to
    enter edit mode and a further click to open the dropdown.

    A first attempt used `EditTrigger.CurrentChanged` and a test that
    called `table.edit()`/inspected state directly after one simulated
    click -- that test passed, but the real running app still needed two
    clicks (the first only selected the row). The trigger-based approach
    was replaced with `table.clicked` wired directly to `table.edit()`
    (see `TaskTableView.__init__`), which forces the editor open on every
    click deterministically instead of depending on Qt's internal
    current-index-changed timing. These tests exercise *that* mechanism:
    the `clicked` signal itself, fired via a real `QTest.mouseClick` on
    the viewport (not a raw model index lookup), including a second click
    on a *different* row to confirm it isn't a one-shot/first-click-only
    fluke."""

    def _build(self):
        tv = TaskTableView()
        objs = [
            Object(id="tc1", type=ObjectType.task, title="Task A", status="active", priority=2,
                   created_at="2026-01-01", updated_at="2026-01-02"),
            Object(id="tc2", type=ObjectType.task, title="Task B", status="waiting", priority=1,
                   created_at="2026-01-01", updated_at="2026-01-02"),
        ]
        tv.set_objects(objs)
        tv.resize(800, 300)
        tv.show()
        return tv

    def test_single_click_opens_combo_editor(self):
        _make_app()
        tv = self._build()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        table = tv._table
        status_col = tv._model.columns().index("status")
        index = table.model().index(0, status_col)
        rect = table.visualRect(index)
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        app.processEvents()
        app.processEvents()

        editor = table.indexWidget(index)
        assert isinstance(editor, QComboBox)

    def test_single_click_works_on_a_row_that_is_not_the_default_current_index(self):
        """The bug report was specifically that the *first* click after
        some other cell was already current/selected only selected --
        it took a second click to actually edit. Click row 1's title
        first (an unrelated cell, establishing a "previous" current
        index), then click row 2's priority cell exactly once and expect
        the editor to already be open."""
        _make_app()
        tv = self._build()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        table = tv._table
        title_col = tv._model.columns().index("title")
        title_index = table.model().index(0, title_col)
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            table.visualRect(title_index).center(),
        )
        app.processEvents()
        app.processEvents()
        table.closePersistentEditor(title_index) if table.isPersistentEditorOpen(title_index) else None
        # closing whatever editor row 1's title opened, same as a user
        # clicking away, before the click under test
        table.setCurrentIndex(title_index)

        priority_col = tv._model.columns().index("priority")
        priority_index = table.model().index(1, priority_col)
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            table.visualRect(priority_index).center(),
        )
        app.processEvents()
        app.processEvents()

        editor = table.indexWidget(priority_index)
        assert isinstance(editor, QComboBox), (
            "expected the dropdown editor to open on the first click on this "
            "cell, not require a second click"
        )

    def test_second_row_also_single_click_edits(self):
        """Not just the row that happens to be default-current on load --
        clicking straight into row 2 (never previously touched) must also
        open its editor on the first click."""
        _make_app()
        tv = self._build()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()

        table = tv._table
        status_col = tv._model.columns().index("status")
        index = table.model().index(1, status_col)
        QTest.mouseClick(
            table.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            table.visualRect(index).center(),
        )
        app.processEvents()
        app.processEvents()

        editor = table.indexWidget(index)
        assert isinstance(editor, QComboBox)
