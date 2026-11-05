"""The University module's evaluation: the ways a discipline is evaluated (stored once, on the course sheet, as `eval:<id>` rows of
`university_sheet`), their dated milestones (an event, a task or both, rows of `university_milestones`), the entry criteria of a way and
the grades. Feature notes: curodav-notes/documentation/features/university-module.md.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, time
from typing import Any

from . import clock, db
from .university_plan import TOPIC_KINDS, PlanError, defaults, exam_reminders, _clock, _date, _labels, _now, _put_sheet, _sheet_rows, _tag_item

# ---------------------------------------------------------------- milestones

def _milestone_title(discipline: str, way: str, title: str) -> str:
    return title.strip() or f"{discipline}: {way}".strip(": ")


def _milestone_row(conn: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM university_milestones WHERE uid = ?", (uid,)).fetchone()


def _drop_milestone_items(conn: sqlite3.Connection, row: sqlite3.Row, *, event: bool = True, task: bool = True) -> None:
    if event and row["event_uid"]:
        db.delete_event(conn, row["event_uid"])
    if task and row["task_uid"]:
        db.delete_task(conn, row["task_uid"])


def _save_milestone(conn: sqlite3.Connection, semester_uid: str, discipline: str, way: dict[str, Any], ms: dict[str, Any], position: int) -> str:
    """A milestone is an event on its day (a day you are somewhere), a task due on its deadline (a day you hand something in), or both,
    joined by an exam link; a date creates or moves the item and clearing it removes the item."""
    day, due = _date(ms.get("day"), "Date", False), _date(ms.get("due"), "Deadline", False)
    start = _clock(ms.get("start") or "09:00", "Start time")
    end = _clock(ms.get("end") or _plus_two_hours(start.strftime("%H:%M")), "End time")
    end_day = _date(ms.get("end_day"), "End date", False) or day
    if day and (end_day, end) <= (day, start):
        raise PlanError("The event ends before it starts")
    title = _milestone_title(discipline, way["name"], ms.get("title") or "")
    uid = ms.get("uid") or ""
    old = _milestone_row(conn, uid) if uid else None
    uid = uid if old else str(uuid.uuid4())
    now = _now()
    event_uid, task_uid = (old["event_uid"] if old else None), (old["task_uid"] if old else None)
    if old and not day and event_uid:
        _drop_milestone_items(conn, old, task=False)
        event_uid = None
    if old and not due and task_uid:
        _drop_milestone_items(conn, old, event=False)
        task_uid = None
    if day:
        event_uid = event_uid or str(uuid.uuid4())
        prev = db.get_event(conn, event_uid)
        db.upsert_event(conn, {**(prev or {}), "uid": event_uid, "title": title, "description": ms["description"].strip() if ms.get("description") is not None else (prev or {}).get("description") or "",
                               "start_at": f"{day.isoformat()}T{start.strftime('%H:%M')}", "end_at": f"{end_day.isoformat()}T{end.strftime('%H:%M')}", "all_day": 0,
                               "location": (ms.get("location") or "").strip(), "status": "active", "tags": _labels(conn, discipline),
                               "reminders": (prev or {}).get("reminders") if prev else exam_reminders(conn),
                               "created_at": (prev or {}).get("created_at") or now, "updated_at": now})
        _tag_item(conn, "event", event_uid, discipline)
    if due:
        task_uid = task_uid or str(uuid.uuid4())
        prev = db.get_task(conn, task_uid)
        db.upsert_task(conn, {**(prev or {}), "uid": task_uid, "title": title, "description": ms["description"].strip() if ms.get("description") is not None else (prev or {}).get("description") or "",
                              "due_at": due.isoformat(), "status": (prev or {}).get("status") or "active", "tags": _labels(conn, discipline),
                              "created_at": (prev or {}).get("created_at") or now, "updated_at": now})
        _tag_item(conn, "task", task_uid, discipline)
    if event_uid and task_uid:
        db.add_event_task_relation(conn, event_uid, task_uid, kind="exam")
    conn.execute("INSERT INTO university_milestones (uid, semester_uid, discipline_tag, way_id, title, day, start, end_day, end, location, due, notes, event_uid, task_uid, position) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET discipline_tag = excluded.discipline_tag, way_id = excluded.way_id, "
                 "title = excluded.title, day = excluded.day, start = excluded.start, end_day = excluded.end_day, end = excluded.end, location = excluded.location, due = excluded.due, "
                 "notes = excluded.notes, event_uid = excluded.event_uid, task_uid = excluded.task_uid, position = excluded.position",
                 (uid, semester_uid, discipline, way["id"], (ms.get("title") or "").strip(), day.isoformat() if day else "", start.strftime("%H:%M") if day else "",
                  end_day.isoformat() if day else "", end.strftime("%H:%M") if day else "", (ms.get("location") or "").strip() if day else "", due.isoformat() if due else "", (ms.get("notes") or "").strip(),
                  event_uid, task_uid, position))
    return uid


def list_milestones(conn: sqlite3.Connection, semester_uid: str, discipline: str | None = None, today: date | None = None, way_id: str | None = None) -> list[dict[str, Any]]:
    """Milestones as the pages show them, dated ones first. `date` is the event day or else the deadline; `weight` is the way's share of the grade."""
    today = today or clock.today()
    sql = "SELECT * FROM university_milestones WHERE semester_uid = ?"
    args: list[Any] = [semester_uid]
    if discipline:
        sql += " AND discipline_tag = ? COLLATE NOCASE"
        args.append(discipline)
    if way_id:
        sql += " AND way_id = ?"
        args.append(way_id)
    out, ways = [], {}
    for r in conn.execute(sql + " ORDER BY position", args).fetchall():
        key = r["discipline_tag"].lower()
        if key not in ways:
            ways[key] = {w["id"]: w for w in get_evaluation(conn, semester_uid, r["discipline_tag"], with_milestones=False)}
        way = ways[key].get(r["way_id"]) or {"name": "", "weight": None}
        when = r["day"] or r["due"]
        status = (db.get_task(conn, r["task_uid"]) or {}).get("status") if r["task_uid"] else ""
        out.append({"uid": r["uid"], "discipline": r["discipline_tag"], "way_id": r["way_id"], "way": way["name"], "weight": way["weight"],
                    "title": _milestone_title(r["discipline_tag"], way["name"], r["title"]), "raw_title": r["title"], "day": r["day"], "start": r["start"], "end_day": r["end_day"], "end": r["end"],
                    "location": r["location"], "due": r["due"], "notes": r["notes"], "event_uid": r["event_uid"] or "", "task_uid": r["task_uid"] or "",
                    "date": when, "days_left": (date.fromisoformat(when) - today).days if when else None, "status": status or ""})
    out.sort(key=lambda m: (not m["date"], m["date"], m["start"]))
    return out


