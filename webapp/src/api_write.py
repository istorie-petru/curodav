"""The write side shared by the REST API and the MCP server: block-level edits to a note, never a whole-note rewrite.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

An edit names the revision it read and a list of operations on block ids. New content arrives as Markdown and is
turned into ordinary blocks by `notebook_markdown`, which escapes any HTML. Only ordinary blocks can be replaced or
deleted; a callout, quote, timeline, figure or any other block keeps its place. Every edit keeps the note as it was in
`note_versions` first, and all operations of one edit apply together or not at all.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from typing import Any

from . import db, note_versions
from .notebook_markdown import markdown_to_blocks

PLAIN_TYPES = frozenset({"paragraph", "header", "list", "code", "delimiter", "table"})
OPS = ("append", "insert_after", "insert_before", "replace", "delete")
MAX_OPS = 50
MAX_MARKDOWN = 100_000

_NOTE_ID = re.compile(r'data-note-id="md-([^"]+)"')


class EditError(ValueError):
    """An edit that cannot be applied; `code` is conflict, not_found or invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _new_id() -> str:
    return secrets.token_urlsafe(8)[:10]


def _blocks_from(markdown: Any) -> list[dict[str, Any]]:
    if not isinstance(markdown, str) or not markdown.strip():
        raise EditError("invalid", "markdown must be non-empty text")
    if len(markdown) > MAX_MARKDOWN:
        raise EditError("invalid", "markdown is too long")
    prefix = _new_id()
    blocks = markdown_to_blocks(markdown)
    for block in blocks:
        block["id"] = _new_id()
        if block.get("type") == "paragraph":
            block["data"]["text"] = _NOTE_ID.sub(lambda m: f'data-note-id="{prefix}-{m.group(1)}"', block["data"].get("text", ""))
    return blocks


def _index(blocks: list[dict[str, Any]], block_id: Any) -> int:
    for i, block in enumerate(blocks):
        if block.get("id") == block_id:
            return i
    raise EditError("not_found", f"No block with id {block_id}")


def apply_ops(blocks: list[dict[str, Any]], ops: Any) -> list[dict[str, Any]]:
    """The blocks after every operation, applied in order to a copy. Raises EditError on the first bad one."""
    if not isinstance(ops, list) or not ops:
        raise EditError("invalid", "ops must be a non-empty list")
    if len(ops) > MAX_OPS:
        raise EditError("invalid", f"at most {MAX_OPS} operations per edit")
    out = [dict(b) for b in blocks]
    for n, op in enumerate(ops, 1):
        kind = op.get("op") if isinstance(op, dict) else None
        if kind not in OPS:
            raise EditError("invalid", f"operation {n}: op must be one of {', '.join(OPS)}")
        if kind == "append":
            out += _blocks_from(op.get("markdown"))
            continue
        at = _index(out, op.get("block_id"))
        if kind in ("replace", "delete") and out[at].get("type") not in PLAIN_TYPES:
            raise EditError("invalid", f"operation {n}: a {out[at].get('type')} block cannot be replaced or deleted here")
        if kind == "insert_after":
            out[at + 1:at + 1] = _blocks_from(op.get("markdown"))
        elif kind == "insert_before":
            out[at:at] = _blocks_from(op.get("markdown"))
        elif kind == "replace":
            out[at:at + 1] = _blocks_from(op.get("markdown"))
        else:
            del out[at]
    return out


def edit_note(conn: sqlite3.Connection, uid: str, revision: str, ops: Any, *, source: str, token_uid: str = "",
              summary: str = "") -> dict[str, Any]:
    """Applies `ops` to the note when `revision` is still its current one; returns the new revision and the version kept."""
    doc = db.get_notebook_document(conn, uid)
    if doc is None or doc.get("is_template"):
        raise EditError("not_found", f"No note with uid {uid}")
    if (revision or "") != (doc.get("updated_at") or ""):
        raise EditError("conflict", "The note changed since it was read; read it again.")
    content = db.get_notebook_document_content(conn, uid) or {"blocks": []}
    new_blocks = apply_ops(content.get("blocks") or [], ops)
    version = note_versions.save(conn, uid, source=source, token_uid=token_uid, summary=summary)
    db.set_notebook_document_content(conn, uid, {**content, "blocks": new_blocks})
    updated = db.get_notebook_document(conn, uid)
    return {"uid": uid, "revision": updated.get("updated_at") or "", "version": version, "blocks": len(new_blocks)}


def restore_version(conn: sqlite3.Connection, version_uid: str, *, source: str, token_uid: str = "") -> dict[str, Any]:
    """Puts a kept version back, keeping the current content as a version of its own first."""
    v = note_versions.get_version(conn, version_uid)
    if v is None:
        raise EditError("not_found", f"No version {version_uid}")
    try:
        content = json.loads(v["content_json"])
    except (json.JSONDecodeError, TypeError):
        raise EditError("invalid", "That version cannot be read") from None
    kept = note_versions.save(conn, v["note_uid"], source=source, token_uid=token_uid, summary="Before restoring a version")
    if kept is None:
        raise EditError("not_found", f"No note with uid {v['note_uid']}")
    db.set_notebook_document_content(conn, v["note_uid"], content)
    updated = db.get_notebook_document(conn, v["note_uid"])
    return {"uid": v["note_uid"], "revision": updated.get("updated_at") or "", "version": kept}


