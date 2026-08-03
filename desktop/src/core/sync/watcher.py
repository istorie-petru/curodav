"""Watchdog file watcher — keeps SQLite cache in sync (REWORK_PLAN §6.2).

Uses the `watchdog` library to detect file creates/modifies/deletes in the
file tree and incrementally update the SQLite query cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class ObjectFileHandler(FileSystemEventHandler):
    """Emits callbacks when object files change."""

    def __init__(
        self,
        cb_modified: Callable[[str], None] | None = None,
        cb_created: Callable[[str], None] | None = None,
        cb_deleted: Callable[[str], None] | None = None,
    ) -> None:
        self.cb_modified = cb_modified
        self.cb_created = cb_created
        self.cb_deleted = cb_deleted

    def on_modified(self, event) -> None:
        if self.cb_modified and getattr(event, "src_path", "").endswith("object.json"):
            object_id = self._object_id_from_path(event.src_path)
            if object_id:
                self.cb_modified(object_id)

    def on_created(self, event) -> None:
        if self.cb_created and getattr(event, "src_path", "").endswith("object.json"):
            object_id = self._object_id_from_path(event.src_path)
            if object_id:
                self.cb_created(object_id)

    def on_deleted(self, event) -> None:
        if self.cb_deleted and getattr(event, "src_path", "").endswith("object.json"):
            object_id = self._object_id_from_path(event.src_path)
            if object_id:
                self.cb_deleted(object_id)

    @staticmethod
    def _object_id_from_path(path: str) -> str | None:
        parts = Path(path).parts
        try:
            idx = parts.index("objects")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        except ValueError:
            return None
        return None


class FileWatcher:
    """Watches the objects directory for changes."""

    def __init__(self, base_path: Path | None = None) -> None:
        self._base_path = base_path or Path.home() / "CommandCenter"
        self._observer: Observer | None = None

    def start(
        self,
        on_modified: Callable[[str], None] | None = None,
        on_created: Callable[[str], None] | None = None,
        on_deleted: Callable[[str], None] | None = None,
    ) -> None:
        objects_dir = self._base_path / "objects"
        if not objects_dir.exists():
            objects_dir.mkdir(parents=True, exist_ok=True)

        handler = ObjectFileHandler(
            cb_modified=on_modified,
            cb_created=on_created,
            cb_deleted=on_deleted,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(objects_dir), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
