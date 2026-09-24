"""Web Push endpoints (2026-09-24, plans/ui-cleanup-2026-09.md item 7,
slice P1). The browser side is static/push_settings.js (Settings >
General's Notifications card); delivery is src/push.py.

- GET  /push/public-key   -> {"key": <applicationServerKey>}
- POST /push/subscribe    JSON PushSubscription (endpoint + keys)
- POST /push/unsubscribe  JSON {"endpoint": ...}
- POST /push/test         send a test notification to every device
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, push
from ..deps import get_db

router = APIRouter(prefix="/push", tags=["push"])

_MAX_FIELD = 2048


@router.get("/public-key")
def public_key(conn=Depends(get_db)):
    return {"key": push.public_key(conn)}


def _valid_endpoint(endpoint) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > _MAX_FIELD:
        return False
    parsed = urlparse(endpoint)
    # Push services are always https; anything else is not a subscription
    # (and posting to it would make this server fetch arbitrary URLs).
    return parsed.scheme == "https" and bool(parsed.netloc)


@router.post("/subscribe")
async def subscribe(request: Request, conn=Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Expected a JSON PushSubscription."}, status_code=400)
    endpoint = (body or {}).get("endpoint")
    keys = (body or {}).get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not _valid_endpoint(endpoint) or not all(isinstance(k, str) and 0 < len(k) < 256 for k in (p256dh, auth)):
        return JSONResponse({"error": "Invalid subscription."}, status_code=400)
    agent = (request.headers.get("user-agent") or "")[:200]
    db.upsert_push_subscription(conn, endpoint, p256dh, auth, agent, datetime.now(timezone.utc).isoformat())
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request, conn=Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "Expected JSON."}, status_code=400)
    endpoint = (body or {}).get("endpoint")
    if isinstance(endpoint, str):
        db.delete_push_subscription(conn, endpoint)
    return {"ok": True}


@router.post("/test")
def send_test(conn=Depends(get_db)):
    if not db.list_push_subscriptions(conn):
        return JSONResponse({"error": "No device has notifications turned on yet."}, status_code=400)
    result = push.send_to_all(conn, "Curodav", "Notifications are working. Nice.", url="/", tag="test")
    return {"ok": result["sent"] > 0, **result}
