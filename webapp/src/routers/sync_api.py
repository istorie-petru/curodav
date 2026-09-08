"""1.8 slice 1 -- the sync API skeleton (plans/open-priority.md §
Offline-first editing & synchronization §8). Thin HTTP wrapper around
`src/offline_sync.py`'s pure apply/pull logic -- this module owns request
parsing and the `sync_devices` cursor bookkeeping only, same "router
computes nothing the pure module doesn't already do" layering as every
other slice in this app.

Slices 3+ added the real PWA/browser client this was originally written
ahead of; it's no longer synthetic-only, though tests still exercise it
the same direct way (POSTing op batches, the same shape a real device's
outbox would send).

Slice 7 adds one lazy side effect to `pull`: `data_health.run_sync_gc`,
the same "check on every request to a natural touchpoint, no cron" idiom
`routers/tasks.py`'s auto-archive check already established for this app
-- a pull is this feature's own most natural heartbeat, since it's the
one endpoint guaranteed to be hit regularly by a healthy, syncing device.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import data_health, db, offline_sync
from ..deps import get_db

router = APIRouter(tags=["sync"])


@router.get("/api/sync/state")
async def state(conn=Depends(get_db)):
    """The server's current data version (db.get_sync_data_version) -- the
    cheap pre-flight check the client makes before running a sync round
    (offline_sync_client.js's round-skip logic): when this equals the
    version the device saved after its last successful pull and the
    outbox is empty, there is nothing to do, so the round is skipped
    entirely -- no pull, no status churn, no toast. A plain single-row
    read (app_meta), deliberately lighter than pull's own field_versions
    scan -- that's the point of checking here first."""
    return JSONResponse({"version": db.get_sync_data_version(conn)})


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
    # 1.8 slice 7 -- run before computing this pull's own response, not
    # after: anything GC purges is by definition already past the
    # retention horizon, hence already older than any cursor this
    # response could legitimately need to include -- running it first
    # just means this response is computed against the already-clean
    # state, with no risk of racing its own result. A no-op call when
    # retention is configured to 0/Never (data_health.run_sync_gc's own
    # force=False default).
    data_health.run_sync_gc(conn)
    result = offline_sync.pull(conn, cursor)
    db.touch_sync_device(conn, device_id, last_pulled_hlc=result["cursor"])
    return JSONResponse(
        {
            "full_resync": result["full_resync"],
            "changes": [
                {**c, "hlc": offline_sync.hlc_to_payload(c["hlc"])} for c in result["changes"]
            ],
            "cursor": offline_sync.hlc_to_payload(result["cursor"]) if result["cursor"] else None,
            # 2026-08-17 -- the server's data version, computed *after*
            # run_sync_gc above has had its chance to purge (a purge moves
            # the version too), so the device that just pulled saves the
            # exact post-pull state and its next round-skip pre-check
            # compares against a current value.
            "version": db.get_sync_data_version(conn),
        }
    )
