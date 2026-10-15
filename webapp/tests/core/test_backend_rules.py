"""Core tests for the backend rules (rules/backend-conventions.md): routers hold no SQL, nothing but the clock helper
reads the wall clock, and every route requires a session unless it is allow-listed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from src import auth, main

ROUTERS = Path(__file__).resolve().parents[2] / "src" / "routers"
PUBLIC_ROUTE_PREFIXES = ("/static", "/public/")
PUBLIC_ROUTES = {"/login", "/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _code(path: Path) -> str:
    """The module's source without comments and docstrings, so only real calls are searched."""
    text = re.sub(r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


@pytest.mark.parametrize("router", sorted(ROUTERS.glob("*.py")), ids=lambda p: p.name)
def test_routers_run_no_sql(router):
    assert not re.search(r"\.(execute|executemany|executescript)\(", _code(router)), \
        f"{router.name} must call a db accessor instead of running SQL"


@pytest.mark.parametrize("router", sorted(ROUTERS.glob("*.py")), ids=lambda p: p.name)
def test_routers_do_not_read_the_wall_clock(router):
    assert not re.search(r"date\.today\(\)|datetime\.(now|utcnow)\(|time\.time\(\)", _code(router)), \
        f"{router.name} must use src.clock"


@pytest.fixture(scope="module")
def locked_client(tmp_path_factory):
    import os

    os.environ["CC_DB_PATH"] = str(tmp_path_factory.mktemp("auth") / "cache.sqlite")
    os.environ["CC_AUTH_USERNAME"] = "alice"
    os.environ["CC_AUTH_PASSWORD"] = "s3cret-pass"
    os.environ.pop("CC_SKIP_AUTH", None)
    try:
        with TestClient(main.create_app(), base_url="http://testserver", follow_redirects=False) as client:
            yield client
    finally:
        os.environ.pop("CC_AUTH_USERNAME", None)
        os.environ.pop("CC_AUTH_PASSWORD", None)


def test_every_route_requires_a_session_unless_allow_listed(locked_client):
    open_routes = []
    for route in locked_client.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or {"GET"}
        if not path or "{" in path or path in PUBLIC_ROUTES or path.startswith(PUBLIC_ROUTE_PREFIXES):
            continue
        method = "GET" if "GET" in methods else sorted(methods)[0]
        response = locked_client.request(method, path)
        if response.status_code not in (302, 303, 401, 403) or (
            response.status_code in (302, 303) and "/login" not in response.headers.get("location", "")
            and "/setup" not in response.headers.get("location", "")
        ):
            open_routes.append((method, path, response.status_code))
    assert not open_routes, f"Routes reachable without a session: {open_routes}"


SRC = Path(__file__).resolve().parents[2] / "src"
MAX_MODULE_LINES = 2200
OVERSIZED: set[str] = set()


def test_no_module_is_over_the_size_limit():
    over = {
        str(path.relative_to(SRC)): len(path.read_text(encoding="utf-8").splitlines())
        for path in SRC.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    over = {name: lines for name, lines in over.items() if lines > MAX_MODULE_LINES and name not in OVERSIZED}
    assert not over, f"Split these modules (limit {MAX_MODULE_LINES} lines): {over}"


def test_logging_goes_through_the_one_helper():
    """No print and no ad hoc logger outside `log.py`; the helper hides secret values at runtime."""
    import re

    src = Path(__file__).resolve().parents[2] / "src"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        if path.name == "log.py" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*print\(|logging\.getLogger\(", text, re.M):
            offenders.append(path.name)
    assert not offenders, f"use src/log.py's get_logger: {offenders}"
