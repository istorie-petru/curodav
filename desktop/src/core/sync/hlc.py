"""Hybrid Logical Clock (ARCHITECTURE.md §7.2).

Ported from app/lib/core/sync/hlc.dart. Encoded as a fixed-width,
lexicographically sortable string: `<millis 15 digits>:<counter 4 hex>:<deviceId>`.
String comparison == causal comparison. Test exhaustively, never touch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, order=True)
class Hlc:
    millis: int
    counter: int
    device_id: str

    def __post_init__(self) -> None:
        assert 0 <= self.counter <= 0xFFFF

    @staticmethod
    def parse(s: str) -> Hlc:
        parts = s.split(":")
        if len(parts) < 3:
            raise ValueError(f"Invalid HLC: {s}")
        return Hlc(
            millis=int(parts[0]),
            counter=int(parts[1], 16),
            device_id=":".join(parts[2:]),
        )

    def __str__(self) -> str:
        return (
            f"{str(self.millis).zfill(15)}:"
            f"{hex(self.counter)[2:].zfill(4)}:"
            f"{self.device_id}"
        )

    def __repr__(self) -> str:
        return f"Hlc({self})"


class HlcClock:
    _wall_clock: ClassVar = time.time_ns

    def __init__(self, device_id: str, restore: Hlc | None = None) -> None:
        self.device_id = device_id
        self._last = restore if restore is not None else Hlc(0, 0, device_id)

    @property
    def last(self) -> Hlc:
        return self._last

    def send(self) -> Hlc:
        wall = self._wall_millis()
        if wall > self._last.millis:
            self._last = Hlc(wall, 0, self.device_id)
        else:
            self._last = Hlc(self._last.millis, self._last.counter + 1, self.device_id)
        return self._last

    def receive(self, remote: Hlc) -> Hlc:
        wall = self._wall_millis()
        max_millis = max(wall, self._last.millis, remote.millis)
        if max_millis == self._last.millis and max_millis == remote.millis:
            counter = max(self._last.counter, remote.counter) + 1
        elif max_millis == self._last.millis:
            counter = self._last.counter + 1
        elif max_millis == remote.millis:
            counter = remote.counter + 1
        else:
            counter = 0
        self._last = Hlc(max_millis, counter, self.device_id)
        return self._last

    def _wall_millis(self) -> int:
        return self._wall_clock() // 1_000_000
