"""Core tests for modal inputs (rules/frontend-conventions.md, Inputs): every input has its own label.

The pages are rendered through the real app, so a form built from several partials is checked as the user sees it.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from src import main

MODAL_ROUTES = [
    "/tasks/new", "/events/new", "/contacts/new", "/settings/labels/new", "/habits/new", "/groups/new",
    "/finance/transactions/new", "/settings/finance-accounts/new", "/finance/tags/new", "/notebook/new",
    "/notebook/citations/new", "/notebook/glossary/new", "/settings/notebook/new", "/settings/holidays/new",
    "/settings/time-blocks/new", "/quick/add",
]
SKIPPED_INPUT_TYPES = {"hidden", "radio", "checkbox", "file"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    path = tmp_path_factory.mktemp("core") / "cache.sqlite"
    os.environ["CC_DB_PATH"] = str(path)
    os.environ["CC_SKIP_AUTH"] = "1"
    with TestClient(main.create_app(), base_url="http://127.0.0.1") as client:
        yield client


@pytest.mark.parametrize("route", MODAL_ROUTES)
def test_every_input_in_a_modal_form_has_its_own_label(client, route):
    response = client.get(route)
    assert response.status_code == 200, route
    body = response.text
    start = body.find("modal-body")
    assert start != -1, route
    missing = _label_gaps(body[start:])
    assert not missing, f"{route}: inputs without a label in their field: {missing}"


def _label_gaps(markup: str) -> list[str]:
    from re import finditer

    gaps = []
    for block in markup.split('<div class="field')[1:]:
        # a field block runs to its own end; an input is labelled when a <label> appears before the next field starts
        has_label = "<label" in block.split("</div>")[0] or "<label" in block[:2500]
        for m in finditer(r"<(input|textarea)\b([^>]*)>", block[:2500]):
            attrs = m.group(2)
            if 'type="hidden"' in attrs or 'type="radio"' in attrs or 'type="checkbox"' in attrs or 'type="file"' in attrs or "multiselect" in attrs:
                continue
            if not has_label:
                gaps.append(attrs[:60])
    return gaps
