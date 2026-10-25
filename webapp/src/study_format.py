"""The versioned JSON format of the University module: export and import of a discipline or a whole semester.

A file is an envelope {"format": "curodav.university", "version": N, "kind": "discipline" | "semester", "data": {...}}. The
format is defined for Curodav and carries its version from the start. `load` validates the envelope and the data and returns plain
dicts; it never touches the database (the settings page, in 4.8.0, turns a loaded document into a previewed plan).
Older versions are brought up to date by the functions in UPGRADES, keyed by the version they upgrade from.
"""

from __future__ import annotations

import json
from typing import Any

FORMAT = "curodav.university"
VERSION = 1
KINDS = ("discipline", "semester")
UPGRADES: dict[int, Any] = {}  # {n: callable(data) -> data of version n + 1}


class FormatError(ValueError):
    """The file is not a valid University document."""


def _text(value: Any, field: str, required: bool = False) -> str:
    if value is None or value == "":
        if required:
            raise FormatError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise FormatError(f"{field} must be text")
    return value.strip()


def _list(value: Any, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FormatError(f"{field} must be a list")
    return value


def _object(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise FormatError(f"{field} must be an object")
    return value


def _discipline(raw: Any, where: str) -> dict[str, Any]:
    d = _object(raw, where)
    timetable = []
    for i, slot in enumerate(_list(d.get("timetable"), f"{where}.timetable")):
        s = _object(slot, f"{where}.timetable[{i}]")
        weekday = s.get("weekday")
        if not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise FormatError(f"{where}.timetable[{i}].weekday must be a number from 0 (Monday) to 6 (Sunday)")
        parity = s.get("weeks", "all")
        if parity not in ("all", "odd", "even"):
            raise FormatError(f"{where}.timetable[{i}].weeks must be all, odd or even")
        timetable.append({"weekday": weekday, "start": _text(s.get("start"), "start", True), "end": _text(s.get("end"), "end", True),
                          "room": _text(s.get("room"), "room"), "kind": _text(s.get("kind"), "kind") or "lecture", "weeks": parity})
    themes = []
    for i, t in enumerate(_list(d.get("themes"), f"{where}.themes")):
        t = _object(t, f"{where}.themes[{i}]")
        importance = t.get("importance", 0)
        if not isinstance(importance, int) or not 0 <= importance <= 3:
            raise FormatError(f"{where}.themes[{i}].importance must be a number from 0 to 3")
        themes.append({"number": t.get("number") if isinstance(t.get("number"), int) else i + 1, "title": _text(t.get("title"), "title", True),
                       "importance": importance})
    exams = []
    for i, e in enumerate(_list(d.get("exams"), f"{where}.exams")):
        e = _object(e, f"{where}.exams[{i}]")
        weight = e.get("weight")
        if weight is not None and (not isinstance(weight, (int, float)) or not 0 <= weight <= 100):
            raise FormatError(f"{where}.exams[{i}].weight must be a percentage from 0 to 100")
        exams.append({"title": _text(e.get("title"), "title", True), "date": _text(e.get("date"), "date"), "time": _text(e.get("time"), "time"),
                      "weight": weight})
    readings = [{"title": _text(_object(r, f"{where}.readings[{i}]").get("title"), "title", True), "author": _text(r.get("author"), "author")}
                for i, r in enumerate(_list(d.get("readings"), f"{where}.readings"))]
    return {"name": _text(d.get("name"), f"{where}.name", True), "color": _text(d.get("color"), "color"), "icon": _text(d.get("icon"), "icon"),
            "teachers": [_text(t, "teacher", True) for t in _list(d.get("teachers"), f"{where}.teachers")],
            "timetable": timetable, "themes": themes, "exams": exams, "readings": readings}


def _semester(raw: Any) -> dict[str, Any]:
    s = _object(raw, "semester")
    return {"name": _text(s.get("name"), "semester.name", True), "start_date": _text(s.get("start_date"), "start_date"),
            "end_date": _text(s.get("end_date"), "end_date"), "class_end_date": _text(s.get("class_end_date"), "class_end_date"),
            "disciplines": [_discipline(d, f"semester.disciplines[{i}]") for i, d in enumerate(_list(s.get("disciplines"), "semester.disciplines"))]}


def dump(kind: str, data: dict[str, Any]) -> str:
    """The JSON text of a discipline or a semester; the data is validated first, so what is written can always be read back."""
    if kind not in KINDS:
        raise FormatError(f"kind must be one of {', '.join(KINDS)}")
    checked = _discipline(data, "discipline") if kind == "discipline" else _semester(data)
    return json.dumps({"format": FORMAT, "version": VERSION, "kind": kind, "data": checked}, indent=2, ensure_ascii=False)


def load(text: str) -> tuple[str, dict[str, Any]]:
    """Parses a University document and returns (kind, data), upgraded to the current version and validated."""
    try:
        doc = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise FormatError("The file is not valid JSON") from exc
    doc = _object(doc, "document")
    if doc.get("format") != FORMAT:
        raise FormatError(f"This is not a {FORMAT} file")
    version = doc.get("version")
    if not isinstance(version, int) or version < 1:
        raise FormatError("The file has no valid version")
    if version > VERSION:
        raise FormatError(f"The file is version {version}; this app reads up to version {VERSION}")
    kind = doc.get("kind")
    if kind not in KINDS:
        raise FormatError(f"kind must be one of {', '.join(KINDS)}")
    data = doc.get("data")
    while version < VERSION:
        data = UPGRADES[version](data)
        version += 1
    return kind, (_discipline(data, "discipline") if kind == "discipline" else _semester(data))
