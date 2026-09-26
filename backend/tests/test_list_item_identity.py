"""ADR-0096 §1/§2 — declared identity, stamped and minted.

A group gains `identity`, naming its own `text` member that identifies an
item. The resolver stamps it onto every list field using that group as
`item_identity` (never for the `item_type` sugar); the save mints an id for
any item lacking one (or repeating an earlier item's), for every OWNED save
path; declared identity wins over ADR-0089's reference-keyed inference; and
the AI extraction path reconciles only a group that DECLARES identity, never
one that merely has a member named `id`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    DeleteMetadataFieldRequest,
    GroupMember,
    LoreEntry,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
    UpsertMetadataGroupRequest,
)
from app.models.ai import AIEntryPatch
from app.scope import WorkScope
from app.services.ai.extraction import (
    _id_bearing_list_field_ids,
    _reconcile_id_bearing_lists,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.list_item_identity import ensure_list_item_identity
from app.services.project.metadata_refs import keyed_list_key
from app.services.project_service import ProjectService


def _layer_id(service: ProjectService) -> str:
    return service.read_metadata_schema_layers().layers[-1].id


class ListItemIdentityTestCase(unittest.TestCase):
    """A user-defined group `sighting` (identity `id`, title member `note`) on
    a list field `sightings`, applied to `lore:location` and `manuscript:scene`
    — the shape spec item 11 asks for: a user-defined group + list field on a
    lore entry type AND a scene type."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "List Item Identity Tests")
        self._define_group_and_list()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _define_group_and_list(self, *, identity: str | None = "sight_id") -> None:
        members = [
            GroupMember(key="sight_id", name="ID", type="text"),
            GroupMember(key="note", name="Note", type="text"),
        ]
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="sighting",
                group=MetadataGroupDefinition(name="Sighting", members=members, identity=identity),
                allow_existing=True,
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="sightings",
                field=MetadataFieldDefinition(name="Sightings", type="list", item_group="sighting"),
                entry_type="lore:location",
                allow_existing=True,
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="sightings",
                field=MetadataFieldDefinition(name="Sightings", type="list", item_group="sighting"),
                entry_type="manuscript:scene",
                allow_existing=True,
            )
        )

    def _create_location(self) -> str:
        return self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Old Mill", entry_type="lore:location")
        ).id

    def _save_location(self, entry_id: str, metadata: dict) -> LoreEntry:
        entry = self.service.read_lore_entry(entry_id)
        return self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:location",
                metadata=metadata,
            ),
        )


# ---------------------------------------------------------------------------
# Resolver stamping
# ---------------------------------------------------------------------------


