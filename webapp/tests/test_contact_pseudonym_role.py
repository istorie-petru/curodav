"""Pseudonym and Role contact fields: stored, synced as vCard NICKNAME and ROLE, and the per-list synced name."""

from datetime import datetime, timezone

import pytest
import vobject

from src import db
from src.vcard_rows import contact_row_to_vcard, vcard_to_contact_row


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _row(**overrides):
    now = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()
    row = {"uid": "c1", "full_name": "Ada Lovelace", "tags": [], "created_at": now, "updated_at": now}
    row.update(overrides)
    return row


def test_pseudonym_and_role_are_stored(conn):
    db.upsert_contact(conn, _row(pseudonym="Countess", role="Analyst", org="Analytical Engines"))
    saved = db.get_contact(conn, "c1")
    assert saved["pseudonym"] == "Countess" and saved["role"] == "Analyst"


def test_vcard_round_trips_pseudonym_and_role():
    card = contact_row_to_vcard(_row(pseudonym="Countess", role="Analyst", title="Lady"))
    parsed = vcard_to_contact_row(vobject.readOne(card))
    assert (parsed["pseudonym"], parsed["role"], parsed["title"]) == ("Countess", "Analyst", "Lady")
    assert "NICKNAME:Countess" in card and "ROLE:Analyst" in card


@pytest.mark.parametrize("name_field, pseudonym, expected_fn", [
    ("full_name", "Countess", "Ada Lovelace"),
    ("pseudonym", "Countess", "Countess"),
    ("pseudonym", None, "Ada Lovelace"),
])
def test_chosen_field_feeds_the_card_name(name_field, pseudonym, expected_fn):
    card = vobject.readOne(contact_row_to_vcard(_row(pseudonym=pseudonym), name_field))
    assert card.fn.value == expected_fn


def test_published_list_remembers_the_name_field(conn):
    db.upsert_published_list(conn, {"id": "l1", "name": "People", "entity_type": "contact", "label_filter": {},
                                    "radicale_collection_path": "published-people", "contact_name_field": "pseudonym"})
    assert db.get_published_list(conn, "l1")["contact_name_field"] == "pseudonym"
    db.upsert_published_list(conn, {"id": "l2", "name": "Other", "entity_type": "contact", "label_filter": {},
                                    "radicale_collection_path": "published-other"})
    assert db.get_published_list(conn, "l2")["contact_name_field"] == "full_name"
