"""The unknown-schema-key walker (#2217) — a pure function over raw YAML
mappings, tested independent of the project/layer machinery it is hooked
into (`test_declared_chain.py` / `lifecycle.py` cover the integration)."""

from __future__ import annotations

import unittest

from app.models import MetadataSchema
from app.services.project.schema_unknown_keys import (
    unknown_key_warning,
    unknown_schema_keys,
)


class FlatUnknownKeyTests(unittest.TestCase):
    def test_a_flat_unknown_key_is_reported(self) -> None:
        hits = unknown_schema_keys(MetadataSchema, {"version": 1, "optoins": []})
        self.assertEqual(hits, [("", "optoins")])

    def test_a_known_top_level_key_is_not_reported(self) -> None:
        hits = unknown_schema_keys(MetadataSchema, {"version": 1, "fields": {}})
        self.assertEqual(hits, [])


class NestedUnknownKeyTests(unittest.TestCase):
    def test_a_nested_unknown_key_under_picker_config_is_reported_with_its_path(self) -> None:
        data = {
            "fields": {
                "companion": {
                    "name": "Companion",
                    "type": "entity_ref",
                    "picker_config": {"kinds": ["lore"]},
                }
            }
        }
        hits = unknown_schema_keys(MetadataSchema, data)
        self.assertEqual(hits, [("fields.companion.picker_config", "kinds")])

    def test_the_retired_kinds_key_gets_a_sources_hint(self) -> None:
        message = unknown_key_warning(
            "metadata.schema.yaml", "fields.companion.picker_config", "kinds"
        )
        self.assertIn("has an unknown key `kinds`", message)
        self.assertIn("Did you mean `sources`?", message)

    def test_entry_types_under_picker_config_also_gets_the_sources_hint(self) -> None:
        message = unknown_key_warning(
            "metadata.schema.yaml", "fields.companion.picker_config", "entry_types"
        )
        self.assertIn("Did you mean `sources`?", message)

    def test_a_plain_unknown_key_gets_no_hint(self) -> None:
        message = unknown_key_warning("metadata.schema.yaml", "", "optoins")
        self.assertEqual(
            message,
            "metadata.schema.yaml: has an unknown key `optoins`; it is ignored.",
        )


class ListAndDictRecursionTests(unittest.TestCase):
    def test_an_unknown_key_on_a_list_member_is_reported_with_its_index(self) -> None:
        data = {
            "groups": {
                "gmo": {
                    "name": "GMO",
                    "members": [
                        {"key": "goal", "name": "Goal", "type": "text"},
                        {"key": "obstacle", "name": "Obstacle", "typ": "text"},
                    ],
                }
            }
        }
        hits = unknown_schema_keys(MetadataSchema, data)
        self.assertEqual(hits, [("groups.gmo.members[1]", "typ")])

    def test_an_unknown_key_on_a_dict_member_is_reported_with_its_key(self) -> None:
        data = {
            "entry_types": {
                "lore:character": {
                    "name": "Character",
                    "kind": "lore",
                    "abstract": False,
                    "displaay_order": ["title"],
                }
            }
        }
        hits = unknown_schema_keys(MetadataSchema, data)
        self.assertEqual(hits, [("entry_types.lore:character", "displaay_order")])


class ConsumedExtraKeyTests(unittest.TestCase):
    def test_display_order_is_a_consumed_key_not_an_unknown_one(self) -> None:
        """`display_order` is read straight off the raw entry_type dict by
        `_resolve_metadata_schema_inheritance` (#89) and never lands on the
        `EntryTypeDefinition` model — a legitimately-authored key, not a typo."""
        data = {
            "entry_types": {
                "manuscript:scene": {
                    "name": "Scene",
                    "kind": "manuscript",
                    "abstract": False,
                    "display_order": ["title", "pov"],
                }
            }
        }
        hits = unknown_schema_keys(MetadataSchema, data)
        self.assertEqual(hits, [])


class CleanSchemaTests(unittest.TestCase):
    def test_a_clean_default_schema_produces_no_warnings(self) -> None:
        from app.services.project.default_schema import DEFAULT_METADATA_SCHEMA

        hits = unknown_schema_keys(MetadataSchema, DEFAULT_METADATA_SCHEMA)
        self.assertEqual(hits, [])
