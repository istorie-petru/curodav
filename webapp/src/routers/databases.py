"""Custom databases (Phase 7): Notion-like user-defined tables with
formula columns. Entirely local -- see db.py's `databases`/
`database_columns`/`database_rows` CREATE TABLE comments. Grade tracking
(a class-as-project's database of assignments, with a WEIGHTAVG summary
formula for the final grade) is the driving example, but nothing here is
grade-specific.

Column values are computed once per request in `_row_display_values`/
`_summary_row` (formula_engine.py) and handed to the template as plain
dicts -- the template itself does no evaluation, it only renders what
this router already resolved, same split every other view in this app
uses (routers compute, templates render)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db, formula_engine
from ..deps import get_db, templates

router = APIRouter(prefix="/databases", tags=["databases"])

COLORS = ["blue", "green", "orange", "red", "purple", "pink", "gray", "yellow"]
COLUMN_TYPES = ["text", "number", "date", "select", "checkbox", "formula"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tags_list(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if t.strip()]


def _rows_by_column_name(columns: list[dict], rows: list[dict]) -> list[dict]:
    """formula_engine.py resolves column references by *name*, not
    column_uid (a formula reads `grade * weight`, not `grade * col-abc123`
    -- uids aren't something a user should ever have to type). This
    re-keys every row's raw values_json (column_uid -> value) into
    name -> value for the columns that currently exist, which is what the
    engine actually needs. Formula-type columns contribute nothing here
    (their value is computed, never stored -- see below), so they're
    simply absent from this dict; a formula that references another
    formula column will correctly fail as "no numeric value" rather than
    silently resolving to something stale.

    Each column is stored under both its original name and its lowercase
    name so that formula references are case-insensitive -- a column
    named "Grade" is reachable as both `Grade` and `grade` in a formula.
    The original name wins on collision (two columns that differ only in
    case are unusual enough that a predictable tiebreak matters more than
    any particular choice)."""
    uid_to_name = {c["uid"]: c["name"] for c in columns if c["type"] != "formula"}
    out = []
    for row in rows:
        named: dict = {}
        for cu, v in row["values"].items():
            if cu not in uid_to_name:
                continue
            name = uid_to_name[cu]
            # Lowercase alias first so the canonical name wins on collision.
            named[name.lower()] = v
            named[name] = v
        out.append(named)
    return out


def _computed_rows(columns: list[dict], rows: list[dict]) -> list[dict]:
    """Each row's `cells` dict, keyed by column_uid, ready for the
    template: stored value for ordinary columns, live-evaluated
    (value, error) for formula columns. All-rows-by-name is computed once
    up front since every formula-column evaluation in every row needs it
    (aggregate functions scan every row)."""
    all_rows_by_name = _rows_by_column_name(columns, rows)
    result = []
    for i, row in enumerate(rows):
        row_by_name = all_rows_by_name[i]
        cells = {}
        for col in columns:
            if col["type"] == "formula":
                value, error = formula_engine.evaluate(col.get("formula") or "", row_by_name, all_rows_by_name)
                cells[col["uid"]] = {"value": value, "error": error, "is_formula": True}
            else:
                cells[col["uid"]] = {"value": row["values"].get(col["uid"]), "error": None, "is_formula": False}
        result.append({"row": row, "cells": cells})
    return result


def _summary_row(columns: list[dict], rows: list[dict]) -> dict[str, dict] | None:
    """One computed value per column that has a summary_formula set, or
    None entirely if no column defines one -- so a database with no
    summary formulas at all renders no footer row, not an empty one."""
    if not any(c.get("summary_formula") for c in columns):
        return None
    all_rows_by_name = _rows_by_column_name(columns, rows)
    out: dict[str, dict] = {}
    for col in columns:
        formula = col.get("summary_formula")
        if not formula:
            continue
        value, error = formula_engine.evaluate(formula, None, all_rows_by_name)
        out[col["uid"]] = {"value": value, "error": error}
    return out


@router.get("")
def list_databases(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "databases_list.html",
        {"request": request, "active_tab": "databases", "databases": db.list_databases(conn)},
    )


@router.get("/new")
def new_database_form(request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "database_form.html",
        {
            "request": request,
            "active_tab": "databases",
            "database": None,
            "colors": COLORS,
            "projects": db.list_projects(conn),
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@router.post("")
def create_database(
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    tags: str = Form(""),
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    name = name.strip()
    if not name:
        return RedirectResponse(url="/databases", status_code=303)
    now = _now()
    uid = str(uuid.uuid4())
    tag_list = _tags_list(tags)
    db.upsert_database(
        conn,
        {
            "uid": uid, "name": name, "description": description, "color": color,
            "icon": icon.strip() or None, "tags": tag_list, "project_uid": project_uid or None,
            "created_at": now, "updated_at": now,
        },
    )
    db.ensure_tags_registered(conn, tag_list)
    # A brand-new database is useless with zero columns -- seed one plain
    # text column ("Name") so the detail page immediately has an "Add row"
    # affordance that makes sense, rather than showing a table with no
    # columns at all.
    db.upsert_database_column(
        conn, {"uid": str(uuid.uuid4()), "database_uid": uid, "name": "Name", "type": "text", "position": 0, "created_at": now}
    )
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.get("/{uid}/edit")
def edit_database_form(uid: str, request: Request, conn=Depends(get_db)):
    return templates.TemplateResponse(
        "database_form.html",
        {
            "request": request,
            "active_tab": "databases",
            "database": db.get_database(conn, uid),
            "colors": COLORS,
            "projects": db.list_projects(conn),
            "tag_names": db.list_tag_names_in_use(conn),
        },
    )


@router.post("/{uid}/edit")
def edit_database(
    uid: str,
    name: str = Form(...),
    description: str = Form(""),
    color: str = Form("blue"),
    icon: str = Form(""),
    tags: str = Form(""),
    project_uid: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_database(conn, uid)
    if existing is None:
        return RedirectResponse(url="/databases", status_code=303)
    tag_list = _tags_list(tags)
    row = dict(existing)
    row.update(
        {
            "name": name.strip() or existing["name"],
            "description": description,
            "color": color,
            "icon": icon.strip() or None,
            "tags": tag_list,
            "project_uid": project_uid or None,
            "updated_at": _now(),
        }
    )
    db.upsert_database(conn, row)
    db.ensure_tags_registered(conn, tag_list)
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/archive")
def archive_database(uid: str, conn=Depends(get_db)):
    db.archive_database(conn, uid, _now())
    return RedirectResponse(url="/databases", status_code=303)


@router.post("/{uid}/unarchive")
def unarchive_database(uid: str, conn=Depends(get_db)):
    db.unarchive_database(conn, uid)
    return RedirectResponse(url="/databases", status_code=303)


@router.post("/{uid}/delete")
def delete_database(uid: str, conn=Depends(get_db)):
    db.delete_database(conn, uid)
    return RedirectResponse(url="/databases", status_code=303)


@router.get("/{uid}")
def database_detail(uid: str, request: Request, conn=Depends(get_db)):
    database = db.get_database(conn, uid)
    ctx = {"request": request, "active_tab": "databases", "database": database, "column_types": COLUMN_TYPES}
    if database:
        columns = db.list_database_columns(conn, uid)
        rows = db.list_database_rows(conn, uid)
        ctx.update(
            {
                "columns": columns,
                "computed_rows": _computed_rows(columns, rows),
                "summary": _summary_row(columns, rows),
                "project": db.get_project(conn, database["project_uid"]) if database.get("project_uid") else None,
            }
        )
    return templates.TemplateResponse("database_detail.html", ctx)


# --------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------- #


@router.post("/{uid}/columns")
def add_column(
    uid: str,
    name: str = Form(...),
    type: str = Form("text"),
    formula: str = Form(""),
    summary_formula: str = Form(""),
    options: str = Form(""),
    conn=Depends(get_db),
):
    name = name.strip()
    if not name or type not in COLUMN_TYPES:
        return RedirectResponse(url=f"/databases/{uid}", status_code=303)
    db.upsert_database_column(
        conn,
        {
            "uid": str(uuid.uuid4()),
            "database_uid": uid,
            "name": name,
            "type": type,
            "formula": formula.strip() or None if type == "formula" else None,
            "summary_formula": summary_formula.strip() or None,
            "options": _tags_list(options) if type == "select" else [],
            "position": db.next_column_position(conn, uid),
            "created_at": _now(),
        },
    )
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/columns/{column_uid}/edit")
def edit_column(
    uid: str,
    column_uid: str,
    name: str = Form(...),
    type: str = Form("text"),
    formula: str = Form(""),
    summary_formula: str = Form(""),
    options: str = Form(""),
    conn=Depends(get_db),
):
    existing = db.get_database_column(conn, column_uid)
    if existing is None or type not in COLUMN_TYPES:
        return RedirectResponse(url=f"/databases/{uid}", status_code=303)
    db.upsert_database_column(
        conn,
        {
            "uid": column_uid,
            "database_uid": uid,
            "name": name.strip() or existing["name"],
            "type": type,
            "formula": formula.strip() or None if type == "formula" else None,
            "summary_formula": summary_formula.strip() or None,
            "options": _tags_list(options) if type == "select" else [],
            "position": existing["position"],
            "created_at": existing.get("created_at"),
        },
    )
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/columns/{column_uid}/delete")
def delete_column(uid: str, column_uid: str, conn=Depends(get_db)):
    db.delete_database_column(conn, column_uid)
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/columns/{column_uid}/move")
def move_column(uid: str, column_uid: str, direction: str = Form(...), conn=Depends(get_db)):
    """Swaps this column's position with its immediate left/right
    neighbor -- simplest correct reorder primitive (no renumbering of the
    rest of the list needed) for a plain "move left"/"move right" pair of
    buttons, same idea as task_lists' persisted column order but applied
    to a float position key instead of a stored order list."""
    columns = db.list_database_columns(conn, uid)
    idx = next((i for i, c in enumerate(columns) if c["uid"] == column_uid), None)
    if idx is None:
        return RedirectResponse(url=f"/databases/{uid}", status_code=303)
    swap_idx = idx - 1 if direction == "left" else idx + 1
    if 0 <= swap_idx < len(columns):
        a, b = columns[idx], columns[swap_idx]
        a_pos, b_pos = a["position"], b["position"]
        conn.execute("UPDATE database_columns SET position = ? WHERE uid = ?", (b_pos, a["uid"]))
        conn.execute("UPDATE database_columns SET position = ? WHERE uid = ?", (a_pos, b["uid"]))
        conn.commit()
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


# --------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------- #


@router.post("/{uid}/rows")
def add_row(uid: str, conn=Depends(get_db)):
    now = _now()
    db.upsert_database_row(
        conn,
        {"uid": str(uuid.uuid4()), "database_uid": uid, "values": {}, "position": db.next_row_position(conn, uid), "created_at": now, "updated_at": now},
    )
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/rows/{row_uid}/delete")
def delete_row(uid: str, row_uid: str, conn=Depends(get_db)):
    db.delete_database_row(conn, row_uid)
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)


@router.post("/{uid}/rows/{row_uid}/cells/{column_uid}")
def set_cell(uid: str, row_uid: str, column_uid: str, value: str = Form(""), conn=Depends(get_db)):
    """Single-cell inline edit -- a plain form POST-redirect-GET, same
    "no JS required" convention as every other write in this app
    (database_detail.html's grid renders each editable cell as its own
    tiny inline form, the same pattern the habit heatmap's day-toggle
    cells use). A checkbox column's value normalizes to a real bool
    before storage; every other type is stored as the raw string the
    input submitted (formula_engine.py's _as_float handles parsing
    numeric-looking strings at read time, so there's no need to coerce
    types on write for number/date columns either)."""
    column = db.get_database_column(conn, column_uid)
    stored_value: object = value
    if column and column["type"] == "checkbox":
        stored_value = value in ("1", "true", "on", "True")
    db.set_database_row_value(conn, row_uid, column_uid, stored_value, _now())
    return RedirectResponse(url=f"/databases/{uid}", status_code=303)
