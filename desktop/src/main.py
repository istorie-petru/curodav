"""Command Center — Qt Desktop App entry point.

Usage:
    python -m src.main
    # or after pip install:
    command-center
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Command Center")
    app.setOrganizationName("CommandCenter")

    font = QFont("IBM Plex Sans", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
