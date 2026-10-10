"""Editor text tools: markdown paste conversion (run under node) and the editor page wiring."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from src import db
from src.routers import notebook as notebook_router

MARKDOWN_JS = Path(__file__).resolve().parent.parent / "src" / "static" / "notebook" / "notebook_markdown.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def convert(markdown: str) -> list[dict]:
    script = "console.log(JSON.stringify(require(process.argv[1]).toBlocks(process.argv[2])))"
    out = subprocess.run(["node", "-e", script, str(MARKDOWN_JS), markdown], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def looks_like_markdown(text: str) -> bool:
    script = "console.log(require(process.argv[1]).looksLikeMarkdown(process.argv[2]))"
    out = subprocess.run(["node", "-e", script, str(MARKDOWN_JS), text], capture_output=True, text=True, check=True)
    return out.stdout.strip() == "true"


@node
class TestMarkdownPaste:
    def test_headings_become_header_blocks_with_their_level(self):
        assert convert("## Two") == [{"type": "header", "data": {"text": "Two", "level": 2}}]

    def test_inline_markers_become_formatting_and_text_is_escaped(self):
        block = convert("a **b** *c* ~~d~~ `e` <x> [f](https://x.org)")[0]
        assert block["data"]["text"] == (
            'a <b>b</b> <i>c</i> <s>d</s> <code class="inline-code">e</code> &lt;x&gt; <a href="https://x.org">f</a>'
        )

    def test_code_inside_backticks_is_not_formatted(self):
        assert convert("`**x**`")[0]["data"]["text"] == '<code class="inline-code">**x**</code>'

    def test_nested_lists_keep_their_depth_and_style(self):
        block = convert("- a\n  - b\n- c")[0]
        assert block["data"]["style"] == "unordered"
        assert [i["content"] for i in block["data"]["items"]] == ["a", "c"]
        assert block["data"]["items"][0]["items"][0]["content"] == "b"

    def test_ordered_list(self):
        assert convert("1. x\n2. y")[0]["data"]["style"] == "ordered"

    def test_fenced_code_keeps_its_language_and_lines(self):
        assert convert("```py\nprint(1)\nprint(2)\n```") == [
            {"type": "code", "data": {"code": "print(1)\nprint(2)", "language": "py"}}]

    def test_quote_table_and_rule(self):
        blocks = convert("> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---")
        assert [b["type"] for b in blocks] == ["quote", "table", "delimiter"]
        assert blocks[1]["data"]["content"] == [["a", "b"], ["1", "2"]]

    def test_lines_of_one_paragraph_join_and_blank_lines_split(self):
        assert [b["data"]["text"] for b in convert("one\ntwo\n\nthree")] == ["one two", "three"]

    @pytest.mark.parametrize("text, expected", [
        ("# Heading", True), ("- item", True), ("some **bold** text", True), ("just plain words", False),
        ("a - b and 3.5 here", False),
    ])
    def test_only_markdown_looking_text_is_converted(self, text, expected):
        assert looks_like_markdown(text) is expected


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "cache.sqlite") as c:
        yield c


def _request(path):
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
                    "server": ("testserver", 80), "root_path": "", "headers": []})


class TestEditorPage:
    def _page(self, conn):
        now = datetime.now(timezone.utc).isoformat()
        db.upsert_notebook_document(conn, {"uid": "d1", "title": "Doc", "content_json": '{"blocks": []}',
                                           "document_type": "full", "note_type": "", "created_at": now,
                                           "updated_at": now, "tags": []})
        return notebook_router.document_page(uid="d1", request=_request("/notebook/d1"), conn=conn).body.decode()

    def test_the_page_loads_the_text_tools_and_has_no_save_status(self, conn):
        body = self._page(conn)
        for script in ("notebook_inline.js", "notebook_block_tunes.js", "notebook_markdown.js", "notebook_inline.css",
                       "notebook_table_model.js", "notebook_table.js", "notebook_table.css", "notebook_mentions.js",
                       "notebook_mentions.css", "notebook_floating.js"):
            assert script in body
        assert "notebook-save-status" not in body
        assert "vendor/table" not in body

    def test_undo_script_loads_after_the_vendored_undo(self, conn):
        body = self._page(conn)
        assert body.index("vendor/undo.umd.js") < body.index("notebook/notebook_undo.js") < body.index("notebook/notebook_editor.js")


class TestEndnotes:
    def _page(self, conn):
        now = datetime.now(timezone.utc).isoformat()
        db.upsert_notebook_document(conn, {"uid": "d1", "title": "Doc", "content_json": '{"blocks": []}',
                                           "document_type": "full", "note_type": "", "created_at": now,
                                           "updated_at": now, "tags": []})
        return notebook_router.document_page(uid="d1", request=_request("/notebook/d1"), conn=conn).body.decode()

    def test_endnotes_cannot_be_created_from_the_slash_menu(self, conn):
        editor_js = (Path(MARKDOWN_JS).parent / "notebook_editor.js").read_text()
        footnotes_js = (Path(MARKDOWN_JS).parent / "notebook_footnotes.js").read_text()
        assert "footnoteInsert" not in editor_js
        assert "NotebookFootnoteBlock" not in footnotes_js
