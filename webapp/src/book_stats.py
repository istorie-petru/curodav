"""Reading statistics: time spent in the reader, progress made, books started and finished, and reading streaks.

Only the numbers are here (no goals, which belong with the habits feature). The reader reports time in small beats while a book
is open and in use; progress comes from the daily progress log and the finished dates the library already keeps.
Feature document: curodav-notes/documentation/features/media.md
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

MAX_BEAT = 120  # seconds one report may add, so a forgotten tab cannot pile up time


def add_time(conn: sqlite3.Connection, citation_uid: str, day: str, seconds: int) -> int:
    """Adds reading time to a book's day; returns the day's total. Reports over MAX_BEAT seconds are cut to it."""
    seconds = max(0, min(int(seconds), MAX_BEAT))
    if not seconds:
        return 0
    conn.execute("INSERT INTO book_reading_time (citation_uid, day, seconds) VALUES (?, ?, ?) "
                 "ON CONFLICT(citation_uid, day) DO UPDATE SET seconds = seconds + excluded.seconds", (citation_uid, day, seconds))
    conn.commit()
    return conn.execute("SELECT seconds FROM book_reading_time WHERE citation_uid = ? AND day = ?", (citation_uid, day)).fetchone()[0]


def period(name: str, today: date) -> tuple[date, date]:
    """The first and last day of "week" (Monday to Sunday), "month", "year" or "all" around `today`."""
    if name == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if name == "month":
        start = today.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1)
    if name == "year":
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    return date(1970, 1, 1), today


def _streaks(days: set[str], today: date) -> dict[str, int]:
    """The run of days ending today (or yesterday, when today has nothing yet) and the longest run in `days`."""
    longest = run = 0
    prev: date | None = None
    for d in sorted(date.fromisoformat(x) for x in days):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    current = 0
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    while cursor.isoformat() in days:
        current += 1
        cursor -= timedelta(days=1)
    return {"current": current, "longest": longest}


def stats(conn: sqlite3.Connection, start: date, end: date, today: date | None = None) -> dict[str, Any]:
    """Totals and per-day figures for the days from `start` to `end`:
    seconds read, progress made, days read, books read, books finished and started, the busiest books, and the streaks."""
    today = today or date.today()
    lo, hi = start.isoformat(), end.isoformat()
    time_rows = conn.execute("SELECT day, SUM(seconds) AS s FROM book_reading_time WHERE day BETWEEN ? AND ? GROUP BY day", (lo, hi)).fetchall()
    progress_rows = conn.execute("SELECT day, SUM(delta) AS d FROM media_progress_log WHERE day BETWEEN ? AND ? AND delta > 0 GROUP BY day", (lo, hi)).fetchall()
    seconds = {r["day"]: r["s"] for r in time_rows}
    progress = {r["day"]: r["d"] for r in progress_rows}
    days = sorted(set(seconds) | set(progress))
    per_day = [{"day": d, "seconds": seconds.get(d, 0), "progress": progress.get(d, 0)} for d in days]
    books = conn.execute(
        "SELECT t.citation_uid AS uid, c.title AS title, c.type AS type, SUM(t.seconds) AS seconds FROM book_reading_time t "
        "JOIN citations c ON c.uid = t.citation_uid WHERE t.day BETWEEN ? AND ? GROUP BY t.citation_uid ORDER BY seconds DESC LIMIT 10", (lo, hi)).fetchall()
    finished = conn.execute("SELECT type, count(*) AS n FROM citations WHERE status = 'finished' AND finished_on BETWEEN ? AND ? GROUP BY type", (lo, hi)).fetchall()
    started = conn.execute("SELECT count(*) FROM citations WHERE started_on BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
    books_read = conn.execute("SELECT count(DISTINCT citation_uid) FROM book_reading_time WHERE day BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
    all_days = {r[0] for r in conn.execute("SELECT day FROM book_reading_time UNION SELECT day FROM media_progress_log WHERE delta > 0")}
    total = sum(seconds.values())
    return {
        "from": lo, "to": hi,
        "seconds": total, "progress": sum(progress.values()), "days_read": len(days), "books_read": books_read,
        "average_seconds_per_day_read": round(total / len(days)) if days else 0,
        "finished": {"total": sum(r["n"] for r in finished), "by_kind": {r["type"]: r["n"] for r in finished}},
        "started": started,
        "top_books": [dict(b) for b in books],
        "per_day": per_day,
        "streak": _streaks(all_days, today),
    }
