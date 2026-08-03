"""Data layer tests — FileRepository, Database, HLC merge."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.core.filerepo.repository import FileRepository
from src.core.models import Object, ObjectStatus, ObjectType


class TestFileRepository:
    def test_create_object(self, file_repo: FileRepository) -> None:
        obj = Object(
            id="new-1",
            type=ObjectType.task,
            title="New task",
            status=ObjectStatus.active,
            priority=2,
            tags=["test"],
            created_at="2026-06-01T00:00:00",
            updated_at="2026-06-01T00:00:00",
        )
        file_repo.write_object(obj)
        path = file_repo.base_path / "objects" / "new-1" / "object.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["title"]["v"] == "New task"
        assert data["type"] == "task"
        assert data["priority"]["v"] == 2

    def test_update_object(self, file_repo: FileRepository) -> None:
        obj = file_repo.read_object("test-1")
        assert obj is not None
        obj.title = "Updated title"
        obj.priority = 3
        file_repo.write_object(obj)
        reloaded = file_repo.read_object("test-1")
        assert reloaded is not None
        assert reloaded.title == "Updated title"
        assert reloaded.priority == 3

    def test_soft_delete(self, file_repo: FileRepository) -> None:
        file_repo.delete_object("test-1")
        obj = file_repo.read_object("test-1")
        assert obj is not None
        assert obj.deleted_at is not None

    def test_read_nonexistent(self, file_repo: FileRepository) -> None:
        obj = file_repo.read_object("does-not-exist")
        assert obj is None

    def test_list_object_ids(self, file_repo: FileRepository) -> None:
        ids = file_repo.list_object_ids()
        assert "test-1" in ids
        assert "test-2" in ids
        assert len(ids) >= 5

    def test_iter_objects(self, file_repo: FileRepository) -> None:
        objects = file_repo.iter_objects()
        titles = {o.title for o in objects}
        assert "Review submission" in titles
        assert "Architecture notes" in titles

    def test_tags(self, file_repo: FileRepository) -> None:
        obj = file_repo.read_object("test-2")
        assert obj is not None
        assert "work" in obj.tags
        assert "presentation" in obj.tags

    def test_milestones(self, file_repo: FileRepository) -> None:
        file_repo.write_milestones("test-1", [{"text": "Phase 1", "done": False}])
        ms = file_repo.read_milestones("test-1")
        assert ms is not None
        assert ms[0]["text"] == "Phase 1"

    def test_body_rw(self, file_repo: FileRepository) -> None:
        file_repo.write_body("test-1", "# Hello\nWorld")
        body = file_repo.read_body("test-1")
        assert body == "# Hello\nWorld"

    def test_checklist(self, file_repo: FileRepository) -> None:
        file_repo.write_checklist("test-1", [{"text": "Item 1", "done": False}])
        cl = file_repo.read_checklist("test-1")
        assert cl is not None
        assert cl[0]["text"] == "Item 1"

    def test_hlc_merge(self, file_repo: FileRepository, tmp_path: Path) -> None:
        obj_dir = file_repo.base_path / "objects" / "test-1"
        obj_file = obj_dir / "object.json"

        main_data = json.loads(obj_file.read_text(encoding="utf-8"))
        main_data["title"] = {"v": "Main title", "h": "2026-06-01T00:00:00Z-desktop"}
        obj_file.write_text(json.dumps(main_data, indent=2), encoding="utf-8")

        conflict = main_data.copy()
        conflict["title"] = {"v": "Conflict title", "h": "2026-06-02T00:00:00Z-desktop"}
        conflict_path = obj_dir / "object.sync-conflict-123.json"
        conflict_path.write_text(json.dumps(conflict, indent=2), encoding="utf-8")

        file_repo.resolve_sync_conflict("test-1")
        resolved = json.loads(obj_file.read_text(encoding="utf-8"))
        assert resolved["title"]["v"] == "Conflict title"


class TestDatabase:
    def test_rebuild(self, db, temp_data_dir: Path) -> None:
        count = db.rebuild_from_path(temp_data_dir)
        assert count >= 5

    def test_search_by_title(self, db) -> None:
        rows = db.search_objects_by_title("Review", limit=5)
        titles = [r["title"] for r in rows]
        assert "Review submission" in titles

    def test_list_tags(self, db) -> None:
        tags = db.list_tags()
        tag_names = {t["name"] for t in tags}
        assert "work" in tag_names
        assert "presentation" in tag_names

    def test_links(self, db) -> None:
        db.create_link("test-1", "test-2", "related")
        outgoing = db.get_outgoing_links("test-1")
        assert len(outgoing) == 1
        assert outgoing[0]["to_id"] == "test-2"

        incoming = db.get_incoming_links("test-2")
        assert len(incoming) == 1
        assert incoming[0]["from_id"] == "test-1"

        db.delete_link(outgoing[0]["id"])
        assert len(db.get_outgoing_links("test-1")) == 0

    def test_tag_crud(self, db) -> None:
        db.add_tag("urgent", "#ff0000")
        tags = db.list_tags()
        matching = [t for t in tags if t["name"] == "urgent"]
        assert len(matching) == 1
        assert matching[0]["color"] == "#ff0000"
        tag_id = matching[0]["id"]

        db.rename_tag(tag_id, "critical")
        tags = db.list_tags()
        assert any(t["name"] == "critical" for t in tags)
        assert not any(t["name"] == "urgent" for t in tags)

        db.update_tag_color(tag_id, "#00ff00")
        tags = db.list_tags()
        matching = [t for t in tags if t["name"] == "critical"]
        assert matching[0]["color"] == "#00ff00"

        db.delete_tag(tag_id)
        tags = db.list_tags()
        assert not any(t["name"] == "critical" for t in tags)
