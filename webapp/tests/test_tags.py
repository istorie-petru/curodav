"""App-wide tags: schema, per-item tags, and the dry-run/apply migration."""

import sqlite3

from src import migrations, tags


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE label_config (name TEXT PRIMARY KEY, color TEXT, icon TEXT, label_group TEXT, is_project INTEGER DEFAULT 0,
            has_deadline INTEGER DEFAULT 0, deadline_date TEXT, end_date TEXT, archived_at TEXT, description TEXT);
        CREATE TABLE object_labels (object_type TEXT, object_id TEXT, label_name TEXT, PRIMARY KEY (object_type, object_id, label_name));
    """)
    conn.executescript("""
        CREATE TABLE finance_tags (group_name TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, color TEXT NOT NULL DEFAULT 'gray', icon TEXT NOT NULL DEFAULT '');
        CREATE TABLE finance_transaction_tags (txn_uid TEXT NOT NULL, tag TEXT NOT NULL);
        CREATE TABLE finance_scheduled_tags (scheduled_uid TEXT NOT NULL, tag TEXT NOT NULL);
    """)
    tags.ensure_schema(conn)
    return conn


def test_set_object_tags_needs_existing_tags_and_rejects_habits():
    conn = _conn()
    conn.execute("INSERT INTO label_tags (name, label_name) VALUES ('Salt', 'Kitchen'), ('Pepper', 'Kitchen')")
    assert tags.set_object_tags(conn, "task", "t1", ["Salt", " Pepper ", "salt"]) == ["Pepper", "Salt"]
    for kind, name in (("task", "Nope"), ("habit", "Salt")):
        try:
            tags.set_object_tags(conn, kind, "x", [name])
        except ValueError:
            continue
        raise AssertionError(f"{kind}/{name} should be refused")


def test_plan_changes_nothing_and_apply_gives_every_label_a_default_tag():
    conn = _conn()
    conn.execute("INSERT INTO finance_tags (group_name, name, color, icon) VALUES ('', 'Rent', 'red', 'home')")
    conn.execute("INSERT INTO finance_transaction_tags VALUES ('tx1', 'Rent')")
    conn.execute("INSERT INTO label_config (name, label_group, is_project, deadline_date) VALUES ('Thesis', 'Office', 1, '2027-01-01')")
    conn.execute("INSERT INTO label_config (name, color) VALUES ('Work', 'blue'), ('Empty', 'green')")
    conn.executemany("INSERT INTO object_labels VALUES (?, ?, ?)",
                     [("task", "t1", "Work"), ("notebook", "n1", "Thesis"), ("habit", "h1", "Work")])
    plan = tags.plan_migration(conn)
    assert plan["projects"] == ["Thesis"] and plan["finance_tags"] == ["Rent"] and "Empty" in plan["labels"]
    assert conn.execute("SELECT COUNT(*) FROM label_tags").fetchone()[0] == 0

    tags.apply_migration(conn)
    by_name = {t["name"]: t for t in tags.list_tags(conn)}
    assert by_name["Rent"]["label_name"] == "Finance" and by_name["Work"]["label_name"] == "Work"
    assert by_name["Empty"]["color"] == "green"
    assert tags.tags_for_object(conn, "transaction", "tx1") == ["Rent"]
    assert tags.tags_for_object(conn, "note", "n1") == ["Thesis"]
    assert tags.tags_for_object(conn, "habit", "h1") == []
    tags.apply_migration(conn)
    assert conn.execute("SELECT COUNT(*) FROM object_tags").fetchone()[0] == 3


def test_folded_projects_become_tags_under_one_label_with_the_latest_deadline():
    conn = _conn()
    conn.executemany("INSERT INTO label_config (name, label_group, is_project, deadline_date) VALUES (?, 'School', 1, ?)",
                     [("Biology", "2027-01-15"), ("Maths", "2027-02-01"), ("Choir", "2026-12-01")])
    conn.execute("INSERT INTO object_labels VALUES ('task', 't1', 'Maths')")
    fold = {"Biology": "1st semester", "Maths": "1st semester", "Nope": "x"}
    assert tags.plan_migration(conn, fold)["folded"] == {"Biology": "1st semester", "Maths": "1st semester"}
    tags.apply_migration(conn, fold)
    by_name = {t["name"]: t["label_name"] for t in tags.list_tags(conn)}
    assert by_name["Biology"] == by_name["Maths"] == "1st semester" and by_name["Choir"] == "Choir"
    row = conn.execute("SELECT has_deadline, deadline_date FROM label_config WHERE name = '1st semester'").fetchone()
    assert tuple(row) == (1, "2027-02-01")
    assert tags.tags_for_object(conn, "task", "t1") == ["Maths"]


def test_label_deadline_archives_and_restore_clears_it():
    conn = _conn()
    conn.execute("INSERT INTO label_config (name, has_deadline, deadline_date) VALUES ('Old', 1, '2026-01-01'), ('Soon', 1, '2099-01-01')")
    assert tags.archive_past_deadlines(conn, "2026-10-23") == 1
    assert tags.archive_past_deadlines(conn, "2026-10-23") == 0
    tags.restore(conn, "Old")
    assert conn.execute("SELECT archived_at, deadline_date FROM label_config WHERE name = 'Old'").fetchone()[:] == (None, None)


def test_tag_tables_migrations_are_registered():
    assert {20, 21} <= {m.number for m in migrations.MIGRATIONS}


def test_an_older_tags_table_does_not_get_in_the_way():
    conn = _conn()
    conn.execute("DROP TABLE label_tags")
    conn.execute("CREATE TABLE tags (uid TEXT PRIMARY KEY, name TEXT, color TEXT, group_uid TEXT, created_at TEXT)")
    conn.execute("INSERT INTO tags VALUES ('u', 'CS', 'blue', NULL, 'x')")
    tags.ensure_schema(conn)
    tags.add_default_tag(conn, "Work")
    assert [t["name"] for t in tags.list_tags(conn)] == ["Work"]
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1


def test_migration_22_turns_the_habit_label_into_a_flag():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE tasks (uid TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE label_config (name TEXT PRIMARY KEY);
        CREATE TABLE object_labels (object_type TEXT, object_id TEXT, label_name TEXT);
        CREATE TABLE task_habit_settings (id INTEGER PRIMARY KEY, habit_label TEXT);
        INSERT INTO tasks VALUES ('h', 'Run'), ('t', 'Plain');
        INSERT INTO label_config VALUES ('Habit'), ('Work');
        INSERT INTO object_labels VALUES ('task', 'h', 'Habit'), ('task', 'h', 'Work'), ('event', 'e', 'Habit'), ('task', 't', 'Work');
        INSERT INTO task_habit_settings VALUES (1, 'Habit');
    """)
    migrations._habit_is_not_a_label(conn)
    assert [(r["uid"], r["is_habit"]) for r in conn.execute("SELECT uid, is_habit FROM tasks ORDER BY uid")] == [("h", 1), ("t", 0)]
    assert [tuple(r) for r in conn.execute("SELECT object_id, label_name FROM object_labels ORDER BY 1")] == [("h", "Work"), ("t", "Work")]
    assert [r[0] for r in conn.execute("SELECT name FROM label_config")] == ["Work"]


