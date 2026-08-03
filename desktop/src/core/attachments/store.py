"""Attachment blob store (REWORK_PLAN §3.1, Phase 3).

Content-addressed storage at `~/CommandCenter/attachments/{sha256}/`.
Each attachment has meta.json + data file.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _default_attachment_dir() -> Path:
    return Path.home() / "CommandCenter" / "attachments"


class AttachmentStore:
    """Content-addressed attachment storage.

    Files are stored by SHA-256 hash at:
      ~/CommandCenter/attachments/{sha256}/meta.json
      ~/CommandCenter/attachments/{sha256}/data
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self._base = base_path or _default_attachment_dir()

    def store(self, source_path: Path, filename: str, mime: str = "") -> dict:
        """Store a file by content hash. Returns metadata dict."""
        sha256 = self._hash_file(source_path)
        att_dir = self._base / sha256
        att_dir.mkdir(parents=True, exist_ok=True)

        data_target = att_dir / "data"
        if not data_target.exists():
            shutil.copy2(source_path, data_target)

        meta = {
            "sha256": sha256,
            "filename": filename,
            "mime": mime or self._guess_mime(filename),
            "size_bytes": source_path.stat().st_size,
        }
        self._write_meta(att_dir / "meta.json", meta)
        return meta

    def store_bytes(
        self, data: bytes, filename: str, mime: str = ""
    ) -> dict:
        """Store raw bytes by content hash."""
        sha256 = hashlib.sha256(data).hexdigest()
        att_dir = self._base / sha256
        att_dir.mkdir(parents=True, exist_ok=True)

        data_target = att_dir / "data"
        if not data_target.exists():
            data_target.write_bytes(data)

        meta = {
            "sha256": sha256,
            "filename": filename,
            "mime": mime or self._guess_mime(filename),
            "size_bytes": len(data),
        }
        self._write_meta(att_dir / "meta.json", meta)
        return meta

    def get_meta(self, sha256: str) -> dict | None:
        path = self._base / sha256 / "meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def get_data_path(self, sha256: str) -> Path | None:
        path = self._base / sha256 / "data"
        return path if path.exists() else None

    def get_all(self) -> list[dict]:
        if not self._base.exists():
            return []
        results = []
        for att_dir in self._base.iterdir():
            if att_dir.is_dir():
                meta = self.get_meta(att_dir.name)
                if meta:
                    results.append(meta)
        return results

    def delete(self, sha256: str) -> bool:
        path = self._base / sha256
        if path.exists():
            shutil.rmtree(path)
            return True
        return False

    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _write_meta(path: Path, meta: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2))

    @staticmethod
    def _guess_mime(filename: str) -> str:
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".json": "application/json",
            ".csv": "text/csv",
            ".zip": "application/zip",
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
        }
        return mime_map.get(ext, "application/octet-stream")
