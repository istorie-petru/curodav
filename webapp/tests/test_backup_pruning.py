"""Pre-migration copies beyond the newest few are gzipped, never deleted."""
import os

from src import migrations


def test_older_copies_are_compressed(tmp_path):
    db = tmp_path / "cache.sqlite"
    db.write_bytes(b"x" * 100)
    for i in range(5):
        copy = tmp_path / f"cache.sqlite.before-migration-{i:04d}-20260101-00000{i}"
        copy.write_bytes(b"y" * 100)
        os.utime(copy, (1000 + i, 1000 + i))
    packed = migrations.compress_old_backups(db, keep=3)
    assert len(packed) == 2
    assert len(list(tmp_path.glob("*.before-migration-*.gz"))) == 2
    assert len([p for p in tmp_path.glob("*.before-migration-*") if p.suffix != ".gz"]) == 3


def test_banner_images_move_to_files(tmp_path):
    import base64
    import json
    import sqlite3

    from src import banner_files

    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT)")
    payload = base64.b64encode(b"\xff\xd8fake").decode()
    conn.execute("INSERT INTO app_meta VALUES ('page_banner_', ?)", (json.dumps({"kind": "upload", "image_b64": payload, "image_type": "jpeg"}),))
    conn.commit()
    migrations._banners_become_files(conn)
    banner = json.loads(conn.execute("SELECT value FROM app_meta").fetchone()[0])
    assert "image_b64" not in banner
    assert banner_files.read(conn, banner) == b"\xff\xd8fake"
    assert (tmp_path / "banners" / banner["image_file"]).exists()
