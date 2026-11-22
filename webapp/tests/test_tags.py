"""Spaces and tags: every tag sits in one space, every item keeps its own space, and the shelf migration."""

import pytest

from src import db, migrations_spaces, tags


@pytest.fixture
def conn(tmp_path):
    with db.connect(tmp_path / "t.sqlite") as c:
        for space in ("Personal", "University"):
            db.ensure_group(c, space)
        tags.add_tag(c, "Gym", "Personal", "green")
        tags.add_tag(c, "Home", "Personal")
        tags.add_tag(c, "Exam", "University", "red")
        yield c


def test_tags_give_an_item_its_space_and_the_space_stays_when_the_tag_goes(conn):
    tags.set_object_tags(conn, "task", "t1", ["Gym"])
    assert tags.item_space(conn, "task", "t1") == "Personal"
    db.delete_label_config(conn, "Gym")
    assert tags.tags_for_object(conn, "task", "t1") == []
    assert tags.item_space(conn, "task", "t1") == "Personal"
    item = {"uid": "t1", "tags": []}
    tags.attach_items(conn, "task", [item])
    assert item["tag_items"][0]["name"] == "Personal" and item["tag_items"][0]["is_space"]


def test_tags_of_two_spaces_are_refused(conn):
    with pytest.raises(tags.SpaceConflict):
        tags.set_object_tags(conn, "task", "t1", ["Gym", "Exam"])
    assert tags.tags_for_object(conn, "task", "t1") == []


def test_a_name_that_is_not_a_tag_is_refused_but_record_skips_it(conn):
    with pytest.raises(ValueError):
        tags.set_object_tags(conn, "task", "t1", ["Nope"])
    tags.record(conn, "task", "t1", ["Nope", "Home"])
    assert tags.tags_for_object(conn, "task", "t1") == ["Home"]


def test_moving_a_tag_moves_its_items(conn):
    tags.set_object_tags(conn, "note", "n1", ["Home"])
    tags.move_tag(conn, "Home", "University")
    assert tags.item_space(conn, "note", "n1") == "University"


def test_shelf_migration_moves_tags_up_and_keeps_item_spaces(tmp_path):
    with db.connect(tmp_path / "m.sqlite") as c:
        db.ensure_group(c, "University")
        c.executescript("""
            CREATE TABLE label_tags (name TEXT PRIMARY KEY COLLATE NOCASE, label_name TEXT NOT NULL, color TEXT NOT NULL DEFAULT 'gray', icon TEXT NOT NULL DEFAULT '', created_at TEXT);
            CREATE TABLE object_tags (object_type TEXT NOT NULL, object_id TEXT NOT NULL, tag_name TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY (object_type, object_id, tag_name));
            INSERT INTO label_config (name, label_group, color) VALUES ('1st Semester', 'University', 'blue'), ('Loose', '', 'red');
            INSERT INTO label_tags (name, label_name, color) VALUES ('Biology', '1st Semester', 'mint');
            INSERT INTO object_labels VALUES ('task', 't1', '1st Semester'), ('task', 't1', 'Loose'), ('event', 'e1', '1st Semester');
            INSERT INTO object_tags VALUES ('task', 't1', 'Biology'), ('note', 'n1', 'Biology');
        """)
        plan = migrations_spaces.plan(c)
        assert plan["removed_shelves"] == ["1st Semester"] and plan["kept_shelves"][0]["name"] == "Loose"
        migrations_spaces.apply(c)
        assert tags.get_tag(c, "Biology")["space"] == "University"
        assert tags.get_tag(c, "1st Semester") is None
        assert tags.tags_for_object(c, "task", "t1") == ["Biology", "Loose"]
        assert tags.tags_for_object(c, "note", "n1") == ["Biology"]
        assert tags.item_space(c, "event", "e1") == "University"
        assert tags.get_tag(c, "Loose")["space"] == "Other"
        migrations_spaces.apply(c)  # twice is harmless
