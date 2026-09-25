# #2199: a JSON schema for the entry-patch envelope, built from the SAME
# `field_contract_stored` descriptors the extraction prompt renders (and the
# post-validate ceiling enforces) — so an Ollama-family provider that supports
# constrained decoding (its native `/api/chat` `format` key) can hold a local
# model to the exact write shape instead of relying on prose instructions
# alone (#2195 wrong shape, #2197 dropped final brace). Cloud providers ignore
# `ChatCall.response_schema`; this schema is deliberately loose on VALUES
# (plain string/number/boolean/array types, no enums or length bounds) — the
# existing validator (`validate_ai_entry_patch_for_type`) stays the authority
# on content, this only pins the outer shape a model must emit.
from __future__ import annotations

from typing import Any

# Descriptor `type` -> JSON-schema value shape. Anything not listed here (an
# unknown/future field type) falls back to `{}` (unconstrained) rather than
# guessing a shape that might reject a legal value.
_SCALAR_SCHEMAS: dict[str, dict[str, Any]] = {
    "text": {"type": "string"},
    "long_text": {"type": "string"},
    "date": {"type": "string"},
    "color": {"type": "string"},
    "select": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
}


def _scalar_schema(field_type: str) -> dict[str, Any]:
    return _SCALAR_SCHEMAS.get(field_type, {})


def _value_schema(field: dict[str, Any]) -> dict[str, Any]:
    """The JSON-schema for one field's value, keyed by descriptor `type`."""
    field_type = field.get("type")
    if field_type in ("multi_select", "entity_ref_list"):
        return {"type": "array", "items": {"type": "string"}}
    if field_type == "list":
        items = field.get("items") or []
        if field.get("item_scalar"):
            member = items[0] if items else {}
            return {"type": "array", "items": _scalar_schema(member.get("type", ""))}
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {m["key"]: _scalar_schema(m.get("type", "")) for m in items},
            },
        }
    return _scalar_schema(field_type or "")


def patch_response_schema(stored: list[dict[str, Any]], *, creating: bool) -> dict[str, Any]:
    """Build the JSON schema an entry-patch reply must conform to, from the
    SAME `stored` descriptor list the envelope was rendered from and the
    commit-time ceiling enforces (ADR-0067 §2/§4) — never re-derived from the
    full field roster, so the schema can't admit a field the chat didn't
    register."""
    ids = {f["id"] for f in stored if isinstance(f, dict) and f.get("id")}
    properties: dict[str, Any] = {}
    required: list[str] = []

    if "body" in ids:
        properties["body"] = {"type": "string"}
        if creating:
            required.append("body")

    field_properties = {
        f["id"]: _value_schema(f) for f in stored if isinstance(f, dict) and f.get("id") != "body"
    }
    fields_required = ["title"] if creating and "title" in field_properties else []
    if fields_required:
        # #2209: required but `""` would still satisfy it, and a nameless draft
        # used to be minted under a placeholder title that prompts contain.
        field_properties["title"] = {**field_properties["title"], "minLength": 1}
    properties["fields"] = {
        "type": "object",
        "properties": field_properties,
        "additionalProperties": False,
        "required": fields_required,
    }
    required.append("fields")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
