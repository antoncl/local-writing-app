"""A nearer layer clears an attribute an ancestor declared (#1916, #1919).

Field definitions, entry types, groups and per-type field overrides merge per
attribute up the chain (`_merge_metadata_schema_section` is `{**base, **layer}`
per key), where an absent key means "inherit". So a layer that wants to switch
an inherited `derived` rule off, drop an inherited `default`, colour or icon, or
un-relabel a field, needs an on-disk spelling for the clear: an explicit `null`.
Every layer writer reads its request the same way (`schema_layer_write`): a
value is stored; a `null` is a clear, stored as `null` when the chain above
declares the attribute and as no key otherwise; a key the request does not
mention leaves the layer's existing spelling alone.

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
    EntryTypeDefinition,
    GroupMember,
    LoreEntry,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
    MoveMetadataFieldRequest,
    SaveLoreEntryRequest,
    SelectOption,
    SetFieldOverrideRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
    UpsertMetadataGroupRequest,
)
from app.services.project_service import ProjectService

_FILMED_OPTIONS = [SelectOption(value="planned"), SelectOption(value="filmed"), SelectOption(value="scrapped")]
_CAST_MEMBERS = [GroupMember(key="lead", name="Lead", type="text")]


def _filmed(**cleared) -> MetadataFieldDefinition:
    """The field as the type editor sends it: every optional attribute
    present, the cleared ones as an explicit null."""
    return MetadataFieldDefinition(name="Filmed", type="select", options=_FILMED_OPTIONS, **cleared)


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
        # to `planned`, and carries a description. The type carries a colour,
        # an icon and a relabel of `filmed`; a group carries an icon (#1919).
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
                "groups": {"cast": {"name": "Cast", "icon": "users", "members": [{"key": "lead", "name": "Lead", "type": "text"}]}},
                "entry_types": {
                    "lore:character": {
                        "fields": ["footage", "filmed"],
                        "color": "red",
                        "icon": "user",
                        "field_overrides": {"filmed": {"label": "Shot", "hidden": False}},
                    }
                },
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _stored(self, layer: Path, key: str, section: str = "fields") -> dict:
        return self.service._read_yaml(layer / "metadata.schema.yaml")[section][key]

    def _upsert(self, layer: Path, field_id: str, field: MetadataFieldDefinition) -> None:
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self._layer_id(layer), field_id=field_id, field=field, entry_type="lore:character"
            )
        )

    def _upsert_type(self, layer: Path, entry_type_id: str, definition: EntryTypeDefinition) -> None:
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self._layer_id(layer), entry_type_id=entry_type_id, entry_type=definition
            )
        )

    def _upsert_group(self, layer: Path, definition: MetadataGroupDefinition) -> None:
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(layer_id=self._layer_id(layer), group_id="cast", group=definition)
        )

    def _set_override(self, layer: Path, field_key: str, *, label: str | None, hidden: bool | None) -> None:
        self.service.set_metadata_field_override(
            SetFieldOverrideRequest(
                layer_id=self._layer_id(layer),
                entry_type_id="lore:character",
                field_key=field_key,
                label=label,
                hidden=hidden,
            )
        )

    def _character(self, title: str) -> LoreEntry:
        return self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:character"))

    # --- field attributes (#1916) --------------------------------------

    def test_the_book_clears_the_ancestor_s_derived_state_default_and_description(self) -> None:
        # The editor's "App-set state → (none)" + an emptied default and
        # description: the payload sends the three as null.
        self._upsert(self.root, "filmed", _filmed(derived=None, default=None, description=None))

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
        self._upsert(self.root, "mood", MetadataFieldDefinition(name="Mood", type="text", default=None, description=None, icon=None, group=None))
        stored = self._stored(self.root, "mood")
        for key in ("derived", "default", "description", "icon", "group"):
            self.assertNotIn(key, stored)

    def test_an_attribute_the_request_does_not_mention_is_left_as_it_is(self) -> None:
        # A client that posts part of a definition (no `derived`, no
        # `description`) neither clears nor re-inherits: the base's
        # description still resolves, and a clear the layer already holds
        # survives the next partial save.
        self._upsert(self.series, "filmed", _filmed(default="planned"))
        self.assertNotIn("derived", self._stored(self.series, "filmed"))
        self.assertEqual(self.service.read_metadata_schema().fields["filmed"].description, "Whether the scene has been shot.")

        self._upsert(self.root, "filmed", _filmed(derived=None, default="planned"))
        self.assertIsNone(self._stored(self.root, "filmed")["derived"])
        self._upsert(self.root, "filmed", _filmed(default="planned"))
        self.assertIsNone(self._stored(self.root, "filmed")["derived"])
        self.assertIsNone(self.service.read_metadata_schema().fields["filmed"].derived)

    def test_a_clear_at_the_series_reaches_the_book_and_leaves_the_base_alone(self) -> None:
        self._upsert(self.series, "filmed", _filmed(derived=None, default="planned"))
        self.assertIsNone(self._stored(self.series, "filmed")["derived"])
        self.assertEqual(self._stored(self.series, "filmed")["default"], "planned")
        self.assertIsNone(self.service.read_metadata_schema().fields["filmed"].derived)
        as_of_base = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.base)).fields["filmed"]
        self.assertEqual(as_of_base.derived, DerivedSelectState(value="filmed", when_set="footage"))

    def test_a_move_carries_the_clear_with_the_field(self) -> None:
        # The series clears the base's rule, then the field moves to the book.
        # What the book inherits is resolved with the series' entry already
        # gone, so the null travels instead of reading as "nothing above".
        self._upsert(self.series, "filmed", _filmed(derived=None, default="planned"))
        self.assertIsNone(self._stored(self.series, "filmed")["derived"])
        self.service.move_metadata_field(
            MoveMetadataFieldRequest(
                field_id="filmed", target_layer_id=self._layer_id(self.root), entry_type="lore:character"
            )
        )
        self.assertNotIn("filmed", self.service._read_yaml(self.series / "metadata.schema.yaml").get("fields", {}))
        self.assertIsNone(self._stored(self.root, "filmed")["derived"])
        self.assertIsNone(self.service.read_metadata_schema().fields["filmed"].derived)

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
                field=MetadataFieldDefinition(name="Page status", type="select", options=options, default="unwritten", derived=None),
                entry_type="plot:card",
            )
        )
        stored = self._stored(self.root, "page_status")
        self.assertIsNone(stored["derived"])
        self.assertEqual(stored["default"], "unwritten")
        field = self.service.read_metadata_schema().fields["page_status"]
        self.assertIsNone(field.derived)
        self.assertEqual(field.default, "unwritten")

    # --- entry-type attributes (#1919) ---------------------------------

    def test_the_book_clears_the_ancestor_s_type_colour_and_icon(self) -> None:
        # The type editor sends `color: null` / `icon: null` for a cleared
        # swatch; the built-in overlay strip leaves the nulls in place. The
        # clear is the layer's alone: the parent type (lore:base) still flows.
        self._upsert_type(self.root, "lore:character", EntryTypeDefinition(name="Character", kind="lore", color=None, icon=None))
        stored = self._stored(self.root, "lore:character", "entry_types")
        self.assertIn("color", stored)
        self.assertIsNone(stored["color"])
        self.assertIn("icon", stored)
        self.assertIsNone(stored["icon"])
        schema = self.service.read_metadata_schema()
        resolved = schema.entry_types["lore:character"]
        parent = schema.entry_types["lore:base"]
        self.assertIsNone(resolved.own_color)
        self.assertIsNone(resolved.own_icon)
        self.assertIsNotNone(parent.color)
        self.assertEqual(resolved.color, parent.color)
        self.assertEqual(resolved.icon, parent.icon)

    def test_a_type_attribute_no_ancestor_declared_writes_no_key(self) -> None:
        self._upsert_type(self.root, "lore:vessel", EntryTypeDefinition(name="Vessel", kind="lore", color=None, icon=None))
        stored = self._stored(self.root, "lore:vessel", "entry_types")
        self.assertNotIn("color", stored)
        self.assertNotIn("icon", stored)

    def test_a_type_save_that_does_not_mention_the_icon_keeps_it(self) -> None:
        # A colour-only save from a client that never sends `icon` is not a clear.
        self._upsert_type(self.root, "lore:character", EntryTypeDefinition(name="Character", kind="lore", color="rose"))
        self.assertNotIn("icon", self._stored(self.root, "lore:character", "entry_types"))
        self.assertEqual(self.service.read_metadata_schema().entry_types["lore:character"].icon, "user")

    def test_a_type_save_keeps_the_layer_s_field_overrides(self) -> None:
        # The override has its own writer; a colour save must not drop it.
        self._set_override(self.root, "filmed", label="Take", hidden=None)
        self._upsert_type(self.root, "lore:character", EntryTypeDefinition(name="Character", kind="lore", color="rose"))
        stored = self._stored(self.root, "lore:character", "entry_types")
        self.assertEqual(stored["field_overrides"]["filmed"]["label"], "Take")
        self.assertEqual(self.service.read_metadata_schema().entry_types["lore:character"].field_overrides["filmed"].label, "Take")

    def test_a_hand_authored_null_clears_the_inherited_type_colour(self) -> None:
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {"version": 1, "entry_types": {"lore:character": {"color": None}}},
        )
        schema = self.service.read_metadata_schema()
        resolved = schema.entry_types["lore:character"]
        self.assertIsNone(resolved.own_color)
        self.assertEqual(resolved.color, schema.entry_types["lore:base"].color)
        self.assertEqual(resolved.icon, "user")

    # --- group attributes (#1919) ---------------------------------------

    def test_the_book_clears_the_ancestor_s_group_icon(self) -> None:
        self._upsert_group(self.root, MetadataGroupDefinition(name="Cast", icon=None, members=_CAST_MEMBERS))
        self.assertIsNone(self._stored(self.root, "cast", "groups")["icon"])
        self.assertIsNone(self.service.read_metadata_schema().groups["cast"].icon)

    def test_a_group_save_that_does_not_mention_the_icon_keeps_the_layer_s_spelling(self) -> None:
        # The groups dialog has no icon control and omits the key: an
        # ancestor's icon survives a member edit, and so does a clear the
        # layer already holds.
        self._upsert_group(self.root, MetadataGroupDefinition(name="Cast", members=_CAST_MEMBERS))
        self.assertNotIn("icon", self._stored(self.root, "cast", "groups"))
        self.assertEqual(self.service.read_metadata_schema().groups["cast"].icon, "users")

        self._upsert_group(self.root, MetadataGroupDefinition(name="Cast", icon=None, members=_CAST_MEMBERS))
        self._upsert_group(self.root, MetadataGroupDefinition(name="Cast", members=_CAST_MEMBERS))
        self.assertIsNone(self._stored(self.root, "cast", "groups")["icon"])
        self.assertIsNone(self.service.read_metadata_schema().groups["cast"].icon)

    # --- per-type field overrides (#1919) ------------------------------

    def test_the_book_clears_the_ancestor_s_field_override(self) -> None:
        self.assertEqual(self.service.read_metadata_schema().entry_types["lore:character"].field_overrides["filmed"].label, "Shot")
        self._set_override(self.root, "filmed", label=None, hidden=None)
        stored = self._stored(self.root, "lore:character", "entry_types")["field_overrides"]["filmed"]
        self.assertEqual(stored, {"label": None, "hidden": None})
        override = self.service.read_metadata_schema().entry_types["lore:character"].field_overrides["filmed"]
        self.assertIsNone(override.label)
        self.assertIsNone(override.hidden)

    def test_a_partial_override_clears_only_the_aspect_it_omits(self) -> None:
        self._set_override(self.root, "filmed", label="Take", hidden=None)
        stored = self._stored(self.root, "lore:character", "entry_types")["field_overrides"]["filmed"]
        self.assertEqual(stored, {"label": "Take", "hidden": None})
        override = self.service.read_metadata_schema().entry_types["lore:character"].field_overrides["filmed"]
        self.assertEqual(override.label, "Take")
        self.assertIsNone(override.hidden)

    def test_a_field_override_no_ancestor_declared_drops_the_entry(self) -> None:
        # `footage` carries no ancestor override: clearing writes nothing, as before.
        self._set_override(self.root, "footage", label="Reel", hidden=None)
        self._set_override(self.root, "footage", label=None, hidden=None)
        stored = self.service._read_yaml(self.root / "metadata.schema.yaml").get("entry_types", {})
        self.assertNotIn("footage", stored.get("lore:character", {}).get("field_overrides", {}))


if __name__ == "__main__":
    unittest.main()
