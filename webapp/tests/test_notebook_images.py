"""Figure pictures live in an image store by content hash; notes hold only their URL."""

from __future__ import annotations

import base64
import datetime as dt
import json

import pytest

from src import data_exchange, db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _note(conn, uid="d1", content=None):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    db.upsert_notebook_document(conn, {
        "uid": uid, "title": "Note", "content_json": json.dumps(content or {"blocks": []}),
        "document_type": "full", "note_type": "notes", "created_at": now, "updated_at": now,
    })


def _figure(src):
    return {"type": "image", "data": {"images": [{"src": src, "alt": "a"}], "caption": "c"}}


def test_saving_moves_embedded_pictures_into_the_store_and_dedupes(conn):
    _note(conn)
    content = {"blocks": [_figure(PNG_URL), _figure(PNG_URL)]}
    assert db.set_notebook_document_content(conn, "d1", content)
    saved = db.get_notebook_document_content(conn, "d1")
    urls = [b["data"]["images"][0]["src"] for b in saved["blocks"]]
    assert urls[0] == urls[1] and urls[0].startswith(db.IMAGE_URL_PREFIX)
    assert conn.execute("SELECT COUNT(*) FROM notebook_images").fetchone()[0] == 1
    assert db.get_notebook_image(conn, urls[0].rsplit("/", 1)[1])["data"] == PNG


def test_an_old_image_block_with_a_data_url_becomes_a_figure(conn):
    _note(conn)
    db.set_notebook_document_content(conn, "d1", {"blocks": [{"type": "image", "data": {"url": PNG_URL, "caption": "Old"}}]})
    data = db.get_notebook_document_content(conn, "d1")["blocks"][0]["data"]
    assert "url" not in data and data["images"][0]["src"].startswith(db.IMAGE_URL_PREFIX)


def test_opening_an_old_note_moves_its_pictures_without_touching_its_date(conn):
    raw = json.dumps({"blocks": [_figure(PNG_URL)]})
    _note(conn)
    conn.execute("UPDATE notebook_documents SET content_json = ?, updated_at = '2020-01-01T00:00:00+00:00' WHERE uid = 'd1'", (raw,))
    conn.commit()
    db.migrate_document_images(conn, "d1")
    row = conn.execute("SELECT content_json, updated_at FROM notebook_documents WHERE uid = 'd1'").fetchone()
    assert "data:image" not in row["content_json"] and row["updated_at"].startswith("2020-01-01")
    assert conn.execute("SELECT COUNT(*) FROM notebook_image_refs").fetchone()[0] == 1


def test_a_picture_no_note_uses_goes_after_a_day_but_not_sooner(conn):
    _note(conn)
    db.set_notebook_document_content(conn, "d1", {"blocks": [_figure(PNG_URL)]})
    image_id = conn.execute("SELECT id FROM notebook_images").fetchone()["id"]
    db.set_notebook_document_content(conn, "d1", {"blocks": []})
    assert db.get_notebook_image(conn, image_id) is not None  # uploaded moments ago, kept for a day
    conn.execute("UPDATE notebook_images SET created_at = '2020-01-01T00:00:00+00:00'")
    db.set_notebook_document_content(conn, "d1", {"blocks": []})
    assert db.get_notebook_image(conn, image_id) is None


def test_export_puts_the_pictures_back_inline(conn):
    _note(conn)
    db.set_notebook_document_content(conn, "d1", {"blocks": [_figure(PNG_URL)]})
    inlined = db.inline_content_images(conn, db.get_notebook_document_content(conn, "d1"))
    assert inlined["blocks"][0]["data"]["images"][0]["src"] == PNG_URL


def test_the_backup_carries_the_pictures(conn):
    _note(conn)
    db.set_notebook_document_content(conn, "d1", {"blocks": [_figure(PNG_URL)]})
    rows = data_exchange.notebook_image_rows(conn)
    assert len(rows) == 1 and base64.b64decode(rows[0]["data_b64"]) == PNG


def test_only_real_image_ids_are_looked_up(conn):
    assert db.get_notebook_image(conn, "../etc/passwd") is None
    assert db.get_notebook_image(conn, "0" * 64) is None
