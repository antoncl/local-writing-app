"""Entry-type `summary_fields` nomination (#2008).

An entry type can nominate an ordered list of field keys as its SUMMARY —
what a list row's detail line, a reference peek card, and the AI's reference
qualifier (`lore_block.py`) show. It behaves exactly like `color`/`icon`:
inherited down the entry-type parent chain unless a subtype declares its own,
clearable per-layer with an explicit `null`, and stamped with the
pre-inheritance `own_summary_fields` twin.

Covers, in order: entry-type parent-chain inheritance + layer clear +
on-disk persistence (mirrors `test_layer_clears_inherited_attribute.py`),
save round-trip through the service and the HTTP endpoint, definition
validation, the pure `schema_summary` fallback rule, and the AI lore-block
reference qualifier (mirrors `test_refs_in_groups_adjacency.py`).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataSchema,
    SaveLoreEntryRequest,
    SelectOption,
    UpsertMetadataEntryTypeRequest,
)
from app.services.ai.lore_block import _format_lore_block
from app.services.project.schema_summary import summary_field_keys, summary_values
from app.services.project_service import ProjectService

# --- entry-type parent-chain inheritance + layer clear ---------------------


class EntryTypeSummaryFieldInheritanceTests(unittest.TestCase):
    """`lore:custom_parent` nominates `aliases`; two children exercise pure
    inheritance and override+clear. Base declares both children's shape so
    the layer-chain clear at the book has a real ancestor value to clear
    against (mirrors `test_the_book_clears_the_ancestor_s_type_colour_and_icon`)."""

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
                    "lore:custom_parent": {
                        "name": "Custom Parent",
                        "kind": "lore",
                        "parent": "lore:base",
                        "fields": ["aliases", "tags"],
                        "summary_fields": ["aliases"],
                    },
                    "lore:custom_child_inherits": {
                        "name": "Custom Child (inherits)",
                        "kind": "lore",
                        "parent": "lore:custom_parent",
                        "fields": [],
                    },
                    "lore:custom_child_overrides": {
                        "name": "Custom Child (overrides)",
                        "kind": "lore",
                        "parent": "lore:custom_parent",
                        "fields": [],
                        "summary_fields": ["tags"],
                    },
                },
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _stored(self, folder: Path, entry_type_id: str) -> dict:
        return self.service._read_yaml(folder / "metadata.schema.yaml")["entry_types"][entry_type_id]

    def _upsert_type(self, folder: Path, entry_type_id: str, definition: EntryTypeDefinition) -> None:
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self._layer_id(folder), entry_type_id=entry_type_id, entry_type=definition
            )
        )

    def test_child_with_no_nomination_inherits_the_parent_s(self) -> None:
        schema = self.service.read_metadata_schema()
        child = schema.entry_types["lore:custom_child_inherits"]
        self.assertEqual(child.summary_fields, ["aliases"])
        self.assertIsNone(child.own_summary_fields)

    def test_child_with_its_own_nomination_wins(self) -> None:
        schema = self.service.read_metadata_schema()
        child = schema.entry_types["lore:custom_child_overrides"]
        self.assertEqual(child.summary_fields, ["tags"])
        self.assertEqual(child.own_summary_fields, ["tags"])

    def test_an_explicit_null_at_the_book_clears_the_ancestor_layer_s_nomination(self) -> None:
        # The book clears its own (ancestor-layer-declared) nomination; the
        # clear reaches past the layer chain, but the entry-type PARENT
        # (`lore:custom_parent`) still flows.
        self._upsert_type(
            self.root,
            "lore:custom_child_overrides",
            EntryTypeDefinition(
                name="Custom Child (overrides)", kind="lore", parent="lore:custom_parent",
                fields=[], summary_fields=None,
            ),
        )
        stored = self._stored(self.root, "lore:custom_child_overrides")
        self.assertIn("summary_fields", stored)
        self.assertIsNone(stored["summary_fields"])

        schema = self.service.read_metadata_schema()
        resolved = schema.entry_types["lore:custom_child_overrides"]
        self.assertIsNone(resolved.own_summary_fields)
        self.assertEqual(resolved.summary_fields, ["aliases"])  # the parent's, again


# --- save round-trip: service + HTTP, own_* never on disk ------------------


class EntryTypeSummaryFieldRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Round Trip Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_service_round_trip_and_own_summary_fields_stays_off_disk(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character", kind="lore", parent="lore:base", fields=[], summary_fields=["aliases"],
                ),
                allow_existing=True,
            )
        )
        character = schema.entry_types["lore:character"]
        self.assertEqual(character.summary_fields, ["aliases"])
        self.assertEqual(character.own_summary_fields, ["aliases"])

        stored = self.service._read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["lore:character"]
        self.assertEqual(stored["summary_fields"], ["aliases"])
        self.assertNotIn("own_summary_fields", stored)

    def test_http_round_trip_and_own_summary_fields_stays_off_disk(self) -> None:
        layer_id = self.service._metadata_schema_layer_id(self.root)
        response = self.client.put(
            "/api/metadata/schema/entry-types",
            json={
                "layer_id": layer_id,
                "entry_type_id": "lore:location",
                "entry_type": {
                    "name": "Location", "kind": "lore", "parent": "lore:base",
                    "fields": [], "summary_fields": ["aliases"],
                },
                "allow_existing": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["entry_types"]["lore:location"]["summary_fields"], ["aliases"])

        stored = self.service._read_yaml(self.root / "metadata.schema.yaml")["entry_types"]["lore:location"]
        self.assertEqual(stored["summary_fields"], ["aliases"])
        self.assertNotIn("own_summary_fields", stored)


# --- definition validation --------------------------------------------------


class EntryTypeSummaryFieldValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Validation Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_an_unknown_nominated_key_is_rejected(self) -> None:
        schema = MetadataSchema(
            fields={"role": MetadataFieldDefinition(name="Role", type="text")},
            entry_types={
                "lore:thing": EntryTypeDefinition(
                    name="Thing", kind="lore", fields=["role"], summary_fields=["role", "ghost"],
                )
            },
        )
        errors = self.service._validate_metadata_schema_definition(schema)
        self.assertTrue(any("lore:thing" in e and "ghost" in e for e in errors), errors)

    def test_a_duplicate_nominated_key_is_rejected(self) -> None:
        schema = MetadataSchema(
            fields={"role": MetadataFieldDefinition(name="Role", type="text")},
            entry_types={
                "lore:thing": EntryTypeDefinition(
                    name="Thing", kind="lore", fields=["role"], summary_fields=["role", "role"],
                )
            },
        )
        errors = self.service._validate_metadata_schema_definition(schema)
        self.assertTrue(any("lore:thing" in e and "more than once" in e for e in errors), errors)

    def test_a_clean_nomination_is_not_flagged(self) -> None:
        schema = MetadataSchema(
            fields={"role": MetadataFieldDefinition(name="Role", type="text")},
            entry_types={
                "lore:thing": EntryTypeDefinition(
                    name="Thing", kind="lore", fields=["role"], summary_fields=["role"],
                )
            },
        )
        self.assertEqual(self.service._validate_metadata_schema_definition(schema), [])


# --- schema_summary: the pure fallback rule ---------------------------------


class SchemaSummaryFallbackRuleTests(unittest.TestCase):
    def _schema(self) -> MetadataSchema:
        return MetadataSchema(
            fields={
                "role": MetadataFieldDefinition(name="Role", type="text"),
                "notes": MetadataFieldDefinition(name="Notes", type="long_text"),
                "friend": MetadataFieldDefinition(name="Friend", type="entity_ref"),
                "buddies": MetadataFieldDefinition(name="Buddies", type="entity_ref_list"),
                "age": MetadataFieldDefinition(name="Age", type="number"),
                "married": MetadataFieldDefinition(name="Married", type="boolean"),
                "faction": MetadataFieldDefinition(
                    name="Faction",
                    type="select",
                    options=[SelectOption(value="reb", label="Rebel"), SelectOption(value="emp", label="Empire")],
                ),
                "colors": MetadataFieldDefinition(name="Colors", type="list", item_type="text"),
                "swatch": MetadataFieldDefinition(name="Swatch", type="color"),
                "cost": MetadataFieldDefinition(name="Cost", type="computed", computed={"function": "noop"}),
                "blank": MetadataFieldDefinition(name="Blank", type="text"),
            },
        )

    def test_a_nomination_wins_in_its_own_order(self) -> None:
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore",
            fields=["role", "age", "married", "faction"],
            summary_fields=["faction", "role"],
        )
        keys = summary_field_keys(entry_type, self._schema(), {"role": "Captain", "faction": "reb"})
        self.assertEqual(keys, ["faction", "role"])

    def test_an_unknown_nominated_key_is_skipped(self) -> None:
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore", fields=["role", "age"], summary_fields=["role", "ghost", "age"],
        )
        keys = summary_field_keys(entry_type, self._schema(), {"role": "Captain", "age": 45})
        self.assertEqual(keys, ["role", "age"])

    def test_fallback_takes_the_first_three_present_scalars_in_schema_order(self) -> None:
        # notes (long_text) and friend (entity_ref) sit ahead of age/married in
        # `fields` but aren't scalar types, so they're skipped, not counted.
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore",
            fields=["role", "notes", "friend", "age", "married", "faction"],
        )
        metadata = {
            "role": "Captain", "notes": "long", "friend": "some-id",
            "age": 45, "married": True, "faction": "reb",
        }
        keys = summary_field_keys(entry_type, self._schema(), metadata)
        self.assertEqual(keys, ["role", "age", "married"])

    def test_fallback_skips_intrinsic_and_hidden_fields(self) -> None:
        # `title` is the identity triple (lives on the node); `secret` is hidden
        # by its def; `role` is hidden by this type's override. None summarise.
        schema = MetadataSchema(
            fields={
                "title": MetadataFieldDefinition(name="Title", type="text", intrinsic=True),
                "secret": MetadataFieldDefinition(name="Secret", type="text", hidden=True),
                "role": MetadataFieldDefinition(name="Role", type="text"),
                "age": MetadataFieldDefinition(name="Age", type="number"),
                "married": MetadataFieldDefinition(name="Married", type="boolean"),
            },
        )
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore",
            fields=["title", "secret", "role", "age", "married"],
            field_overrides={"role": {"hidden": True}},
        )
        metadata = {"title": "T", "secret": "s", "role": "Captain", "age": 45, "married": False}
        self.assertEqual(summary_field_keys(entry_type, schema, metadata), ["age", "married"])

    def test_fallback_skips_non_scalar_types_and_empty_values(self) -> None:
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore", fields=["swatch", "colors", "cost", "blank", "role"],
        )
        metadata = {"swatch": "amber", "colors": ["a", "b"], "cost": 5, "blank": "", "role": "Captain"}
        keys = summary_field_keys(entry_type, self._schema(), metadata)
        self.assertEqual(keys, ["role"])

    def test_summary_values_renders_select_as_its_option_label(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["faction"], summary_fields=["faction"])
        values = summary_values(entry_type, self._schema(), {"faction": "reb"})
        self.assertEqual(values, [("faction", "Faction", "Rebel")])

    def test_summary_values_renders_boolean_as_yes_no(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["married"], summary_fields=["married"])
        self.assertEqual(summary_values(entry_type, self._schema(), {"married": True}), [("married", "Married", "Yes")])
        self.assertEqual(summary_values(entry_type, self._schema(), {"married": False}), [("married", "Married", "No")])

    def test_summary_values_skips_a_nominated_key_with_no_present_value(self) -> None:
        entry_type = EntryTypeDefinition(
            name="Thing", kind="lore", fields=["role", "age"], summary_fields=["role", "age"],
        )
        values = summary_values(entry_type, self._schema(), {"role": "Captain"})
        self.assertEqual(values, [("role", "Role", "Captain")])

    def test_entity_ref_renders_the_raw_id_with_no_resolver(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["friend"], summary_fields=["friend"])
        values = summary_values(entry_type, self._schema(), {"friend": "lore_abc123"})
        self.assertEqual(values, [("friend", "Friend", "lore_abc123")])

    def test_entity_ref_renders_the_resolved_title_when_a_resolver_is_given(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["friend"], summary_fields=["friend"])
        values = summary_values(
            entry_type, self._schema(), {"friend": "lore_abc123"}, resolve_title=lambda rid: "Pip"
        )
        self.assertEqual(values, [("friend", "Friend", "Pip")])

    def test_entity_ref_list_renders_raw_ids_with_no_resolver(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["buddies"], summary_fields=["buddies"])
        values = summary_values(entry_type, self._schema(), {"buddies": ["a", "b"]})
        self.assertEqual(values, [("buddies", "Buddies", "a, b")])

    def test_entity_ref_list_renders_resolved_titles_joined_by_comma(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["buddies"], summary_fields=["buddies"])
        titles = {"a": "Pip", "b": "Nimitz"}
        values = summary_values(
            entry_type, self._schema(), {"buddies": ["a", "b"]}, resolve_title=lambda rid: titles.get(rid)
        )
        self.assertEqual(values, [("buddies", "Buddies", "Pip, Nimitz")])

    def test_entity_ref_falls_back_to_the_raw_id_when_the_resolver_finds_nothing(self) -> None:
        entry_type = EntryTypeDefinition(name="Thing", kind="lore", fields=["friend"], summary_fields=["friend"])
        values = summary_values(
            entry_type, self._schema(), {"friend": "dangling"}, resolve_title=lambda rid: None
        )
        self.assertEqual(values, [("friend", "Friend", "dangling")])


# --- lore_block: the AI reference qualifier ---------------------------------


class LoreBlockSummaryQualifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Summary Qualifier Tests")
        # lore:character nominates `aliases` as its summary (a built-in field
        # every character carries, ADR-0006's ref/lore-block choke point).
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character", kind="lore", parent="lore:base", fields=[], summary_fields=["aliases"],
                ),
                allow_existing=True,
            )
        )
        self.target = self._make_character("Pip", aliases=["Pipsqueak"])
        self.empty_target = self._make_character("Blank", aliases=[])
        self.hero = self._make_character("Hero", related_entries=[self.target, self.empty_target])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_character(self, title: str, **metadata) -> str:
        created = self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type="lore:character"))
        entry = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title, body="", base_revision=entry.revision, entry_type="lore:character", metadata=metadata,
            ),
        )
        return created.id

    def test_a_ref_to_a_summarized_target_carries_the_summary_attribute(self) -> None:
        block = _format_lore_block(self.service, [self.hero])
        self.assertIn(f'<entry id="{self.target}" summary="Pipsqueak">Pip</entry>', block)

    def test_a_ref_to_a_target_with_no_summary_omits_the_attribute(self) -> None:
        block = _format_lore_block(self.service, [self.hero])
        self.assertIn(f'<entry id="{self.empty_target}">Blank</entry>', block)
        self.assertNotIn(f'id="{self.empty_target}" summary', block)

    def test_the_target_is_read_exactly_once(self) -> None:
        original = ProjectService.read_node
        calls = {"n": 0}

        def counting(self_: ProjectService, node_id: str):
            if node_id == self.target:
                calls["n"] += 1
            return original(self_, node_id)

        with mock.patch.object(ProjectService, "read_node", counting):
            _format_lore_block(self.service, [self.hero])
        self.assertEqual(calls["n"], 1)


class LoreBlockNestedRefSummaryTests(unittest.TestCase):
    """A referenced node's type nominates an `entity_ref` field (#2008
    follow-up): the AI qualifier's `summary="…"` names the NESTED target's
    title, not its raw id."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Nested Ref Summary Tests")
        # lore:character nominates the built-in entity_ref `home_place` (#1316).
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character", kind="lore", parent="lore:base", fields=[], summary_fields=["home_place"],
                ),
                allow_existing=True,
            )
        )
        self.home = self._make_entry("Manticore", "lore:location")
        self.friend = self._make_entry("Pip", "lore:character", home_place=self.home)
        self.hero = self._make_entry("Hero", "lore:character", related_entries=[self.friend])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_entry(self, title: str, entry_type: str, **metadata) -> str:
        created = self.service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type=entry_type))
        entry = self.service.read_lore_entry(created.id)
        self.service.save_lore_entry(
            created.id,
            SaveLoreEntryRequest(
                title=title, body="", base_revision=entry.revision, entry_type=entry_type, metadata=metadata,
            ),
        )
        return created.id

    def test_the_nested_ref_s_summary_shows_the_target_s_title(self) -> None:
        block = _format_lore_block(self.service, [self.hero])
        self.assertIn(f'<entry id="{self.friend}" summary="Manticore">Pip</entry>', block)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
