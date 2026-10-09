"""Readability index for the accent palette (frontend-conventions.md, Color and
readability).

An accent (a label or event colour used as a fill) must stand out against the
page surface in both themes, and the text on it must stay readable. Both are
WCAG contrast ratios: STAND_OUT against the theme's two surfaces, TEXT between
the fill and its text colour. `nudge` finds the nearest fill that meets both,
keeping the hue, lighter on dark themes and darker on light ones.
"""

import colorsys
import re
from pathlib import Path

STYLE_CSS = Path(__file__).resolve().parent / "static" / "style.css"
STAND_OUT = 3.0
TEXT = 4.5
DARK_TEXT = "#1d1d1f"
LIGHT_TEXT = "#ffffff"
SURFACES = {"light": ("#ffffff", "#f2f4f7"), "dark": ("#3e3e3e", "#363636")}


def _rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def luminance(color: str) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def text_for(fill: str) -> str:
    return max((LIGHT_TEXT, DARK_TEXT), key=lambda t: contrast(fill, t))


def stands_out(fill: str, theme: str) -> float:
    return min(contrast(fill, s) for s in SURFACES[theme])


def index(fill: str, theme: str) -> tuple[float, float]:
    """(stand-out ratio, text ratio) of a fill in a theme."""
    return stands_out(fill, theme), contrast(fill, text_for(fill))


def meets(fill: str, theme: str) -> bool:
    out, txt = index(fill, theme)
    return out >= STAND_OUT and txt >= TEXT


def nudge(fill: str, theme: str) -> str:
    """The closest colour to `fill` (same hue and saturation) that meets the index."""
    if meets(fill, theme):
        return fill
    h, light, s = colorsys.rgb_to_hls(*_rgb(fill))
    step = 0.004 if theme == "dark" else -0.004
    for _ in range(250):
        light = min(1.0, max(0.0, light + step))
        r, g, b = colorsys.hls_to_rgb(h, light, s)
        candidate = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
        if meets(candidate, theme):
            return candidate
    raise ValueError(f"no readable {theme} variant of {fill}")


def _theme_blocks(css: str) -> tuple[str, str]:
    marker = '[data-theme="dark"]{'
    dark_at = css.index(marker)
    return css[:dark_at], css[dark_at:]


def accent_fills(css: str | None = None) -> dict[str, dict[str, str]]:
    """{accent: {theme: fill}} as the stylesheet defines them (a dark
    override wins over the shared :root value)."""
    css = css if css is not None else STYLE_CSS.read_text(encoding="utf-8")
    light_css, dark_css = _theme_blocks(css)
    pattern = re.compile(r"--cal-bg-([a-z]+):\s*(#[0-9a-fA-F]{6})")
    light = dict(pattern.findall(light_css))
    dark = {**light, **dict(pattern.findall(dark_css))}
    return {name: {"light": light[name], "dark": dark[name]} for name in light}


def report() -> dict[str, dict[str, tuple[float, float]]]:
    return {
        name: {theme: index(fill, theme) for theme, fill in themes.items()}
        for name, themes in accent_fills().items()
    }


def failures() -> list[str]:
    bad = []
    for name, themes in report().items():
        for theme, (out, txt) in themes.items():
            if out < STAND_OUT or txt < TEXT:
                bad.append(f"{name} on {theme}: stands out {out:.2f}, text {txt:.2f}")
    return bad
