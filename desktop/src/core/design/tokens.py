"""Native theme integration.

Replaces the old OKLCH/Density/Shape/Accent token system (removed 2026-07-17).
That system computed a full custom color palette but `MainWindow._generate_qss`
never actually referenced any of it -- the generated stylesheet hardcoded a
fixed macOS-style dark palette (literal hex colors, "-apple-system" font,
macOS traffic-light window buttons) regardless of any setting. Concretely:
Density and Shape were saved to settings.json and read back nowhere at all;
Theme (light/dark) and Accent were computed into a `ThemeTokens` instance
that `_generate_qss` received as an argument and then never read. None of it
had any visible effect, and the hardcoded result looked nothing like a native
Linux/Plasma app regardless.

The replacement: don't carry a second color system at all. Pull colors from
the widget's live `QPalette`, which Qt populates from the desktop's actual
theme (Breeze/Breeze Dark on Plasma, Adwaita on GNOME, etc.) via the platform
theme plugin. `palette(window)`, `palette(base)`, `palette(highlight)`, and
so on are real Qt Style Sheet functions -- Qt resolves them against the
current QPalette at paint time, so switching the system theme (including
live, via QGuiApplication.styleHints().colorSchemeChanged) updates the app
without any custom logic. Only a handful of semantic status colors
(danger/warning/success) are still hardcoded, because "overdue" should mean
the same shade of red in light or dark mode and QPalette has no role for
that -- but even those are chosen to work *with* the active theme's
lightness, not against it.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget


def is_dark(widget: QWidget) -> bool:
    """True if the widget's active palette is a dark theme.

    Judged by the lightness of the window background, which is how Qt/KDE
    itself tells light and dark color schemes apart -- no separate "theme
    mode" setting needed, this just asks the palette what it already is.
    """
    return widget.palette().color(QPalette.ColorRole.Window).lightnessF() < 0.5


def semantic_colors(dark: bool) -> dict[str, str]:
    """Status colors that must stay legible regardless of theme.

    Danger/warning/success need to read as "danger/warning/success" in both
    light and dark mode, which QPalette can't give us (there's no
    "destructive" role) -- so these are the one deliberate exception to
    "everything comes from the palette". Tuned per mode so they stay
    readable against whatever background QPalette.Window actually is.
    """
    if dark:
        return {"danger": "#FF6B6B", "warning": "#F5C063", "success": "#6BCB77"}
    return {"danger": "#C62828", "warning": "#B36B00", "success": "#2E7D32"}


FONT_FAMILIES = {
    "mono": "'IBM Plex Mono', 'Cascadia Code', 'Fira Code', monospace",
}
