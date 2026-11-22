"""A space travels with an item in calendar and contact sync (X-CURODAV-SPACE) and sticks when it has no tag."""

import pytest
import vobject

from src import db, ical_rows, tags, vcard_rows


@pytest.fixture
def conn(tmp_path):
    with db.connect(tmp_path / "t.sqlite") as c:
        db.ensure_group(c, "Uni")
        tags.add_tag(c, "Exam", "Uni")
        c.commit()
        yield c


def test_a_task_carries_its_space_through_ical(conn):
    row = {"uid": "t1", "title": "Read", "description": "", "status": "active", "created_at": "2026-11-22T00:00:00+00:00", "tags": ["Exam"], "space": "Uni"}
    out = ical_rows.task_row_to_ical(row)
    text = out.decode() if isinstance(out, bytes) else str(out)
    assert "CATEGORIES:Exam" in text and "X-CURODAV-SPACE:Uni" in text


def test_a_space_without_tags_is_kept_on_import_and_a_made_up_space_is_ignored(conn):
    db.upsert_task(conn, {"uid": "t1", "title": "Read", "description": "", "status": "active", "created_at": "2026-11-22T00:00:00+00:00", "tags": [], "space": "Uni"})
    db.upsert_task(conn, {"uid": "t2", "title": "Other", "description": "", "status": "active", "created_at": "2026-11-22T00:00:00+00:00", "tags": [], "space": "Made up"})
    assert tags.item_space(conn, "task", "t1") == "Uni" and tags.item_space(conn, "task", "t2") is None
    assert db.get_task(conn, "t1")["space"] == "Uni"


def test_a_contact_carries_its_space_through_vcard():
    text = vcard_rows.contact_row_to_vcard({"uid": "c1", "full_name": "Ana", "tags": ["Exam"], "space": "Uni"})
    assert "X-CURODAV-SPACE:Uni" in text
    assert vcard_rows.vcard_to_contact_row(vobject.readOne(text))["space"] == "Uni"
