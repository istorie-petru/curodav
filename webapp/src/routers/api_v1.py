"""The versioned REST API, /api/v1: read-only JSON over `api_service`, for scripts and a future phone app.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

Every route needs a bearer token holding the scope of its area (read:notes, read:calendar, read:university), and an
edit the matching write scope. Errors are
{"detail": {"error", "message"}}. A note answers with an ETag holding its revision, and an edit names it in If-Match.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response

from .. import access_tokens, api_service, api_write, note_versions
from ..api_auth import require, require_read
from ..deps import get_db

router = APIRouter(prefix="/api/v1", tags=["api-v1"])

Limit = Annotated[int, Query(ge=1, le=api_service.MAX_LIMIT)]


def _log(conn, token: dict[str, Any], request: Request) -> None:
    access_tokens.log_activity(conn, token["uid"], "api", f"GET {request.url.path}")


def _found(read, *args, **kwargs):
    try:
        return read(*args, **kwargs)
    except api_service.NotFound:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "Nothing has that uid."}) from None


@router.get("/search")
def search(request: Request, q: str, kinds: Annotated[list[str] | None, Query()] = None, limit: Limit = 20,
           conn=Depends(get_db), token=Depends(require_read)):
    _log(conn, token, request)
    return {"results": api_service.search(conn, q, api_service.kinds_for(token, kinds), limit)}


@router.get("/notes")
def list_notes(request: Request, shelf: str = "", tag: str = "", note_type: str = "", updated_since: str = "", cursor: str = "",
               limit: Limit = 30, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return api_service.list_notes(conn, shelf=shelf, tag=tag, note_type=note_type, updated_since=updated_since,
                                  cursor=cursor, limit=limit)


@router.get("/notes/{uid}")
def get_note(request: Request, response: Response, uid: str, include_blocks: bool = False, conn=Depends(get_db),
             token=Depends(require("read:notes"))):
    _log(conn, token, request)
    note = _found(api_service.get_note, conn, uid, include_blocks=include_blocks)
    response.headers["ETag"] = f'"{note["revision"]}"'
    return note


@router.get("/citations")
def list_citations(request: Request, q: str = "", types: Annotated[list[str] | None, Query()] = None, cursor: str = "",
                   limit: Limit = 30, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return api_service.list_citations(conn, q=q, types=types, cursor=cursor, limit=limit)


@router.get("/citations/{uid}")
def get_citation(request: Request, uid: str, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return _found(api_service.get_citation, conn, uid)


@router.get("/entries")
def list_entries(request: Request, q: str = "", kind: str = "", conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return {"items": api_service.list_entries(conn, q=q, kind=kind)}


@router.get("/entry-kinds")
def list_entry_kinds(request: Request, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return {"items": api_service.list_entry_kinds(conn)}


@router.get("/entries/{uid}")
def get_entry(request: Request, uid: str, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return _found(api_service.get_entry, conn, uid)


@router.get("/tasks")
def list_tasks(request: Request, status: str = "", tag: str = "", due_before: str = "", due_after: str = "", cursor: str = "",
               limit: Limit = 30, conn=Depends(get_db), token=Depends(require("read:calendar"))):
    _log(conn, token, request)
    return api_service.list_tasks(conn, status=status, tag=tag, due_before=due_before, due_after=due_after, cursor=cursor,
                                  limit=limit)


@router.get("/tasks/{uid}")
def get_task(request: Request, uid: str, conn=Depends(get_db), token=Depends(require("read:calendar"))):
    _log(conn, token, request)
    return _found(api_service.get_task, conn, uid)


@router.get("/events")
def list_events(request: Request, start: str = "", end: str = "", tag: str = "", cursor: str = "", limit: Limit = 30,
                conn=Depends(get_db), token=Depends(require("read:calendar"))):
    _log(conn, token, request)
    return api_service.list_events(conn, start=start, end=end, tag=tag, cursor=cursor, limit=limit)


@router.get("/events/{uid}")
def get_event(request: Request, uid: str, conn=Depends(get_db), token=Depends(require("read:calendar"))):
    _log(conn, token, request)
    return _found(api_service.get_event, conn, uid)


@router.get("/organisation")
def organisation(request: Request, conn=Depends(get_db), token=Depends(require_read)):
    _log(conn, token, request)
    return api_service.list_organisation(conn)


@router.get("/media/now")
def media_now(request: Request, finished_days: Annotated[int, Query(ge=0, le=3650)] = 60, conn=Depends(get_db),
              token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return api_service.media_now(conn, finished_days=finished_days)


@router.get("/university")
def university_overview(request: Request, semester_uid: str = "", conn=Depends(get_db), token=Depends(require("read:university"))):
    _log(conn, token, request)
    return _found(api_service.university_overview, conn, semester_uid=semester_uid)


@router.get("/university/exams")
def list_exams(request: Request, semester_uid: str = "", discipline: str = "", upcoming: bool = False, conn=Depends(get_db),
               token=Depends(require("read:university"))):
    _log(conn, token, request)
    return _found(api_service.list_exams, conn, semester_uid=semester_uid, discipline=discipline, upcoming=upcoming)


@router.get("/university/disciplines/{name}")
def get_discipline(request: Request, name: str, semester_uid: str = "", conn=Depends(get_db), token=Depends(require("read:university"))):
    _log(conn, token, request)
    return _found(api_service.get_discipline, conn, name, semester_uid=semester_uid)


_EDIT_STATUS = {"conflict": 409, "not_found": 404, "invalid": 422}


def _edit(run, *args, **kwargs):
    try:
        return run(*args, **kwargs)
    except api_write.EditError as exc:
        raise HTTPException(status_code=_EDIT_STATUS[exc.code], detail={"error": exc.code, "message": str(exc)}) from None


@router.patch("/notes/{uid}/blocks")
def edit_note(request: Request, response: Response, uid: str, body: Annotated[dict[str, Any], Body()],
              if_match: Annotated[str, Header()] = "", conn=Depends(get_db), token=Depends(require("write:notes"))):
    """Body: {"ops": [...], "summary": "..."}; the revision comes from If-Match (or "revision" in the body)."""
    access_tokens.log_activity(conn, token["uid"], "api", f"PATCH {request.url.path}")
    revision = if_match.strip().strip('"') or str(body.get("revision") or "")
    result = _edit(api_write.edit_note, conn, uid, revision, body.get("ops"), source="api", token_uid=token["uid"],
                   summary=str(body.get("summary") or ""))
    response.headers["ETag"] = f'"{result["revision"]}"'
    return result


@router.get("/notes/{uid}/versions")
def list_note_versions(request: Request, uid: str, conn=Depends(get_db), token=Depends(require("read:notes"))):
    _log(conn, token, request)
    return {"items": note_versions.list_versions(conn, uid)}


@router.post("/note-versions/{version_uid}/restore")
def restore_note_version(request: Request, version_uid: str, conn=Depends(get_db), token=Depends(require("write:notes"))):
    access_tokens.log_activity(conn, token["uid"], "api", f"POST {request.url.path}")
    return _edit(api_write.restore_version, conn, version_uid, source="api", token_uid=token["uid"])
