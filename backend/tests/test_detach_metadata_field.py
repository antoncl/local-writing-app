"""Remove a field from ONE entry type (#2280).

The inverse of "+ Existing field": the type's own listing goes from every layer
that has one; the field definition and every other type stay. Refused when the
field reaches the type another way (parent type, group, built-in schema), since
membership only ever adds. Values are cleared from this project's documents of
every type that loses the field.

Chain: `writing (base) → aetheria (series) → book (root)`. The series defines
`truth`; the book declares `main_character` (parent `lore:character`) and a
`sidekick` type that also lists `truth`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    CreateLoreEntryRequest,
    DetachMetadataFieldRequest,
    SaveLoreEntryRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService

_MAIN = "lore:character:main_character"
_SIDEKICK = "lore:character:sidekick"


def _type(name: str, parent: str, fields: list[str], **extra) -> dict:
    return {"name": name, "kind": "lore", "parent": parent, "fields": fields, **extra}


class DetachMetadataFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "aetheria"
        self.root = self.series / "book"
        self.service = ProjectService.created_at(self.root, "Book")
        declare_full_chain(self.service, self.root, self.base)
        self._write(
            self.series,
            {"fields": {"truth": {"name": "Truth", "type": "long_text"}, "want": {"name": "Want", "type": "long_text"}}},
        )
        self._write(
            self.root,
            {
                "entry_types": {
                    _MAIN: _type("Main character", "lore:character", ["truth", "want"], summary_fields=["truth"]),
                    _SIDEKICK: _type("Sidekick", "lore:character", ["truth"]),
                }
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, folder: Path, data: dict) -> None:
        self.service._write_yaml(folder / "metadata.schema.yaml", {"version": 1, **data})

    def _layer(self, folder: Path) -> dict:
        return self.service._read_yaml(folder / "metadata.schema.yaml")

    def _entry(self, title: str, entry_type: str, metadata: dict):
        created = self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type=entry_type))
        return self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title, body="", base_revision=created.revision, entry_type=entry_type, metadata=metadata
            ),
        )

    def _detach(self, entry_type_id: str, field_id: str):
        return self.service.detach_metadata_field(
            DetachMetadataFieldRequest(entry_type_id=entry_type_id, field_id=field_id)
        )

    def test_removes_the_field_from_one_type_only(self) -> None:
        hero = self._entry("Hero", _MAIN, {"truth": "love wins", "want": "revenge"})
        pal = self._entry("Pal", _SIDEKICK, {"truth": "loyalty"})

        schema = self._detach(_MAIN, "truth")

        self.assertNotIn("truth", schema.entry_types[_MAIN].fields)
        self.assertIn("truth", schema.entry_types[_SIDEKICK].fields)
        self.assertIn("truth", schema.fields, "the definition stays")
        self.assertEqual(self._layer(self.root)["entry_types"][_MAIN]["summary_fields"], [])
        self.assertEqual(self.service.read_lore_entry(hero.id).metadata, {"want": "revenge"})
        self.assertEqual(self.service.read_lore_entry(pal.id).metadata["truth"], "loyalty")

    def test_the_preview_names_the_listing_layer_and_the_other_users(self) -> None:
        preview = self.service.preview_field_removal(_MAIN, "truth")

        self.assertIsNone(preview.blocked_by)
        self.assertEqual([(listing.layer_label, listing.shared) for listing in preview.listings], [("Book", False)])
        self.assertEqual(preview.other_types, [_SIDEKICK])
        self.assertEqual(preview.subtypes_losing, [])

    def test_a_listing_in_a_higher_layer_is_removed_and_marked_shared(self) -> None:
        series = self._layer(self.series)
        series["entry_types"] = {_MAIN: {"fields": ["truth"]}}
        self.service._write_yaml(self.series / "metadata.schema.yaml", series)

        preview = self.service.preview_field_removal(_MAIN, "truth")
        self.assertEqual(
            [(listing.layer_label, listing.shared) for listing in preview.listings],
            [("aetheria", True), ("Book", False)],
        )

        schema = self._detach(_MAIN, "truth")
        self.assertNotIn("truth", schema.entry_types[_MAIN].fields)
        self.assertEqual(self._layer(self.series)["entry_types"][_MAIN]["fields"], [])

    def test_a_subtype_that_had_it_only_through_the_type_loses_it_too(self) -> None:
        book = self._layer(self.root)
        book["entry_types"]["lore:character:mentor"] = _type("Mentor", _MAIN, [], summary_fields=["truth"])
        self.service._write_yaml(self.root / "metadata.schema.yaml", book)
        sage = self._entry("Sage", "lore:character:mentor", {"truth": "patience"})

        self.assertEqual(self.service.preview_field_removal(_MAIN, "truth").subtypes_losing, ["lore:character:mentor"])
        schema = self._detach(_MAIN, "truth")

        self.assertNotIn("truth", schema.entry_types["lore:character:mentor"].fields)
        self.assertEqual(self._layer(self.root)["entry_types"]["lore:character:mentor"]["summary_fields"], [])
        self.assertNotIn("truth", self.service.read_lore_entry(sage.id).metadata)

    def test_a_field_from_the_parent_type_is_refused_and_names_the_parent(self) -> None:
        book = self._layer(self.root)
        book["entry_types"]["lore:character:mentor"] = _type("Mentor", _MAIN, ["truth"])
        self.service._write_yaml(self.root / "metadata.schema.yaml", book)

        preview = self.service.preview_field_removal("lore:character:mentor", "truth")
        self.assertEqual((preview.blocked_by, preview.inherited_from), ("parent", _MAIN))
        with self.assertRaises(ProjectServiceError) as raised:
            self._detach("lore:character:mentor", "truth")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn(_MAIN, str(raised.exception))
        self.assertIn("truth", self._layer(self.root)["entry_types"]["lore:character:mentor"]["fields"])

    def test_a_built_in_listing_is_refused(self) -> None:
        preview = self.service.preview_field_removal("lore:character", "role")
        self.assertEqual(preview.blocked_by, "built_in")
        with self.assertRaises(ProjectServiceError):
            self._detach("lore:character", "role")

    def test_a_field_the_type_does_not_carry_is_a_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as raised:
            self._detach(_SIDEKICK, "want")
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
