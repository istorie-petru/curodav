import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/core/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.core)
