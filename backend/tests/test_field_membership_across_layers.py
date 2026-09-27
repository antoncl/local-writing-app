"""A field defined above the layer that declares its entry type (#2276, #2277).

A series defines a field; the book's own character type lists it. The field's
DEFINITION lives in the series layer, its MEMBERSHIP in the book layer — and
every field write has to keep the two apart:

- creating the field at the series lists it on the type where the type lives,
  never on a stand-in `manuscript` type minted in the series (#2277);
- moving it up to the series leaves the membership in the book (#2277);
- deleting or renaming it rewrites the book's listing too, instead of leaving
  it dangling and failing validation (#2276).

Chain: `writing (base) → aetheria (series) → book (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    DeleteMetadataFieldRequest,
    MetadataFieldDefinition,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService

_TYPE = "lore:character:main_character"


class FieldMembershipAcrossLayersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "aetheria"
        self.root = self.series / "book"
        self.service = ProjectService.created_at(self.root, "Book")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    _TYPE: {"name": "Main character", "kind": "lore", "parent": "lore:character", "fields": []}
                },
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _layer(self, folder: Path) -> dict:
        path = folder / "metadata.schema.yaml"
        return self.service._read_yaml(path) if path.exists() else {}

    def _create(self, folder: Path, field_id: str) -> None:
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self._layer_id(folder),
                field_id=field_id,
                field=MetadataFieldDefinition(name=field_id.title(), type="long_text"),
                entry_type=_TYPE,
            )
        )

    def _assert_no_stand_in_type(self, folder: Path) -> None:
        self.assertNotIn(_TYPE, self._layer(folder).get("entry_types") or {})

    def test_creating_at_the_series_lists_the_field_on_the_book_s_type(self) -> None:
        self._create(self.series, "truth")

        self.assertIn("truth", self._layer(self.series)["fields"])
        self._assert_no_stand_in_type(self.series)
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["fields"], ["truth"])
        resolved = self.service.read_metadata_schema().entry_types[_TYPE]
        self.assertEqual(resolved.kind, "lore")
        self.assertIn("truth", resolved.fields)

    def test_moving_up_to_the_series_leaves_the_membership_in_the_book(self) -> None:
        self._create(self.root, "truth")

        self.service.move_metadata_field(
            MoveMetadataFieldRequest(field_id="truth", target_layer_id=self._layer_id(self.series), entry_type=_TYPE)
        )

        self.assertIn("truth", self._layer(self.series)["fields"])
        self.assertNotIn("truth", self._layer(self.root).get("fields") or {})
        self._assert_no_stand_in_type(self.series)
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["fields"], ["truth"])

    def _series_defines_truth_and_book_lists_it(self) -> None:
        """The reporter's on-disk shape, written directly so the delete/rename
        tests don't depend on the create path getting the membership right."""
        self.service._write_yaml(
            self.series / "metadata.schema.yaml",
            {"version": 1, "fields": {"truth": {"name": "Truth", "type": "long_text"}}},
        )
        book = self._layer(self.root)
        book["entry_types"][_TYPE]["fields"] = ["truth"]
        self.service._write_yaml(self.root / "metadata.schema.yaml", book)

    def test_deleting_a_series_field_drops_the_book_s_listing(self) -> None:
        self._series_defines_truth_and_book_lists_it()

        schema = self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="truth", entry_type=_TYPE))

        self.assertNotIn("truth", schema.fields)
        self.assertNotIn("truth", self._layer(self.series).get("fields") or {})
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["fields"], [])

    def test_renaming_a_series_field_renames_the_book_s_listing(self) -> None:
        self._series_defines_truth_and_book_lists_it()

        schema = self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="truth", new_field_id="lesson", entry_type=_TYPE)
        )

        self.assertIn("lesson", schema.entry_types[_TYPE].fields)
        self.assertIn("lesson", self._layer(self.series)["fields"])
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["fields"], ["lesson"])

    def test_a_summary_nomination_follows_a_delete_and_a_rename(self) -> None:
        self._series_defines_truth_and_book_lists_it()
        book = self._layer(self.root)
        book["entry_types"][_TYPE]["summary_fields"] = ["truth"]
        self.service._write_yaml(self.root / "metadata.schema.yaml", book)

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="truth", new_field_id="lesson", entry_type=_TYPE)
        )
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["summary_fields"], ["lesson"])

        self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="lesson", entry_type=_TYPE))
        self.assertEqual(self._layer(self.root)["entry_types"][_TYPE]["summary_fields"], [])

    def test_deleting_strips_every_type_that_lists_the_field_not_just_the_named_one(self) -> None:
        self._create(self.root, "truth")
        book = self._layer(self.root)
        book["entry_types"]["lore:character:sidekick"] = {
            "name": "Sidekick",
            "kind": "lore",
            "parent": "lore:character",
            "fields": ["truth"],
        }
        self.service._write_yaml(self.root / "metadata.schema.yaml", book)

        self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="truth", entry_type=_TYPE))

        entry_types = self._layer(self.root)["entry_types"]
        self.assertEqual(entry_types[_TYPE]["fields"], [])
        self.assertEqual(entry_types["lore:character:sidekick"]["fields"], [])


if __name__ == "__main__":
    unittest.main()
