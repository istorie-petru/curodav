"""Seeding helpers shared by the dashboard tests."""

from __future__ import annotations

from datetime import datetime, timezone

from src import db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_task(conn, uid, due_at=None, tags=None, status="active"):
    db.upsert_task(conn, {
        "uid": uid,
        "title": uid, "description": "", "status": status, "due_at": due_at,
        "tags": tags or [], "created_at": now_iso(),
    })


def set_completed_at(conn, uid, moment: datetime):
    """Place a task's completion at a known moment (completing stamps the real clock)."""
    conn.execute("UPDATE tasks SET completed_at = ? WHERE uid = ?", (moment.isoformat(), uid))
    conn.commit()


def seed_event(conn, uid, start_at=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": "active", "all_day": 0, "start_at": start_at,
        "tags": tags or [], "created_at": now_iso(),
    })


def seed_recurring_event(conn, uid, start_at, end_at=None, recurrence=None, tags=None):
    db.upsert_event(conn, {
        "uid": uid, "title": uid,
        "description": "", "status": "active", "all_day": 0,
        "start_at": start_at, "end_at": end_at, "recurrence": recurrence,
        "tags": tags or [], "created_at": now_iso(),
    })