class StampingTests(ListItemIdentityTestCase):
    def test_stamps_item_identity_from_the_group(self) -> None:
        field = self.service.read_metadata_schema().fields["sightings"]
        self.assertEqual(field.item_identity, "sight_id")

    def test_never_stamped_for_the_item_type_sugar(self) -> None:
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="nicknames",
                field=MetadataFieldDefinition(name="Nicknames", type="list", item_type="text"),
                entry_type="lore:location",
                allow_existing=True,
            )
        )
        field = self.service.read_metadata_schema().fields["nicknames"]
        self.assertIsNone(field.item_identity)

    def test_not_stamped_when_identity_names_a_missing_member(self) -> None:
        # Direct YAML write (not the API), which validates and 422s on this —
        # the resolver still must not stamp a hand-edited invalid schema.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["sighting"]["identity"] = "nope"
        self.service._write_yaml(schema_path, data)
        field = self.service.read_metadata_schema().fields["sightings"]
        self.assertIsNone(field.item_identity)

    def test_not_stamped_when_identity_names_a_non_text_member(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["sighting"]["members"].append({"key": "count", "name": "Count", "type": "number"})
        data["groups"]["sighting"]["identity"] = "count"
        self.service._write_yaml(schema_path, data)
        field = self.service.read_metadata_schema().fields["sightings"]
        self.assertIsNone(field.item_identity)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationTests(ListItemIdentityTestCase):
    def test_identity_naming_no_member_is_a_soft_error(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["sighting"]["identity"] = "nope"
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("names no member" in e and "sighting" in e for e in errors), errors)

    def test_identity_naming_a_non_text_member_is_a_soft_error(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data["groups"]["sighting"]["members"].append({"key": "count", "name": "Count", "type": "number"})
        data["groups"]["sighting"]["identity"] = "count"
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(any("must name a text member" in e for e in errors), errors)

    def test_no_identity_declared_is_not_an_error(self) -> None:
        self._define_group_and_list(identity=None)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertFalse(any("sighting" in e for e in errors), errors)


# ---------------------------------------------------------------------------
# Group member rename / removal carries identity
# ---------------------------------------------------------------------------


class MemberRenameCarriesIdentityTests(ListItemIdentityTestCase):
    def test_renaming_the_identity_member_renames_identity(self) -> None:
        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="sight_id", new_field_id="sighting_id", entry_type="lore:location")
        )
        group = self.service.read_metadata_schema().groups["sighting"]
        self.assertEqual(group.identity, "sighting_id")
        field = self.service.read_metadata_schema().fields["sightings"]
        self.assertEqual(field.item_identity, "sighting_id")

    def test_removing_the_identity_member_clears_identity(self) -> None:
        self.service.delete_metadata_field(
            DeleteMetadataFieldRequest(field_id="sight_id", entry_type="lore:location")
        )
        group = self.service.read_metadata_schema().groups["sighting"]
        self.assertIsNone(group.identity)
        field = self.service.read_metadata_schema().fields["sightings"]
        self.assertIsNone(field.item_identity)

    def test_renaming_a_non_identity_member_leaves_identity_alone(self) -> None:
        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="note", new_field_id="comment", entry_type="lore:location")
        )
        group = self.service.read_metadata_schema().groups["sighting"]
        self.assertEqual(group.identity, "sight_id")

    def test_whole_group_replace_clears_a_dangling_identity(self) -> None:
        # The Groups dialog's whole-group replace has no rename tracking (a
        # member rename there is delete-old/add-new): a replace that drops the
        # identity member without also clearing `identity` must not leave a
        # dangling reference on disk.
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="sighting",
                group=MetadataGroupDefinition(
                    name="Sighting",
                    identity="sight_id",
                    members=[GroupMember(key="note", name="Note", type="text")],
                ),
                allow_existing=True,
            )
        )
        group = self.service.read_metadata_schema().groups["sighting"]
        self.assertIsNone(group.identity)


# ---------------------------------------------------------------------------
# Built-in plot groups
# ---------------------------------------------------------------------------


class BuiltinGroupsDeclareIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Builtin Groups Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_plot_beat_and_plot_instance_beat_declare_identity(self) -> None:
        groups = self.service.read_metadata_schema().groups
        self.assertEqual(groups["plot_beat"].identity, "id")
        self.assertEqual(groups["plot_instance_beat"].identity, "id")

    def test_beat_fields_are_stamped_with_item_identity(self) -> None:
        fields = self.service.read_metadata_schema().fields
        self.assertEqual(fields["beats"].item_identity, "id")
        self.assertEqual(fields["instance_beats"].item_identity, "id")


# ---------------------------------------------------------------------------
# Declared identity wins over ADR-0089's reference-keyed inference
# ---------------------------------------------------------------------------


class KeyedListVsDeclaredIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Keyed vs Identity Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_field(self, *, identity: str | None) -> None:
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    identity=identity,
                    members=[
                        GroupMember(key="label", name="Label", type="text"),
                        GroupMember(key="who", name="Who", type="entity_ref"),
                    ],
                ),
                allow_existing=True,
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="connections",
                field=MetadataFieldDefinition(name="Connections", type="list", item_group="rel"),
                entry_type="lore:character",
                allow_existing=True,
            )
        )

    def test_a_group_with_one_entity_ref_member_and_no_identity_is_keyed(self) -> None:
        self._make_field(identity=None)
        field = self.service.read_metadata_schema().fields["connections"]
        self.assertEqual(keyed_list_key(field), "who")

    def test_declaring_identity_on_the_same_shape_turns_off_keying(self) -> None:
        self._make_field(identity="label")
        field = self.service.read_metadata_schema().fields["connections"]
        self.assertIsNone(keyed_list_key(field))


