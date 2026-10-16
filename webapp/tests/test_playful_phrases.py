"""Playful wording only replaces text when the Terminology setting is playful."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src import db, deps, terminology


def _request(db_path):
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(db_path=db_path, radicale_base_url="")))
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "scheme": "http",
                    "server": ("t", 80), "root_path": "", "headers": [], "app": app})


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "cache.sqlite"
    with db.connect(path):
        pass
    return path


def _phrase(db_path, text):
    token = terminology.current_request.set(_request(db_path))
    try:
        return deps._phrase(text)
    finally:
        terminology.current_request.reset(token)


def test_standard_leaves_text_alone(db_path):
    assert _phrase(db_path, "No tags yet.") == "No tags yet."
    assert _phrase(db_path, "Good evening, Dana") == "Good evening, Dana"


def test_playful_swaps_known_phrases_and_greetings(db_path):
    with db.connect(db_path) as conn:
        db.set_app_meta(conn, deps.TERMINOLOGY_KEY, "playful")
    assert _phrase(db_path, "No tags yet.") == "No tags yet. Nothing here but tumbleweeds"
    assert _phrase(db_path, "Good morning, Dana") == "Rise and shine, Dana"
    assert _phrase(db_path, "Good evening") == "Evening"
    assert _phrase(db_path, "Something unlisted") == "Something unlisted"

