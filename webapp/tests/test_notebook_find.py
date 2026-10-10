"""Find and replace in block JSON touches visible text only."""

from __future__ import annotations

from src import notebook_find as nf


def p(text):
    return {"type": "paragraph", "data": {"text": text}}


def test_find_counts_matches_and_gives_snippets():
    report = nf.find([p("Athens and athens"), p("none here")], "athens")
    assert report.count == 2 and "Athens" in report.snippets[0]


def test_case_and_whole_word_options():
    blocks = [p("cat concat Cat")]
    assert nf.find(blocks, "cat", case=True).count == 2
    assert nf.find(blocks, "cat", whole=True).count == 2
    assert nf.find(blocks, "cat", case=True, whole=True).count == 1


def test_replace_keeps_markup_and_escapes_the_new_text():
    blocks = [p('A <b>bold</b> <a href="x">red</a> &amp; red')]
    new, n = nf.replace(blocks, "red", "<blue>")
    assert n == 2
    assert new[0]["data"]["text"] == 'A <b>bold</b> <a href="x">&lt;blue&gt;</a> &amp; &lt;blue&gt;'
    assert blocks[0]["data"]["text"].count("red") == 2


def test_attributes_are_never_touched():
    blocks = [p('<span data-note="red note">plain</span>')]
    assert nf.replace(blocks, "red", "x")[1] == 0


def test_lists_quotes_callouts_and_tables_are_searched_but_code_and_formulas_are_not():
    blocks = [
        {"type": "list", "data": {"items": [{"content": "red one", "items": [{"content": "red two", "items": []}]}, "red old"]}},
        {"type": "quote", "data": {"text": "red", "caption": "red"}},
        {"type": "callout", "data": {"text": "red"}},
        {"type": "table", "data": {"content": [["red", "=C1&\"red\""], ["x", "<b>red</b>"]]}},
        {"type": "code", "data": {"code": "red"}},
    ]
    new, n = nf.replace(blocks, "red", "blue")
    assert n == 8
    assert new[0]["data"]["items"][0]["items"][0]["content"] == "blue two"
    assert new[0]["data"]["items"][1] == "blue old"
    assert new[3]["data"]["content"] == [["blue", "=C1&\"red\""], ["x", "<b>blue</b>"]]
    assert new[4]["data"]["code"] == "red"


def test_empty_query_changes_nothing():
    assert nf.find([p("x")], "").count == 0
    assert nf.replace([p("x")], "", "y")[1] == 0


def test_routes_preview_then_replace_only_selected(tmp_path):
    import json
    from datetime import datetime, timezone

    from src import db
    from src.routers import notebook as router

    with db.connect(tmp_path / "c.sqlite") as conn:
        now = datetime.now(timezone.utc).isoformat()
        for uid in ("a", "b"):
            db.upsert_notebook_document(conn, {"uid": uid, "title": uid, "content_json": json.dumps({"blocks": [p("red fox")]}),
                                               "document_type": "full", "note_type": "", "created_at": now, "updated_at": now, "tags": []})
        assert [h["uid"] for h in router._find_hits(conn, "red", False, False)] == ["a", "b"]
        result = json.loads(router.find_replace(q="red", replacement="blue", case=False, whole=False, uids=["a"], conn=conn).body)
        assert result["documents"] == 1 and result["replacements"] == 1 and not result["warn"]
        assert "blue" in db.get_notebook_document(conn, "a")["content_json"]
        assert "red" in db.get_notebook_document(conn, "b")["content_json"]
        for i in range(6):
            db.upsert_notebook_document(conn, {"uid": f"m{i}", "title": "m", "content_json": json.dumps({"blocks": [p("red")]}),
                                               "document_type": "full", "note_type": "", "created_at": now, "updated_at": now, "tags": []})
        many = json.loads(router.find_replace(q="red", replacement="x", case=False, whole=False,
                                              uids=["b"] + [f"m{i}" for i in range(6)], conn=conn).body)
        assert many["documents"] == 7 and many["warn"]
