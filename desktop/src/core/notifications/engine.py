"""Notification engine for reminders (REWORK_PLAN Phase 3).

Periodically checks for overdue/due-soon items and shows tray notifications.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from ..models import Object, ObjectStatus


class NotificationEngine:
    """Checks for items needing attention and fires tray notifications."""

    def __init__(
        self,
        tray_icon: QSystemTrayIcon | None = None,
        notify: Callable[[str, str], None] | None = None,
        interval_s: int = 300,
    ) -> None:
        self._tray = tray_icon
        self._notify = notify or self._default_notify
        self._interval = interval_s
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._last_seen: set[str] = set()

    def start(self) -> None:
        self._timer.start(self._interval * 1000)

    def stop(self) -> None:
        self._timer.stop()

    def check_now(self, objects: list[Object]) -> None:
        self._check_with(objects)

    def _check(self) -> None:
        pass

    def _check_with(self, objects: list[Object]) -> None:
        today = date.today()
        overdue = []
        due_soon = []

        for o in objects:
            if not o.due_at or not ObjectStatus.is_open(o.status):
                continue
            try:
                due = date.fromisoformat(o.due_at)
            except (ValueError, TypeError):
                continue
            if o.id in self._last_seen:
                continue
            if due < today:
                overdue.append(o)
            elif due == today or due == today + timedelta(days=1):
                due_soon.append(o)

        for o in overdue:
            self._notify(
                "Overdue",
                f'"{o.title}" was due {o.due_at}',
            )
            self._last_seen.add(o.id)

        for o in due_soon:
            label = "Due today" if o.due_at == today.isoformat() else "Due tomorrow"
            self._notify(
                label,
                f'"{o.title}" — {o.due_at}',
            )
            self._last_seen.add(o.id)

    def _default_notify(self, title: str, message: str) -> None:
        if self._tray:
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def reset_seen(self) -> None:
        self._last_seen.clear()
