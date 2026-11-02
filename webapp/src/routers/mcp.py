"""The MCP endpoint, /mcp: Streamable HTTP without a server stream, each POST answered with one JSON response.

Feature document: curodav-notes/documentation/features/api-and-mcp.md
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from .. import access_tokens, api_activity, mcp_server
from ..api_auth import require_read
from ..deps import get_db

router = APIRouter(tags=["mcp"])


async def _raw_body(request: Request) -> bytes:
    return await request.body()


def _foreign_origin(request: Request) -> bool:
    """A browser page on another site (DNS rebinding); Claude's own servers send no Origin."""
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = origin.split("://", 1)[-1].rstrip("/")
    return host != request.headers.get("host")


@router.post("/mcp")
def mcp_post(request: Request, body: bytes = Depends(_raw_body), conn=Depends(get_db), token=Depends(require_read)):
    if _foreign_origin(request):
        return JSONResponse({"error": "forbidden", "message": "Cross-site requests are refused."}, status_code=403)
    try:
        message = json.loads(body or b"")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": mcp_server.PARSE_ERROR, "message": "Parse error"}},
                            status_code=400)
    if isinstance(message, dict) and message.get("method") == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        what, where = api_activity.describe_tool(conn, params.get("name") or "", params.get("arguments"))
        access_tokens.log_activity(conn, token["uid"], "mcp", what, where)
    reply = mcp_server.handle(conn, message, token)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


@router.get("/mcp")
def mcp_get(token=Depends(require_read)):
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
def mcp_delete(token=Depends(require_read)):
    return Response(status_code=405, headers={"Allow": "POST"})
