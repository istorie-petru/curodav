"""What the window of an event or a task says when the University module is behind it: for a class, its attendance, what it covers and what
comes next; for an exam or one of its steps, the whole way of evaluating. The module never writes this into the description."""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import quote

from . import clock, db
from . import university_attendance as ua
from . import university_evaluation as ue
from . import university_plan as up


def _milestone_of(conn: sqlite3.Connection, column: str, uid: str) -> sqlite3.Row | None:
    sql = "SELECT * FROM university_milestones WHERE event_uid = ?" if column == "event_uid" else "SELECT * FROM university_milestones WHERE task_uid = ?"
    return conn.execute(sql, (uid,)).fetchone()


def _exam(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """The way of evaluating that a milestone belongs to: its weight, its other steps with dates, and whether its conditions are met."""
    today = clock.today()
    standing = ue.standing(conn, row["semester_uid"], row["discipline_tag"], today)
    way = next((w for w in standing["ways"] if w["id"] == row["way_id"]), None)
    if not way:
        return {"kind": "exam", "edit_url": "", "discipline": row["discipline_tag"], "way": "", "steps": [], "conditions": []}
    steps = []
    for m in way["milestones"]:
        link = f"/events/{m['event_uid']}" if m.get("event_uid") else (f"/tasks/{m['task_uid']}" if m.get("task_uid") else "")
        steps.append({"title": m["title"], "date": m.get("date") or "", "start": m.get("start") or "", "done": m.get("status") == "done", "url": link,
                      "here": m["uid"] == row["uid"] if m.get("uid") else False})
    return {"kind": "exam", "edit_url": f"/settings/university/evaluation/{row['way_id']}/edit?discipline={quote(row['discipline_tag'], safe='')}", "discipline": row["discipline_tag"], "way": way["name"], "form": way.get("form") or "", "weight": way.get("weight"),
            "elimination": way.get("elimination"), "min_grade": way.get("min_grade"), "grade": way.get("grade"), "steps": steps,
            "conditions": [{"label": c["label"], "state": c["is_met"]} for c in way.get("condition_rows", [])], "criteria": way.get("criteria") or ""}


def for_event(conn: sqlite3.Connection, event: dict[str, Any]) -> dict[str, Any] | None:
    """A class of the semester, an exam event of a way of evaluating, or None."""
    attendance = ua.for_event(conn, event)
    if attendance:
        links = up.class_links(conn, event["uid"])
        slot = conn.execute("SELECT semester_uid, kind FROM university_slots WHERE series_uid = ?", (event.get("series_uid"),)).fetchone()
        today = event["start_at"][:10]
        upcoming = []
        for c in up.list_classes(conn, slot["semester_uid"], attendance["discipline"], clock.today()):
            if c["date"] > today and not upcoming:
                topics = [f"{t['number']}. {t['title']}" for t in up.class_links(conn, c["uid"])["topics"]]
                upcoming.append({"uid": c["uid"], "date": c["date"], "start": c["start"], "label": f"{c['kind_label']} {c['number']}", "topic": "; ".join(topics)})
        return {"kind": "class", "edit_url": f"/university/class/{event['uid']}/content", "attendance": attendance, "topics": [f"{t['number']}. {t['title']}" for t in links["topics"]],
                "competences": [f"{c['number']}. {c['title']}" for c in links["competences"]], "upcoming": upcoming, "composed": up.composed_text(conn, event["uid"])}
    row = _milestone_of(conn, "event_uid", event["uid"])
    return _exam(conn, row) if row else None


def for_task(conn: sqlite3.Connection, task: dict[str, Any]) -> dict[str, Any] | None:
    """A step of a way of evaluating, or None."""
    row = _milestone_of(conn, "task_uid", task["uid"])
    return _exam(conn, row) if row else None


def can_attach(conn: sqlite3.Connection) -> bool:
    """Whether the current semester has a way of evaluating an event or task could be attached to (for a plain event or task whose window offers it)."""
    semester = up.current_semester(conn)
    return bool(semester and conn.execute("SELECT 1 FROM university_sheet WHERE semester_uid = ? AND key LIKE 'eval:%' LIMIT 1", (semester["uid"],)).fetchone())
