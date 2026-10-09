"""Password recovery: a recovery token exists for every install, resets the login
when it matches, and is replaced after use."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from src import auth, db


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


SETTINGS = SimpleNamespace(auth_session_secret=None, auth_username=None, auth_password=None, deploy_mode="local")


def test_the_token_is_created_once_and_kept(conn):
    first = auth.ensure_recovery_token(conn)
    assert auth.ensure_recovery_token(conn) == first
    assert len(first) == 19 and first.count("-") == 3


def test_a_matching_token_sets_the_new_login_and_rotates_the_token(conn):
    token = auth.ensure_recovery_token(conn)
    old_secret = auth.session_secret(SETTINGS, conn)
    new_token = auth.reset_credentials_with_token(SETTINGS, conn, token.lower(), "alice", "s3cret-pass")
    username, stored_hash = auth.get_persisted_credentials(conn)
    assert username == "alice"
    assert auth.verify_credentials(SETTINGS, "alice", "s3cret-pass", conn)
    assert new_token != token
    assert auth.get_recovery_token(conn) == new_token
    assert auth.session_secret(SETTINGS, conn) != old_secret


def test_a_wrong_token_changes_nothing(conn):
    auth.ensure_recovery_token(conn)
    with pytest.raises(ValueError):
        auth.reset_credentials_with_token(SETTINGS, conn, "WRONG-TOKEN-0000-0000", "alice", "pw")
    assert auth.get_persisted_credentials(conn) is None


def test_the_old_token_stops_working_after_a_reset(conn):
    token = auth.ensure_recovery_token(conn)
    auth.reset_credentials_with_token(SETTINGS, conn, token, "alice", "pw-one")
    with pytest.raises(ValueError):
        auth.reset_credentials_with_token(SETTINGS, conn, token, "bob", "pw-two")


def _run_cli(monkeypatch, tmp_path, answers, passwords, *args):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("password_reset", Path(__file__).resolve().parents[1] / "scripts" / "password_reset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "cli.sqlite"))
    monkeypatch.delenv("CC_AUTH_USERNAME", raising=False)
    monkeypatch.delenv("CC_AUTH_PASSWORD", raising=False)
    answers, passwords = iter(answers), iter(passwords)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(passwords))
    return module.main(list(args))


def test_the_command_line_tool_resets_the_login_with_the_token(monkeypatch, tmp_path, capsys):
    with db.connect(tmp_path / "cli.sqlite") as c:
        token = auth.ensure_recovery_token(c)
    assert _run_cli(monkeypatch, tmp_path, [token, "alice"], ["pw-long-enough", "pw-long-enough"]) == 0
    assert "new recovery token" in capsys.readouterr().out
    with db.connect(tmp_path / "cli.sqlite") as c:
        assert auth.get_persisted_credentials(c)[0] == "alice"


def test_the_command_line_tool_refuses_a_wrong_token(monkeypatch, tmp_path, capsys):
    with db.connect(tmp_path / "cli.sqlite") as c:
        auth.ensure_recovery_token(c)
    assert _run_cli(monkeypatch, tmp_path, ["NOPE", "alice"], ["pw", "pw"]) == 1
    assert "not correct" in capsys.readouterr().err


def test_dev_clear_deletes_the_stored_login(monkeypatch, tmp_path):
    with db.connect(tmp_path / "cli.sqlite") as c:
        auth.set_persisted_credentials(c, "alice", "pw")
    assert _run_cli(monkeypatch, tmp_path, [], [], "--dev-clear") == 0
    with db.connect(tmp_path / "cli.sqlite") as c:
        assert auth.get_persisted_credentials(c) is None
