"""Settings > API access: a new token is shown once and can be removed."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src import access_tokens, db, main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("CC_AUTH_USERNAME", "alice")
    monkeypatch.setenv("CC_AUTH_PASSWORD", "s3cret-pass")
    monkeypatch.delenv("CC_SKIP_AUTH", raising=False)
    with TestClient(main.create_app(), base_url="http://testserver", follow_redirects=False) as c:
        c.post("/login", data={"username": "alice", "password": "s3cret-pass", "next": "/"}, headers={"Origin": "http://testserver"})
        yield c


def _conn(client):
    return db.connect(client.app.state.settings.db_path, reuse_schema=True)


def test_a_new_token_is_shown_once_on_the_next_full_page_load(client):
    created = client.post("/settings/api-access/tokens", data={"name": "Claude Code"}, headers={"Origin": "http://testserver"})
    assert created.status_code == 303
    assert "api-secret" not in client.get(created.headers["location"], headers={"X-Requested-With": "fetch"}).text
    page = client.get(created.headers["location"]).text
    secret = page.split('class="api-secret">', 1)[1].split("<", 1)[0]
    assert "Claude Code" in page and secret not in client.get(created.headers["location"]).text
    with _conn(client) as conn:
        assert access_tokens.check_token(conn, secret) is not None


def test_removing_a_token_stops_it(client):
    with _conn(client) as conn:
        uid, secret = access_tokens.create_personal_token(conn, "Script")
    client.post(f"/settings/api-access/tokens/{uid}/revoke", headers={"Origin": "http://testserver"})
    with _conn(client) as conn:
        assert access_tokens.check_token(conn, secret) is None
    assert "Script" not in client.get("/settings/api-access").text


def _secret(page: str) -> str:
    return page.split('class="api-secret">', 1)[1].split("<", 1)[0]


def test_the_new_token_window_starts_with_the_three_read_switches_on(client):
    page = client.get("/settings/api-access/new").text
    assert page.count('role="switch"') == 6 and page.count(" checked") == 3


def test_a_token_gets_exactly_the_switches_that_were_on(client):
    client.post("/settings/api-access/tokens", data={"name": "Uni", "scopes_sent": "1", "grant": ["write:university"]},
                headers={"Origin": "http://testserver"})
    page = client.get("/settings/api-access").text
    with _conn(client) as conn:
        token = access_tokens.check_token(conn, _secret(page), None)
    assert token["scopes"] == "read:university write:university"
    assert "Reads university; edits university" in page


def test_changing_a_token_saves_and_says_so(client):
    with _conn(client) as conn:
        uid, secret = access_tokens.create_personal_token(conn, "Script")
    window = client.get(f"/settings/api-access/tokens/{uid}/edit").text
    assert window.count(" checked") == 3
    saved = client.post(f"/settings/api-access/tokens/{uid}", data={"scopes_sent": "1", "grant": ["read:notes", "write:notes"]},
                        headers={"Origin": "http://testserver"})
    assert saved.headers["location"].endswith("note=Access%20saved")
    with _conn(client) as conn:
        assert access_tokens.check_token(conn, secret, "write:notes") is not None
        assert access_tokens.check_token(conn, secret, "read:calendar") is None


def test_a_change_is_listed_and_undone_from_settings(client):
    from src import mcp_server

    with _conn(client) as conn:
        result = mcp_server.handle(conn, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "create_note", "arguments": {"title": "From the assistant"}}}, {"uid": "t", "scopes": "write:notes"})
        uid = result["result"]["structuredContent"]["uid"]
        change = conn.execute("SELECT uid FROM api_changes").fetchone()[0]
    assert "Created note From the assistant" in client.get("/settings/api-access").text
    done = client.post(f"/settings/api-access/changes/{change}/undo", headers={"Origin": "http://testserver"})
    assert done.headers["location"].endswith("note=Undone")
    with _conn(client) as conn:
        assert db.get_notebook_document(conn, uid) is None
    assert "undone" in client.get("/settings/api-access").text


def test_the_backups_page_lists_the_start_backup_and_opens_it(client):
    from src import auto_backups

    settings = client.app.state.settings
    name = auto_backups.make(settings.db_path, settings.backup_dir, "morning").name
    assert "Morning" in client.get("/settings/backups").text
    window = client.get(f"/settings/backups/{name}").text
    assert "Compared with now" in window and "Restore everything" in window
