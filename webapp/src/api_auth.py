"""Bearer-token gate for /api/v1 and /mcp, with a per-address limit on failed attempts.

Feature document: curodav-notes/documentation/features/api-and-mcp.md

These paths skip the session-cookie middleware (auth.API_PATHS) and accept only `Authorization: Bearer`, so a
browser session can never be used to reach them and they stay closed on an install without a login.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from . import access_tokens, clock
from .auth import client_ip
from .deps import get_db
from .routers.settings_api_access import base_url

FAILED_MAX = 30
FAILED_WINDOW_SECONDS = 15 * 60

_failed: dict[str, list[float]] = {}


def resource_metadata_url(request: Request) -> str:
    return f"{base_url(request)}/.well-known/oauth-protected-resource/mcp"


def _recent_failures(key: str) -> list[float]:
    now = clock.now().timestamp()
    kept = [t for t in _failed.get(key, []) if now - t < FAILED_WINDOW_SECONDS]
    _failed[key] = kept
    return kept


def reset_rate_limits() -> None:
    _failed.clear()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _deny(request: Request, status: int, error: str, message: str) -> HTTPException:
    challenge = f'Bearer resource_metadata="{resource_metadata_url(request)}"'
    if error:
        challenge += f', error="{error}"'
    return HTTPException(status_code=status, detail={"error": error or "unauthorized", "message": message},
                         headers={"WWW-Authenticate": challenge})


def authenticate(request: Request, conn, scope: str = "read") -> dict[str, Any]:
    key = client_ip(request)
    if len(_recent_failures(key)) >= FAILED_MAX:
        raise HTTPException(status_code=429, detail={"error": "rate_limited", "message": "Too many failed attempts; try later."},
                            headers={"Retry-After": str(FAILED_WINDOW_SECONDS)})
    secret = _bearer(request)
    token = access_tokens.check_token(conn, secret, scope)
    if token is None:
        if secret:
            _failed.setdefault(key, []).append(clock.now().timestamp())
            raise _deny(request, 401, "invalid_token", "The token is unknown, expired, revoked or lacks the scope.")
        raise _deny(request, 401, "", "A bearer token is required.")
    return token


def require(scope: str):
    """A dependency that lets a request through when its token holds `scope` ("read" is any reading at all)."""
    def check(request: Request, conn=Depends(get_db)) -> dict[str, Any]:
        return authenticate(request, conn, scope)
    return check


require_read = require("read")
