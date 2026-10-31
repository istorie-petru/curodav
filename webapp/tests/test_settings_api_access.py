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


def test_a_token_can_be_made_to_edit_notes(client):
    client.post("/settings/api-access/tokens", data={"name": "Writer", "can_edit": "1"}, headers={"Origin": "http://testserver"})
    page = client.get("/settings/api-access").text
    secret = page.split('class="api-secret">', 1)[1].split("<", 1)[0]
    with _conn(client) as conn:
        assert access_tokens.check_token(conn, secret, "write") is not None
    assert "Read and edit" in page
