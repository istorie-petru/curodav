"""Import/Export utilities (REWORK_PLAN Phase 3).

JSON dump/restore, markdown export, Obsidian vault import.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Object, ObjectType


def export_json(objects: list[Object], path: Path) -> None:
    """Export all objects as a JSON dump.

    Format: { "version": "1", "exported_at": "...", "objects": [...] }
    """
    data = {
        "version": "1",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "objects": [
            {
                "id": o.id,
                "type": o.type.value,
                "title": o.title,
                "description": o.description,
                "icon": o.icon,
                "status": o.status,
                "priority": o.priority,
                "progress": o.progress,
                "start_at": o.start_at,
                "due_at": o.due_at,
                "pinned": o.pinned,
                "parent_id": o.parent_id,
                "sort_key": o.sort_key,
                "created_at": o.created_at,
                "updated_at": o.updated_at,
                "deleted_at": o.deleted_at,
            }
            for o in objects
        ],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def import_json(path: Path) -> list[Object]:
    """Import objects from a JSON dump."""
    data = json.loads(path.read_text())
    objects_data = data.get("objects", [])
    result = []
    for od in objects_data:
        obj = Object(
            id=od.get("id", ""),
            type=ObjectType.from_db(od.get("type", "task")),
            title=od.get("title", ""),
            description=od.get("description", ""),
            icon=od.get("icon"),
            status=od.get("status", "active"),
            priority=od.get("priority"),
            progress=od.get("progress"),
            start_at=od.get("start_at"),
            due_at=od.get("due_at"),
            pinned=od.get("pinned", False),
            parent_id=od.get("parent_id"),
            sort_key=od.get("sort_key"),
            created_at=od.get("created_at", ""),
            updated_at=od.get("updated_at", ""),
            deleted_at=od.get("deleted_at"),
        )
        result.append(obj)
    return result


def export_markdown(obj: Object, path: Path, body: str = "") -> None:
    """Export a single object as a markdown file."""
    lines = [
        f"# {obj.title}",
        "",
        f"**Type:** {obj.type.value}  ",
        f"**Status:** {obj.status}  ",
    ]
    if obj.due_at:
        lines.append(f"**Due:** {obj.due_at}  ")
    if obj.priority:
        lines.append(f"**Priority:** P{obj.priority}  ")
    if obj.description:
        lines.append("")
        lines.append(obj.description)
    if body:
        lines.append("")
        lines.append(body)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def export_all_markdown(objects: list[Object], output_dir: Path) -> None:
    """Export all objects as individual markdown files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for obj in objects:
        safe_name = obj.title.replace("/", "_").replace("\\", "_") or obj.id
        path = output_dir / f"{safe_name}.md"
        export_markdown(obj, path)


def import_obsidian_vault(vault_path: Path) -> list[Object]:
    """Scan an Obsidian vault and create objects from markdown files.

    Each .md file becomes a Note-type object. Wikilinks are preserved
    in the description for later link resolution.
    """
    objects = []
    if not vault_path.exists():
        return objects

    md_files = list(vault_path.rglob("*.md"))
    for md_file in md_files:
        rel = md_file.relative_to(vault_path)
        title = rel.stem
        body = md_file.read_text(encoding="utf-8")

        obj = Object(
            id=str(abs(hash(str(rel))) % 10**15),
            type=ObjectType.note,
            title=title,
            description=f"Imported from Obsidian: {rel}",
            status="active",
            created_at=datetime.utcnow().isoformat() + "Z",
            updated_at=datetime.utcnow().isoformat() + "Z",
        )
        obj.details["body"] = body
        objects.append(obj)

    return objects
