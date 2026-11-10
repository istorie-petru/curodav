"""The Academic module keeps its semester on a shelf: the space stays ordinary, the old University names migrate and still redirect."""

import pytest
from starlette.requests import Request

from src import api_service, db, mcp_server, migrations_university, modules
from src import university_plan as up


def _request(path="/", query=b""):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query, "scheme": "http", "server": ("testserver", 80),
                    "root_path": "", "headers": []})


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_MODULES", "academic")
    with db.connect(tmp_path / "c.sqlite") as c:
        yield c


def test_the_old_module_key_still_forces_the_module_on(monkeypatch):
    from src import university  # noqa: F401  (registers the module)

    monkeypatch.setenv("CC_MODULES", "university")
    assert modules.is_enabled("academic")


def test_the_migration_renames_keys_and_hands_the_space_its_default_page_back(conn):
    uid = up.save_semester(conn, uid=None, name="Autumn", shelf_name="", start_date="", end_date="", class_end_date="")
    db.ensure_group(conn, "University")
    db.set_group_page_type(conn, "University", "study")
    conn.execute("UPDATE label_config SET managed_by = 'university', page_type = 'sections', sidebar_pin = 0, label_group = 'University' WHERE name = 'Autumn'")
    conn.execute("UPDATE app_meta SET key = 'university_current' WHERE key = 'academic_current'")
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('modules_enabled', 'university,other')")
    conn.commit()
    for _ in range(2):  # it can run twice
        migrations_university.academic_rename(conn)
    cfg = db.get_label_config(conn, "Autumn")
    assert (cfg["managed_by"], cfg["page_type"], cfg["sidebar_pin"], cfg["label_group"]) == ("academic", "academic", 1, "University")
    assert db.get_group(conn, "University")["page_type"] == "dashboard"
    assert db.get_app_meta(conn, "academic_current") == uid and db.get_app_meta(conn, "university_current") is None
    assert db.get_app_meta(conn, "modules_enabled") == "academic,other"


def test_old_addresses_redirect(conn):
    from src import university, university_discipline

    up.save_semester(conn, uid=None, name="Autumn", shelf_name="", start_date="", end_date="", class_end_date="")
    db.ensure_group(conn, "University")
    up.save_semester(conn, uid=up.current_semester(conn)["uid"], name="Autumn", shelf_name="", start_date="", end_date="", class_end_date="", space="University")
    resp = university_discipline.legacy_discipline_page("University", "Biology", _request(), conn=conn)
    assert resp.headers["location"] == "/labels/Autumn/disciplines/Biology"
    resp = university.legacy_settings(_request("/settings/university/slot/new", b"weekday=1"), rest="slot/new")
    assert resp.headers["location"] == "/settings/academic/slot/new?weekday=1"


def test_the_old_tool_names_still_work_and_are_not_listed():
    names = {t.name for t in mcp_server.visible_tools({"scopes": "read write"})}
    assert "academic_overview" in names and "university_overview" not in names
    assert mcp_server.LEGACY_NAMES["university_save_semester"] == "academic_save_semester"


def test_the_semester_tool_takes_a_space(conn):
    db.ensure_group(conn, "Studies")
    token = {"scopes": "write:university"}
    result = mcp_server.call_tool(conn, "university_save_semester", {"name": "Spring", "space": "Studies"}, token)
    assert not result.get("isError"), result
    assert db.get_label_config(conn, "Spring")["label_group"] == "Studies"


def test_a_library_entry_never_carries_a_file(conn):
    uid = db.upsert_citation(conn, {"type": "book", "title": "Cell Biology", "authors": [{"family": "Alberts"}]}) if hasattr(db, "upsert_citation") else None
    if uid is None:
        pytest.skip("no citation helper")
    out = api_service.get_citation(conn, uid)
    flat = repr(out)
    assert "file_name" not in flat and "calibre" not in flat


def test_a_radicale_timeout_is_logged_as_one(conn, caplog, monkeypatch):
    import logging
    import requests

    from src import published_lists

    class Bridge:
        request_timeout = 15

    def boom(c, b, row):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(published_lists.db, "list_published_lists", lambda c: [{"id": "1", "name": "Tasks", "visibility": "public"}])
    monkeypatch.setattr(published_lists, "materialize", boom)
    with caplog.at_level(logging.WARNING):
        published_lists.materialize_all(conn, Bridge())
    assert any("timed out" in r.getMessage() and "at most 15 s" in r.getMessage() for r in caplog.records)
    assert published_lists.is_timeout(RuntimeError("x")) is False
