"""The University edits shared by the REST API and the MCP server, so a course sheet can be filled from a document.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Each function calls the same domain code as the University windows (`university_plan`, `university_evaluation`), so the
same checks apply and the app shows the result exactly as if it had been typed. A refused input raises
`api_write.EditError` with the domain's own message.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import api_service
from .api_write import EditError

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _plan():
    from . import university_plan

    return university_plan


def _colors() -> list[str]:
    from .routers.labels import COLORS

    return COLORS


def _semester(conn: sqlite3.Connection, uid: str = "") -> dict[str, Any]:
    try:
        semester = api_service._semester(conn, uid)
    except api_service.NotFound:
        raise EditError("not_found", f"No semester {uid}") from None
    if semester is None:
        raise EditError("not_found", "There is no semester yet; save one first")
    return semester


def _discipline(conn: sqlite3.Connection, semester: dict[str, Any], name: str) -> str:
    found = next((d["name"] for d in _plan().disciplines(conn, semester) if d["name"].lower() == (name or "").strip().lower()), None)
    if found is None:
        raise EditError("not_found", f"No discipline named {name} in {semester['name']}")
    return found


def _run(fn, *args, **kwargs):
    from .university_plan import PlanError

    try:
        return fn(*args, **kwargs)
    except PlanError as exc:
        raise EditError("invalid", str(exc)) from None


def save_semester(conn: sqlite3.Connection, *, name: str, start_date: str = "", end_date: str = "", class_end_date: str = "",
                  uid: str = "") -> dict[str, Any]:
    """Creates a semester, or changes the dates and name of the one with `uid`."""
    old = _semester(conn, uid) if uid else None
    saved = _run(_plan().save_semester, conn, uid=uid or None, name=name, shelf_name=old["shelf_name"] if old else "",
                 start_date=start_date, end_date=end_date, class_end_date=class_end_date)
    return {"semester_uid": saved}


def save_discipline(conn: sqlite3.Connection, *, name: str, old_name: str = "", color: str = "", icon: str = "",
                    semester_uid: str = "") -> dict[str, Any]:
    """Adds a discipline (an unused colour and an abbreviation are picked when none is given) or renames and restyles one."""
    semester, up = _semester(conn, semester_uid), _plan()
    if color and color not in _colors():
        raise EditError("invalid", f"color must be one of {', '.join(_colors())}")
    if old_name:
        current = _discipline(conn, semester, old_name)
        look = next(d for d in up.disciplines(conn, semester) if d["name"] == current)
        saved = _run(up.save_discipline, conn, semester, old=current, name=name, color=color or look.get("color") or "gray",
                     icon=icon or look.get("icon") or "", teacher_names=None, colors=_colors())
    elif color or icon:
        saved = _run(up.save_discipline, conn, semester, old="", name=name, color=color or "blue", icon=icon or "book-open",
                     teacher_names=None, colors=_colors())
    else:
        saved = _run(up.quick_discipline, conn, semester, name, _colors())
    return {"discipline": saved}


def set_course_sheet(conn: sqlite3.Connection, *, discipline: str, fields: dict[str, Any] | None = None,
                     extra: list[dict[str, Any]] | None = None, semester_uid: str = "") -> dict[str, Any]:
    """Fills fixed course sheet fields by key, and with `extra` replaces the fields of one's own ({section, label, value})."""
    semester, up = _semester(conn, semester_uid), _plan()
    name = _discipline(conn, semester, discipline)
    known = dict(up.SHEET_FIELDS)
    values = {k: str(v if v is not None else "") for k, v in (fields or {}).items()}
    unknown = [k for k in values if k not in known]
    if unknown:
        raise EditError("invalid", f"unknown course sheet fields: {', '.join(unknown)}; known: {', '.join(known)}")
    custom = None
    if extra is not None:
        custom = [(str(r.get("section") or "identification"), str(r.get("label") or ""), str(r.get("value") or "")) for r in extra]
    _run(up.save_sheet, conn, semester["uid"], name, values, custom)
    return {"discipline": name, "sheet": up.get_sheet(conn, semester["uid"], name)["values"]}


