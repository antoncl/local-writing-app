"""ADR-0095 §9 (S3): deletes and schema changes reach mutation sets and
overrides, closes #2232.

- Deleting an entry deletes the sets pinned to it (replacing ADR-0055 §3's
  purge of the pin, which would have turned an active set into an unpinned
  template) and folds their ids into the same purge pass, so a chat's
  `staged_set` naming one is purged too. The anchors are left in the prose,
  reported by Verify as missing.
- Deleting a set purges references to it, a chat's `staged_set` included.
- Renaming/deleting a metadata field reaches mutation-set and override rows,
  plain and as a keyed-list member path, the same way it already reaches
  scene/lore metadata; resolution follows.
- An option rename/delete rewrites row values the same way it rewrites
  stored metadata values.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mutation_helpers import save_scenes_with_mutations
from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreateMutationSetEntryRequest,
    CreateSceneRequest,
    DeleteMetadataFieldRequest,
    GroupMember,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
    MutationSetRow,
    RenameMetadataFieldRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
    UpsertMetadataGroupRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.mutation_anchors import render_anchor
from app.services.project_service import ProjectService


def _layer_id(service: ProjectService) -> str:
    return service.read_metadata_schema_layers().layers[-1].id


def _define_field(service: ProjectService, field_id: str, field_type: str, name: str, **kwargs) -> None:
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=_layer_id(service),
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type, **kwargs),
            entry_type="lore:character",
        )
    )


class MutationSetIntegrityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Mutation Set Integrity Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_character(self, node_id: str, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

    def _pinned_set(self, target_entity: str, rows: list[MutationSetRow], title: str = "Set") -> str:
        return self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title=title,
                target_entry_type="lore:character",
                target_entity=target_entity,
                rows=rows,
            )
        ).id

    def _anchor_scene(self, set_id: str, anchor_id: str) -> str:
        scene = self.service.create_scene(CreateSceneRequest(title=f"Scene {anchor_id}"))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title=scene.title, body=render_anchor(set_id, anchor_id)),
        )
        return scene.id

    def _set_paths(self) -> list[Path]:
        return list((self.root / "mutation-sets").glob("*.md"))


class EntryDeleteCascadeTests(MutationSetIntegrityTestCase):
    def test_entry_delete_removes_its_pinned_sets_and_only_those(self) -> None:
        self._write_character("mira")
        self._write_character("erik")
        pinned = self._pinned_set("mira", [MutationSetRow(field="title", value="The Wolf")])
        other = self._pinned_set("erik", [MutationSetRow(field="title", value="Ranger")])
        self._anchor_scene(pinned, "a1")

        self.service.delete_lore_entry("mira")

        remaining_ids = {p.stem for p in self._set_paths()}
        self.assertNotIn(pinned, remaining_ids)
        self.assertIn(other, remaining_ids)
        with self.assertRaises(ProjectServiceError):
            self.service.read_mutation_set_entry(pinned)

    def test_a_chats_staged_set_naming_a_pinned_set_is_purged(self) -> None:
        self._write_character("mira")
        pinned = self._pinned_set("mira", [MutationSetRow(field="title", value="The Wolf")])
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="Brainstorm", staged_set=pinned))

        self.service.delete_lore_entry("mira")

        self.assertEqual(self.service.read_chat_session(chat.id).staged_set, "")

    def test_anchors_stay_in_the_prose_as_missing_pills_reported_by_verify(self) -> None:
        self._write_character("mira")
        pinned = self._pinned_set("mira", [MutationSetRow(field="title", value="The Wolf")])
        scene_id = self._anchor_scene(pinned, "a1")
        body_before = self.service.read_scene(scene_id).body
        self.assertIn(pinned, body_before)

        self.service.delete_lore_entry("mira")

        body_after = self.service.read_scene(scene_id).body
        self.assertEqual(body_before, body_after)  # prose editing never deletes an anchor (§9)

        result = self.service.validate_project()
        self.assertTrue(any(pinned in w and "does not exist" in w for w in result.warnings))


class SetDeletePurgesReferencesTests(MutationSetIntegrityTestCase):
    def test_deleting_a_set_purges_a_chats_staged_set(self) -> None:
        self._write_character("mira")
        set_id = self._pinned_set("mira", [MutationSetRow(field="title", value="The Wolf")])
        chat = self.service.create_chat_session(CreateChatSessionRequest(title="Brainstorm", staged_set=set_id))

        self.service.delete_mutation_set_entry(set_id)

        self.assertEqual(self.service.read_chat_session(chat.id).staged_set, "")


class FieldRenameReachesRowsTests(MutationSetIntegrityTestCase):
    def setUp(self) -> None:
        super().setUp()
        _define_field(self.service, "rank", "text", "Rank")
        self._write_character("mira")

    def _write_override(self, target_id: str, field: str, value: str) -> Path:
        (self.root / "overrides").mkdir(parents=True, exist_ok=True)
        path = self.root / "overrides" / f"{target_id}-override.md"
        self.service._write_markdown_with_front_matter(
            path,
            {
                "id": "override_test",
                "title": "Override",
                "entry_type": "override:override",
                "target": target_id,
                "rows": [{"field": field, "op": "replace", "value": value}],
            },
            "",
        )
        return path

    def test_rename_renames_set_rows(self) -> None:
        set_id = self._pinned_set("mira", [MutationSetRow(field="rank", op="replace", value="Captain")])

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rank", new_field_id="service_rank", entry_type="lore:character")
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([row.field for row in entry.rows], ["service_rank"])

    def test_rename_renames_override_rows(self) -> None:
        override_path = self._write_override("mira", "rank", "Commodore")

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rank", new_field_id="service_rank", entry_type="lore:character")
        )

        front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
        self.assertEqual(front_matter["rows"][0]["field"], "service_rank")

    def test_rename_renames_a_keyed_list_member_path(self) -> None:
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="note", name="Note", type="text"),
                    ],
                ),
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="rels",
                field=MetadataFieldDefinition(
                    name="Rels",
                    type="list",
                    item_group="rel",
                    item_scalar=False,
                    item_members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="note", name="Note", type="text"),
                    ],
                ),
                entry_type="lore:character",
            )
        )
        set_id = self._pinned_set(
            "mira", [MutationSetRow(field="rels.erik.note", op="replace", value="owes her")]
        )

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rels", new_field_id="connections", entry_type="lore:character")
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([row.field for row in entry.rows], ["connections.erik.note"])

    def test_rename_still_applies_after_the_rename(self) -> None:
        set_id = self._pinned_set("mira", [MutationSetRow(field="rank", op="replace", value="Captain")])
        scene_id = self._anchor_scene(set_id, "a1")

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rank", new_field_id="service_rank", entry_type="lore:character")
        )

        state = self.service.effective_state("mira", scene_id)
        self.assertEqual(state.get("service_rank"), "Captain")
        self.assertNotIn("rank", state)

    def test_delete_removes_the_rows(self) -> None:
        set_id = self._pinned_set(
            "mira",
            [
                MutationSetRow(field="rank", op="replace", value="Captain"),
                MutationSetRow(field="title", op="replace", value="The Captain"),
            ],
        )

        self.service.delete_metadata_field(
            DeleteMetadataFieldRequest(field_id="rank", entry_type="lore:character")
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([row.field for row in entry.rows], ["title"])

    def test_delete_removes_override_rows(self) -> None:
        override_path = self._write_override("mira", "rank", "Commodore")

        self.service.delete_metadata_field(
            DeleteMetadataFieldRequest(field_id="rank", entry_type="lore:character")
        )

        front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
        self.assertEqual(front_matter.get("rows"), [])


class OptionRenameReachesRowValuesTests(MutationSetIntegrityTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._write_character("mira")

    def test_select_replace_row_rewrites_and_resolution_follows(self) -> None:
        _define_field(self.service, "condition", "select", "Condition", options=["Alive", "Dead"])
        set_id = self._pinned_set("mira", [MutationSetRow(field="condition", op="replace", value="Alive")])
        scene_id = self._anchor_scene(set_id, "a1")

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="condition",
                field=MetadataFieldDefinition(name="Condition", type="select", options=["alive", "dead"]),
                entry_type="lore:character",
                option_migration={"Alive": "alive", "Dead": "dead"},
            )
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.rows[0].value, "alive")
        state = self.service.effective_state("mira", scene_id)
        self.assertEqual(state.get("condition"), "alive")

    def test_select_replace_row_cleared_when_option_removed(self) -> None:
        _define_field(self.service, "condition", "select", "Condition", options=["Alive", "Dead"])
        set_id = self._pinned_set("mira", [MutationSetRow(field="condition", op="replace", value="Dead")])

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="condition",
                field=MetadataFieldDefinition(name="Condition", type="select", options=["Alive"]),
                entry_type="lore:character",
            )
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.rows[0].value, "")

    def test_multi_select_add_remove_rows_rewrite_their_member(self) -> None:
        _define_field(self.service, "traits", "multi_select", "Traits", options=["Brave", "Cruel"])
        set_id = self._pinned_set(
            "mira",
            [
                MutationSetRow(field="traits", op="add", value="Brave"),
                MutationSetRow(field="traits", op="remove", value="Cruel"),
            ],
        )

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="traits",
                field=MetadataFieldDefinition(name="Traits", type="multi_select", options=["brave", "cruel"]),
                entry_type="lore:character",
                option_migration={"Brave": "brave", "Cruel": "cruel"},
            )
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([(row.op, row.value) for row in entry.rows], [("add", "brave"), ("remove", "cruel")])

    def test_multi_select_add_row_dropped_when_option_removed(self) -> None:
        _define_field(self.service, "traits", "multi_select", "Traits", options=["Brave", "Cruel"])
        set_id = self._pinned_set("mira", [MutationSetRow(field="traits", op="add", value="Cruel")])

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="traits",
                field=MetadataFieldDefinition(name="Traits", type="multi_select", options=["Brave"]),
                entry_type="lore:character",
            )
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.rows, [])

    def test_multi_select_comma_joined_replace_row_rewrites_each_member(self) -> None:
        _define_field(self.service, "traits", "multi_select", "Traits", options=["Brave", "Cruel", "Kind"])
        set_id = self._pinned_set(
            "mira", [MutationSetRow(field="traits", op="replace", value="Brave,Cruel,Kind")]
        )

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="traits",
                field=MetadataFieldDefinition(name="Traits", type="multi_select", options=["brave", "Kind"]),
                entry_type="lore:character",
                option_migration={"Brave": "brave"},
            )
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.rows[0].value, "brave,Kind")


class LegacyGrammarStillConvertsThroughSetsTests(MutationSetIntegrityTestCase):
    """Sanity: the ADR-0095 S1 conversion helper still lands rows a rename can
    reach, so a migrated project gets the same integrity fix."""

    def test_a_converted_sets_row_still_renames(self) -> None:
        self._write_character("mira")
        _define_field(self.service, "rank", "text", "Rank")
        scene = self.service.create_scene(CreateSceneRequest(title="Chapter One"))
        ids = save_scenes_with_mutations(
            self.service,
            {scene.id: "Before. <!-- mutate:entity=mira;field=rank;value=Captain;id=m1 --> After."},
        )
        set_id, _anchor_id = next(iter(ids.values()))

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rank", new_field_id="service_rank", entry_type="lore:character")
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([row.field for row in entry.rows], ["service_rank"])


if __name__ == "__main__":
    unittest.main()
