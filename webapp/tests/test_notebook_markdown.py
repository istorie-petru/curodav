"""Notes as Markdown: blocks and Markdown convert both ways, and frontmatter carries the note's metadata."""

from __future__ import annotations

from src import notebook_markdown as md


def test_headings_paragraphs_and_inline_formatting_round_trip():
    blocks = [
        {"type": "header", "data": {"text": "Plan", "level": 2}},
        {"type": "paragraph", "data": {"text": "A <b>bold</b>, <i>soft</i> and <code class=\"inline-code\">code</code> <a href=\"https://a.org\">link</a>"}},
    ]
    text = md.blocks_to_markdown(blocks)
    assert text == "## Plan\n\nA **bold**, *soft* and `code` [link](https://a.org)\n"
    again = md.markdown_to_blocks(text)
    assert again[0]["data"] == {"text": "Plan", "level": 2}
    assert again[1]["data"]["text"] == 'A <b>bold</b>, <i>soft</i> and <code class="inline-code">code</code> <a href="https://a.org">link</a>'


def test_lists_nested_ordered_and_checklists_round_trip():
    items = [{"content": "one", "meta": {}, "items": [{"content": "nested", "meta": {}, "items": []}]}, {"content": "two", "meta": {}, "items": []}]
    text = md.blocks_to_markdown([{"type": "list", "data": {"style": "unordered", "items": items}}])
    assert text == "- one\n  - nested\n- two\n"
    parsed = md.markdown_to_blocks(text)[0]["data"]
    assert parsed["style"] == "unordered" and parsed["items"][0]["items"][0]["content"] == "nested"
    tasks = md.markdown_to_blocks("- [x] done\n- [ ] todo\n")[0]["data"]
    assert tasks["style"] == "checklist" and [i["meta"]["checked"] for i in tasks["items"]] == [True, False]
    assert md.blocks_to_markdown([{"type": "list", "data": tasks}]) == "- [x] done\n- [ ] todo\n"


def test_quotes_code_rules_and_tables_round_trip():
    text = "> wise words\n\n```python\nprint(1)\n```\n\n---\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    blocks = md.markdown_to_blocks(text)
    assert [b["type"] for b in blocks] == ["quote", "code", "delimiter", "table"]
    assert blocks[1]["data"] == {"code": "print(1)", "language": "python"}
    assert blocks[3]["data"]["content"] == [["a", "b"], ["1", "2"]]
    assert md.blocks_to_markdown(blocks) == "> wise words\n\n```python\nprint(1)\n```\n\n---\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"


def test_unsupported_inline_markup_falls_back_to_plain_text():
    text = md.blocks_to_markdown([{"type": "paragraph", "data": {"text": 'x <span style="color:red">red</span> &amp; y'}}])
    assert text == "x red & y\n"


def test_a_note_carries_its_metadata_in_frontmatter():
    doc = {"uid": "u1", "title": "Ada: notes", "note_type": "person", "is_template": 1, "tags": ["History"],
           "properties": [{"key": "born", "value": "1815"}]}
    text = md.note_to_markdown(doc, [{"type": "paragraph", "data": {"text": "Hi"}}])
    note = md.parse_note(text, "x.md")
    assert note["uid"] == "u1" and note["title"] == "Ada: notes" and note["note_type"] == "person"
    assert note["is_template"] == 1 and note["tags"] == ["History"] and note["properties"] == [{"key": "born", "value": "1815"}]
    assert note["blocks"][0]["data"]["text"] == "Hi"


def test_a_plain_markdown_file_gets_its_title_from_the_first_heading_or_the_filename():
    assert md.parse_note("# Big idea\n\nbody\n", "a.md")["title"] == "Big idea"
    assert md.parse_note("body only\n", "folder/Meeting notes.md")["title"] == "Meeting notes"


def test_foreign_frontmatter_styles_are_understood():
    note = md.parse_note("---\ntitle: Obsidian note\ntags:\n  - a\n  - b\nstatus: draft\n---\ntext\n", "n.md")
    assert note["title"] == "Obsidian note" and note["tags"] == ["a", "b"] and note["properties"] == [{"key": "status", "value": "draft"}]
    assert md.parse_note("---\ntags: [x, y]\n---\nt\n", "n.md")["tags"] == ["x", "y"]


def _marker(note_id, text):
    return f'<sup class="cdx-footnote-ref" data-note-id="{note_id}" data-note="{text}"></sup>'


def test_endnotes_export_as_numbered_markdown_footnotes_in_reading_order():
    blocks = [
        {"type": "paragraph", "data": {"text": "First" + _marker("a", "Source &lt;b&gt;one&lt;/b&gt;") + " and second" + _marker("b", "Two")}},
        {"type": "list", "data": {"style": "unordered", "items": [{"content": "item" + _marker("c", "In a list"), "meta": {}, "items": []}]}},
    ]
    assert md.blocks_to_markdown(blocks) == (
        "First[^1] and second[^2]\n\n- item[^3]\n\n[^1]: Source **one**\n\n[^2]: Two\n\n[^3]: In a list\n")


def test_markdown_footnotes_import_as_endnote_markers():
    blocks = md.markdown_to_blocks("Claim[^src] here.\n\n[^src]: The *source* page\n")
    assert len(blocks) == 1
    text = blocks[0]["data"]["text"]
    assert text.startswith("Claim<sup") and 'class="cdx-footnote-ref"' in text and 'data-note-id="md-src"' in text
    assert "The &lt;i&gt;source&lt;/i&gt; page" in text


def test_endnotes_survive_a_round_trip():
    blocks = [{"type": "paragraph", "data": {"text": "Fact" + _marker("a", "Why") + "."}}]
    again = md.markdown_to_blocks(md.blocks_to_markdown(blocks))
    assert md.blocks_to_markdown(again) == "Fact[^1].\n\n[^1]: Why\n"


def test_a_reference_without_a_definition_stays_plain_text():
    assert md.markdown_to_blocks("Odd[^x] text\n")[0]["data"]["text"] == "Odd[^x] text"


def test_a_timeline_exports_as_a_list_with_its_dates():
    block = {"type": "timeline", "data": {"showDates": True, "items": [
        {"date": "1961", "title": "Wall", "description": "built overnight"}, {"date": "", "title": "End", "description": ""}, {"date": "", "title": "", "description": ""}]}}
    assert md.blocks_to_markdown([block]) == "- 1961: **Wall** built overnight\n- **End**\n"


def test_a_timeline_with_rich_text_exports_as_markdown():
    from src.notebook_markdown import blocks_to_markdown
    out = blocks_to_markdown([{"type": "timeline", "data": {"items": [{"title": "<b>First</b>", "description": "Desc <i>one</i>", "date": ""}]}}])
    assert out == "- **First** *Desc one*" or "First" in out and "<" not in out


def test_a_figure_exports_each_image_then_its_caption_and_credit():
    blocks = [{"type": "image", "data": {
        "images": [{"src": "data:image/png;base64,AA", "alt": "Left"}, {"src": "data:image/png;base64,BB", "alt": "Right"}],
        "caption": "Two views", "credit": "Source: lab"}}]
    out = md.blocks_to_markdown(blocks)
    assert out.startswith("![Left](data:image/png;base64,AA)\n\n![Right](data:image/png;base64,BB)")
    assert "*Two views Source: lab*" in out


def test_a_figure_saved_by_the_old_image_block_still_exports():
    out = md.blocks_to_markdown([{"type": "image", "data": {"url": "data:image/png;base64,AA", "caption": "Old"}}])
    assert "![Old](data:image/png;base64,AA)" in out
