"""#2239: renaming/deleting a field that is a MEMBER of a reference-keyed
list's group (ADR-0089 §1) reaches stored items and mutation-set/override
rows the same way ADR-0095 §9 (S3) already reaches the LIST field's own id.

- A member rename/delete rewrites the member's key inside every stored item,
  the matching `<list>.<target>.<member>` rows, and an `add` row's encoded
  item value.
- The KEY member (the list's `entity_ref`) is renamed the same way — its id
  is part of the group, not the member-path token.
- An option rename on a member `select` rewrites item values and a
  member-path `replace` row's value, mirroring the top-level reach.
- A plain field with no group involvement is unaffected (regression).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateMutationSetEntryRequest,
    DeleteMetadataFieldRequest,
    GroupMember,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
    MutationSetRow,
    RenameMetadataFieldRequest,
    UpsertMetadataFieldRequest,
    UpsertMetadataGroupRequest,
)
from app.services.project.lore_mutation_items import encode_item
from app.services.project.mutation_anchors import render_anchor
from app.services.project_service import ProjectService


def _layer_id(service: ProjectService) -> str:
    return service.read_metadata_schema_layers().layers[-1].id


class MemberFieldRenameTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Member Field Rename Tests")
        self._define_group_and_list()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _define_group_and_list(self, *, state_options: list[str] | None = None) -> None:
        members = [
            GroupMember(key="who", name="Who", type="entity_ref"),
            GroupMember(key="note", name="Note", type="text"),
        ]
        if state_options is not None:
            members.append(GroupMember(key="state", name="State", type="select", options=state_options))
        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(name="Rel", members=members),
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

    def _write_character(self, node_id: str, items: list[dict] | None = None, title: str = "Mira") -> None:
        (self.root / "lore").mkdir(parents=True, exist_ok=True)
        metadata = {"connections": items} if items is not None else {}
        self.service._write_markdown_with_front_matter(
            self.root / "lore" / f"{node_id}.md",
            {"id": node_id, "title": title, "entry_type": "lore:character", "metadata": metadata},
            "Body.",
        )

    def _pinned_set(self, target_entity: str, rows: list[MutationSetRow]) -> str:
        return self.service.create_mutation_set_entry(
            CreateMutationSetEntryRequest(
                title="Set",
                target_entry_type="lore:character",
                target_entity=target_entity,
                rows=rows,
            )
        ).id

    def _write_override(self, target_id: str, rows: list[dict]) -> Path:
        (self.root / "overrides").mkdir(parents=True, exist_ok=True)
        path = self.root / "overrides" / f"{target_id}-override.md"
        self.service._write_markdown_with_front_matter(
            path,
            {
                "id": "override_test",
                "title": "Override",
                "entry_type": "override:override",
                "target": target_id,
                "rows": rows,
            },
            "",
        )
        return path

    def _anchor_scene(self, set_id: str, anchor_id: str) -> str:
        from app.models import CreateSceneRequest, SaveSceneRequest

        scene = self.service.create_scene(CreateSceneRequest(title=f"Scene {anchor_id}"))
        self.service.save_scene(
            scene.id,
            SaveSceneRequest(title=scene.title, body=render_anchor(set_id, anchor_id)),
        )
        return scene.id


class RenameNonKeyMemberTests(MemberFieldRenameTestCase):
    def test_rename_reaches_items_rows_and_resolution(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("figaro", title="Figaro")
        self._write_character("mira", items=[{"who": "erik", "note": "Owes debt"}])
        set_id = self._pinned_set(
            "mira",
            [
                MutationSetRow(field="connections.erik.note", op="replace", value="Owes more"),
                MutationSetRow(field="connections", op="add", value=encode_item({"who": "figaro", "note": "Ally"})),
            ],
        )
        override_path = self._write_override(
            "mira", [{"field": "connections.erik.note", "op": "replace", "value": "Owes even more"}]
        )
        scene_id = self._anchor_scene(set_id, "a1")

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="note", new_field_id="comment")
        )

        entry = self.service._read_markdown_with_front_matter(self.root / "lore" / "mira.md", strict=True)[0]
        self.assertEqual(entry["metadata"]["connections"], [{"who": "erik", "comment": "Owes debt"}])

        set_entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(
            [(row.field, row.op, row.value) for row in set_entry.rows],
            [
                ("connections.erik.comment", "replace", "Owes more"),
                ("connections", "add", encode_item({"who": "figaro", "comment": "Ally"})),
            ],
        )

        front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
        self.assertEqual(front_matter["rows"][0]["field"], "connections.erik.comment")

        state = self.service.effective_state("mira", scene_id)
        items = {item["who"]: item for item in state["connections"]}
        self.assertEqual(items["erik"]["comment"], "Owes more")
        self.assertEqual(items["figaro"]["comment"], "Ally")
        self.assertNotIn("note", items["erik"])


class DeleteMemberTests(MemberFieldRenameTestCase):
    def test_delete_strips_items_and_rows(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("figaro", title="Figaro")
        self._write_character("mira", items=[{"who": "erik", "note": "Owes debt"}])
        set_id = self._pinned_set(
            "mira",
            [
                MutationSetRow(field="connections.erik.note", op="replace", value="Owes more"),
                MutationSetRow(field="connections", op="add", value=encode_item({"who": "figaro", "note": "Ally"})),
            ],
        )

        self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="note"))

        entry = self.service._read_markdown_with_front_matter(self.root / "lore" / "mira.md", strict=True)[0]
        self.assertEqual(entry["metadata"]["connections"], [{"who": "erik"}])

        set_entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(
            [(row.field, row.op, row.value) for row in set_entry.rows],
            [("connections", "add", encode_item({"who": "figaro"}))],
        )


class RenameKeyMemberTests(MemberFieldRenameTestCase):
    def test_rename_key_member_keeps_items_and_rows_resolving(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("figaro", title="Figaro")
        self._write_character("mira", items=[{"who": "erik", "note": "Owes debt"}])
        set_id = self._pinned_set(
            "mira", [MutationSetRow(field="connections", op="add", value=encode_item({"who": "figaro", "note": "Ally"}))]
        )
        scene_id = self._anchor_scene(set_id, "a1")

        self.service.rename_metadata_field(RenameMetadataFieldRequest(old_field_id="who", new_field_id="contact"))

        entry = self.service._read_markdown_with_front_matter(self.root / "lore" / "mira.md", strict=True)[0]
        self.assertEqual(entry["metadata"]["connections"], [{"contact": "erik", "note": "Owes debt"}])

        state = self.service.effective_state("mira", scene_id)
        items = {item["contact"]: item for item in state["connections"]}
        self.assertEqual(items["erik"]["note"], "Owes debt")
        self.assertEqual(items["figaro"]["note"], "Ally")


class MemberOptionRenameTests(MemberFieldRenameTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Member Field Rename Tests")
        self._define_group_and_list(state_options=["trusted", "wary"])

    def test_option_rename_rewrites_items_and_rows(self) -> None:
        self._write_character("mira", items=[{"who": "erik", "state": "trusted"}])
        override_path = self._write_override(
            "mira", [{"field": "connections.erik.state", "op": "replace", "value": "trusted"}]
        )

        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="note", name="Note", type="text"),
                        GroupMember(key="state", name="State", type="select", options=["confided", "wary"]),
                    ],
                ),
                allow_existing=True,
                member_option_migration={"state": {"trusted": "confided"}},
            )
        )

        entry = self.service._read_markdown_with_front_matter(self.root / "lore" / "mira.md", strict=True)[0]
        self.assertEqual(entry["metadata"]["connections"], [{"who": "erik", "state": "confided"}])

        front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
        self.assertEqual(front_matter["rows"][0]["value"], "confided")


class TopLevelFieldRegressionTests(MemberFieldRenameTestCase):
    def test_plain_field_rename_unaffected_by_member_reach(self) -> None:
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=_layer_id(self.service),
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="text"),
                entry_type="lore:character",
            )
        )
        self._write_character("mira")
        set_id = self._pinned_set("mira", [MutationSetRow(field="rank", op="replace", value="Captain")])

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="rank", new_field_id="service_rank", entry_type="lore:character")
        )

        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual([row.field for row in entry.rows], ["service_rank"])


class GroupUpsertReconciliationTests(MemberFieldRenameTestCase):
    """The dialog never calls rename/delete-field for a member — it saves the
    whole group. `upsert_metadata_group` must detect what disappeared (read
    BEFORE the write, per #2239's follow-up) and clean stored data itself."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Member Field Rename Tests")
        self._define_group_and_list(state_options=["trusted", "wary"])

    def _mira_metadata(self) -> dict:
        return self.service._read_markdown_with_front_matter(self.root / "lore" / "mira.md", strict=True)[0]["metadata"]

    def test_upsert_dropping_a_member_cleans_items_and_rows(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("mira", items=[{"who": "erik", "note": "Owes debt", "state": "trusted"}])
        set_id = self._pinned_set("mira", [MutationSetRow(field="connections.erik.note", op="replace", value="Owes more")])

        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="state", name="State", type="select", options=["trusted", "wary"]),
                    ],
                ),
                allow_existing=True,
            )
        )

        self.assertEqual(self._mira_metadata()["connections"], [{"who": "erik", "state": "trusted"}])
        entry = self.service.read_mutation_set_entry(set_id)
        self.assertEqual(entry.rows, [])

    def test_upsert_dropping_an_option_cleans_values(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("mira", items=[{"who": "erik", "state": "trusted"}])
        override_path = self._write_override(
            "mira", [{"field": "connections.erik.state", "op": "replace", "value": "trusted"}]
        )

        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    members=[
                        GroupMember(key="who", name="Who", type="entity_ref"),
                        GroupMember(key="note", name="Note", type="text"),
                        GroupMember(key="state", name="State", type="select", options=["wary"]),
                    ],
                ),
                allow_existing=True,
            )
        )

        self.assertEqual(self._mira_metadata()["connections"], [{"who": "erik", "state": ""}])
        front_matter, _ = self.service._read_markdown_with_front_matter(override_path, strict=True)
        self.assertEqual(front_matter["rows"][0]["value"], "")

    def test_upsert_relabel_only_touches_no_data_files(self) -> None:
        self._write_character("erik", title="Erik")
        self._write_character("mira", items=[{"who": "erik", "note": "Owes debt", "state": "trusted"}])
        override_path = self._write_override(
            "mira", [{"field": "connections.erik.state", "op": "replace", "value": "trusted"}]
        )
        lore_path = self.root / "lore" / "mira.md"
        lore_mtime_before = lore_path.stat().st_mtime_ns
        override_mtime_before = override_path.stat().st_mtime_ns

        self.service.upsert_metadata_group(
            UpsertMetadataGroupRequest(
                layer_id=_layer_id(self.service),
                group_id="rel",
                group=MetadataGroupDefinition(
                    name="Rel",
                    members=[
                        GroupMember(key="who", name="Contact", type="entity_ref"),
                        GroupMember(key="note", name="Comment", type="text"),
                        GroupMember(key="state", name="Standing", type="select", options=["trusted", "wary"]),
                    ],
                ),
                allow_existing=True,
            )
        )

        # Keys and option values are untouched (only display names/labels
        # changed) — no item or row file should be rewritten.
        self.assertEqual(lore_path.stat().st_mtime_ns, lore_mtime_before)
        self.assertEqual(override_path.stat().st_mtime_ns, override_mtime_before)
        self.assertEqual(
            self._mira_metadata()["connections"], [{"who": "erik", "note": "Owes debt", "state": "trusted"}]
        )


if __name__ == "__main__":
    unittest.main()
