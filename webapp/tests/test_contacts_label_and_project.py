"""A contact carries one label and one project; groups are by label."""

import asyncio
from datetime import datetime, timezone

import pytest

from src import db
from src.routers import contacts as contacts_router

_EMPTY = dict(
    pseudonym="", title="", role="", org="", phone_type=[], phone_value=[], email_type=[], email_value=[],
    website_type=[], website_url=[], address_type=[], address_po_box=[], address_extended=[], address_street=[],
    address_city=[], address_region=[], address_postal_code=[], address_country=[], social_type=[], social_value=[],
    birthday="", notes="", photo=None, remove_photo="",
)


@pytest.fixture
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        db.upsert_label_config(c, {"name": "Trip", "is_project": 1})
        yield c


def _save(conn, uid, **kw):
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_contact(conn, {"uid": uid, "full_name": "Ada", "tags": [], "created_at": now, "updated_at": now})
    asyncio.run(contacts_router.update_contact(uid=uid, full_name="Ada", tags="", conn=conn, **_EMPTY, **kw))
    return db.get_contact(conn, uid)["tags"]


def test_label_and_project_are_both_kept(conn):
    tags = _save(conn, "c1", tags_labels=["Family"], tags_labels_new="", project="Trip", project_field="1")
    assert sorted(tags) == ["Family", "Trip"]


def test_project_dropdown_replaces_a_project_typed_as_the_label(conn):
    tags = _save(conn, "c1", tags_labels=["Trip"], tags_labels_new="", project="", project_field="1")
    assert tags == []


def test_grouping_ignores_the_project():
    groups = contacts_router._group_contacts_by_label([{"uid": "c1", "tags": ["Trip", "Family"]}], {"Trip"})
    assert [g["name"] for g in groups] == ["Family"]
