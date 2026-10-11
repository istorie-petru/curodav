"""Authoritative types for Notebook properties: coerce and validate a raw form value against its schema field."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

TRUE_WORDS = {"true", "yes", "1", "on"}
FALSE_WORDS = {"false", "no", "0", "off"}
RESERVED_KEYS = {"title", "note_type"}


def schema_fields(fields: list[dict]) -> list[dict]:
    """The fields that become typed inputs in the modal (title and type have their own columns)."""
    return [f for f in fields if f["key"] not in RESERVED_KEYS]


def input_name(field: dict) -> str:
    return "field__" + field["key"]


def stored_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return [v.strip() for v in (value or "").split(",") if v.strip()]
    return [str(v) for v in data] if isinstance(data, list) else []


def coerce(field: dict, raw: str | list[str]) -> tuple[str, str | None]:
    """Returns (stored value, error). An empty value is always valid; anything else must fit the field's type."""
    kind = field["type"]
    label = field.get("label") or field["key"]
    if kind == "multi-select":
        items = [v.strip() for v in (raw if isinstance(raw, list) else stored_list(raw)) if v and v.strip()]
        options = {o["value"].lower(): o["value"] for o in field.get("options", [])}
        picked: list[str] = []
        for item in items:
            canonical = options.get(item.lower())
            if canonical is None:
                return "", f"{label}: '{item}' is not one of the options"
            if canonical not in picked:
                picked.append(canonical)
        return (json.dumps(picked) if picked else ""), None
    value = (raw if isinstance(raw, str) else (raw[0] if raw else "")).strip()
    if not value:
        return "", None
    if kind == "number":
        try:
            number = Decimal(value.replace(",", "."))
        except InvalidOperation:
            return "", f"{label} must be a number"
        if not number.is_finite():
            return "", f"{label} must be a number"
        text = format(number.normalize(), "f")
        return text, None
    if kind == "date":
        try:
            return date.fromisoformat(value).isoformat(), None
        except ValueError:
            return "", f"{label} must be a date like 2026-10-31"
    if kind == "boolean":
        word = value.lower()
        if word in TRUE_WORDS:
            return "true", None
        if word in FALSE_WORDS:
            return "false", None
        return "", f"{label} must be yes or no"
    if kind == "url":
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "", f"{label} must be a web address starting with http:// or https://"
        return value, None
    if kind == "select":
        for option in field.get("options", []):
            if option["value"].lower() == value.lower():
                return option["value"], None
        return "", f"{label}: '{value}' is not one of the options"
    return value, None


def build_properties(
    fields: list[dict],
    typed: dict[str, str | list[str]],
    free: list[dict],
) -> tuple[list[dict], dict[str, str]]:
    """Typed schema inputs first, then free rows. A free row whose key is a schema key is validated as that
    field (the typed input wins when both are filled). Returns (properties, {input name: error})."""
    by_key = {f["key"].lower(): f for f in schema_fields(fields)}
    items: list[dict] = []
    errors: dict[str, str] = {}
    seen: set[str] = set()
    for field in schema_fields(fields):
        value, error = coerce(field, typed.get(input_name(field), ""))
        if error:
            errors[input_name(field)] = error
        if value:
            items.append({"key": field["key"], "value": value})
        seen.add(field["key"].lower())
    for row in free:
        key = (row.get("key") or "").strip()
        if not key:
            continue
        field = by_key.get(key.lower())
        if field is None:
            items.append({"key": key, "value": (row.get("value") or "").strip()})
        elif (row.get("value") or "").strip() and not any(i["key"] == field["key"] for i in items):
            value, error = coerce(field, row["value"])
            if error:
                errors["property_value"] = error
            elif value:
                items.append({"key": field["key"], "value": value})
    return items, errors