def save_item(conn: sqlite3.Connection, semester_uid: str, discipline: str, way_id: str, ms: dict[str, Any]) -> str:
    """Adds or changes one milestone (an event, a task, or both) of a way without touching the way's other items; `description` goes on the event and the task."""
    way = next((w for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False) if w["id"] == way_id), None)
    if not way:
        raise PlanError("That way of evaluating no longer exists")
    if not any(str(ms.get(k) or "").strip() for k in ("title", "day", "due")):
        raise PlanError("Give it a title or a date")
    position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM university_milestones WHERE way_id = ?", (way_id,)).fetchone()[0]
    existing = _milestone_row(conn, ms.get("uid") or "")
    uid = _save_milestone(conn, semester_uid, discipline, way, ms, existing["position"] if existing else position)
    conn.commit()
    return uid


def attach_item(conn: sqlite3.Connection, semester_uid: str, discipline: str, way_id: str, kind: str, uid: str) -> str:
    """Makes an event or a task that already exists a milestone of a way: it gets the discipline's tag and its title and date are then kept on the course sheet."""
    way = next((w for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False) if w["id"] == way_id), None)
    if not way:
        raise PlanError("That way of evaluating no longer exists")
    if conn.execute("SELECT 1 FROM university_milestones WHERE event_uid = ? OR task_uid = ?", (uid, uid)).fetchone():
        raise PlanError("That is already part of a way of evaluating")
    item = db.get_event(conn, uid) if kind == "event" else db.get_task(conn, uid)
    if not item or (kind == "event" and conn.execute("SELECT 1 FROM university_slots WHERE series_uid = ?", (item.get("series_uid"),)).fetchone()):
        raise PlanError("Only a plain event or task can be attached")
    m_uid = str(uuid.uuid4())
    day = (item["start_at"][:10], item["start_at"][11:16], (item.get("end_at") or "")[:10] or item["start_at"][:10], (item.get("end_at") or "")[11:16]) if kind == "event" else ("", "", "", "")
    due = (item.get("due_at") or "")[:10] if kind == "task" else ""
    position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM university_milestones WHERE way_id = ?", (way_id,)).fetchone()[0]
    conn.execute("INSERT INTO university_milestones (uid, semester_uid, discipline_tag, way_id, title, day, start, end_day, end, location, due, notes, event_uid, task_uid, position) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)",
                 (m_uid, semester_uid, discipline, way_id, item["title"], day[0], day[1], day[2], day[3], (item.get("location") or "") if kind == "event" else "", due,
                  uid if kind == "event" else None, uid if kind == "task" else None, position))
    _tag_item(conn, kind, uid, discipline)
    conn.commit()
    return m_uid