def test_apply_keeps_the_tag_links_an_item_already_has():
    conn = _conn()
    conn.execute("INSERT INTO label_config (name) VALUES ('Work')")
    conn.execute("INSERT INTO label_tags (name, label_name) VALUES ('Report', 'Work')")
    conn.executemany("INSERT INTO object_labels VALUES (?, ?, ?)", [("task", "picked", "Work"), ("task", "plain", "Work")])
    conn.execute("INSERT INTO object_tags VALUES ('task', 'picked', 'Report')")
    tags.apply_migration(conn)
    assert tags.tags_for_object(conn, "task", "picked") == ["Report"]
    assert tags.tags_for_object(conn, "task", "plain") == ["Work"]


def test_migration_23_moves_finance_tags_under_the_finance_shelf_and_drops_the_old_tables():
    conn = _conn()
    conn.execute("INSERT INTO finance_tags (name, color, icon) VALUES ('Rent', 'red', 'home'), ('Work', 'blue', '')")
    conn.executemany("INSERT INTO finance_transaction_tags VALUES (?, ?)", [("tx1", "Rent"), ("tx2", "Work"), ("tx3", "Loose")])
    conn.execute("INSERT INTO finance_scheduled_tags VALUES ('s1', 'Rent')")
    conn.execute("INSERT INTO label_config (name) VALUES ('Work')")
    conn.execute("INSERT INTO label_tags (name, label_name) VALUES ('Work', 'Work')")
    conn.execute("CREATE TABLE projects (uid TEXT)")
    conn.execute("CREATE TABLE tags (uid TEXT, name TEXT)")
    migrations._finance_tags_become_tags(conn)
    by_name = {t["name"]: t for t in tags.list_tags(conn)}
    assert by_name["Rent"]["label_name"] == "Finance" and by_name["Rent"]["color"] == "red"
    assert by_name["Work (finance)"]["label_name"] == "Finance"  # "Work" already means a shelf
    assert by_name["Loose"]["label_name"] == "Finance"  # used on a transaction but never listed
    assert tags.tags_for_object(conn, "transaction", "tx2") == ["Work (finance)"]
    assert tags.tags_for_object(conn, "scheduled", "s1") == ["Rent"]
    for table in ("finance_tags", "finance_transaction_tags", "finance_scheduled_tags", "projects", "tags"):
        assert not tags._has(conn, table)
    assert tags._has(conn, "label_tags")
