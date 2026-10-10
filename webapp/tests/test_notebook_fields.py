"""Frontmatter types are authoritative: each schema field coerces and validates its value on save."""

from __future__ import annotations

import json

import pytest

from src import notebook_fields as nf


def field(kind, key="f", required=False, options=()):
    return {"key": key, "label": key.title(), "type": kind, "required": required,
            "options": [{"value": o} for o in options]}


@pytest.mark.parametrize("kind,raw,expected", [
    ("text", "  hi ", "hi"),
    ("number", "3,50", "3.5"),
    ("number", "12", "12"),
    ("date", "2026-10-31", "2026-10-31"),
    ("boolean", "Yes", "true"),
    ("boolean", "off", "false"),
    ("url", "https://a.org/x", "https://a.org/x"),
    ("select", "draft", "Draft"),
])
def test_valid_values_are_normalised(kind, raw, expected):
    assert nf.coerce(field(kind, options=["Draft", "Done"]), raw) == (expected, None)


@pytest.mark.parametrize("kind,raw", [
    ("number", "abc"), ("number", "nan"), ("date", "31/10/2026"), ("date", "2026-02-30"),
    ("boolean", "maybe"), ("url", "example.org"), ("url", "javascript:alert(1)"), ("select", "Other"),
])
def test_invalid_values_report_an_error(kind, raw):
    value, error = nf.coerce(field(kind, options=["Draft"]), raw)
    assert value == "" and error


def test_required_blank_is_an_error_and_optional_blank_is_fine():
    assert nf.coerce(field("text", required=True), "  ")[1] == "F is required"
    assert nf.coerce(field("number"), "") == ("", None)


def test_multi_select_is_stored_as_a_json_list_without_duplicates():
    f = field("multi-select", options=["A", "B"])
    assert nf.coerce(f, ["a", "B", "A"]) == (json.dumps(["A", "B"]), None)
    assert nf.coerce(f, ["C"])[1]
    assert nf.stored_list('["A", "B"]') == ["A", "B"]


def test_build_properties_merges_typed_and_free_rows():
    fields = [field("number", key="year", required=True), field("text", key="title"), field("text", key="note")]
    items, errors = nf.build_properties(
        fields, {"field__year": "1999", "field__note": ""},
        [{"key": "Year", "value": "2000"}, {"key": "DOI", "value": "10.1/x"}, {"key": "", "value": "x"}],
    )
    assert items == [{"key": "year", "value": "1999"}, {"key": "DOI", "value": "10.1/x"}] and errors == {}


def test_build_properties_validates_a_free_row_with_a_schema_key_and_flags_missing_required():
    fields = [field("number", key="year")]
    _, errors = nf.build_properties(fields, {}, [{"key": "year", "value": "soon"}])
    assert errors == {"property_value": "Year must be a number"}
    _, errors = nf.build_properties([field("text", key="a", required=True)], {}, [])
    assert errors == {"field__a": "A is required"}


def test_the_save_route_enforces_types(tmp_path):
    from datetime import datetime, timezone

    from src import db
    from src.routers import notebook as router

    with db.connect(tmp_path / "c.sqlite") as conn:
        now = datetime.now(timezone.utc).isoformat()
        db.upsert_notebook_document(conn, {"uid": "d", "title": "T", "content_json": "{}", "document_type": "full",
                                           "note_type": "", "created_at": now, "updated_at": now, "tags": []})
        db.upsert_notebook_field_config(conn, {"key": "year", "label": "Year", "type": "number", "required": 1})

        def save(typed, header=None):
            return router.update_document_properties(
                "d", title="T", note_type="", note_type_new="", tags_labels=[], property_key=[], property_value=[],
                typed=typed, x_requested_with=header, conn=conn)

        bad = save({"field__year": ["soon"]}, "fetch")
        assert bad.status_code == 422 and "Year must be a number" in bad.body.decode()
        assert "error=" in save({"field__year": [""]}).headers["location"]
        assert save({"field__year": ["1999"]}, "fetch").status_code == 200
        assert db.get_notebook_document(conn, "d")["properties"][0]["value"] == "1999"
