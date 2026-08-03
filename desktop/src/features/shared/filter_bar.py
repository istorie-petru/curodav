"""TagFilterBar — horizontal row of tag chips for filtering (PHASE 3).

Embedded above list views (tasks, dashboard, search). Click to toggle
include/exclude. Active filters highlighted with accent color.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QWidget


class TagFilterBar(QScrollArea):
    """Horizontal row of tag chips. Emits `filter_changed(tag_names)` on toggle."""

    filter_changed = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setProperty("class", "filter-bar")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        self._layout = QHBoxLayout(container)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setWidget(container)

        self._chips: dict[str, QLabel] = {}
        self._active: set[str] = set()

    def set_tags(self, tag_names: list[str]) -> None:
        for chip in self._chips.values():
            chip.deleteLater()
        self._chips.clear()
        self._active.clear()

        for name in tag_names:
            chip = QLabel(name)
            chip.setProperty("class", "tag-chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.mousePressEvent = lambda e, n=name: self._toggle(n)
            self._layout.insertWidget(self._layout.count() - 1, chip)
            self._chips[name] = chip

    def _toggle(self, name: str) -> None:
        if name in self._active:
            self._active.discard(name)
            chip = self._chips.get(name)
            if chip:
                chip.setProperty("class", "tag-chip")
                chip.style().unpolish(chip)
                chip.style().polish(chip)
        else:
            self._active.add(name)
            chip = self._chips.get(name)
            if chip:
                chip.setProperty("class", "tag-chip-active")
                chip.style().unpolish(chip)
                chip.style().polish(chip)

        self.filter_changed.emit(sorted(self._active))

    def active_tags(self) -> list[str]:
        return sorted(self._active)

    def clear(self) -> None:
        for name in list(self._active):
            self._toggle(name)
