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
#
# #2296: the fields are an ARRAY of `{"field": <id>, "value": ...}` items, not
# an object keyed by id. Ollama compiles the schema to a grammar that fixes an
# object's keys to their DECLARED order (each skippable, never reorderable), so
# a model that wrote the last-declared field first could no longer emit any
# other — it either dropped them or smuggled them into that field's string as
# escaped JSON. Array items carry no order, so the model writes fields in any
# order it likes. `body` is one of the items for the same reason: as a sibling
# key of "fields" it could only ever come first.
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


def _item_schema(field_id: str, value: dict[str, Any]) -> dict[str, Any]:
    """One `{"field": <id>, "value": ...}` item, its value typed for that id."""
    return {
        "type": "object",
        "properties": {"field": {"const": field_id}, "value": value},
        "required": ["field", "value"],
        "additionalProperties": False,
    }


def patch_response_schema(stored: list[dict[str, Any]], *, creating: bool) -> dict[str, Any]:
    """Build the JSON schema an entry-patch reply must conform to, from the
    SAME `stored` descriptor list the envelope was rendered from and the
    commit-time ceiling enforces (ADR-0067 §2/§4) — never re-derived from the
    full field roster, so the schema can't admit a field the chat didn't
    register.

    An array can't require a particular member without `contains`, which the
    grammar compiler doesn't support, so create mode no longer forces title or
    body into the reply here — the create path refuses a titleless draft at
    accept (`treeActions.createDraft`, #2209) and the envelope asks for the
    title. A proposed create-mode title must still be non-empty."""
    items: list[dict[str, Any]] = []
    for f in stored:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        field_id = f["id"]
        value = {"type": "string"} if field_id == "body" else _value_schema(f)
        if creating and field_id == "title":
            # #2209: a nameless draft used to be minted under a placeholder
            # title that prompts contain.
            value = {**value, "minLength": 1}
        items.append(_item_schema(field_id, value))

    return {
        "type": "object",
        "properties": {"fields": {"type": "array", "items": {"anyOf": items}}},
        "required": ["fields"],
        "additionalProperties": False,
    }
