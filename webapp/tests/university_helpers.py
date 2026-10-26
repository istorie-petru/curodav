"""Shared builders for the University tests."""

from src import university_plan as up


def _as_input(way: dict) -> dict:
    fmt = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
    return {"id": way["id"], "name": way["name"], "weight": fmt(way["weight"]),
            "subs": [{"id": s["id"], "name": s["name"], "weight": fmt(s["weight"])} for s in way["subs"]]}


def add_exam(conn, sem, *, title="Final", day="2027-01-20", start="09:00", end="11:00", weight="", location="", discipline="Biology", due=None) -> str:
    """Adds a way of evaluating named after the exam with one milestone: an event on `day` and a task due on `due` (default the same day).
    Returns the milestone's task uid."""
    ways = [_as_input(w) for w in up.get_evaluation(conn, sem["uid"], discipline, with_milestones=False)]
    ways.append({"id": "", "name": title or "Exam", "weight": weight, "subs": [], "milestones": [
        {"title": title, "day": day, "start": start, "end": end, "location": location, "due": day if due is None else due}]})
    up.save_evaluation(conn, sem["uid"], discipline, [dict(w, milestones=None) if w["id"] else w for w in ways])
    return up.list_milestones(conn, sem["uid"], discipline)[-1]["task_uid"]
