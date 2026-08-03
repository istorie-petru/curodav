"""Interaction tests — simulate user actions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.core.db.database import Database
from src.core.filerepo.repository import FileRepository
from src.core.models import Object, ObjectStatus, ObjectType
from src.features.shared.create import create_task_from_quickadd


def _make_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_repo(tmp_path: Path) -> FileRepository:
    base = tmp_path / "CommandCenter"
    (base / "objects").mkdir(parents=True, exist_ok=True)
    return FileRepository(base_path=base)


class TestQuickAdd:
    def test_create_task(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        obj = create_task_from_quickadd("Buy groceries !2 @tomorrow >home", repo)
        assert obj.title == "Buy groceries"
        assert obj.priority == 2
        assert obj.due_at is not None
        assert "home" in obj.tags

    def test_create_task_with_project(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        obj = create_task_from_quickadd("Fix bug #TestProject", repo)
        assert obj.parent_id is not None
        proj = repo.read_object(obj.parent_id)
        assert proj is not None
        assert proj.type == ObjectType.project
        assert proj.title == "TestProject"

    def test_multiple_quickadds(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        titles = ["Task A", "Task B", "Task C", "Task D", "Task E"]
        for t in titles:
            obj = create_task_from_quickadd(t, repo)
            assert obj.title == t
        ids = repo.list_object_ids()
        # 5 new + any pre-existing
        assert any(t in repo.read_object(oid).title for oid in ids for t in titles)

    def test_parse_priority(self):
        obj = create_task_from_quickadd("Urgent !1", _make_repo(Path("/tmp/test_qa")))
        assert obj.priority == 1


class TestInspector:
    def test_create_and_edit(self, tmp_path: Path) -> None:
        from src.widgets.inspector import InspectorPanel

        _make_app()
        repo = _make_repo(tmp_path)
        now = "2026-01-01T00:00:00"
        obj = Object(id="insp-1", type=ObjectType.task, title="Original",
                     status=ObjectStatus.active,
                     created_at=now, updated_at=now)
        repo.write_object(obj)

        panel = InspectorPanel()
        panel.set_file_repo(repo)
        panel.open_object(obj)

        assert panel._title_edit.text() == "Original"

        panel._title_edit.setText("Edited")
        # Simulate status change
        panel._status_combo.setCurrentText(ObjectStatus.done)
        panel._save()
        reloaded = repo.read_object("insp-1")
        assert reloaded is not None
        assert reloaded.title == "Edited"
        assert reloaded.status == ObjectStatus.done

    def test_recurrence_round_trips(self, tmp_path: Path) -> None:
        """2026-07-19: set a weekly repeat + an exception date through the
        inspector's recurrence controls, save, and verify it persists and
        parses back to the same rule (core/recurrence.py)."""
        from PySide6.QtCore import QDate
        from src.core.recurrence import RecurrenceRule
        from src.widgets.inspector import InspectorPanel

        _make_app()
        repo = _make_repo(tmp_path)
        now = "2026-07-06T09:00:00"
        obj = Object(id="ev-recur", type=ObjectType.event, title="Standup",
                     status=ObjectStatus.active, due_at="2026-07-06", start_at=now,
                     created_at=now, updated_at=now)
        repo.write_object(obj)

        panel = InspectorPanel()
        panel.set_file_repo(repo)
        panel.open_object(obj)

        panel._recur_enabled.setChecked(True)
        panel._recur_freq.setCurrentIndex(panel._recur_freq.findData("weekly"))
        panel._recur_weekday_checks[0].setChecked(True)  # Monday
        panel._recur_end_combo.setCurrentIndex(panel._recur_end_combo.findData("until"))
        panel._recur_until.setDate(QDate(2026, 8, 3))
        panel._add_recur_exception()  # excepts the due date currently on the form (2026-07-06)
        panel._save()

        reloaded = repo.read_object("ev-recur")
        rule = RecurrenceRule.from_rule_string(reloaded.details.get("recurrence"))
        assert rule is not None
        assert rule.freq == "weekly"
        assert rule.weekdays == frozenset({0})
        assert rule.until == date(2026, 8, 3)
        assert date(2026, 7, 6) in rule.exceptions
        # start_at's time-of-day must survive the save (a real bug found
        # while wiring this up -- the date-only QDateEdit used to clobber it)
        assert reloaded.start_at == "2026-07-06T09:00:00"


class TestCalendarInteractions:
    def test_view_switch(self):
        from src.features.calendar import CalendarView

        _make_app()
        view = CalendarView()
        assert view._stack.currentIndex() == 0

        view._on_view_switched(1)
        assert view._stack.currentIndex() == 1

        view._on_view_switched(2)
        assert view._stack.currentIndex() == 2

        view._on_view_switched(3)
        assert view._stack.currentIndex() == 3


class TestFilterInteractions:
    """2026-07-19: the Smart view's tag-filter bar and the Tasks toolbar's
    project-filter dropdown were both removed along with the Smart view
    itself (see features/tasks.md). The Smart filters that survived moved
    to a chip bar above the Table view (`TaskTableFilterBar`); that's what
    these now exercise instead."""

    def test_smart_filter_chip_narrows_table_rows(self):
        from src.features.tasks import TasksView
        from src.features.tasks.table_view import SMART_FILTERS

        _make_app()
        today = date.today().isoformat()
        objects = [
            Object(id="f1", type=ObjectType.task, title="Done task",
                   status=ObjectStatus.done, due_at=today,
                   created_at="2026-01-01", updated_at="2026-01-02"),
            Object(id="f2", type=ObjectType.task, title="Active task",
                   status=ObjectStatus.active, due_at=today,
                   created_at="2026-01-01", updated_at="2026-01-02"),
        ]

        view = TasksView()
        view.set_objects(objects)
        table = view._table_view
        completed_idx = next(i for i, (name, _fn) in enumerate(SMART_FILTERS) if name == "Completed")
        table._on_filter_changed(completed_idx)
        assert table._model.rowCount() == 1
        assert table._model.object_at(0).id == "f1"

    def test_project_column_resolves_title(self):
        from src.features.tasks import TasksView

        _make_app()
        today = date.today().isoformat()
        objects = [
            Object(id="p1", type=ObjectType.task, title="Project task",
                   status=ObjectStatus.active, parent_id="p3",
                   due_at=today,
                   created_at="2026-01-01", updated_at="2026-01-02"),
            Object(id="p3", type=ObjectType.project, title="Proj",
                   status=ObjectStatus.active,
                   created_at="2026-01-01", updated_at="2026-01-02"),
        ]
        view = TasksView()
        view.set_objects(objects)
        table = view._table_view
        table._on_filter_changed(2)  # "All Open" -- includes the task above
        obj = table._model.object_at(0)
        assert table._model._project_title(obj) == "Proj"


class TestTaskViewInteraction:
    def test_view_switcher(self):
        from src.features.tasks import TasksView

        _make_app()
        view = TasksView()
        assert view._stack.currentIndex() == 0
        view._on_view_switched(1)
        assert view._stack.currentIndex() == 1
        view._on_view_switched(2)
        assert view._stack.currentIndex() == 2


class TestContextMenuActionsPersist:
    """Regression tests for the 2026-07-20 fix: the right-click context
    menu shared by the smart-list row and the Timeline bar
    (`TasksView._on_task_context_action`), and Kanban's card context menu
    (`KanbanBoard._on_card_action`), mutated `_all_objects` in memory and
    re-rendered, but never called `FileRepository().write_object()` /
    `.delete_object()` for the duplicate/delete/status actions -- so a
    status change, duplicate, or delete looked like it worked for the
    rest of the session and silently reverted on the next app restart.
    Drag-and-drop already persisted correctly in both views; only these
    three right-click actions were missing it.

    Both handlers construct `FileRepository()` with no arguments (by
    design, matching every other ad-hoc call site in the app -- see
    `_default_command_center()`'s docstring), so these tests patch that
    resolution function rather than passing an explicit repository,
    to exercise the exact code path a real click goes through.
    """

    def _patch_default_repo(self, monkeypatch, tmp_path: Path) -> Path:
        import src.core.filerepo.repository as fr_mod
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(fr_mod, "_default_command_center", lambda: base)
        return base

    def _reread(self, base: Path, object_id: str) -> Object | None:
        """Simulate an app restart: a brand new, independently-constructed
        FileRepository re-reading from disk, not the same instance/cache."""
        return FileRepository(base_path=base).read_object(object_id)

    def test_timeline_status_change_persists(self, monkeypatch, tmp_path: Path) -> None:
        from src.features.tasks import TasksView

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        repo = FileRepository(base_path=base)
        obj = Object(id="ctx1", type=ObjectType.task, title="Task", status="waiting",
                     created_at="2026-01-01", updated_at="2026-01-02")
        repo.write_object(obj)

        view = TasksView()
        view.set_file_repo(repo)
        view.set_objects([obj])
        view._on_task_context_action("ctx1", "status:done")

        reread = self._reread(base, "ctx1")
        assert reread is not None
        assert reread.status == "done"

    def test_timeline_duplicate_persists(self, monkeypatch, tmp_path: Path) -> None:
        from src.features.tasks import TasksView

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        repo = FileRepository(base_path=base)
        obj = Object(id="ctx2", type=ObjectType.task, title="Task", status="active",
                     created_at="2026-01-01", updated_at="2026-01-02")
        repo.write_object(obj)

        view = TasksView()
        view.set_file_repo(repo)
        view.set_objects([obj])
        view._on_task_context_action("ctx2", "duplicate")

        reread_repo = FileRepository(base_path=base)
        dup_ids = [oid for oid in reread_repo.list_object_ids() if oid != "ctx2"]
        assert len(dup_ids) == 1
        dup = reread_repo.read_object(dup_ids[0])
        assert dup.title == "Task (copy)"

    def test_timeline_delete_persists(self, monkeypatch, tmp_path: Path) -> None:
        from src.features.tasks import TasksView

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        repo = FileRepository(base_path=base)
        obj = Object(id="ctx3", type=ObjectType.task, title="Task", status="active",
                     created_at="2026-01-01", updated_at="2026-01-02")
        repo.write_object(obj)

        view = TasksView()
        view.set_file_repo(repo)
        view.set_objects([obj])
        view._on_task_context_action("ctx3", "delete")

        reread = self._reread(base, "ctx3")
        assert reread is not None
        assert reread.deleted_at is not None, "delete should soft-delete on disk, not just vanish from memory"

    def test_kanban_status_change_persists(self, monkeypatch, tmp_path: Path) -> None:
        from src.features.tasks.kanban_view import KanbanBoard

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        repo = FileRepository(base_path=base)
        obj = Object(id="kctx1", type=ObjectType.task, title="Card", status="active",
                     created_at="2026-01-01", updated_at="2026-01-02")
        repo.write_object(obj)

        board = KanbanBoard()
        board.set_objects([obj])
        board._on_card_action("kctx1", "status:done")

        reread = self._reread(base, "kctx1")
        assert reread is not None
        assert reread.status == "done"

    def test_kanban_duplicate_and_delete_persist(self, monkeypatch, tmp_path: Path) -> None:
        from src.features.tasks.kanban_view import KanbanBoard

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        repo = FileRepository(base_path=base)
        obj = Object(id="kctx2", type=ObjectType.task, title="Card", status="active",
                     created_at="2026-01-01", updated_at="2026-01-02")
        repo.write_object(obj)

        board = KanbanBoard()
        board.set_objects([obj])
        board._on_card_action("kctx2", "duplicate")
        reread_repo = FileRepository(base_path=base)
        dup_ids = [oid for oid in reread_repo.list_object_ids() if oid != "kctx2"]
        assert len(dup_ids) == 1

        board._on_card_action("kctx2", "delete")
        reread = self._reread(base, "kctx2")
        assert reread is not None
        assert reread.deleted_at is not None


class TestCalendarMonthAndGridClicks:
    """2026-07-19: MonthGrid had no click handling of any kind (no click-to-
    open a day, no click-to-open a chip, no click-to-create in the week/day
    time grid) despite `calendar.md` claiming some of this existed. These
    cover the new `_DayCell`/`_ChipLabel`/`_HourCell` click wiring end to
    end through the real `CalendarView`, not just the helper classes in
    isolation."""

    def _patch_default_repo(self, monkeypatch, tmp_path: Path) -> Path:
        import src.core.filerepo.repository as fr_mod
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(fr_mod, "_default_command_center", lambda: base)
        return base

    def test_month_day_click_zooms_to_day_view(self) -> None:
        from datetime import date as _date
        from src.features.calendar import CalendarView

        _make_app()
        view = CalendarView()
        view._switch_to_view("month")
        assert view._stack.currentIndex() == 0

        target = _date(2026, 7, 22)
        view._on_month_day_clicked(target)

        assert view._stack.currentIndex() == view._view_names.index("day")
        assert view._day_grid._current_date == target

    def test_month_chip_click_opens_inspector(self) -> None:
        from src.features.calendar import CalendarView

        _make_app()
        view = CalendarView()
        received: list[str] = []
        view.open_object_requested.connect(received.append)

        view._month_grid.object_clicked.emit("some-obj-id")
        assert received == ["some-obj-id"]

    def test_week_grid_cell_click_creates_and_persists_event(self, monkeypatch, tmp_path: Path) -> None:
        from datetime import datetime as _datetime
        from src.features.calendar import CalendarView
        from src.core.filerepo.repository import FileRepository

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        view = CalendarView()
        opened: list[str] = []
        view.open_object_requested.connect(opened.append)

        slot = _datetime(2026, 7, 22, 14, 0)
        view._week_grid.cell_clicked.emit(slot)

        assert len(opened) == 1
        new_id = opened[0]
        reread = FileRepository(base_path=base).read_object(new_id)
        assert reread is not None
        assert reread.type.value == "event"
        assert reread.start_at == slot.isoformat()
        assert reread.details.get("end_at") == "2026-07-22T15:00:00"
        assert reread.due_at == "2026-07-22"

    def test_day_grid_cell_click_creates_and_persists_event(self, monkeypatch, tmp_path: Path) -> None:
        from datetime import datetime as _datetime
        from src.features.calendar import CalendarView
        from src.core.filerepo.repository import FileRepository

        _make_app()
        base = self._patch_default_repo(monkeypatch, tmp_path)
        view = CalendarView()
        opened: list[str] = []
        view.open_object_requested.connect(opened.append)

        slot = _datetime(2026, 7, 22, 9, 0)
        view._day_grid.cell_clicked.emit(slot)

        assert len(opened) == 1
        reread = FileRepository(base_path=base).read_object(opened[0])
        assert reread is not None
        assert reread.start_at == slot.isoformat()

    def test_now_line_hidden_when_displayed_range_excludes_today(self) -> None:
        """The current-time line should only show when today is actually in
        the visible week/day -- not leak onto a page you've navigated away
        from."""
        from datetime import date as _date
        from src.features.calendar.widgets import WeekGrid, DayGrid

        _make_app()
        week = WeekGrid()
        week.navigate_to_date(_date(2020, 1, 6))  # a Monday, far from today
        assert week._now_line.isHidden()

        day = DayGrid()
        day.navigate_to_date(_date(2020, 1, 6))
        assert day._now_line.isHidden()

    def test_now_line_visible_for_today(self) -> None:
        from datetime import date as _date
        from src.features.calendar.widgets import WeekGrid, DayGrid

        _make_app()
        week = WeekGrid()
        week.navigate_to_date(_date.today())
        assert not week._now_line.isHidden()

        day = DayGrid()
        day.navigate_to_date(_date.today())
        assert not day._now_line.isHidden()
