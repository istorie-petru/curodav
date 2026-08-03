"""Edge case tests — empty data, corruption, extreme inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

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


class TestEmptyData:
    def test_empty_repo(self, tmp_path: Path) -> None:
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True, exist_ok=True)
        repo = FileRepository(base_path=base)
        objects = repo.iter_objects()
        assert objects == []

    def test_empty_db(self, tmp_path: Path) -> None:
        db = Database(db_path=tmp_path / "empty.sqlite")
        db.open()
        tags = db.list_tags()
        assert tags == []

    def test_empty_dashboard(self):
        _make_app()
        from src.features.dashboard import DashboardView
        view = DashboardView()
        view.set_objects([])
        assert view is not None

    def test_empty_tasks(self):
        """The Smart view (and its `_empty_label`) was removed 2026-07-19
        -- Table view has no empty-state label of its own, it just shows
        zero rows. This now just confirms an empty object list doesn't
        crash any of the three remaining views."""
        _make_app()
        from src.features.tasks import TasksView
        view = TasksView()
        view.show()
        view.set_objects([])
        assert view._table_view._model.rowCount() == 0

    def test_empty_calendar(self):
        _make_app()
        from src.features.calendar import CalendarView
        view = CalendarView()
        view.set_objects([])
        assert view is not None

    def test_empty_search(self):
        _make_app()
        from src.features.search import SearchView
        view = SearchView()
        view.show()
        assert view._empty_state.isVisible()


class TestCorruptedData:
    def test_corrupted_json(self, tmp_path: Path) -> None:
        base = tmp_path / "CommandCenter"
        obj_dir = base / "objects" / "corrupt-1"
        obj_dir.mkdir(parents=True, exist_ok=True)
        (obj_dir / "object.json").write_text("this is not json", encoding="utf-8")
        repo = FileRepository(base_path=base)
        # Should not crash
        obj = repo.read_object("corrupt-1")
        assert obj is None

    def test_db_rebuild_corrupted(self, tmp_path: Path) -> None:
        base = tmp_path / "CommandCenter"
        obj_dir = base / "objects" / "bad-obj"
        obj_dir.mkdir(parents=True, exist_ok=True)
        (obj_dir / "object.json").write_text("{invalid", encoding="utf-8")

        db = Database(db_path=tmp_path / "corrupt.sqlite")
        db.open()
        count = db.rebuild_from_path(base)
        assert count == 0


class TestMissingData:
    def test_task_no_due_date(self):
        _make_app()
        from src.features.calendar import CalendarView
        view = CalendarView()
        obj = Object(id="no-due", type=ObjectType.task, title="No due",
                     status=ObjectStatus.active,
                     created_at="2026-01-01", updated_at="2026-01-02")
        view.set_objects([obj])
        assert view is not None

    def test_event_no_start(self):
        _make_app()
        from src.features.calendar import CalendarView
        view = CalendarView()
        obj = Object(id="no-start", type=ObjectType.event, title="No start",
                     status=ObjectStatus.active,
                     created_at="2026-01-01", updated_at="2026-01-02")
        view.set_objects([obj])
        assert view is not None


class TestExtremeInput:
    def test_long_title(self, tmp_path: Path) -> None:
        repo = FileRepository(base_path=tmp_path / "CommandCenter")
        repo.base_path.mkdir(parents=True, exist_ok=True)
        long_title = "A" * 500
        obj = create_task_from_quickadd(long_title, repo)
        assert obj.title == long_title
        reloaded = repo.read_object(obj.id)
        assert reloaded is not None
        assert len(reloaded.title) == 500

    def test_many_tags(self, tmp_path: Path) -> None:
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True, exist_ok=True)
        repo = FileRepository(base_path=base)
        tags = [f"tag-{i}" for i in range(50)]
        token_str = " ".join(f">{t}" for t in tags)
        obj = create_task_from_quickadd(f"Many tags {token_str}", repo)
        assert len(obj.tags) == 50

    def test_rapid_quickadd(self, tmp_path: Path) -> None:
        base = tmp_path / "CommandCenter"
        (base / "objects").mkdir(parents=True, exist_ok=True)
        repo = FileRepository(base_path=base)
        created = []
        for i in range(10):
            obj = create_task_from_quickadd(f"Rapid task {i}", repo)
            created.append(obj)
        ids = repo.list_object_ids()
        # At least the 10 we created
        assert len([oid for oid in ids if oid.startswith("rapid") or True]) >= 10
