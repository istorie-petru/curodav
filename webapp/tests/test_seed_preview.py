"""scripts/seed_preview.py (2026-09-25 UI audit): the preview-data seeder
later sessions use for screenshots. Runs it for real against a temp DB so a
schema change that breaks it shows up here, not mid-session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src import db

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_preview.py"


def _run(*args):
    return subprocess.run([sys.executable, str(_SCRIPT), *args], capture_output=True, text=True)


def test_seeds_realistic_data_with_app_conventions(tmp_path):
    path = tmp_path / "preview.sqlite"
    assert _run(str(path)).returncode == 0
    with db.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 24
        statuses = {r[0] for r in conn.execute("SELECT status FROM tasks")}
        assert statuses <= {"active", "in_progress", "done"}
        colors = {r[0] for r in conn.execute("SELECT color FROM label_config")}
        assert not any(c.startswith("#") for c in colors)
        # all-day events end on the inclusive last day at 23:59
        ends = [r[0] for r in conn.execute("SELECT end_at FROM events WHERE all_day = 1")]
        assert ends and all(e.endswith("T23:59:00") for e in ends)
        assert conn.execute("SELECT COUNT(*) FROM task_completions").fetchone()[0] > 100


def test_refuses_a_populated_database_without_force(tmp_path):
    path = tmp_path / "preview.sqlite"
    assert _run(str(path)).returncode == 0
    second = _run(str(path))
    assert second.returncode != 0
    assert "refusing" in second.stderr
    assert _run(str(path), "--force").returncode == 0
