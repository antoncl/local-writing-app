"""The as-of-L metadata-schema read, and the write path that uses it (#393).

`read_metadata_schema(root)` merges the whole ancestor chain down to the open
project — the *resolution scope*. ADR-0042 §3 needs a second reading: a write
bound to an authoring layer L must see only `base → L`, so it cannot store a
field a more-local layer defines. ADR-0045 §4 makes that a rule about what a
*write accepts*, not only what a picker offers, and marks the save path as a
live gap #313/#314 must not ship without closing.

Tags already had this shape (`read_known_tags(up_to_layer_id=…)`, #339). These
tests pin the same capability for the schema, plus the faction example both ADRs
use: a field defined at the book is unresolvable as of the series, so a write
authored there is rejected and no ancestor file is touched.

The chain is the same four layers the tag suite uses:
`writing (base) → honorverse → honor-harrington → book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
from app.scope import WorkScope
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class AsOfLayerSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved for the same reason the tag suite resolves: Windows hands back
        # the 8.3 short form while the walk canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(
            layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder
        )

    def _define_faction_at(self, folder: Path) -> None:
        """Add a `faction` text field to `lore:character` at one layer."""
        self.service._write_yaml(
            folder / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {"faction": {"name": "faction", "type": "text", "label": "Faction"}},
                "entry_types": {"lore:character": {"fields": ["faction"]}},
            },
        )

    def _authored_at(self, layer: Path | None) -> ProjectService:
        """A service bound to the same project on disk, authoring at `layer`.

        No client sends `authoring_layer` yet (#313/#314 will), so a test that
        needs L constructs the `WorkScope` directly — the same shape the
        resolver will build once a picker ships.
        """
        return ProjectService(WorkScope(root=self.root, authoring_layer=layer))

    def _character_with_faction(self, service: ProjectService, faction: str) -> None:
        entry = service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor Harrington", entry_type="lore:character")
        )
        service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Honor Harrington",
                body="Body.",
                entry_type="lore:character",
                metadata={"faction": faction},
            ),
        )

    # --- the read ------------------------------------------------------

    def test_a_field_defined_below_L_is_absent_as_of_L(self) -> None:
        # `faction` lives at the book (root); as of the series it is gone.
        self._define_faction_at(self.root)

        as_of_series = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.series))
        self.assertNotIn("faction", as_of_series.fields)
        self.assertNotIn("faction", as_of_series.entry_types["lore:character"].fields)

    def test_the_field_is_present_at_and_below_the_layer_that_defines_it(self) -> None:
        self._define_faction_at(self.series)

        # As of the series (where it is defined) and as of the book (below it):
        # a truncation reaches down, never up, so both see it.
        as_of_series = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.series))
        as_of_book = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.root))
        self.assertIn("faction", as_of_series.fields)
        self.assertIn("faction", as_of_book.fields)

        # But as of the universe, one layer above, it is not yet defined.
        as_of_universe = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.universe))
        self.assertNotIn("faction", as_of_universe.fields)

    def test_no_layer_id_reads_the_whole_chain(self) -> None:
        self._define_faction_at(self.root)

        # The default is identical to today's resolution-scope read — the field
        # at the innermost layer is present.
        self.assertIn("faction", self.service.read_metadata_schema().fields)
        self.assertIn(
            "faction",
            self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.root)).fields,
        )

    def test_reading_at_an_unknown_layer_fails_loudly(self) -> None:
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.read_metadata_schema(up_to_layer_id="nosuchlayer")
        self.assertEqual(caught.exception.status_code, 404)

    # --- the write -----------------------------------------------------

    def test_a_write_authored_at_the_book_accepts_a_book_field(self) -> None:
        self._define_faction_at(self.root)
        authored_at_book = self._authored_at(self.root)

        self._character_with_faction(authored_at_book, "Manticore")

        entries = self.service.list_lore_entries().entries
        stored = self.service.read_lore_entry(entries[0].id)
        self.assertEqual(stored.metadata["faction"], "Manticore")

    def test_a_write_authored_at_the_series_rejects_a_book_field_and_touches_nothing(self) -> None:
        # The faction example, from the write side. `faction` is a book field.
        self._define_faction_at(self.root)
        # It exists at the book, so a book-authored save lands it.
        self._character_with_faction(self._authored_at(self.root), "Manticore")
        entry_id = self.service.list_lore_entries().entries[0].id
        on_disk_before = self._lore_file_for(entry_id).read_text(encoding="utf-8")

        # Move the authoring layer up to the series and try to overwrite it. As
        # of the series the field is unresolvable, so the write is rejected.
        with self.assertRaises(ProjectServiceError) as caught:
            self._authored_at(self.series).save_lore_entry(
                entry_id,
                SaveLoreEntryRequest(
                    title="Honor Harrington",
                    body="Body.",
                    entry_type="lore:character",
                    metadata={"faction": "Haven"},
                ),
            )
        self.assertEqual(caught.exception.status_code, 422)

        # Nothing was written: the book's file still says Manticore, and the
        # series (the ancestor) never grew a file for a write it did not accept.
        self.assertEqual(self._lore_file_for(entry_id).read_text(encoding="utf-8"), on_disk_before)
        self.assertFalse((self.series / "lore").exists())

    def test_a_write_with_no_authoring_layer_sees_the_whole_chain(self) -> None:
        # Absent L (every client today) resolves the full chain, so the same
        # book field the series rejects is accepted — behaviour is unchanged.
        self._define_faction_at(self.root)

        self._character_with_faction(self._authored_at(None), "Manticore")

        entry_id = self.service.list_lore_entries().entries[0].id
        self.assertEqual(self.service.read_lore_entry(entry_id).metadata["faction"], "Manticore")

    # --- helpers that need a node id -----------------------------------

    def _lore_file_for(self, entry_id: str) -> Path:
        return self.service._path_for_node_id(entry_id, "lore")


if __name__ == "__main__":
    unittest.main()
