"""Image editor aspect-ratio lock (2026-09-24, plans/ui-cleanup-2026-09.md
item 16): static/avatar_cropper.js gives each upload kind exactly one
enforced ratio -- avatars 1:1, banners 5:1 -- with no Free/4:3/16:9 preset
buttons left to pick a different one. Drag behavior (ratio held through
every handle, box capped at the canvas edge, output exactly the ratio) was
verified live with Playwright; this pins the source-level contract so a
preset toolbar or a free-form ratio can't quietly come back.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS = (Path(__file__).resolve().parent.parent / "src" / "static" / "avatar_cropper.js").read_text()


def _kind_block(kind: str) -> str:
    start = _JS.index(f"    {kind}: {{")
    return _JS[start:_JS.index("\n    },", start)]


def test_avatar_locked_square():
    assert re.search(r"^\s*ratio: 1,$", _kind_block("avatar"), re.M)


def test_banner_locked_five_to_one():
    assert re.search(r"^\s*ratio: 5,$", _kind_block("banner"), re.M)


def test_no_ratio_presets_or_free_mode():
    assert "RATIOS" not in _JS
    assert "data-ratio" not in _JS
    assert "setRatio" not in _JS
    assert "defaultRatio" not in _JS
    assert 'free: null' not in _JS


def test_output_height_derived_from_locked_ratio():
    assert "out.height = Math.max(1, Math.round(out.width / state.ratio));" in _JS
