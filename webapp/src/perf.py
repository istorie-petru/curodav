"""Local timing tracking for a few things that matter: startup, background ticks, the main pages, and the browser editor.

Measurements are summed in memory and flushed once a minute into `perf_daily` (one row per day, kind and name; 30 days
kept), so trends need no external service and nothing leaves the machine. The log stays quiet for a single slow
moment. It gets a warning only when something is problematic: a single measurement far over its limit, a metric that
is slow often today, or one that has got clearly slower than its last week. Each metric warns at most once a day.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from . import clock
from .log import get_logger

log = get_logger(__name__)

KEEP_DAYS = 30
FLUSH_SECONDS = 60
# Milliseconds above which one measurement counts as slow, per kind.
LIMITS_MS = {"request": 1000, "startup": 5000, "background": 30000}
# A single measurement this many times over its limit is logged on the spot.
EXTREME_FACTOR = 3
# Browser metrics the editor reports (name -> slow limit in ms); anything else sent is dropped.
BROWSER_LIMITS_MS = {"editor open": 3000, "editor typing": 100, "editor change": 100, "editor save": 2000}
# Requests aggregated for trends; any other request is stored only when it runs over its limit.
WATCHED_ROUTES = {"/", "/tasks", "/calendar", "/contacts", "/notebook", "/notebook/{uid}/content"}
IGNORED_PATHS = ("/static", "/health", "/settings/logs/entries", "/perf/report")
# Alert rules: slow share of today's measurements, and slowdown against the previous week.
SLOW_SHARE = 0.2
SLOWDOWN = 2.0
MIN_SAMPLES = 10

_lock = threading.Lock()


@dataclass
class _Stat:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    slow: int = 0


_pending: dict[tuple[str, str], _Stat] = {}
_alerted: set[tuple[str, str, str]] = set()


def limit_for(kind: str, name: str = "") -> int:
    if kind == "browser":
        return BROWSER_LIMITS_MS.get(name, 0)
    return LIMITS_MS.get(kind, LIMITS_MS["request"])


def _add(kind: str, name: str, count: int, total_ms: float, max_ms: float, slow: int) -> None:
    with _lock:
        stat = _pending.setdefault((kind, name), _Stat())
        stat.count += count
        stat.total_ms += total_ms
        stat.max_ms = max(stat.max_ms, max_ms)
        stat.slow += slow


def record(kind: str, name: str, ms: float, detail: str = "", always: bool = True) -> bool:
    """Adds one measurement; returns True when it was slow. `always` False stores it only if slow."""
    limit = limit_for(kind, name)
    slow = ms > limit
    if not (slow or always):
        return False
    _add(kind, name, 1, ms, ms, int(slow))
    if ms > limit * EXTREME_FACTOR:
        suffix = f"\n{detail}" if detail else ""
        log.warning("Very slow %s: %s\n%d ms (limit %d ms)%s", kind, name, round(ms), limit, suffix)
    return slow


@contextmanager
def timed(kind: str, name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        record(kind, name, (time.perf_counter() - started) * 1000)


def record_browser(report: dict) -> None:
    """Adds a batch from the browser: {name: {count, total, max, slow}}. Unknown names and bad numbers are dropped."""
    for name, stat in report.items():
        if name not in BROWSER_LIMITS_MS or not isinstance(stat, dict):
            continue
        try:
            count = min(max(int(stat["count"]), 0), 100000)
            total = min(max(float(stat["total"]), 0.0), 1e9)
            peak = min(max(float(stat["max"]), 0.0), 1e7)
            slow = min(max(int(stat["slow"]), 0), count)
        except (KeyError, TypeError, ValueError):
            continue
        if count:
            _add("browser", name, count, total, peak, slow)


def _problems(conn: sqlite3.Connection, today: str) -> list[str]:
    """Metrics that are problematic today and have not been reported yet today."""
    found = []
    rows = conn.execute("SELECT kind, name, count, total_ms, slow FROM perf_daily WHERE day = ?", (today,)).fetchall()
    for row in rows:
        key = (today, row["kind"], row["name"])
        if key in _alerted or row["count"] < MIN_SAMPLES:
            continue
        average = row["total_ms"] / row["count"]
        before = conn.execute(
            "SELECT SUM(count) AS count, SUM(total_ms) AS total_ms FROM perf_daily "
            "WHERE kind = ? AND name = ? AND day < ? AND day >= date(?, '-7 days')",
            (row["kind"], row["name"], today, today),
        ).fetchone()
        limit = limit_for(row["kind"], row["name"])
        if row["slow"] / row["count"] >= SLOW_SHARE:
            found.append(f"Slow {row['kind']} often: {row['name']}\n{row['slow']} of {row['count']} today were over {limit} ms (average {round(average)} ms)")
        elif before["count"] and before["count"] >= MIN_SAMPLES and average > SLOWDOWN * before["total_ms"] / before["count"] and average > limit / 4:
            usual = round(before["total_ms"] / before["count"])
            found.append(f"Slower than usual: {row['kind']} {row['name']}\naverage {round(average)} ms today against {usual} ms over the last week")
        else:
            continue
        _alerted.add(key)
    return found


def flush(conn: sqlite3.Connection) -> None:
    """Writes the pending aggregates into today's rows, drops rows past KEEP_DAYS and logs what is problematic."""
    with _lock:
        batch = dict(_pending)
        _pending.clear()
    today = clock.today().isoformat()
    for (kind, name), stat in batch.items():
        conn.execute(
            "INSERT INTO perf_daily (day, kind, name, count, total_ms, max_ms, slow) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(day, kind, name) DO UPDATE SET count = count + excluded.count, "
            "total_ms = total_ms + excluded.total_ms, max_ms = MAX(max_ms, excluded.max_ms), slow = slow + excluded.slow",
            (today, kind, name, stat.count, stat.total_ms, stat.max_ms, stat.slow),
        )
    conn.execute("DELETE FROM perf_daily WHERE day < date(?, ?)", (today, f"-{KEEP_DAYS} days"))
    conn.commit()
    if batch:
        for problem in _problems(conn, today):
            log.warning("%s", problem)


