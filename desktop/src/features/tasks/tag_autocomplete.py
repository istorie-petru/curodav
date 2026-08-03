"""Shared tag-name autocomplete for QLineEdit fields.

Wired into the inspector's tag input and the Table view's Tags cell editor
(`table_view.py`) -- anywhere a tag gets typed by name should suggest from
every tag already used elsewhere, per the tag-management rework (2026-07-19,
see features/tags-and-linking.md).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter, QLineEdit

from ..shared.tag_names import known_tags


def install_tag_completer(line_edit: QLineEdit, multi: bool = True) -> QCompleter:
    """Attach a case-insensitive completer sourced from every currently
    known tag name. `multi=True` (the default, used for comma-separated
    fields like the Table view's Tags cell) completes only the fragment
    after the last comma rather than the whole field; single-tag inputs
    (the inspector's "type tag name + Enter" field) can pass `multi=False`
    for plain whole-field completion.
    """
    completer = QCompleter(known_tags(), line_edit)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    line_edit.setCompleter(completer)

    if multi:
        def _insert_completion(text: str) -> None:
            current = line_edit.text()
            parts = current.split(",")
            parts[-1] = f" {text}" if len(parts) > 1 else text
            line_edit.setText(",".join(parts).lstrip())

        completer.activated.connect(_insert_completion)

    return completer