# ---- One note's title, tag and properties, and new notes ----

def _note_for_edit(conn: sqlite3.Connection, uid: str, revision: str) -> dict[str, Any]:
    doc = db.get_notebook_document(conn, uid)
    if doc is None or doc.get("is_template"):
        raise EditError("not_found", f"No note with uid {uid}")
    if (revision or "") != (doc.get("updated_at") or ""):
        raise EditError("conflict", "The note changed since it was read; read it again.")
    return doc


def _tag_labels(conn: sqlite3.Connection, tag: str) -> list[str]:
    from . import tags

    if not tag:
        return []
    if tags.get_tag(conn, tag) is None:
        raise EditError("invalid", f"No tag named {tag}; tags are made in Settings, not here")
    return tags.labels_of(conn, [tag])


def _save_note(conn: sqlite3.Connection, doc: dict[str, Any], *, source: str, token_uid: str, summary: str,
               tag: str | None = None) -> dict[str, Any]:
    from . import clock, tags

    version = note_versions.save(conn, doc["uid"], source=source, token_uid=token_uid, summary=summary)
    doc["updated_at"] = clock.now().isoformat()
    db.upsert_notebook_document(conn, doc)
    if tag is not None:
        tags.record(conn, "notebook", doc["uid"], [tag] if tag else [])
    return {"uid": doc["uid"], "revision": doc["updated_at"], "version": version}


def create_note(conn: sqlite3.Connection, *, title: str, note_type: str = "", tag: str = "", markdown: str = "",
                template_uid: str = "", source: str, token_uid: str = "") -> dict[str, Any]:
    """A new note: blank, from Markdown, or from a template's body and type."""
    import uuid

    from . import clock, tags

    template = db.get_notebook_document(conn, template_uid) if template_uid else None
    if template_uid and (template is None or not template.get("is_template")):
        raise EditError("not_found", f"No template with uid {template_uid}")
    if markdown and template:
        raise EditError("invalid", "give markdown or a template, not both")
    content = template["content_json"] if template else json.dumps({"blocks": _blocks_from(markdown) if markdown else []})
    labels = _tag_labels(conn, tag)
    uid, now = str(uuid.uuid4()), clock.now().isoformat()
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": (title or "").strip() or "Untitled", "content_json": content, "document_type": "full",
        "note_type": (note_type or "").strip() or (template["note_type"] if template else ""), "created_at": now, "updated_at": now,
        "tags": labels})
    if tag:
        tags.record(conn, "notebook", uid, [tag])
    return {"uid": uid, "revision": now}


def rename_note(conn: sqlite3.Connection, uid: str, revision: str, title: str, *, source: str, token_uid: str = "") -> dict[str, Any]:
    doc = _note_for_edit(conn, uid, revision)
    if not (title or "").strip():
        raise EditError("invalid", "a note needs a title")
    old = doc["title"]
    doc["title"] = title.strip()
    return _save_note(conn, doc, source=source, token_uid=token_uid, summary=f"Renamed from {old}")


def set_note_tag(conn: sqlite3.Connection, uid: str, revision: str, tag: str, *, source: str, token_uid: str = "") -> dict[str, Any]:
    """The note's one tag; an empty tag takes it off."""
    doc = _note_for_edit(conn, uid, revision)
    doc["tags"] = _tag_labels(conn, (tag or "").strip())
    return _save_note(conn, doc, source=source, token_uid=token_uid, summary=f"Tag set to {tag or 'none'}", tag=(tag or "").strip())


def set_note_properties(conn: sqlite3.Connection, uid: str, revision: str, properties: dict[str, Any], *, note_type: str | None = None,
                        source: str, token_uid: str = "") -> dict[str, Any]:
    """Sets front matter fields by name (an empty value removes one) with the same checks as the properties window; the
    other fields stay."""
    from . import notebook_fields

    doc = _note_for_edit(conn, uid, revision)
    if not isinstance(properties, dict):
        raise EditError("invalid", "properties must be an object of name to value")
    wanted = {str(k).strip(): v for k, v in properties.items() if str(k).strip()}
    lowered = {k.lower() for k in wanted}
    free = [{"key": p["key"], "value": p["value"]} for p in doc.get("properties") or [] if p["key"].lower() not in lowered]
    for key, value in wanted.items():
        text = json.dumps(value) if isinstance(value, list) else ("" if value is None else str(value))
        if text:
            free.append({"key": key, "value": text})
    fields = db.list_notebook_field_config(conn)
    typed = {notebook_fields.input_name(f): next((r["value"] for r in free if r["key"].lower() == f["key"].lower()), "")
             for f in notebook_fields.schema_fields(fields)}
    schema_keys = {f["key"].lower() for f in notebook_fields.schema_fields(fields)}
    items, errors = notebook_fields.build_properties(fields, typed, [r for r in free if r["key"].lower() not in schema_keys])
    if errors:
        raise EditError("invalid", "; ".join(f"{name.removeprefix('field__')}: {msg}" for name, msg in errors.items()))
    doc["properties"] = items
    if note_type is not None:
        doc["note_type"] = note_type.strip()
    return _save_note(conn, doc, source=source, token_uid=token_uid, summary="Properties changed")
