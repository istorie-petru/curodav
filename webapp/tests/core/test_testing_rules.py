"""Core tests for the testing conventions (rules/testing-conventions.md).

A test never asserts on the text of CSS, template or script source. Reading a
file the test itself wrote is fine. LEGACY_SOURCE_TEXT_TESTS is empty: the rule
is done.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
SOURCE_READ = re.compile(r"(?i)(?:read_text\(|open\().*(?:\bsrc\b|static|templates)|(?:static|templates).*read_text\(")

LEGACY_SOURCE_TEXT_TESTS: set[str] = set()


def _files_reading_source() -> set[str]:
    found = set()
    for path in TESTS_DIR.rglob("test_*.py"):
        if path.parent.name == "core":
            continue
        if any(SOURCE_READ.search(line) for line in path.read_text().splitlines()):
            found.add(path.name)
    return found


def test_no_new_test_asserts_on_source_text():
    offenders = _files_reading_source() - LEGACY_SOURCE_TEXT_TESTS
    assert not offenders, f"Tests must not read source files: {sorted(offenders)}"


def test_legacy_list_has_no_stale_entries():
    stale = LEGACY_SOURCE_TEXT_TESTS - _files_reading_source()
    assert not stale, f"Remove from LEGACY_SOURCE_TEXT_TESTS (fixed): {sorted(stale)}"