def delete_milestone(conn: sqlite3.Connection, uid: str) -> None:
    row = _milestone_row(conn, uid)
    if not row:
        return
    _drop_milestone_items(conn, row)
    conn.execute("DELETE FROM university_milestones WHERE uid = ?", (uid,))
    conn.commit()



def _plus_two_hours(start: str) -> str:
    t = _clock(start, "Start time")
    return time(min(t.hour + 2, 23), t.minute).strftime("%H:%M")


# ---------------------------------------------------------------- ways of evaluating

def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if str(value).strip() else None
    except ValueError:
        return None


def get_evaluation(conn: sqlite3.Connection, semester_uid: str, discipline: str, with_milestones: bool = True) -> list[dict[str, Any]]:
    """The ways a discipline is evaluated: each has a name and a weight in percent of the whole, may have components whose weights are percent
    of their way (`subs`), and may have dated milestones. `effective` is the share of the whole grade; a component's is its weight times its way's."""
    out = []
    for key, row in _sheet_rows(conn, semester_uid, discipline).items():
        if not key.startswith("eval:"):
            continue
        try:
            data = json.loads(row["value"] or "{}")
        except ValueError:
            data = {}
        weight = _num(data.get("weight"))
        elimination = bool(data.get("elimination"))
        comp = {"id": data.get("id") or key[5:], "name": row["label"], "form": data.get("form", ""), "weight": None if elimination else weight,
                "stored_weight": weight, "elimination": elimination, "notes": data.get("notes", ""), "effective": None if elimination else weight,
                "criteria": data.get("criteria", ""), "min_grade": _num(data.get("min_grade")), "note_uids": [u for u in data.get("note_uids", []) if u], "conditions": [c for c in data.get("conditions", []) if c.get("kind") in CONDITION_KINDS],
                "subs": [], "milestones": []}
        for sub in data.get("subs", []):
            w = _num(sub.get("weight"))
            comp["subs"].append({"id": sub.get("id") or "", "name": sub.get("name", ""), "weight": w, "parent": comp["id"],
                                 "effective": round(weight * w / 100, 4) if comp["weight"] is not None and w is not None else None})
        out.append(comp)
    out.sort(key=lambda c: (c["elimination"], -(c["stored_weight"] or 0)))
    if with_milestones and out:
        by_way: dict[str, list[dict[str, Any]]] = {}
        for m in list_milestones(conn, semester_uid, discipline):
            by_way.setdefault(m["way_id"], []).append(m)
        for comp in out:
            comp["milestones"] = by_way.get(comp["id"], [])
    return out


def evaluation_warnings(components: list[dict[str, Any]]) -> list[str]:
    """What does not add up: the weights of the whole should reach 100, and the components of one way should reach 100 of it."""
    notes = []
    weights = [c["weight"] for c in components if c["weight"] is not None]
    if weights and abs(sum(weights) - 100) > 0.01:
        notes.append(f"The evaluation weights add up to {sum(weights):g}%, not 100%")
    for c in components:
        subs = [s["weight"] for s in c["subs"] if s["weight"] is not None]
        if subs and abs(sum(subs) - 100) > 0.01:
            notes.append(f"The components of {c['name'] or 'a way of evaluating'} add up to {sum(subs):g}%, not 100%")
    return notes


