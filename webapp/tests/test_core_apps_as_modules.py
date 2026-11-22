"""Notebook, Library and Finance are modules: off, their pages and sidebar entries are gone; their data stays."""

import pytest
from fastapi.testclient import TestClient

from src import db, main, modules


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("CC_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    monkeypatch.delenv("CC_MODULES")  # replaces the suite's default, which forces the three on
    monkeypatch.setattr(modules, "_stored", set())
    with TestClient(main.create_app()) as c:
        yield c


def test_a_new_installation_starts_without_them(client):
    for url in ("/notebook", "/library", "/finance/transactions", "/settings/notebook", "/settings/finance"):
        assert client.get(url).status_code == 404
    home = client.get("/").text
    for href in ('href="/notebook"', 'href="/library"', 'href="/finance"'):
        assert href not in home


def test_switching_one_on_brings_back_its_pages_and_sidebar_entry(client):
    assert client.post("/settings/modules/notebook", data={"enabled": "1"}, follow_redirects=False).status_code == 303
    assert client.get("/notebook").status_code == 200
    assert 'href="/notebook"' in client.get("/").text
    assert client.get("/library").status_code == 404
    client.post("/settings/modules/notebook", data={"enabled": "0"})
    assert client.get("/notebook").status_code == 404


def test_the_modules_page_lists_them_all(client):
    page = client.get("/settings/modules").text
    for name in ("Notebook", "Library", "Finance", "Academic", "Accounts"):
        assert name in page
