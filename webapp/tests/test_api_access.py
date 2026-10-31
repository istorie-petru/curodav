"""Access to /api/v1 and /mcp: bearer tokens, the OAuth flow Claude connectors use, and what stays closed."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from src import access_tokens, api_auth, clock, db, main

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("CC_AUTH_USERNAME", "alice")
    monkeypatch.setenv("CC_AUTH_PASSWORD", "s3cret-pass")
    monkeypatch.delenv("CC_SKIP_AUTH", raising=False)
    api_auth.reset_rate_limits()
    with TestClient(main.create_app(), base_url="http://testserver", follow_redirects=False) as client:
        yield client
    api_auth.reset_rate_limits()


def _conn(client):
    return db.connect(client.app.state.settings.db_path, reuse_schema=True)


def _personal_token(client, scopes="read"):
    with _conn(client) as conn:
        return access_tokens.create_personal_token(conn, "Script", scopes)


def _note(client, uid="n1", title="Kant lecture"):
    with _conn(client) as conn:
        db.upsert_notebook_document(conn, {"uid": uid, "title": title, "content_json": json.dumps({"blocks": [
            {"id": "b1", "type": "paragraph", "data": {"text": "The categorical imperative"}}]}), "document_type": "full",
            "note_type": "", "created_at": "2026-10-01T10:00:00+00:00", "updated_at": "2026-10-01T10:00:00+00:00"})


def _bearer(secret):
    return {"Authorization": f"Bearer {secret}"}


def _login(client):
    response = client.post("/login", data={"username": "alice", "password": "s3cret-pass", "next": "/"},
                           headers={"Origin": "http://testserver"})
    assert response.status_code in (302, 303)


def test_api_without_a_token_says_where_to_get_one(app_client):
    response = app_client.get("/api/v1/notes")
    assert response.status_code == 401
    assert 'resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp"' in response.headers["www-authenticate"]


def test_a_browser_session_does_not_open_the_api(app_client):
    _login(app_client)
    assert app_client.get("/api/v1/notes").status_code == 401
    assert app_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401


def test_a_personal_token_reads_notes_with_an_etag(app_client):
    _note(app_client)
    _uid, secret = _personal_token(app_client)
    listing = app_client.get("/api/v1/notes", headers=_bearer(secret)).json()
    assert [n["uid"] for n in listing["items"]] == ["n1"]
    note = app_client.get("/api/v1/notes/n1", headers=_bearer(secret))
    assert note.headers["etag"] == '"2026-10-01T10:00:00+00:00"'
    assert app_client.get("/api/v1/notes/missing", headers=_bearer(secret)).json()["detail"]["error"] == "not_found"


def test_a_revoked_token_stops_working(app_client):
    uid, secret = _personal_token(app_client)
    with _conn(app_client) as conn:
        access_tokens.revoke_token(conn, uid)
    response = app_client.get("/api/v1/notes", headers=_bearer(secret))
    assert response.status_code == 401 and 'error="invalid_token"' in response.headers["www-authenticate"]


def test_tokens_are_stored_only_as_hashes(app_client):
    _uid, secret = _personal_token(app_client)
    with _conn(app_client) as conn:
        dump = "\n".join(conn.iterdump())
    assert secret not in dump


def test_repeated_bad_tokens_are_rate_limited(app_client):
    for _ in range(api_auth.FAILED_MAX):
        app_client.get("/api/v1/notes", headers=_bearer("cdv_wrong"))
    assert app_client.get("/api/v1/notes", headers=_bearer("cdv_wrong")).status_code == 429


def test_mcp_over_http_initializes_and_calls_a_tool(app_client):
    _note(app_client)
    _uid, secret = _personal_token(app_client)
    init = app_client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                                  "params": {"protocolVersion": "2025-06-18"}})
    assert init.json()["result"]["serverInfo"]["name"] == "curodav"
    note = app_client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                                  "params": {"name": "search", "arguments": {"query": "categorical"}}})
    assert note.json()["result"]["structuredContent"]["results"][0]["uid"] == "n1"
    assert app_client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    with _conn(app_client) as conn:
        assert access_tokens.recent_activity(conn)[0]["action"] == "tool search"


def test_mcp_refuses_another_site_and_bad_json(app_client):
    _uid, secret = _personal_token(app_client)
    foreign = app_client.post("/mcp", headers={**_bearer(secret), "Origin": "https://evil.example"},
                              json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert foreign.status_code == 403
    broken = app_client.post("/mcp", headers={**_bearer(secret), "Content-Type": "application/json"}, content=b"{not json")
    assert broken.json()["error"]["code"] == -32700


def test_discovery_documents_point_at_each_other(app_client):
    resource = app_client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == "http://testserver/mcp"
    server = app_client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == resource["authorization_servers"][0]
    assert server["code_challenge_methods_supported"] == ["S256"]


def _register(client, uris=(CALLBACK,)):
    return client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": list(uris),
                                                "token_endpoint_auth_method": "none"})


def test_registration_refuses_plain_http_callbacks_except_loopback(app_client):
    assert _register(app_client, ["http://example.com/cb"]).json()["error"] == "invalid_redirect_uri"
    assert _register(app_client, ["http://localhost:4321/callback"]).status_code == 201


def _authorize_params(client_id, **extra):
    return {"client_id": client_id, "redirect_uri": CALLBACK, "response_type": "code", "scope": "read", "state": "xyz",
            "code_challenge": CHALLENGE, "code_challenge_method": "S256", **extra}


def _approve(client, client_id):
    _login(client)
    page = client.get("/oauth/authorize", params=_authorize_params(client_id))
    assert page.status_code == 200 and "Claude" in page.text
    decision = client.post("/oauth/authorize", data={**_authorize_params(client_id), "decision": "allow"},
                           headers={"Origin": "http://testserver"})
    assert decision.status_code == 303
    query = parse_qs(urlsplit(decision.headers["location"]).query)
    assert query["state"] == ["xyz"] and query["iss"] == ["http://testserver"]
    return query["code"][0]


def _exchange(client, client_id, code, verifier=VERIFIER):
    return client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id,
                                             "redirect_uri": CALLBACK, "code_verifier": verifier})


def test_the_consent_page_needs_the_normal_login(app_client):
    client_id = _register(app_client).json()["client_id"]
    response = app_client.get("/oauth/authorize", params=_authorize_params(client_id))
    assert response.status_code == 302 and "/login" in response.headers["location"]


def test_full_oauth_flow_gives_a_token_that_opens_mcp(app_client):
    client_id = _register(app_client).json()["client_id"]
    code = _approve(app_client, client_id)
    tokens = _exchange(app_client, client_id, code).json()
    assert tokens["token_type"] == "Bearer" and tokens["scope"] == "read"
    app_client.cookies.clear()
    ping = app_client.post("/mcp", headers=_bearer(tokens["access_token"]), json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert ping.json()["result"] == {}


def test_a_code_works_once_and_only_with_its_verifier(app_client):
    client_id = _register(app_client).json()["client_id"]
    code = _approve(app_client, client_id)
    assert _exchange(app_client, client_id, code, verifier="w" * 64).json()["error"] == "invalid_grant"
    assert _exchange(app_client, client_id, code).json()["error"] == "invalid_grant"


def test_refresh_rotates_and_the_old_refresh_token_dies(app_client):
    client_id = _register(app_client).json()["client_id"]
    first = _exchange(app_client, client_id, _approve(app_client, client_id)).json()
    form = {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": client_id}
    second = app_client.post("/oauth/token", data=form).json()
    assert second["access_token"] != first["access_token"]
    assert app_client.post("/oauth/token", data=form).json()["error"] == "invalid_grant"
    assert app_client.get("/api/v1/notes", headers=_bearer(first["access_token"])).status_code == 401
    assert app_client.get("/api/v1/notes", headers=_bearer(second["access_token"])).status_code == 200


def test_an_access_token_expires_after_an_hour(app_client):
    client_id = _register(app_client).json()["client_id"]
    tokens = _exchange(app_client, client_id, _approve(app_client, client_id)).json()
    clock.set_override(datetime.now(timezone.utc) + timedelta(hours=2))
    try:
        assert app_client.get("/api/v1/notes", headers=_bearer(tokens["access_token"])).status_code == 401
    finally:
        clock.set_override(None)


def test_denying_sends_the_app_away_without_a_code(app_client):
    client_id = _register(app_client).json()["client_id"]
    _login(app_client)
    decision = app_client.post("/oauth/authorize", data={**_authorize_params(client_id), "decision": "deny"},
                               headers={"Origin": "http://testserver"})
    query = parse_qs(urlsplit(decision.headers["location"]).query)
    assert query["error"] == ["access_denied"] and "code" not in query


def test_an_unknown_callback_gets_an_error_page_not_a_redirect(app_client):
    client_id = _register(app_client).json()["client_id"]
    _login(app_client)
    page = app_client.get("/oauth/authorize", params=_authorize_params(client_id, redirect_uri="https://evil.example/cb"))
    assert page.status_code == 400


def test_nothing_can_be_approved_on_an_install_without_a_login(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.delenv("CC_AUTH_USERNAME", raising=False)
    monkeypatch.delenv("CC_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("CC_SKIP_AUTH", raising=False)
    with TestClient(main.create_app(), base_url="http://testserver", follow_redirects=False) as client:
        client_id = _register(client).json()["client_id"]
        assert client.get("/oauth/authorize", params=_authorize_params(client_id)).status_code == 403
        assert client.get("/api/v1/notes").status_code == 401



def test_university_routes_answer_with_a_token(app_client):
    _uid, secret = _personal_token(app_client)
    assert app_client.get("/api/v1/university", headers=_bearer(secret)).json()["semester"] is None
    assert app_client.get("/api/v1/university/disciplines/Biology", headers=_bearer(secret)).status_code == 404


def _blocks_note(client):
    with _conn(client) as conn:
        db.upsert_notebook_document(conn, {"uid": "n1", "title": "Kant", "content_json": json.dumps({"blocks": [
            {"id": "p1", "type": "paragraph", "data": {"text": "First"}},
            {"id": "c1", "type": "callout", "data": {"text": "Keep me"}}]}), "document_type": "full", "note_type": "",
            "created_at": "2026-10-01T10:00:00+00:00", "updated_at": "2026-10-01T10:00:00+00:00"})


def _tools(client, secret):
    reply = client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {t["name"] for t in reply.json()["result"]["tools"]}


def test_a_read_token_neither_sees_nor_calls_the_edit_tools(app_client):
    _blocks_note(app_client)
    _uid, secret = _personal_token(app_client)
    assert "edit_note" not in _tools(app_client, secret)
    call = app_client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "edit_note", "arguments": {"uid": "n1", "revision": "2026-10-01T10:00:00+00:00", "ops": [{"op": "append", "markdown": "x"}]}}})
    assert "error" in call.json()
    patch = app_client.patch("/api/v1/notes/n1/blocks", headers={**_bearer(secret), "If-Match": '"2026-10-01T10:00:00+00:00"'},
                             json={"ops": [{"op": "append", "markdown": "x"}]})
    assert patch.status_code == 401


def test_a_write_token_edits_through_mcp_and_the_change_can_be_undone(app_client):
    _blocks_note(app_client)
    _uid, secret = _personal_token(app_client, "read write")
    assert {"edit_note", "restore_note_version"} <= _tools(app_client, secret)
    call = app_client.post("/mcp", headers=_bearer(secret), json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "edit_note", "arguments": {"uid": "n1", "revision": "2026-10-01T10:00:00+00:00", "summary": "Add a line",
                                           "ops": [{"op": "append", "markdown": "Added"}]}}}).json()["result"]
    version = call["structuredContent"]["version"]
    note = app_client.get("/api/v1/notes/n1?include_blocks=true", headers=_bearer(secret)).json()
    assert [b["data"].get("text") for b in note["blocks"]] == ["First", "Keep me", "Added"]
    app_client.post(f"/api/v1/note-versions/{version}/restore", headers=_bearer(secret))
    assert len(app_client.get("/api/v1/notes/n1?include_blocks=true", headers=_bearer(secret)).json()["blocks"]) == 2


def test_rest_edit_needs_the_current_revision_in_if_match(app_client):
    _blocks_note(app_client)
    _uid, secret = _personal_token(app_client, "read write")
    headers = {**_bearer(secret), "If-Match": '"2026-10-01T10:00:00+00:00"'}
    first = app_client.patch("/api/v1/notes/n1/blocks", headers=headers, json={"ops": [{"op": "append", "markdown": "One"}]})
    assert first.status_code == 200 and first.headers["etag"] != headers["If-Match"]
    assert app_client.patch("/api/v1/notes/n1/blocks", headers=headers, json={"ops": [{"op": "append", "markdown": "Two"}]}).status_code == 409
    refused = app_client.patch("/api/v1/notes/n1/blocks", headers={**_bearer(secret), "If-Match": first.headers["etag"]},
                               json={"ops": [{"op": "delete", "block_id": "c1"}]})
    assert refused.status_code == 422


def test_oauth_can_grant_edit_access_when_asked(app_client):
    client_id = _register(app_client).json()["client_id"]
    _login(app_client)
    params = _authorize_params(client_id, scope="read write")
    assert "Allow read and edit" in app_client.get("/oauth/authorize", params=params).text
    decision = app_client.post("/oauth/authorize", data={**params, "decision": "allow"}, headers={"Origin": "http://testserver"})
    code = parse_qs(urlsplit(decision.headers["location"]).query)["code"][0]
    assert _exchange(app_client, client_id, code).json()["scope"] == "read write"
