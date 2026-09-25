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


class PatchResponseSchemaTests(unittest.TestCase):
    def test_create_mode_exact_shape(self) -> None:
        schema = patch_response_schema(_STORED, creating=True)
        self.assertEqual(
            schema,
            {
                "type": "object",
                "properties": {
                    "body": {"type": "string"},
                    "fields": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "minLength": 1},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "age": {"type": "number"},
                            "beats": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "who": {"type": "string"},
                                        "what": {"type": "string"},
                                    },
                                },
                            },
                        },
                        "additionalProperties": False,
                        "required": ["title"],
                    },
                },
                "required": ["body", "fields"],
                "additionalProperties": False,
            },
        )

    def test_revise_mode_body_not_required_and_fields_not_required(self) -> None:
        schema = patch_response_schema(_STORED, creating=False)
        self.assertEqual(schema["required"], ["fields"])
        self.assertEqual(schema["properties"]["fields"]["required"], [])
        # body is still an offered property in revise mode, just not required.
        self.assertIn("body", schema["properties"])
        # #2209: a revise may leave the title alone, so no minLength there.
        self.assertEqual(schema["properties"]["fields"]["properties"]["title"], {"type": "string"})

    def test_body_not_registered_has_no_body_property(self) -> None:
        stored = [f for f in _STORED if f["id"] != "body"]
        schema = patch_response_schema(stored, creating=True)
        self.assertNotIn("body", schema["properties"])
        self.assertNotIn("body", schema["required"])

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
            schema["properties"]["fields"]["properties"]["tags"],
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
        self.assertEqual(schema["properties"]["fields"]["properties"]["mystery"], {})


if __name__ == "__main__":
    unittest.main()