EVALUATION_TONES = {"Exam": "red", "Colloquium": "red", "Oral": "red", "Practical": "red", "Continuous assessment": "orange", "Project": "blue", "Homework": "blue"}
EVALUATION_FORMS = ("Exam", "Colloquium", "Continuous assessment", "Project", "Homework", "Oral", "Practical", "Other")
# What a type of evaluation usually needs: a day you are somewhere (an event), a day you hand something in (a task), or neither until asked.
FORM_ITEMS = {"Exam": "event", "Colloquium": "event", "Oral": "event", "Practical": "event", "Project": "task", "Homework": "task", "Continuous assessment": "both"}


def save_evaluation(conn: sqlite3.Connection, semester_uid: str, discipline: str, components: list[dict[str, Any]]) -> list[str]:
    """Replaces the ways of evaluating with the given ones ({id, name, weight, subs: [{id, name, weight}], milestones: [{uid, title, day, start, end,
    location, due, notes}]}). Ids that were sent are kept; a way with no name is dropped. A way or milestone that is no longer sent is removed with its
    events and tasks. Returns the warnings, which the user may keep: weights
    that do not add up, and what was removed."""
    sent = {c.get("id") for c in components if c.get("id")}
    removed = 0
    for old in get_evaluation(conn, semester_uid, discipline, with_milestones=False):
        if old["id"] not in sent:
            for m in list_milestones(conn, semester_uid, discipline, way_id=old["id"]):
                delete_milestone(conn, m["uid"])
                removed += 1
    conn.execute("DELETE FROM university_sheet WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND key LIKE 'eval:%'", (semester_uid, discipline))
    n = 0
    plans = []
    for comp in components:
        name = (comp.get("name") or "").strip()
        if not name:
            continue
        if str(comp.get("weight") or "").strip() and _num(comp.get("weight")) is None:
            conn.rollback()
            raise PlanError(f"Weight of {name} must be a number")
        subs = []
        for sub in comp.get("subs", []):
            if (sub.get("name") or "").strip():
                if str(sub.get("weight") or "").strip() and _num(sub.get("weight")) is None:
                    conn.rollback()
                    raise PlanError(f"Weight of {sub['name']} must be a number")
                subs.append({"id": sub.get("id") or uuid.uuid4().hex[:8], "name": sub["name"].strip(), "weight": str(sub.get("weight") or "").strip()})
        min_grade = str(comp.get("min_grade") or "").strip()
        if min_grade and _num(min_grade) is None:
            conn.rollback()
            raise PlanError(f"The minimum grade of {name} must be a number")
        n += 1
        cid = comp.get("id") or uuid.uuid4().hex[:8]
        _put_sheet(conn, semester_uid, discipline, f"eval:{cid}", name, json.dumps({"id": cid, "form": (comp.get("form") or "").strip(), "weight": str(comp.get("weight") or "").strip(), "subs": subs,
                                                                                                     "elimination": bool(comp.get("elimination")), "notes": (comp.get("notes") or "").strip(),
                                                                                                     "criteria": (comp.get("criteria") or "").strip(), "min_grade": min_grade,
                                                                                                     "note_uids": [u for u in (comp.get("note_uids") or []) if u],
                                                                                                     "conditions": _clean_conditions(comp.get("conditions") or [])}), 200 + n)
        plans.append(({"id": cid, "name": name}, comp.get("milestones")))
    for way, milestones in plans:
        if milestones is None:
            continue
        keep = {m.get("uid") for m in milestones if m.get("uid")}
        for old in list_milestones(conn, semester_uid, discipline, way_id=way["id"]):
            if old["uid"] not in keep:
                delete_milestone(conn, old["uid"])
                removed += 1
        for i, ms in enumerate(milestones):
            if any(str(ms.get(k) or "").strip() for k in ("title", "day", "due", "notes")):
                _save_milestone(conn, semester_uid, discipline, way, ms, i)
    conn.commit()
    notes = evaluation_warnings(get_evaluation(conn, semester_uid, discipline, with_milestones=False))
    if removed:
        notes.append(f"{removed} milestone{'s' if removed != 1 else ''} removed with {'its' if removed == 1 else 'their'} events and tasks")
    return notes


def _ways_as_input(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> list[dict[str, Any]]:
    fmt = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
    return [{"id": w["id"], "name": w["name"], "form": w["form"], "weight": fmt(w["stored_weight"]), "elimination": w["elimination"], "notes": w["notes"], "criteria": w["criteria"],
             "min_grade": fmt(w["min_grade"]), "note_uids": w["note_uids"], "conditions": w["conditions"], "subs": [{**x, "weight": fmt(x["weight"])} for x in w["subs"]]}
            for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False)]


