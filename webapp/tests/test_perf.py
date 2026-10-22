"""Timing tracking: totals survive flushes, the log only speaks when something is problematic, the browser reports in."""

from __future__ import annotations

from datetime import date

import pytest
from starlette.testclient import TestClient

from src import db, log, main, perf


@pytest.fixture(autouse=True)
def _clean_stats():
    perf._pending.clear()
    perf._alerted.clear()


@pytest.fixture
def conn(tmp_path):
    with db.connect(tmp_path / "c.sqlite") as connection:
        yield connection


def _warnings_during(action):
    entries = log.entries("all")
    start = entries[-1]["id"] if entries else 0
    action()
    return [w["message"].split("\n")[0] for w in log.entries("warnings", after=start)]


def test_one_slow_moment_is_stored_but_not_logged():
    assert _warnings_during(lambda: perf.record("request", "GET /tasks", 2500)) == []
    assert perf._pending[("request", "GET /tasks")].slow == 1


def test_an_extreme_moment_is_logged():
    assert _warnings_during(lambda: perf.record("request", "GET /tasks", 4000)) == ["Very slow request: GET /tasks"]


def test_totals_add_up_across_flushes(conn):
    perf.record("background", "radicale sync", 100)
    perf.flush(conn)
    perf.record("background", "radicale sync", 300)
    row = next(r for r in perf.summary(conn) if r["name"] == "radicale sync")
    assert (row["count"], row["average_ms"], row["max_ms"], row["slow"]) == (2, 200, 300, 0)


def test_a_metric_slow_often_warns_once_a_day(conn):
    for _ in range(10):
        perf.record("request", "GET /tasks", 1500)

    assert _warnings_during(lambda: perf.flush(conn)) == ["Slow request often: GET /tasks"]
    perf.record("request", "GET /tasks", 1500)
    assert _warnings_during(lambda: perf.flush(conn)) == []


def test_a_metric_much_slower_than_last_week_warns(conn, frozen_today):
    frozen_today(date(2026, 10, 19))
    conn.execute("INSERT INTO perf_daily VALUES ('2026-10-15', 'request', 'GET /', 100, 10000, 300, 0)")
    for _ in range(10):
        perf.record("request", "GET /", 400)

    assert _warnings_during(lambda: perf.flush(conn)) == ["Slower than usual: request GET /"]
    assert next(r for r in perf.summary(conn) if r["name"] == "GET /")["trend"] == "slower"


def test_a_steady_metric_stays_quiet(conn, frozen_today):
    frozen_today(date(2026, 10, 19))
    conn.execute("INSERT INTO perf_daily VALUES ('2026-10-15', 'request', 'GET /', 100, 10000, 300, 0)")
    for _ in range(10):
        perf.record("request", "GET /", 110)
    assert _warnings_during(lambda: perf.flush(conn)) == []


def test_old_days_are_dropped(conn, frozen_today):
    conn.execute("INSERT INTO perf_daily VALUES ('2026-01-01', 'request', 'GET /old', 1, 5, 5, 0)")
    frozen_today(date(2026, 10, 19))
    perf.flush(conn)
    assert conn.execute("SELECT COUNT(*) FROM perf_daily WHERE name = 'GET /old'").fetchone()[0] == 0


def test_browser_reports_keep_known_names_and_clean_numbers():
    perf.record_browser(
        {
            "editor typing": {"count": 20, "total": 600, "max": 90, "slow": 99},
            "something else": {"count": 1, "total": 1, "max": 1, "slow": 0},
            "editor save": {"count": "x"},
        }
    )
    assert set(perf._pending) == {("browser", "editor typing")}
    assert perf._pending[("browser", "editor typing")].slow == 20


def test_unwatched_requests_are_stored_only_when_slow():
    perf.record("request", "GET /habits", 50, always=False)
    perf.record("request", "GET /habits", 1500, always=False)
    assert perf._pending[("request", "GET /habits")].count == 1


def test_requests_are_timed_and_the_browser_can_report(monkeypatch, tmp_path):
    monkeypatch.setenv("CC_DB_PATH", str(tmp_path / "c.sqlite"))
    monkeypatch.setenv("CC_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setenv("CC_SKIP_AUTH", "1")
    with TestClient(main.create_app()) as client:
        client.get("/tasks")
        client.get("/health")
        resp = client.post("/perf/report", json={"editor open": {"count": 1, "total": 800, "max": 800, "slow": 0}})
        assert resp.status_code == 204
        assert client.get("/settings/logs").status_code == 200
    import sqlite3

    with sqlite3.connect(tmp_path / "c.sqlite") as check:
        saved = {(k, n) for k, n in check.execute("SELECT kind, name FROM perf_daily")}
    assert {("request", "GET /tasks"), ("startup", "ready"), ("browser", "editor open")} <= saved
    assert not any(name.endswith("/health") or name == "POST /perf/report" for _, name in saved)
