"""CURODAV_ settings win over the older CC_ names, and the data folder falls back to the legacy one."""

from src import config


def test_curodav_variable_wins_over_the_old_name(monkeypatch):
    monkeypatch.setenv("CC_DB_PATH", "/tmp/old.sqlite")
    monkeypatch.setenv("CURODAV_DB_PATH", "/tmp/new.sqlite")
    assert str(config.load_settings().db_path) == "/tmp/new.sqlite"


def test_old_variable_alone_still_works(monkeypatch):
    monkeypatch.delenv("CURODAV_DB_PATH", raising=False)
    monkeypatch.setenv("CC_DB_PATH", "/tmp/old.sqlite")
    assert str(config.load_settings().db_path) == "/tmp/old.sqlite"


def test_default_path_uses_legacy_folder_until_it_is_moved(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(config, "LEGACY_DATA_DIR", tmp_path / "old")
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", tmp_path / "new")
    assert config.default_db_path() == tmp_path / "new" / "curodav.sqlite"
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "cache.sqlite").write_bytes(b"x")
    assert config.default_db_path() == tmp_path / "old" / "cache.sqlite"
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / "curodav.sqlite").write_bytes(b"x")
    assert config.default_db_path() == tmp_path / "old" / "cache.sqlite"
    assert "Two databases exist" in caplog.text
    (tmp_path / "old" / "cache.sqlite").unlink()
    assert config.default_db_path() == tmp_path / "new" / "curodav.sqlite"