def save_way(conn: sqlite3.Connection, semester_uid: str, discipline: str, way: dict[str, Any]) -> list[str]:
    """Adds a way of evaluating, or replaces the one with the same id in its place; the other ways and their milestones are left as they are."""
    ways = _ways_as_input(conn, semester_uid, discipline)
    if way.get("id") and any(w["id"] == way["id"] for w in ways):
        ways = [way if w["id"] == way["id"] else w for w in ways]
    else:
        ways.append(way)
    return save_evaluation(conn, semester_uid, discipline, ways)


def delete_way(conn: sqlite3.Connection, semester_uid: str, discipline: str, way_id: str) -> list[str]:
    return save_evaluation(conn, semester_uid, discipline, [w for w in _ways_as_input(conn, semester_uid, discipline) if w["id"] != way_id])


# ---------------------------------------------------------------- entry conditions and grades

CONDITION_KINDS = {"attendance": "Attendance within the limit", "grade": "Minimum grade", "done": "Handed in", "other": "Other"}


def _clean_conditions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A condition is a kind and a target (a class kind, a way or component id, a milestone uid) with a value: the minimum grade, or the
    words of an Other condition. An Other condition is ticked by hand, so it keeps `met`."""
    out = []
    for row in rows:
        kind, target, value = row.get("kind") or "", (row.get("target") or "").strip(), (row.get("value") or "").strip()
        if kind not in CONDITION_KINDS or (kind == "other" and not value) or (kind != "other" and not target):
            continue
        if kind == "grade" and _num(value) is None:
            raise PlanError("A minimum grade condition needs a number")
        out.append({"id": row.get("id") or uuid.uuid4().hex[:8], "kind": kind, "target": target, "value": value, "met": bool(row.get("met"))})
    return out


def passing_grade(conn: sqlite3.Connection, semester_uid: str | None = None, discipline: str | None = None) -> float:
    """The grade that passes: the one set for the discipline on its course sheet, else the app's default."""
    if semester_uid and discipline:
        own = _num((_sheet_rows(conn, semester_uid, discipline).get("passing") or {}).get("value"))
        if own:
            return own
    return _num(defaults(conn)["passing_grade"]) or 5.0


def get_grades(conn: sqlite3.Connection, semester_uid: str, discipline: str) -> dict[str, float]:
    rows = conn.execute("SELECT item_id, grade FROM university_grades WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE", (semester_uid, discipline))
    return {r["item_id"]: r["grade"] for r in rows}


def set_grades(conn: sqlite3.Connection, semester_uid: str, discipline: str, grades: dict[str, str]) -> None:
    """Saves the grades typed for ways and components; an empty value clears the grade."""
    known = {w["id"] for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False)}
    known |= {s["id"] for w in get_evaluation(conn, semester_uid, discipline, with_milestones=False) for s in w["subs"]}
    for item_id, raw in grades.items():
        if item_id not in known:
            continue
        value = _num(raw)
        if str(raw or "").strip() and value is None:
            raise PlanError("A grade must be a number")
        if value is None:
            conn.execute("DELETE FROM university_grades WHERE semester_uid = ? AND discipline_tag = ? COLLATE NOCASE AND item_id = ?", (semester_uid, discipline, item_id))
        else:
            conn.execute("INSERT INTO university_grades (semester_uid, discipline_tag, item_id, grade, updated_at) VALUES (?, ?, ?, ?, ?) "
                         "ON CONFLICT(semester_uid, discipline_tag, item_id) DO UPDATE SET grade = excluded.grade, updated_at = excluded.updated_at",
                         (semester_uid, discipline, item_id, value, _now()))
    conn.commit()


def set_minimums(conn: sqlite3.Connection, semester_uid: str, discipline: str, minimums: dict[str, str]) -> None:
    """The lowest grade that counts as passed on each way of evaluating; an empty value goes back to the course's passing grade."""
    ways = _ways_as_input(conn, semester_uid, discipline)
    for w in ways:
        if w["id"] in minimums and not w["elimination"]:
            w["min_grade"] = str(minimums[w["id"]] or "").strip()
    save_evaluation(conn, semester_uid, discipline, ways)


