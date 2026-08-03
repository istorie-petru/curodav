"""Activity feed (REWORK_PLAN Phase 3).

Computed from object history — created_at, updated_at, status changes.
Shown as a chronological list in the dashboard or as a standalone panel.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Object, ObjectStatus


class ActivityEntry(QFrame):
    """A single activity entry in the feed."""

    def __init__(
        self,
        kind: str,
        title: str,
        timestamp: str,
        detail: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "activity-entry")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        kind_map = {
            "created": "+",
            "status_changed": "→",
            "completed": "✓",
            "edited": "✎",
            "overdue": "!",
        }
        icon = QLabel(kind_map.get(kind, "•"))
        icon.setProperty("class", f"activity-icon-{kind}")
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        text_layout = QVBoxLayout()
        text = QLabel(title)
        text.setProperty("class", "activity-title")
        text_layout.addWidget(text)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setProperty("class", "activity-detail")
            text_layout.addWidget(detail_label)

        layout.addLayout(text_layout, 1)

        time_label = QLabel(self._format_time(timestamp))
        time_label.setProperty("class", "activity-time")
        layout.addWidget(time_label)

    @staticmethod
    def _format_time(ts: str) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo if dt.tzinfo else None)
            diff = now - dt
            if diff.total_seconds() < 3600:
                mins = int(diff.total_seconds() / 60)
                return f"{mins}m ago"
            if diff.total_seconds() < 86400:
                hours = int(diff.total_seconds() / 3600)
                return f"{hours}h ago"
            return dt.strftime("%d %b")
        except (ValueError, TypeError):
            return ts


class ActivityFeed(QScrollArea):
    """Chronological activity feed computed from object history."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "activity-feed")

        container = QWidget()
        self.setWidget(container)
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        header = QLabel("Activity")
        header.setProperty("class", "section-title")
        self._layout.addWidget(header)

        self._entries_layout = QVBoxLayout()
        self._entries_layout.setSpacing(2)
        self._layout.addLayout(self._entries_layout)

        self._empty = QLabel("No recent activity")
        self._empty.setProperty("class", "section-empty")
        self._layout.addWidget(self._empty)

        self._layout.addStretch(1)

    def set_objects(self, objects: list[Object]) -> None:
        while self._entries_layout.count():
            item = self._entries_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries: list[tuple[str, str, str, str]] = []

        for o in objects:
            if o.created_at:
                entries.append((
                    "created",
                    f'Created "{o.title}"',
                    o.created_at,
                    o.type.value,
                ))
            if o.updated_at and o.updated_at != o.created_at:
                entries.append((
                    "edited",
                    f'Edited "{o.title}"',
                    o.updated_at,
                    o.type.value,
                ))
            if o.status == ObjectStatus.done and o.updated_at:
                entries.append((
                    "completed",
                    f'Completed "{o.title}"',
                    o.updated_at,
                    "",
                ))
            if o.due_at:
                try:
                    due = date.fromisoformat(o.due_at)
                    if due < date.today() and ObjectStatus.is_open(o.status):
                        entries.append((
                            "overdue",
                            f'Overdue "{o.title}"',
                            o.due_at,
                            f"was due {o.due_at}",
                        ))
                except (ValueError, TypeError):
                    pass

        entries.sort(key=lambda e: e[2], reverse=True)
        entries = entries[:50]

        for kind, title, ts, detail in entries:
            entry = ActivityEntry(kind, title, ts, detail)
            self._entries_layout.addWidget(entry)

        self._empty.setVisible(len(entries) == 0)
