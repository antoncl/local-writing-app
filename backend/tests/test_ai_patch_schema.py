"""#2199: the JSON schema an entry-patch reply must conform to, built from the
SAME `field_contract_stored` descriptors the envelope/ceiling use — never
re-derived from the full field roster."""

from __future__ import annotations

import unittest

from app.services.ai.patch_schema import patch_response_schema

_STORED = [
    {"id": "title", "label": "Title", "type": "text", "options": [], "description": None, "group": None, "proposable": True},
    {"id": "body", "label": "Body", "type": "long_text", "options": [], "description": None, "group": None, "proposable": True},
    {
        "id": "aliases",
        "label": "Aliases",
        "type": "multi_select",
        "options": ["a", "b"],
        "description": None,
        "group": None,
        "proposable": True,
    },
    {"id": "age", "label": "Age", "type": "number", "options": [], "description": None, "group": None, "proposable": True},
    {
        "id": "beats",
        "label": "Beats",
        "type": "list",
        "options": [],
        "description": None,
        "group": None,
        "proposable": True,
        "item_scalar": False,
        "items": [
            {"key": "who", "label": "Who", "type": "text", "options": []},
            {"key": "what", "label": "What", "type": "long_text", "options": []},
        ],
    },
]


def _item(field_id: str, value: dict) -> dict:
    return {
        "type": "object",
        "properties": {"field": {"const": field_id}, "value": value},
        "required": ["field", "value"],
        "additionalProperties": False,
    }


def _value_schemas(schema: dict) -> dict[str, dict]:
    """field id -> its item's value schema."""
    return {
        branch["properties"]["field"]["const"]: branch["properties"]["value"]
        for branch in schema["properties"]["fields"]["items"]["anyOf"]
    }


class PatchResponseSchemaTests(unittest.TestCase):
    def test_create_mode_exact_shape(self) -> None:
        # #2296: fields are an order-free ARRAY of {field, value} items, one
        # anyOf branch per registered field — body included — never an object
        # whose keys a grammar would pin to declaration order.
        schema = patch_response_schema(_STORED, creating=True)
        self.assertEqual(
            schema,
            {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                _item("title", {"type": "string", "minLength": 1}),
                                _item("body", {"type": "string"}),
                                _item("aliases", {"type": "array", "items": {"type": "string"}}),
                                _item("age", {"type": "number"}),
                                _item(
                                    "beats",
                                    {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "who": {"type": "string"},
                                                "what": {"type": "string"},
                                            },
                                        },
                                    },
                                ),
                            ]
                        },
                    },
                },
                "required": ["fields"],
                "additionalProperties": False,
            },
        )

    def test_revise_mode_title_has_no_min_length(self) -> None:
        schema = patch_response_schema(_STORED, creating=False)
        # #2209: a revise may leave the title alone, so no minLength there.
        self.assertEqual(_value_schemas(schema)["title"], {"type": "string"})
        self.assertEqual(_value_schemas(schema)["body"], {"type": "string"})

    def test_no_object_keyed_by_field_id_anywhere_at_the_top(self) -> None:
        # #2296: the only top-level key is "fields", so no sibling can be
        # locked out by having been declared earlier.
        schema = patch_response_schema(_STORED, creating=False)
        self.assertEqual(list(schema["properties"]), ["fields"])
        self.assertEqual(schema["properties"]["fields"]["type"], "array")

    def test_body_not_registered_has_no_body_item(self) -> None:
        stored = [f for f in _STORED if f["id"] != "body"]
        schema = patch_response_schema(stored, creating=True)
        self.assertNotIn("body", _value_schemas(schema))

    def test_item_scalar_list_uses_flat_array(self) -> None:
        stored = [
            {
                "id": "tags",
                "label": "Tags",
                "type": "list",
                "options": [],
                "description": None,
                "group": None,
                "proposable": True,
                "item_scalar": True,
                "items": [{"key": "value", "label": "Value", "type": "text", "options": []}],
            }
        ]
        schema = patch_response_schema(stored, creating=False)
        self.assertEqual(
            _value_schemas(schema)["tags"],
            {"type": "array", "items": {"type": "string"}},
        )

    def test_unknown_type_is_unconstrained(self) -> None:
        stored = [
            {
                "id": "mystery",
                "label": "Mystery",
                "type": "entity_ref",
                "options": [],
                "description": None,
                "group": None,
                "proposable": True,
            }
        ]
        schema = patch_response_schema(stored, creating=False)
        self.assertEqual(_value_schemas(schema)["mystery"], {})


if __name__ == "__main__":
    unittest.main()