def tick_condition(conn: sqlite3.Connection, semester_uid: str, discipline: str, way_id: str, condition_id: str, met: bool) -> None:
    """Ticks or unticks an Other condition, the only kind that is not worked out from the data."""
    ways = _ways_as_input(conn, semester_uid, discipline)
    for w in ways:
        if w["id"] == way_id:
            for c in w["conditions"]:
                if c["id"] == condition_id and c["kind"] == "other":
                    c["met"] = met
    save_evaluation(conn, semester_uid, discipline, ways)


def _way_grade(way: dict[str, Any], grades: dict[str, float]) -> float | None:
    """The grade of a way: its own, or else the weighted mean of its components once every weighted component has one."""
    if way["id"] in grades:
        return grades[way["id"]]
    weighted = [s for s in way["subs"] if s["weight"]]
    if weighted and all(s["id"] in grades for s in weighted):
        total = sum(s["weight"] for s in weighted)
        return round(sum(grades[s["id"]] * s["weight"] for s in weighted) / total, 2)
    return None


def standing(conn: sqlite3.Connection, semester_uid: str, discipline: str, today: date | None = None) -> dict[str, Any]:
    """Where a discipline stands: each way with its grade, whether it reaches its minimum and whether its conditions are met (True, False,
    or None while it cannot be known yet), and the final grade once every weighted way has a grade (`so_far` until then)."""
    from . import university_attendance as ua

    today = today or clock.today()
    passing = passing_grade(conn, semester_uid, discipline)
    ways = get_evaluation(conn, semester_uid, discipline)
    grades = get_grades(conn, semester_uid, discipline)
    attendance = {k["kind"]: k for k in ua.discipline_attendance(conn, semester_uid, discipline, today)["kinds"]}
    names = {w["id"]: w["name"] for w in ways} | {s["id"]: f"{w['name']}: {s['name']}" for w in ways for s in w["subs"]}
    milestones = {m["uid"]: m for w in ways for m in w["milestones"]}
    for w in ways:
        w["grade"] = _way_grade(w, grades)
        for s in w["subs"]:
            s["grade"] = grades.get(s["id"])
        w["minimum"] = None if w["elimination"] else (w["min_grade"] if w["min_grade"] is not None else passing)
        if w["elimination"]:
            w["passed"] = w["grade"] is not None and w["grade"] >= 1  # an elimination way is failed until it is passed
        else:
            w["passed"] = None if w["grade"] is None else w["grade"] >= w["minimum"]
        rows = []
        for c in w["conditions"]:
            if c["kind"] == "attendance":
                k = attendance.get(c["target"])
                label, met = f"{CONDITION_KINDS['attendance']}: {TOPIC_KINDS.get(c['target'], c['target']).lower()}", (None if not k or k["limit"] is None else not k["over"])
            elif c["kind"] == "grade":
                value = (grades.get(c["target"]) if c["target"] in grades else _way_grade(next((x for x in ways if x["id"] == c["target"]), {"id": "", "subs": []}), grades))
                label, met = f"At least {c['value']} on {names.get(c['target'], 'a removed part')}", (None if value is None else value >= (_num(c["value"]) or 0))
            elif c["kind"] == "done":
                m = milestones.get(c["target"])
                label, met = f"{CONDITION_KINDS['done']}: {m['title'] if m else 'a removed task'}", (m["status"] == "done" if m and m["task_uid"] else None)
            else:
                label, met = c["value"], c["met"]
            rows.append({**c, "label": label, "is_met": met})
        w["condition_rows"] = rows
        w["eligible"] = False if any(r["is_met"] is False for r in rows) else (True if rows and all(r["is_met"] for r in rows) else None)
    weighted = [w for w in ways if w["weight"]]
    graded = [w for w in weighted if w["grade"] is not None]
    final = round(sum(w["grade"] * w["weight"] for w in weighted) / sum(w["weight"] for w in weighted), 2) if weighted and len(graded) == len(weighted) else None
    so_far = round(sum(w["grade"] * w["weight"] for w in graded) / sum(w["weight"] for w in graded), 2) if graded and final is None else None
    failed_minimum = any(w["passed"] is False for w in ways)
    return {"ways": ways, "final": final, "so_far": so_far, "passing": passing, "graded": len(graded), "weighted": len(weighted),
            "passed": None if final is None else (final >= passing and not failed_minimum), "warnings": evaluation_warnings(ways)}
