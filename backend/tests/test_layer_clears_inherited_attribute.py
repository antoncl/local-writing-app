"""A nearer layer clears a field attribute an ancestor declared (#1916).

Field definitions merge per attribute up the chain (`_merge_metadata_schema_section`
is `{**base, **layer}` per field), where an absent key means "inherit". So a
layer that wants to switch an inherited `derived` rule off, or drop an
inherited `default` / `description`, needs an on-disk spelling for the clear:
an explicit `null`. The type editor omits a cleared attribute; the layer
write (`_layer_field_payload`) turns that omission into the explicit null
whenever the chain above the layer declares the attribute, and writes no key
when nothing above declares it — so a fresh field's yaml stays as sparse as
before.

The chain is the four layers the as-of-L suite uses:
`writing (base) → honorverse → honor-harrington (series) → book01 (root)`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import (
    CreateLoreEntryRequest,
    DerivedSelectState,
    LoreEntry,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    SelectOption,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService

_FILMED_OPTIONS = [SelectOption(value="planned"), SelectOption(value="filmed"), SelectOption(value="scrapped")]


class LayerClearsInheritedAttributeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "honorverse" / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        # The base declares the how-to's worked example on lore:character:
        # `filmed` is app-set to `filmed` while `footage` is attached, defaults
        # to `planned`, and carries a description.
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "footage": {"name": "Footage", "type": "entity_ref"},
                    "filmed": {
                        "name": "Filmed",
                        "type": "select",
                        "options": ["planned", "filmed", "scrapped"],
                        "default": "planned",
                        "description": "Whether the scene has been shot.",
                        "derived": {"value": "filmed", "when_set": "footage"},
                    },
                },
                "entry_types": {"lore:character": {"fields": ["footage", "filmed"]}},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _upsert(self, layer: Path, field_id: str, field: MetadataFieldDefinition) -> None:
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self._layer_id(layer), field_id=field_id, field=field, entry_type="lore:character"
            )
        )

    def _stored(self, layer: Path, field_id: str) -> dict:
        return self.service._read_yaml(layer / "metadata.schema.yaml")["fields"][field_id]

    def _character(self, title: str) -> LoreEntry:
        return self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:character"))

    # --- the clear ----------------------------------------------------

    def test_the_book_clears_the_ancestor_s_derived_state_default_and_description(self) -> None:
        # The editor's "App-set state → (none)" + an emptied default and
        # description: the payload simply omits the three keys.
        self._upsert(self.root, "filmed", MetadataFieldDefinition(name="Filmed", type="select", options=_FILMED_OPTIONS))

        stored = self._stored(self.root, "filmed")
        for key in ("derived", "default", "description"):
            self.assertIn(key, stored)
            self.assertIsNone(stored[key])
        field = self.service.read_metadata_schema().fields["filmed"]
        self.assertIsNone(field.derived)
        self.assertIsNone(field.default)
        self.assertIsNone(field.description)
        self.assertEqual([option.value for option in field.options], ["planned", "filmed", "scrapped"])

        # And the rule no longer fires: an authored value stands beside the reference.
        reel = self._character("Reel")
        hero = self._character("Seren")
        saved = self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title=hero.title, body="", base_revision=hero.revision, entry_type="lore:character",
                metadata={"footage": reel.id, "filmed": "scrapped"},
            ),
        )
        self.assertEqual(saved.metadata["filmed"], "scrapped")

    def test_an_attribute_no_ancestor_declared_writes_no_key(self) -> None:
        self._upsert(self.root, "mood", MetadataFieldDefinition(name="Mood", type="text"))
        stored = self._stored(self.root, "mood")
        for key in ("derived", "default", "description", "icon", "group"):
            self.assertNotIn(key, stored)

    def test_a_clear_at_the_series_reaches_the_book_and_leaves_the_base_alone(self) -> None:
        self._upsert(
            self.series,
            "filmed",
            MetadataFieldDefinition(name="Filmed", type="select", options=_FILMED_OPTIONS, default="planned"),
        )
        self.assertIsNone(self._stored(self.series, "filmed")["derived"])
        self.assertEqual(self._stored(self.series, "filmed")["default"], "planned")
        self.assertIsNone(self.service.read_metadata_schema().fields["filmed"].derived)
        as_of_base = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.base)).fields["filmed"]
        self.assertEqual(as_of_base.derived, DerivedSelectState(value="filmed", when_set="footage"))

    def test_a_hand_authored_null_clears_the_inherited_attribute(self) -> None:
        # The on-disk spelling the writer produces is one an author can type.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {"version": 1, "fields": {"filmed": {"derived": None, "description": None}}},
        )
        field = self.service.read_metadata_schema().fields["filmed"]
        self.assertIsNone(field.derived)
        self.assertIsNone(field.description)
        self.assertEqual(field.default, "planned")

    def test_the_project_layer_switches_off_the_built_in_page_status_rule(self) -> None:
        # The loudest case from #1916: a book that does not want cards forced
        # to on_page while a scene is attached. The built-in declaration is
        # the outermost layer of the chain, so the clear must reach past it.
        options = [SelectOption(value="unwritten"), SelectOption(value="off_page"), SelectOption(value="on_page")]
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self._layer_id(self.root),
                field_id="page_status",
                field=MetadataFieldDefinition(name="Page status", type="select", options=options, default="unwritten"),
                entry_type="plot:card",
            )
        )
        stored = self._stored(self.root, "page_status")
        self.assertIsNone(stored["derived"])
        self.assertEqual(stored["default"], "unwritten")
        field = self.service.read_metadata_schema().fields["page_status"]
        self.assertIsNone(field.derived)
        self.assertEqual(field.default, "unwritten")


if __name__ == "__main__":
    unittest.main()