def summary(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Per kind and name over the last `days` days with a trend against the days before today, worst first."""
    flush(conn)
    today = clock.today().isoformat()
    rows = conn.execute(
        "SELECT kind, name, SUM(count) AS count, SUM(total_ms) AS total_ms, MAX(max_ms) AS max_ms, SUM(slow) AS slow "
        "FROM perf_daily WHERE day >= date(?, ?) GROUP BY kind, name",
        (today, f"-{days - 1} days"),
    ).fetchall()
    result = []
    for r in rows:
        now = conn.execute(
            "SELECT count, total_ms FROM perf_daily WHERE day = ? AND kind = ? AND name = ?", (today, r["kind"], r["name"])
        ).fetchone()
        before = conn.execute(
            "SELECT SUM(count) AS count, SUM(total_ms) AS total_ms FROM perf_daily "
            "WHERE kind = ? AND name = ? AND day < ? AND day >= date(?, '-7 days')",
            (r["kind"], r["name"], today, today),
        ).fetchone()
        trend = "new"
        if before["count"] and now and now["count"]:
            ratio = (now["total_ms"] / now["count"]) / (before["total_ms"] / before["count"])
            trend = "slower" if ratio > 1.3 else "faster" if ratio < 0.7 else "steady"
        result.append(
            {
                "kind": r["kind"],
                "name": r["name"],
                "count": r["count"],
                "average_ms": round(r["total_ms"] / r["count"]),
                "max_ms": round(r["max_ms"]),
                "slow": r["slow"],
                "trend": trend,
            }
        )
    return sorted(result, key=lambda row: (-row["slow"], -row["max_ms"]))


class TimingMiddleware:
    """Times each HTTP request from first byte in to last byte out, under the route's path pattern."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(IGNORED_PATHS):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 0

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                path = getattr(scope.get("route"), "path", None) or "(unmatched)"
                watched = path in WATCHED_ROUTES
                record("request", f"{scope['method']} {path}", (time.perf_counter() - started) * 1000, f"status {status}", always=watched)
            await send(message)

        await self.app(scope, receive, timed_send)


def start_flusher(db_path) -> threading.Event:
    """Background thread that flushes every minute and once more when the returned event is set."""
    from . import db

    stop_event = threading.Event()

    def loop() -> None:
        while True:
            stopping = stop_event.wait(FLUSH_SECONDS)
            try:
                with db.connect(db_path) as conn:
                    flush(conn)
            except Exception:
                log.exception("Could not save timing statistics")
            if stopping:
                return

    threading.Thread(target=loop, daemon=True, name="perf-flush").start()
    return stop_event
