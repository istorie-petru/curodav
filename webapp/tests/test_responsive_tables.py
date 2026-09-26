"""Responsive tables (2026-09-24, plans/ui-cleanup-2026-09.md's
"Responsive tables" item): the main list-page tables opt into a named
`rtable` query container (`.table-responsive`) and tag low-priority
columns `.col-opt-1` (drops first) / `.col-opt-2` (drops next) on BOTH the
header `<th>` and every body `<td>` of that column. The browser-side
behavior was verified live with Playwright; what can silently break
without a browser is the header/body tagging drifting apart -- a `<th>`
hidden while its column's `<td>`s stay visible shifts every later cell
under the wrong header. These tests pin that alignment, column by column.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
_TEMPLATES = _SRC / "templates"


def _read(name: str) -> str:
    return (_TEMPLATES / name).read_text()


def _opt(tag: str) -> str | None:
    m = re.search(r"col-opt-(\d)", tag)
    return m.group(0) if m else None


def _cells(fragment: str, cell: str) -> list[str | None]:
    return [_opt(t) for t in re.findall(rf"<{cell}\b[^>]*>", fragment)]


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def _thead(fragment: str) -> list[str | None]:
    return _cells(_between(fragment, "<thead>", "</thead>"), "th")


def _first_body_row(fragment: str) -> list[str | None]:
    body = fragment[fragment.index("<tbody"):]
    return _cells(_between(body, "<tr", "</tr>"), "td")


def _macro(text: str, name: str) -> str:
    return _between(text, "{% macro " + name, "{% endmacro %}")


class TestCss:
    def test_container_and_tiers_defined(self):
        css = (_SRC / "static" / "style.css").read_text()
        assert ".table-responsive{container:rtable / inline-size;}" in css
        assert "@container rtable (max-width:720px){ .col-opt-1{display:none;} }" in css
        assert "@container rtable (max-width:520px){ .col-opt-2{display:none;} }" in css


class TestWrappersOptIn:
    @pytest.mark.parametrize(
        "template,wrapper",
        [
            ("_tasks_body.html", '<div id="task-table" class="card table-scroll table-responsive task-group-card">'),
            ("labels_manage.html", '<div class="card table-scroll table-responsive" id="labels-table-wrapper">'),
            ("settings_holidays.html", '<div class="card table-scroll table-responsive" id="holidays-table-wrapper">'),
            ("settings_time_blocks.html", '<div class="card table-scroll table-responsive" id="time-block-table-wrapper">'),
            ("published_lists.html", '<div class="card table-scroll table-responsive">'),
        ],
    )
    def test_wrapper_is_query_container(self, template, wrapper):
        assert wrapper in _read(template)


class TestHeaderBodyAlignment:
    def test_tasks_table(self):
        body = _read("_tasks_body.html")
        main = _between(body, '<div id="task-table"', "</table>")
        header = _thead(main)
        assert header == [None, None, "col-opt-2", None, "col-opt-1", None]
        assert _cells(_macro(_read("_task_row.html"), "task_row"), "td") == header


    def test_labels_table(self):
        text = _read("_labels_table_body.html")
        header = _thead(text[text.index('<table class="entity-table labels-table">'):])
        assert header == [None, None, "col-opt-2", None]
        assert _cells(_macro(text, "_group_row"), "td") == header
        assert _cells(_macro(text, "_label_row"), "td") == header

    @pytest.mark.parametrize(
        "template,expected",
        [
            ("settings_holidays.html", [None, None, "col-opt-2", None, None]),
            ("settings_time_blocks.html", [None, None, "col-opt-2", None, None, None]),
            ("published_lists.html", [None, "col-opt-2", "col-opt-1", None, None, None]),
        ],
    )
    def test_inline_row_tables(self, template, expected):
        text = _read(template)
        assert _thead(text) == expected
        assert _first_body_row(text) == expected
