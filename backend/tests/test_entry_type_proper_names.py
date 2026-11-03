"""Entry-type `proper_names` setting (#2658).

Whether a type's names are proper nouns — the proofreading dictionary keeps the
title's words case-sensitive when true and also accepts lower case when false.
Behaves like `summary_fields`/`color`: inherited down the entry-type parent
chain, clearable per layer with an explicit `null`, stamped with the
pre-inheritance `own_proper_names` twin that never reaches disk.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import EntryTypeDefinition, UpsertMetadataEntryTypeRequest
from app.services.project_service import ProjectService


class BuiltInProperNamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Proper Names Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_character_and_location_are_proper_names(self) -> None:
        types = self.service.read_metadata_schema().entry_types
        self.assertIs(types["lore:character"].proper_names, True)
        self.assertIs(types["lore:location"].proper_names, True)

    def test_other_lore_types_are_not(self) -> None:
        types = self.service.read_metadata_schema().entry_types
        for type_id in ("lore:base", "lore:note", "lore:item"):
            self.assertIs(types[type_id].proper_names, False, type_id)

    def test_a_project_type_extending_lore_base_is_not(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:material",
                entry_type=EntryTypeDefinition(name="Material", kind="lore", parent="lore:base", fields=[]),
            )
        )
        self.assertIs(schema.entry_types["lore:material"].proper_names, False)
        self.assertIsNone(schema.entry_types["lore:material"].own_proper_names)


class ProperNamesInheritanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "honorverse" / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:faction": {
                        "name": "Faction", "kind": "lore", "parent": "lore:base",
                        "fields": [], "proper_names": True,
                    },
                    "lore:cabal": {
                        "name": "Cabal", "kind": "lore", "parent": "lore:faction", "fields": [],
                    },
                    "lore:guild": {
                        "name": "Guild", "kind": "lore", "parent": "lore:faction",
                        "fields": [], "proper_names": False,
                    },
                },
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def test_a_child_inherits_the_parent_s_value(self) -> None:
        child = self.service.read_metadata_schema().entry_types["lore:cabal"]
        self.assertIs(child.proper_names, True)
        self.assertIsNone(child.own_proper_names)

    def test_a_child_s_own_false_wins(self) -> None:
        child = self.service.read_metadata_schema().entry_types["lore:guild"]
        self.assertIs(child.proper_names, False)
        self.assertIs(child.own_proper_names, False)

    def test_an_explicit_null_at_the_book_clears_back_to_inherited(self) -> None:
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self._layer_id(self.root),
                entry_type_id="lore:guild",
                entry_type=EntryTypeDefinition(
                    name="Guild", kind="lore", parent="lore:faction", fields=[], proper_names=False,
                ),
                allow_existing=True,
            )
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self._layer_id(self.root),
                entry_type_id="lore:guild",
                entry_type=EntryTypeDefinition(
                    name="Guild", kind="lore", parent="lore:faction", fields=[], proper_names=None,
                ),
                allow_existing=True,
            )
        )
        stored = self.service._read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["lore:guild"]
        self.assertIn("proper_names", stored)
        self.assertIsNone(stored["proper_names"])
        resolved = self.service.read_metadata_schema().entry_types["lore:guild"]
        self.assertIsNone(resolved.own_proper_names)
        self.assertIs(resolved.proper_names, True)  # the parent's, again


class ProperNamesRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Round Trip Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_a_layer_can_set_it_and_own_stays_off_disk(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:item",
                entry_type=EntryTypeDefinition(
                    name="Item", kind="lore", parent="lore:base", fields=[], proper_names=True,
                ),
                allow_existing=True,
            )
        )
        item = schema.entry_types["lore:item"]
        self.assertIs(item.proper_names, True)
        self.assertIs(item.own_proper_names, True)
        stored = self.service._read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["lore:item"]
        self.assertIs(stored["proper_names"], True)
        self.assertNotIn("own_proper_names", stored)

    def test_http_round_trip_and_own_stays_off_disk(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        response = self.client.put(
            "/api/metadata/schema/entry-types",
            json={
                "layer_id": layer_id,
                "entry_type_id": "lore:location",
                "entry_type": {
                    "name": "Location", "kind": "lore", "parent": "lore:base",
                    "fields": [], "proper_names": False, "own_proper_names": True,
                },
                "allow_existing": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIs(response.json()["entry_types"]["lore:location"]["proper_names"], False)
        stored = self.service._read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["lore:location"]
        self.assertIs(stored["proper_names"], False)
        self.assertNotIn("own_proper_names", stored)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
