"""Core tests for what a modal body may contain (rules/modals-and-inputs.md).

The modals are rendered through the real app on seeded data and found by following every `data-modal` link from the
main pages, so a rule broken inside a partial is caught as the user would see it. ALLOWED lists, per rule, the
modal routes that still break it; it only shrinks.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

import pytest
from starlette.testclient import TestClient

SEED = Path(__file__).resolve().parents[2] / "scripts" / "seed_preview.py"
START = [
    "/", "/tasks", "/calendar", "/contacts", "/habits", "/finance/transactions", "/notebook", "/library",
    "/notebook/glossary", "/settings/labels", "/settings/holidays", "/settings/time-blocks", "/settings/finance-accounts",
    "/published-lists", "/quick/add", "/tasks/new", "/events/new", "/contacts/new", "/settings/labels/new", "/habits/new",
    "/groups/new", "/finance/transactions/new", "/settings/finance-accounts/new", "/notebook/new", "/library/new",
    "/notebook/glossary/new", "/settings/notebook/new", "/settings/holidays/new", "/settings/time-blocks/new",
    "/export/modal", "/export/import-modal", "/settings/university", "/groups/University/disciplines/Biology",
    "/settings/university/discipline/new", "/settings/university/evaluation/new?discipline=Biology",
    "/settings/university/slot/new?discipline=Biology", "/settings/university/reading/new?discipline=Biology",
    "/settings/university/homework/new?discipline=Biology", "/settings/university/sheet/Biology",
    "/settings/university/syllabus/Biology", "/settings/profile-photo/upload",
]
# Pages that also open as a modal keep their own layout (modals-and-inputs.md, Modal kinds).
PAGES = (r"/settings(/[a-z-]+)?$", r"/taxonomy", r"/dashboard/customize", r"/library$", r"/library/filters", r"/banners/editor")
ALLOWED: dict[str, set[str]] = {
    "placeholder": set(),
    "hint": set(),
    "checkbox": set(),
    "paragraph": set(),
    "native": set(),
    "unlabelled-button": set(),
    "details": set(),
    "wordy-shelf": set(),
}


def _shape(url: str) -> str:
    path, _, query = url.partition("?")
    keys = sorted(part.split("=")[0] for part in query.split("&") if part)
    return re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}|\d+", "N", path) + ("?" + "&".join(keys) if keys else "")


@pytest.fixture(scope="module")
def modals(tmp_path_factory):
    path = tmp_path_factory.mktemp("modal-body") / "cache.sqlite"
    subprocess.run([sys.executable, str(SEED), str(path)], check=True, capture_output=True)
    os.environ["CC_DB_PATH"] = str(path)
    os.environ["CC_SKIP_AUTH"] = "1"
    modules = os.environ.get("CC_MODULES")
    os.environ["CC_MODULES"] = "university"
    from src import db, main, university_plan
    from src.routers.labels import COLORS

    with db.connect(path) as conn:
        uid = university_plan.save_semester(conn, uid=None, name="Autumn", shelf_name="", start_date="2026-10-05", end_date="2027-02-14", class_end_date="2026-12-18")
        university_plan.save_discipline(conn, university_plan.get_semester(conn, uid), old="", name="Biology", color="green", icon="leaf", teacher_names="Dr Ionescu", colors=COLORS)
        conn.commit()

    found: dict[str, str] = {}
    seen: set[str] = set()
    queue = list(START)
    with TestClient(main.create_app(), base_url="http://127.0.0.1") as client:
        while queue:
            url = queue.pop(0)
            if _shape(url) in seen:
                continue
            seen.add(_shape(url))
            response = client.get(url)
            if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                continue
            text = response.text
            for match in re.finditer(r'<a\b[^>]*\bdata-modal\b[^>]*>|data-modal="(/[^"]+)"', text):
                href = match.group(1) or (re.search(r'href="(/[^"]*)"', match.group(0)) or [None, None])[1]
                if href and "/delete" not in href and _shape(unescape(href)) not in seen:
                    queue.append(unescape(href))
            if 'id="modal-target"' in text and not any(re.fullmatch(p, url.split("?")[0]) for p in PAGES):
                body = text.split('<div class="modal-body">', 1)[-1].split('<div class="modal-footer">', 1)[0]
                found[_shape(url)] = body
    if modules is None:
        os.environ.pop("CC_MODULES")
    else:
        os.environ["CC_MODULES"] = modules
    assert len(found) > 25, sorted(found)
    return found


def _offenders(modals, test) -> set[str]:
    return {url for url, body in modals.items() if test(body)}


def _check(modals, rule, test):
    found = _offenders(modals, test)
    assert not found - ALLOWED[rule], f"{rule} in modal bodies: {sorted(found - ALLOWED[rule])}"
    assert not ALLOWED[rule] - found, f"Fixed, remove from ALLOWED[{rule!r}]: {sorted(ALLOWED[rule] - found)}"


def test_no_placeholder_text(modals):
    _check(modals, "placeholder", lambda b: "placeholder=" in b)


def test_no_hint_text(modals):
    _check(modals, "hint", lambda b: "field-hint" in b or "settings-hint" in b)


def _stray_checkbox(body: str) -> bool:
    for m in re.finditer(r'<input type="checkbox"(?![^>]*role="switch")[^>]*>', body):
        before = body[max(0, m.start() - 300):m.start()]
        if "multiselect-option" in before or "dtr-allday-box" in m.group(0) or "weekday" in before:
            continue
        return True
    return False


def test_yes_or_no_is_a_switch(modals):
    _check(modals, "checkbox", _stray_checkbox)


def test_no_explaining_paragraphs(modals):
    _check(modals, "paragraph", lambda b: len([p for p in re.findall(r"<p\b[^>]*>", b) if 'role="status"' not in p and "modal-sentence" not in p]) > 0 or b.count("modal-sentence") > 1)


def test_no_native_pickers(modals):
    _check(modals, "native", lambda b: re.search(r'<select\b|<datalist\b|type="(date|time|datetime-local|color|range)"', b) is not None)


def test_every_icon_button_and_dropdown_is_named(modals):
    def unnamed(body):
        buttons = re.findall(r'<button\b[^>]*class="[^"]*(?:icon-btn|multiselect-trigger)[^"]*"[^>]*>', body)
        return any("aria-label" not in b for b in buttons)

    _check(modals, "unlabelled-button", unnamed)


def test_a_shelf_is_a_noun(modals):
    """A shelf names the field; a format, an example or an instruction in brackets is hint text in disguise."""
    def wordy(body):
        labels = re.findall(r"<label\b[^>]*>\s*([^<]{1,160})<", body)
        # a unit in brackets, such as "Weight (%)", is part of the name
        return any(re.search(r"\([^)]{4,}\)", label) or "e.g." in label.lower() for label in labels)

    _check(modals, "wordy-shelf", wordy)


def test_details_is_one_section_and_only_on_a_long_form(modals):
    def wrong(body):
        sections = len(re.findall(r'<details class="form-details[ "]', body))
        if not sections:
            return False
        nested = re.search(r'<details class="form-details[^"]*"[^>]*>(?:(?!</details>).)*<details class="form-details', body, re.S)
        forms = max(1, body.count("<form"))
        return bool(nested) or sections > forms or body.count('class="field') < 6

    _check(modals, "details", wrong)
