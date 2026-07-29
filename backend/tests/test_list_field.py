"""List field type (#698, ADR-0048 §6).

An ordered list whose item shape is a named group (`item_group`, values =
maps keyed by member key) or a single scalar (`item_type` sugar, values =
flat scalars). Covers: the model's exactly-one-shape rule, resolver stamping
of `item_members` (one internal model), schema-integrity checks (unknown
group, reference-typed members banned from item shapes), per-item value
validation through the real save path, and the AI patch path's per-item
salvage + field-catalog item descriptors.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain
from pydantic import ValidationError

from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
)
from app.services.ai.helpers import _field_catalog
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class ListFieldModelTests(unittest.TestCase):
    def test_list_requires_exactly_one_item_shape(self) -> None:
        with self.assertRaises(ValidationError):
            MetadataFieldDefinition(name="Qs", type="list")
        with self.assertRaises(ValidationError):
            MetadataFieldDefinition(name="Qs", type="list", item_group="g", item_type="text")
        MetadataFieldDefinition(name="Qs", type="list", item_group="g")
        MetadataFieldDefinition(name="Qs", type="list", item_type="text")

    def test_item_shape_keys_are_list_only(self) -> None:
        with self.assertRaises(ValidationError):
            MetadataFieldDefinition(name="T", type="text", item_type="text")
        with self.assertRaises(ValidationError):
            MetadataFieldDefinition(name="T", type="text", item_group="g")


class ListFieldProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.root = self.base / "universe" / "series" / "test"
        self.service = ProjectService.created_at(self.root, "Test Project")
        declare_full_chain(self.service, self.root, self.base)
        self._seed_list_schema()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed_list_schema(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["open_question"] = {
            "name": "Open question",
            "members": [
                {"key": "question", "name": "Question", "type": "text"},
                {"key": "status", "name": "Status", "type": "select", "options": ["open", "answered"]},
                {"key": "note", "name": "Note", "type": "long_text"},
            ],
        }
        fields = data.setdefault("fields", {})
        fields["open_questions"] = {"name": "Open questions", "type": "list", "item_group": "open_question"}
        fields["aliases"] = {"name": "Aliases", "type": "list", "item_type": "text"}
        character = data["entry_types"].get("lore:character") or {}
        member_fields = list(character.get("fields") or [])
        for field_id in ("open_questions", "aliases"):
            if field_id not in member_fields:
                member_fields.append(field_id)
        character["fields"] = member_fields
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def _create_character(self) -> str:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        return entry.id

    def _save_metadata(self, entry_id: str, metadata: dict) -> None:
        entry = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata=metadata,
            ),
        )

    # ---- resolver stamping (one internal model) ----

    def test_resolver_stamps_group_item_members(self) -> None:
        field = self.service.read_metadata_schema().fields["open_questions"]
        assert field.item_members is not None
        self.assertEqual([m.key for m in field.item_members], ["question", "status", "note"])
        self.assertEqual(field.item_members[1].type, "select")
        self.assertEqual([opt.value for opt in field.item_members[1].options], ["open", "answered"])

    def test_resolver_normalizes_item_type_sugar_to_one_member(self) -> None:
        field = self.service.read_metadata_schema().fields["aliases"]
        assert field.item_members is not None
        self.assertEqual(len(field.item_members), 1)
        self.assertEqual(field.item_members[0].key, "value")
        self.assertEqual(field.item_members[0].type, "text")

    # ---- schema integrity ----

    def test_unknown_item_group_is_a_schema_error(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["fields"]["broken"] = {"name": "Broken", "type": "list", "item_group": "nope"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("references unknown group nope" in error for error in errors), errors)

    def test_reference_members_are_rejected_in_item_shapes(self) -> None:
        # v1 exclusion: the read-side healers only walk top-level values, so a
        # nested ref they cannot heal/purge would be a silent mis-link.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["cast"] = {
            "name": "Cast",
            "members": [{"key": "who", "name": "Who", "type": "entity_ref"}],
        }
        data["fields"]["cast_list"] = {"name": "Cast list", "type": "list", "item_group": "cast"}
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(
            any("member who of type entity_ref" in error for error in errors), errors
        )

    # ---- per-item value validation through the real save path ----

    def test_saves_valid_items_both_shapes(self) -> None:
        entry_id = self._create_character()
        self._save_metadata(
            entry_id,
            {
                "open_questions": [
                    {"question": "Who forged the letter?", "status": "open", "note": "Ch. 12"},
                    {"question": "Where is the key?"},
                ],
                "aliases": ["Ash", "Harbor Rat"],
            },
        )
        saved = self.service.read_lore_entry(entry_id)
        self.assertEqual(len(saved.metadata["open_questions"]), 2)
        self.assertEqual(saved.metadata["aliases"], ["Ash", "Harbor Rat"])

    def test_rejects_bad_member_value_naming_the_item(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[1\]\.status must be one of"):
            self._save_metadata(
                entry_id,
                {"open_questions": [{"question": "ok"}, {"question": "x", "status": "bogus"}]},
            )

    def test_rejects_unknown_member_key(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[0\] has unknown member severity"):
            self._save_metadata(entry_id, {"open_questions": [{"severity": "high"}]})

    def test_rejects_non_map_item_for_group_shape(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"open_questions\[0\] must be a map"):
            self._save_metadata(entry_id, {"open_questions": ["just a string"]})

    def test_rejects_non_scalar_item_for_item_type(self) -> None:
        entry_id = self._create_character()
        with self.assertRaisesRegex(ProjectServiceError, r"aliases\[1\] must be text"):
            self._save_metadata(entry_id, {"aliases": ["ok", 7]})

    # ---- AI patch path: per-item salvage + catalog ----

    def test_ai_draft_salvages_valid_list_items(self) -> None:
        raw = json.dumps(
            {
                "body": "",
                "fields": {
                    "open_questions": [
                        {"question": "Good", "status": "open"},
                        {"question": "Bad", "status": "bogus"},
                        "not a map",
                    ],
                    "aliases": ["ok", 5],
                },
            }
        )
        patch = self.service.validate_ai_entry_draft("lore:character", raw)
        self.assertFalse(patch.garbled)
        self.assertEqual(len(patch.fields["open_questions"]), 1)
        self.assertEqual(patch.fields["open_questions"][0]["question"], "Good")
        self.assertEqual(patch.fields["aliases"], ["ok"])
        self.assertIn("open_questions[1]", patch.dropped)
        self.assertIn("open_questions[2]", patch.dropped)
        self.assertIn("aliases[1]", patch.dropped)

    def test_field_catalog_describes_item_shapes(self) -> None:
        schema = self.service.read_metadata_schema()
        catalog = _field_catalog(self.service, schema, "lore:character")
        by_id = {descriptor["id"]: descriptor for descriptor in catalog}
        self.assertIn("open_questions", by_id)
        self.assertFalse(by_id["open_questions"]["item_scalar"])
        self.assertEqual(
            [member["key"] for member in by_id["open_questions"]["items"]],
            ["question", "status", "note"],
        )
        self.assertEqual(by_id["open_questions"]["items"][1]["options"], ["open", "answered"])
        self.assertTrue(by_id["aliases"]["item_scalar"])
        self.assertEqual(by_id["aliases"]["items"][0]["type"], "text")


if __name__ == "__main__":
    unittest.main()
