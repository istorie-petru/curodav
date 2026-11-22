"""The Accounts module's routes through the app: off by default, then create, unlock, read one secret, lock (features/accounts-vault.md)."""

import pytest
from fastapi.testclient import TestClient

from src import modules, vault_kdbx as kdbx, vault_session as session


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    monkeypatch.setattr(kdbx, "DEFAULT_KDF", {"iterations": 2, "memory": 8 * 1024 * 1024, "parallelism": 1})
    session.lock_all()
    session._failures.clear()
    from src.main import create_app

    with TestClient(create_app(), base_url="http://localhost", client=("127.0.0.1", 50000)) as c:
        yield c
    session.lock_all()


def test_the_module_is_off_until_switched_on(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: False)
    assert client.get("/accounts").status_code == 404


def test_create_add_read_lock_and_unlock(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    fetch = {"X-Requested-With": "fetch"}
    assert client.post("/accounts/create", data={"password": "short", "confirm": "short"}, headers=fetch).status_code == 422
    assert client.post("/accounts/create", data={"password": "long-enough-pass", "confirm": "long-enough-pass"}).status_code == 200
    rows = {"field_idx": ["1", "2", "3"], "field_key_1": "User name", "field_value_1": "ana", "field_secret_1": "0",
            "field_key_2": "Password", "field_value_2": "p4ss-wörd", "field_secret_2": "1",
            "field_key_3": "Pet", "field_value_3": "Rex", "field_secret_3": "1"}
    page = client.post("/accounts/entry", data={"title": "Mail", **rows}, follow_redirects=True)
    assert page.status_code == 200 and "Mail" in page.text and "p4ss-wörd" not in page.text
    uid = page.text.split('data-uuid="')[1].split('"')[0]
    assert client.post(f"/accounts/entry/{uid}/secret", data={"field": "Password"}).json() == {"value": "p4ss-wörd"}
    assert client.post(f"/accounts/entry/{uid}/secret", data={"field": "Pet"}).json() == {"value": "Rex"}
    form = client.get(f"/accounts/entry/{uid}/edit").text
    assert 'value="User name"' in form and 'value="Pet"' in form and 'Show' in form
    client.post("/accounts/lock")
    assert client.post(f"/accounts/entry/{uid}/secret", data={"field": "Password"}).status_code == 423
    assert client.post("/accounts/unlock", data={"password": "wrong-pass-123"}, headers=fetch).status_code == 422
    client.post("/accounts/unlock", data={"password": "long-enough-pass"})
    assert client.get("/accounts/status").json() == {"unlocked": True}


def test_unlocking_over_plain_http_from_another_machine_is_refused(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    from src.routers import accounts

    monkeypatch.setattr(accounts, "_safe_transport", lambda request: False)
    response = client.post("/accounts/create", data={"password": "long-enough-pass", "confirm": "long-enough-pass"}, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 422 and "HTTPS" in response.text


def test_new_passwords_follow_the_rule_saved_in_settings(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    client.post("/settings/accounts/generator", data={"mode": "random", "length": "16", "sets": ["digits"], "exclude": "0123"})
    made = client.get("/accounts/generate").json()
    assert len(made["value"]) == 16 and set(made["value"]) <= set("456789") and made["rating"]
    preview = client.get("/accounts/generate", params={"mode": "memorable", "words": "3", "separator": "+"}).json()
    assert preview["value"].count("+") == 2


def test_a_type_can_take_the_keepass_fields_by_name(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    form = client.get("/settings/accounts/type/new").text
    assert 'data-acc-standard="Password"' in form and 'data-acc-standard="One-time code"' in form
    client.post("/settings/accounts/type", data={"name": "Router", "field_idx": ["1", "2"], "field_name_1": "password", "field_kind_1": "text",
                                                 "field_name_2": "Model", "field_kind_2": "text"})
    settings = client.get("/settings/accounts").text
    key = settings.split("Router")[0].rsplit('/settings/accounts/type/', 1)[1].split('"')[0]
    assert "Password, Model" in settings.split("Router", 1)[1].split("</a>")[0]
    edit = client.get(f"/settings/accounts/type/{key}").text
    assert 'data-standard="Password"' in edit


def test_changing_a_password_offers_an_undo(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    client.post("/accounts/create", data={"password": "long-enough-pass", "confirm": "long-enough-pass"})
    rows = {"field_idx": ["1"], "field_key_1": "Password", "field_value_1": "first-pass", "field_secret_1": "1"}
    page = client.post("/accounts/entry", data={"title": "Mail", **rows}, follow_redirects=True)
    uid = page.text.split('data-uuid="')[1].split('"')[0]
    changed = client.post(f"/accounts/entry/{uid}/update-field", json={"field": "Password", "value": "second-pass"}).json()
    assert changed["undo"]["field"] == "Password" and changed["undo"]["url"].endswith("/undo-field")
    assert "undo" not in client.post(f"/accounts/entry/{uid}/update-field", json={"field": "Title", "value": "Mail 2"}).json()
    assert client.post(f"/accounts/entry/{uid}/undo-field", json={"field": "Password"}).json() == {"ok": True}
    assert client.post(f"/accounts/entry/{uid}/secret", data={"field": "Password"}).json() == {"value": "first-pass"}
    edited = client.post(f"/accounts/entry/{uid}", data={"title": "Mail 2", **{**rows, "field_value_1": "third-pass"}}, follow_redirects=False)
    assert f"undo_password={uid}" in edited.headers["location"]


def test_bulk_routes_move_change_bin_and_restore(client, monkeypatch):
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    client.post("/accounts/create", data={"password": "long-enough-pass", "confirm": "long-enough-pass"})
    ids = []
    for title in ("One", "Two"):
        page = client.post("/accounts/entry", data={"title": title}, follow_redirects=True)
        ids.append(page.text.split(f'data-uuid="')[1].split('"')[0] if not ids else None)
    page = client.get("/accounts?space=_")
    ids = [chunk.split('"')[0] for chunk in page.text.split('class="contact-row-wrap accounts-row" data-uuid="')[1:]]
    assert len(ids) == 2
    joined = ",".join(ids)
    assert client.get(f"/accounts/bulk?uuids={joined}").status_code == 200 and client.get("/accounts/bulk").status_code == 400
    done = client.post("/accounts/bulk/edit", data={"uuids": joined, "space": "__keep", "type": "__keep", "add_tags": "a, b", "remove_tags": ""}, follow_redirects=False)
    assert "2+entries+changed" in done.headers["location"]
    assert client.post("/accounts/bulk/delete", data={"uuids": joined}, follow_redirects=False).status_code == 303
    assert "Recycle bin" in client.get("/accounts?view=trash").text and client.get("/accounts?space=_").text.count("data-uuid=") < 6
    assert "2+restored" in client.post("/accounts/bulk/restore", data={"uuids": joined}, follow_redirects=False).headers["location"]


def test_the_unlock_window_can_come_back_to_the_settings_page():
    from src.routers import accounts

    assert accounts._next("/settings/accounts") == "/settings/accounts"
    assert accounts._next("https://elsewhere.example/") == "/accounts" and accounts._next("") == "/accounts"
