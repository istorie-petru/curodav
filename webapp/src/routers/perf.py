"""Receives the browser's timing reports (see static/perf_client.js)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Response

from .. import perf

router = APIRouter(tags=["perf"])


@router.post("/perf/report", status_code=204)
def report(body: dict = Body(...)):
    perf.record_browser(body)
    return Response(status_code=204)
