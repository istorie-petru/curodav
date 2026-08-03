"""Syncthing REST API client (REWORK_PLAN §4.3).

Interacts with Syncthing via its REST API on localhost:8384.
Displays sync status, connected device list, triggers rescan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError


@dataclass
class SyncthingStatus:
    running: bool = False
    my_id: str = ""
    version: str = ""
    uptime: int = 0
    folder_count: int = 0
    device_count: int = 0

    @classmethod
    def from_api(cls, data: dict) -> SyncthingStatus:
        return cls(
            running=True,
            my_id=data.get("myID", ""),
            version=data.get("version", ""),
            uptime=data.get("uptime", 0),
        )


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    connected: bool
    address: str = ""
    compression: str = ""
    paused: bool = False

    @classmethod
    def from_api(cls, device_id: str, data: dict) -> DeviceInfo:
        return cls(
            device_id=device_id,
            name=data.get("name", device_id[:8]),
            connected=data.get("connected", False),
            address=data.get("address", ""),
            compression=data.get("compression", ""),
            paused=data.get("paused", False),
        )


@dataclass
class FolderStatus:
    folder_id: str
    label: str = ""
    status: str = "unknown"
    global_bytes: int = 0
    in_sync_bytes: int = 0
    need_bytes: int = 0
    need_files: int = 0

    @classmethod
    def from_api(cls, data: dict) -> FolderStatus:
        return cls(
            folder_id=data.get("folder", ""),
            label=data.get("label", ""),
            status=data.get("state", "unknown"),
            global_bytes=data.get("globalBytes", 0),
            in_sync_bytes=data.get("inSyncBytes", 0),
            need_bytes=data.get("needBytes", 0),
            need_files=data.get("needFiles", 0),
        )

    @property
    def sync_percent(self) -> float:
        if self.global_bytes == 0:
            return 1.0
        return self.in_sync_bytes / self.global_bytes


class SyncthingClient:
    """REST API client for Syncthing (localhost:8384 by default)."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "http://127.0.0.1:8384",
        timeout: int = 5,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def ping(self) -> bool:
        try:
            self._get("/rest/system/ping")
            return True
        except (URLError, OSError):
            return False

    def status(self) -> SyncthingStatus:
        data = self._get("/rest/system/status")
        return SyncthingStatus.from_api(data)

    def connections(self) -> list[DeviceInfo]:
        data = self._get("/rest/system/connections")
        connections = data.get("connections", {})
        devices = data.get("devices", {})
        results = []
        for dev_id, conn in connections.items():
            dev_info = devices.get(dev_id, {})
            info = DeviceInfo.from_api(dev_id, {**conn, **dev_info})
            results.append(info)
        return results

    def folder_status(self, folder_id: str = "") -> FolderStatus:
        data = self._get("/rest/db/status")
        if isinstance(data, list):
            for f in data:
                if f.get("folder") == folder_id or not folder_id:
                    return FolderStatus.from_api(f)
        elif isinstance(data, dict):
            if folder_id and folder_id in data:
                return FolderStatus.from_api(data[folder_id])
            for f in data.values():
                return FolderStatus.from_api(f)
        return FolderStatus()

    def all_folder_statuses(self) -> list[FolderStatus]:
        data = self._get("/rest/db/status")
        if isinstance(data, list):
            return [FolderStatus.from_api(f) for f in data]
        if isinstance(data, dict):
            return [FolderStatus.from_api(f) for f in data.values()]
        return []

    def trigger_rescan(self, folder_id: str = "") -> bool:
        body = json.dumps({"folder": folder_id}).encode()
        try:
            self._post("/rest/db/scan", body)
            return True
        except (URLError, OSError):
            return False

    def device_list(self) -> list[dict]:
        data = self._get("/rest/system/config")
        devices = data.get("devices", []) if isinstance(data, dict) else []
        return devices

    # ------------------------------------------------------------------ #

    def _get(self, path: str) -> Any:
        req = Request(f"{self._base_url}{path}", method="GET")
        return self._request(req)

    def _post(self, path: str, body: bytes) -> Any:
        req = Request(f"{self._base_url}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        return self._request(req)

    def _request(self, req: Request) -> Any:
        if self._api_key:
            req.add_header("X-API-Key", self._api_key)
        with urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())