def set_teachers(conn: sqlite3.Connection, *, discipline: str, lecture: list[str] | None = None, seminar: list[str] | None = None,
                 semester_uid: str = "") -> dict[str, Any]:
    """The people who teach lectures and seminars or labs, by name; a name no contact has becomes a new contact."""
    semester, up = _semester(conn, semester_uid), _plan()
    name = _discipline(conn, semester, discipline)
    sheet = up.get_sheet(conn, semester["uid"], name)
    keep = lambda people: [p["uid"] for p in people]  # noqa: E731
    _run(up.set_teachers, conn, semester["uid"], name, keep(sheet["lecture_teachers"]) if lecture is None else lecture,
         keep(sheet["seminar_teachers"]) if seminar is None else seminar)
    sheet = up.get_sheet(conn, semester["uid"], name)
    return {"discipline": name, "lecture": [p["name"] for p in sheet["lecture_teachers"]], "seminar": [p["name"] for p in sheet["seminar_teachers"]]}


def save_class_slot(conn: sqlite3.Connection, *, discipline: str, weekday: str, start: str, end: str, kind: str = "lecture",
                    weeks: str = "all", room: str = "", series_uid: str = "", semester_uid: str = "") -> dict[str, Any]:
    """Adds a weekly class to the timetable (its classes are created up to the class end date), or changes the slot `series_uid`."""
    semester, up = _semester(conn, semester_uid), _plan()
    name = _discipline(conn, semester, discipline)
    day = (weekday or "").strip().lower()
    if day not in WEEKDAYS:
        raise EditError("invalid", "weekday must be a day name, such as Monday")
    slot = {"weekday": WEEKDAYS.index(day), "start": start, "end": end, "kind": kind, "weeks": weeks, "room": room}
    saved = _run(up.save_slot, conn, semester, name, slot, series_uid or None)
    return {"discipline": name, "series_uid": saved}


def save_evaluation_way(conn: sqlite3.Connection, *, discipline: str, way: dict[str, Any], semester_uid: str = "") -> dict[str, Any]:
    """Adds a way of evaluating (or replaces the one with the same id) with its weight, conditions and exams; the others stay."""
    from . import university_evaluation as ue

    semester = _semester(conn, semester_uid)
    name = _discipline(conn, semester, discipline)
    if not str(way.get("name") or "").strip():
        raise EditError("invalid", "a way of evaluating needs a name")
    exams = way.get("exams")
    milestones = None if exams is None else [
        {k: str(e.get(k) or "") for k in ("uid", "title", "day", "start", "end", "location", "due", "notes")} for e in exams]
    item = {"id": str(way.get("id") or ""), "name": str(way["name"]), "form": str(way.get("form") or ""),
            "weight": str(way.get("weight") if way.get("weight") is not None else ""), "elimination": bool(way.get("elimination")),
            "notes": str(way.get("notes") or ""), "criteria": str(way.get("criteria") or ""),
            "min_grade": str(way.get("min_grade") if way.get("min_grade") is not None else ""),
            "subs": [{"id": str(x.get("id") or ""), "name": str(x.get("name") or ""), "weight": str(x.get("weight") or "")}
                     for x in way.get("parts") or []],
            "milestones": milestones}
    if item["id"]:
        current = next((w for w in ue.get_evaluation(conn, semester["uid"], name, with_milestones=False) if w["id"] == item["id"]), None)
        if current is None:
            raise EditError("not_found", f"No way of evaluating with id {item['id']}")
        item["conditions"] = current["conditions"]
    warnings = _run(ue.save_way, conn, semester["uid"], name, item)
    return {"discipline": name, "warnings": warnings,
            "evaluation": api_service.get_discipline(conn, name, semester_uid=semester["uid"])["evaluation"]}


def save_reading(conn: sqlite3.Connection, *, discipline: str, title: str = "", author: str = "", citation_uid: str = "",
                 locator: str = "", category: str = "recommended", due: str = "", notes: str = "", task_uid: str = "",
                 semester_uid: str = "") -> dict[str, Any]:
    """A reading of the discipline: a library entry (citation_uid) or a typed title and author, with pages and a category."""
    semester, up = _semester(conn, semester_uid), _plan()
    name = _discipline(conn, semester, discipline)
    uid = _run(up.save_reading, conn, semester, name, task_uid=task_uid or None, title=title, author=author, due=due,
               citation_id=citation_uid, locator=locator, category=category, notes=notes)
    return {"discipline": name, "task_uid": uid}


def save_homework(conn: sqlite3.Connection, *, discipline: str, title: str, due: str = "", status: str = "active", task_uid: str = "",
                  semester_uid: str = "") -> dict[str, Any]:
    semester, up = _semester(conn, semester_uid), _plan()
    name = _discipline(conn, semester, discipline)
    uid = _run(up.save_homework, conn, semester, name, task_uid=task_uid or None, title=title, due=due, status=status or "active")
    return {"discipline": name, "task_uid": uid}
