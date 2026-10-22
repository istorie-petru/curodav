"""Core tests for the installable shell: the manifest is valid, its icons exist,
and the service worker only precaches files that exist."""

import json
import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
STATIC_DIR = SRC_DIR / "static"


def _manifest() -> dict:
    return json.loads((STATIC_DIR / "manifest.webmanifest").read_text())


def test_manifest_is_valid_and_installable():
    manifest = _manifest()
    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_every_manifest_icon_exists_on_disk():
    for icon in _manifest()["icons"]:
        assert icon["src"].startswith("/static/")
        assert (STATIC_DIR / icon["src"][len("/static/"):]).exists(), icon["src"]


def test_precache_list_only_names_assets_that_exist():
    script = (STATIC_DIR / "sw.js").read_text()
    match = re.search(r"SHELL_ASSETS\s*=\s*\[(.*?)\];", script, re.S)
    assert match, "couldn't find SHELL_ASSETS in sw.js"
    urls = [u for u in re.findall(r'"(/[^"]+)"', match.group(1)) if u != "/manifest.webmanifest"]
    assert urls, "SHELL_ASSETS parsed empty"
    for url in urls:
        assert url.startswith("/static/"), url
        assert (STATIC_DIR / url[len("/static/"):]).exists(), url


def test_every_label_icon_exists_in_the_sprite():
    from src.routers import labels

    sprite = (SRC_DIR / "templates" / "_icons_sprite.html").read_text()
    sprite_ids = set(re.findall(r'id="icon-([a-z0-9-]+)"', sprite))
    missing = set(labels.LABEL_ICONS) - sprite_ids
    assert not missing, f"icons referenced but not in the sprite: {missing}"


def test_scripts_never_set_a_style_attribute():
    """The CSP blocks style attributes; a hidden <svg> given one by script showed up 150px tall and brought back the page scrollbar."""
    offenders = [p.name for p in STATIC_DIR.glob("*.js") if re.search(r"setAttribute\(\s*[\"']style[\"']", p.read_text())]
    assert offenders == []


def test_script_bundles_are_current():
    """Pages load three joined script files; edit the source scripts, then run scripts/build_static_bundle.py."""
    import importlib.util

    path = STATIC_DIR.parent.parent / "scripts" / "build_static_bundle.py"
    spec = importlib.util.spec_from_file_location("build_static_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stale = [name for name, text in module.build().items() if (STATIC_DIR / name).read_text() != text]
    assert stale == [], f"stale bundles: {stale}; run scripts/build_static_bundle.py"