# ---------------------------------------------------------------------------
# Minting on save
# ---------------------------------------------------------------------------


class MintingOnSaveTests(ListItemIdentityTestCase):
    def test_lore_owned_save_mints_ids_for_a_user_group(self) -> None:
        entry_id = self._create_location()
        saved = self._save_location(
            entry_id, {"sightings": [{"note": "Seen at dusk"}, {"note": "Seen at dawn"}]}
        )
        ids = [item["sight_id"] for item in saved.metadata["sightings"]]
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(isinstance(i, str) and i.startswith("item_") for i in ids))
        self.assertEqual(len(set(ids)), 2)

    def test_scene_save_mints_ids_for_a_user_group(self) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Chapter One"))
        saved = self.service.save_scene(
            scene.id,
            SaveSceneRequest(
                title=scene.title,
                body="Body.",
                entry_type="manuscript:scene",
                metadata={"sightings": [{"note": "A shadow passes"}]},
            ),
        )
        ids = [item["sight_id"] for item in saved.metadata["sightings"]]
        self.assertEqual(len(ids), 1)
        self.assertTrue(ids[0].startswith("item_"))

    def test_an_existing_id_is_never_changed(self) -> None:
        entry_id = self._create_location()
        first = self._save_location(entry_id, {"sightings": [{"note": "Seen at dusk"}]})
        first_id = first.metadata["sightings"][0]["sight_id"]
        second = self._save_location(
            entry_id, {"sightings": [{"sight_id": first_id, "note": "Seen at dusk, revised"}]}
        )
        self.assertEqual(second.metadata["sightings"][0]["sight_id"], first_id)

    def test_a_repeated_id_is_reminted(self) -> None:
        entry_id = self._create_location()
        saved = self._save_location(
            entry_id,
            {
                "sightings": [
                    {"sight_id": "item_dupe", "note": "First"},
                    {"sight_id": "item_dupe", "note": "Second"},
                ]
            },
        )
        ids = [item["sight_id"] for item in saved.metadata["sightings"]]
        self.assertEqual(ids[0], "item_dupe")
        self.assertNotEqual(ids[1], "item_dupe")
        self.assertEqual(len(set(ids)), 2)

    def test_a_blank_item_still_saves_and_gains_an_id(self) -> None:
        entry_id = self._create_location()
        saved = self._save_location(entry_id, {"sightings": [{}]})
        self.assertTrue(saved.metadata["sightings"][0]["sight_id"])

    def test_ensure_list_item_identity_reports_what_it_minted(self) -> None:
        schema = self.service.read_metadata_schema()
        metadata = {"sightings": [{"note": "a"}, {"sight_id": "item_x", "note": "b"}]}
        minted = ensure_list_item_identity(metadata, "lore:location", schema)
        self.assertEqual(len(minted.get("sightings", [])), 1)
        self.assertEqual(metadata["sightings"][1]["sight_id"], "item_x")


# ---------------------------------------------------------------------------
# No minting on an override save
# ---------------------------------------------------------------------------


class OverrideSaveMintsNothingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "groups": {
                    "sighting": {
                        "name": "Sighting",
                        "identity": "id",
                        "members": [
                            {"key": "id", "name": "ID", "type": "text"},
                            {"key": "note", "name": "Note", "type": "text"},
                        ],
                    }
                },
                "fields": {"sightings": {"name": "Sightings", "type": "list", "item_group": "sighting"}},
                "entry_types": {"lore:character": {"fields": ["sightings"]}},
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def test_override_save_from_a_descendant_layer_mints_nothing(self) -> None:
        # The ancestor's own item has no id yet (written directly, bypassing
        # the owning save that would mint one) — the realistic shape of an
        # entry not saved since identity was declared.
        writer = ProjectService(WorkScope(root=self.base))
        writer._write_lore_entry_file(
            self.base / "lore" / "honor.md",
            LoreEntry(
                id="honor",
                title="Honor Harrington",
                body="Body.",
                revision="",
                entry_type="lore:character",
                metadata={"sightings": [{"note": "Seen at the academy"}]},
            ),
        )
        # An echoed save at the book layer (unchanged list) must succeed —
        # never mint, never manufacture the difference an override refuses.
        saved = self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington",
                body="Body.",
                entry_type="lore:character",
                metadata={"sightings": [{"note": "Seen at the academy"}]},
                authoring_layer_id=self._layer_id(self.root),
            ),
        )
        self.assertNotIn("id", saved.metadata["sightings"][0])

    def test_a_differing_list_override_save_still_422s(self) -> None:
        writer = ProjectService(WorkScope(root=self.base))
        writer._write_lore_entry_file(
            self.base / "lore" / "honor.md",
            LoreEntry(
                id="honor",
                title="Honor Harrington",
                body="Body.",
                revision="",
                entry_type="lore:character",
                metadata={"sightings": [{"note": "Seen at the academy"}]},
            ),
        )
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.save_lore_entry(
                "honor",
                SaveLoreEntryRequest(
                    title="Honor Harrington",
                    body="Body.",
                    entry_type="lore:character",
                    metadata={"sightings": [{"note": "Seen at the academy"}, {"note": "Seen twice"}]},
                    authoring_layer_id=self._layer_id(self.root),
                ),
            )
        self.assertEqual(caught.exception.status_code, 422)


# ---------------------------------------------------------------------------
# AI extraction reconcile
# ---------------------------------------------------------------------------


class AIExtractionReconcileTests(ListItemIdentityTestCase):
    def test_id_bearing_list_field_ids_selects_a_declared_group(self) -> None:
        self.assertIn("sightings", _id_bearing_list_field_ids(self.service.read_metadata_schema(), "lore:location"))

    def test_id_bearing_list_field_ids_ignores_an_undeclared_id_member(self) -> None:
        # A user's own group with an `id` member it never declared as
        # identity is an ordinary text member, not reconciled.
        self._define_group_and_list(identity=None)
        self.assertNotIn("sightings", _id_bearing_list_field_ids(self.service.read_metadata_schema(), "lore:location"))

    def test_reconciles_a_declared_group_against_the_stored_list(self) -> None:
        entry_id = self._create_location()
        saved = self._save_location(entry_id, {"sightings": [{"note": "Seen at dusk"}]})
        stored_id = saved.metadata["sightings"][0]["sight_id"]
        # No id_key/title_key match the literal "id"/"title" — reconciliation
        # must use the field's DECLARED identity/title members instead. The
        # proposed title matches the stored one exactly, so the invented
        # sight_id is replaced by the stored item's real one.
        patch = AIEntryPatch(
            fields={"sightings": [{"sight_id": "invented", "note": "Seen at dusk"}]},
        )
        reconciled, reports = _reconcile_id_bearing_lists(
            self.service, entry_type="lore:location", node_id=entry_id, patch=patch
        )
        self.assertIn("sightings", reports)
        self.assertEqual(reconciled.fields["sightings"][0]["sight_id"], stored_id)

    def test_does_not_reconcile_an_undeclared_group_with_an_id_member(self) -> None:
        self._define_group_and_list(identity=None)
        entry_id = self._create_location()
        self._save_location(entry_id, {"sightings": [{"sight_id": "hand_authored", "note": "Seen at dusk"}]})
        patch = AIEntryPatch(fields={"sightings": [{"sight_id": "invented", "note": "Seen at dusk, revised"}]})
        reconciled, reports = _reconcile_id_bearing_lists(
            self.service, entry_type="lore:location", node_id=entry_id, patch=patch
        )
        self.assertEqual(reports, {})
        # Untouched — an undeclared `id` member is ordinary data, left as the
        # model proposed it.
        self.assertEqual(reconciled.fields["sightings"][0]["sight_id"], "invented")
