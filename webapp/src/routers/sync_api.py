"""1.8 slice 1 -- the sync API skeleton (plans/open-priority.md §
Offline-first editing & synchronization §8). Thin HTTP wrapper around
`src/offline_sync.py`'s pure apply/pull logic -- this module owns request
parsing and the `sync_devices` cursor bookkeeping only, same "router
computes nothing the pure module doesn't already do" layering as every
other slice in this app.

No PWA/browser client exists yet (§11: that's slices 3+); this is only
ever called synthetically today, by tests POSTing op batches the same way
a future service worker's outbox would. `/api/sync/*` (not a page route)
because this is exactly the "thin JSON sync API" §0 describes -- it does
not replace or wrap any existing page router, and no existing router
gains sync awareness because of this file's existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, offline_sync
from ..deps import get_db

router = APIRouter(tags=["sync"])


@router.post("/api/sync/push")
async def push(request: Request, conn=Depends(get_db)):
    payload = await request.json()
    device_id = payload["device_id"]
    ops = payload.get("ops", [])
    results = offline_sync.apply_batch(conn, ops)
    db.touch_sync_device(conn, device_id, last_pushed_hlc=_batch_max_hlc(ops))
    return JSONResponse({"results": results})


def _batch_max_hlc(ops: list[dict]) -> tuple[int, int, str] | None:
    """The device's own cursor bookkeeping (`sync_devices.last_pushed_*`)
    only needs the newest HLC it *sent*, not what was actually applied
    (a stale field is still a real, ordered write from that device's own
    perspective -- §6's silent no-op is about which value wins server-
    side, not about whether the device's own clock advanced)."""
    hlcs: list[tuple[int, int, str]] = []
    for op in ops:
        if op.get("op_type") in ("create", "field_set"):
            for spec in (op.get("fields") or {}).values():
                hlcs.append(offline_sync.hlc_from_payload(spec["hlc"]))
        elif "hlc" in op:
            hlcs.append(offline_sync.hlc_from_payload(op["hlc"]))
    return max(hlcs) if hlcs else None


@router.post("/api/sync/pull")
async def pull(request: Request, conn=Depends(get_db)):
    payload = await request.json()
    device_id = payload["device_id"]
    cursor_payload = payload.get("cursor")
    cursor = offline_sync.hlc_from_payload(cursor_payload) if cursor_payload else None
    result = offline_sync.pull(conn, cursor)
    db.touch_sync_device(conn, device_id, last_pulled_hlc=result["cursor"])
    return JSONResponse(
        {
            "full_resync": result["full_resync"],
            "changes": [
                {**c, "hlc": offline_sync.hlc_to_payload(c["hlc"])} for c in result["changes"]
            ],
            "cursor": offline_sync.hlc_to_payload(result["cursor"]) if result["cursor"] else None,
        }
    )
