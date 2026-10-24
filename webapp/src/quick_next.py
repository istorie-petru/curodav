"""Rows for the "What's next" column of the New modal: what comes up soon when the search box is empty, or the
matches for a typed search. Pure and clock-free; the router passes today's date and the already scoped items."""

from datetime import date, timedelta

CURATED_DAYS = 14
LIMIT = 12


def _day(value: str | None) -> str:
    return (value or "")[:10]


def task_row(task: dict, overdue: bool = False) -> dict:
    return {"kind": "task", "uid": task["uid"], "title": task["title"], "url": f"/tasks/{task['uid']}",
            "date": task.get("due_at"), "all_day": len(task.get("due_at") or "") <= 10, "tags": task.get("tags") or [], "tag_items": task.get("tag_items") or [],
            "done": task.get("status") == "done", "overdue": overdue}


def event_row(event: dict) -> dict:
    url = f"/events/{event['uid']}"
    if event.get("recurrence") and event.get("occurrence_date"):
        url += "?occurrence_date=" + event["occurrence_date"]
    return {"kind": "event", "uid": event["uid"], "title": event["title"], "url": url, "date": event.get("start_at"),
            "all_day": bool(event.get("all_day")), "tags": event.get("tags") or [], "tag_items": event.get("tag_items") or [], "done": False, "overdue": False}


def contact_row(contact: dict) -> dict:
    return {"kind": "contact", "uid": contact["uid"], "title": contact.get("name") or contact.get("title") or "",
            "url": f"/contacts/{contact['uid']}", "date": None, "all_day": True, "tags": contact.get("tags") or [], "tag_items": contact.get("tag_items") or [],
            "done": False, "overdue": False}


def curated(today: date, tasks: list[dict], events: list[dict]) -> list[dict]:
    """Open tasks due within CURATED_DAYS (overdue first) and events in the same window, by date."""
    today_iso = today.isoformat()
    end_iso = (today + timedelta(days=CURATED_DAYS)).isoformat()
    rows = [
        task_row(t, overdue=_day(t["due_at"]) < today_iso)
        for t in tasks
        if t.get("due_at") and t.get("status") not in ("done", "archived") and _day(t["due_at"]) <= end_iso
    ]
    rows += [event_row(e) for e in events if today_iso <= _day(e.get("start_at")) <= end_iso]
    rows.sort(key=lambda r: (r["date"] or "", r["title"]))
    return rows[:LIMIT]


def from_search(hits: list[dict]) -> list[dict]:
    rows = []
    for hit in hits:
        entity = hit["entity"]
        if hit["type"] == "task":
            rows.append(task_row(entity))
        elif hit["type"] == "event":
            rows.append(event_row(entity))
        elif hit["type"] == "contact":
            rows.append(contact_row({**entity, "name": hit["title"]}))
    return rows
