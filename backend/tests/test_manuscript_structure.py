from __future__ import annotations

import unittest
from unittest.mock import patch

from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveSceneRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.tree_structure import TreeStructureService


class ManuscriptStructureTests(MetadataValidationBase):
    def test_new_project_drops_sequence_from_container_types(self) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        types = [
            item["type"] for item in manifest["manuscript_structure"]["container_types"]
        ]
        self.assertEqual(types, ["manuscript:act", "manuscript:chapter"])

    def test_create_structure_node_inserts_container_under_root(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_nodes = [
            child for child in updated.root.children if child.type == "manuscript:act"
        ]
        self.assertEqual(len(act_nodes), 1)
        self.assertEqual(act_nodes[0].title, "Act One")
        self.assertIsNotNone(act_nodes[0].scene_id)
        backing_file = self.service._path_for_node_id(
            act_nodes[0].scene_id, "manuscript"
        )
        self.assertTrue(backing_file.exists())
        self.assertEqual(backing_file.stem, "Act One")

    def test_container_is_loadable_as_scene(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            child for child in updated.root.children if child.type == "manuscript:act"
        )

        scene = self.service.read_scene(act_node.scene_id)

        self.assertEqual(scene.id, act_node.scene_id)
        self.assertEqual(scene.title, "Act One")
        self.assertEqual(scene.entry_type, "manuscript:act")

    def test_structure_carries_counter_in_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )

        structure = self.service.read_structure()
        act_nodes = [
            child for child in structure.root.children if child.type == "manuscript:act"
        ]
        numbers = [node.computed_metadata.get("number") for node in act_nodes]
        self.assertEqual(numbers, [1, 2])

    def test_structure_yaml_does_not_persist_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )

        raw = self.service._read_yaml(self.root / "manuscript.structure.yaml")

        def has_computed(node: dict) -> bool:
            if "computed_metadata" in node:
                return True
            return any(has_computed(child) for child in node.get("children", []))

        self.assertFalse(has_computed(raw["root"]))

    def test_structure_surfaces_scene_metadata_for_filtering(self) -> None:
        """#184 Phase 3: the Draft roster carries each scene's status + full
        front-matter metadata so a view can filter it by scene field
        (status/pov/…) in one pass, without a per-scene fetch."""
        from app.models import CreateLoreEntryRequest, SaveSceneRequest

        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="revised",
                entry_type="manuscript:scene",
                metadata={"pov": hero.id},
            ),
        )

        structure = self.service.read_structure()
        node = next(
            child
            for child in structure.root.children
            if child.scene_id == self.scene_id
        )
        self.assertEqual(node.status, "revised")
        self.assertIsNotNone(node.metadata)
        self.assertEqual(node.metadata["pov"], hero.id)

    def test_structure_yaml_does_not_persist_scene_metadata(self) -> None:
        """The surfaced `metadata` projection must never echo into the tree
        YAML — it would drift from the leaf front-matter (same invariant as
        status/color/computed_metadata)."""
        from app.models import CreateStructureNodeRequest, SaveSceneRequest

        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="revised",
                entry_type="manuscript:scene",
                metadata={"summary": "Opening beat"},
            ),
        )
        # A structure mutation triggers the write path that must strip it.
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        raw = self.service._read_yaml(self.root / "manuscript.structure.yaml")

        def has_metadata(node: dict) -> bool:
            if "metadata" in node:
                return True
            return any(has_metadata(child) for child in node.get("children", []))

        self.assertFalse(has_metadata(raw["root"]))

    def test_display_template_inherits_from_manuscript_structure(self) -> None:
        schema = self.service.read_metadata_schema()
        for type_id in ("manuscript:act", "manuscript:chapter", "manuscript:scene"):
            self.assertEqual(
                schema.entry_types[type_id].display_template, "{number}. {title}"
            )
        self.assertEqual(
            schema.entry_types["lore:character"].display_template, "{title}"
        )

    def test_has_body_inherits_false_for_containers_true_for_scene(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertFalse(schema.entry_types["manuscript:base"].has_body)
        self.assertFalse(schema.entry_types["manuscript:act"].has_body)
        self.assertFalse(schema.entry_types["manuscript:chapter"].has_body)
        self.assertTrue(schema.entry_types["manuscript:scene"].has_body)
        self.assertTrue(schema.entry_types["lore:character"].has_body)

    def test_status_field_seeds_with_colored_options(self) -> None:
        """The default `status` field ships with colored options. Verifies
        the SelectOption wire shape and the seed colors."""
        schema = self.service.read_metadata_schema()
        status = schema.fields["status"]
        self.assertEqual(status.type, "select")
        # Stored as SelectOption objects with stable colors.
        values = [(o.value, o.color) for o in status.options]
        self.assertEqual(
            values,
            [("draft", "stone"), ("revised", "amber"), ("complete", "moss")],
        )

    def test_select_options_accept_bare_strings(self) -> None:
        """Existing YAMLs with `options: [a, b]` keep working via the
        back-compat validator on MetadataFieldDefinition."""

        field = MetadataFieldDefinition.model_validate(
            {
                "name": "Tier",
                "type": "select",
                "options": ["cheap", "balanced", "best"],
            }
        )
        self.assertEqual(
            [o.value for o in field.options], ["cheap", "balanced", "best"]
        )
        self.assertTrue(all(o.color is None for o in field.options))

    def test_color_inherits_through_parent_chain(self) -> None:
        """Built-in seeds set color on scene/lore_entry/prompt/assistant; child
        types inherit unless they override. Verifies the inheritance list in
        _resolve_metadata_schema_inheritance picks up `color`."""
        schema = self.service.read_metadata_schema()
        # Direct seeds.
        self.assertEqual(schema.entry_types["manuscript:scene"].color, "forest")
        self.assertEqual(schema.entry_types["lore:base"].color, "slate-blue")
        self.assertEqual(schema.entry_types["prompt:base"].color, "warm-brown")
        self.assertEqual(schema.entry_types["assistant:assistant"].color, "graphite")
        # Inherited through one parent link.
        self.assertEqual(schema.entry_types["lore:character"].color, "slate-blue")
        self.assertEqual(schema.entry_types["lore:location"].color, "slate-blue")
        self.assertEqual(schema.entry_types["lore:item"].color, "slate-blue")
        self.assertEqual(schema.entry_types["prompt:continuation"].color, "warm-brown")
        self.assertEqual(schema.entry_types["prompt:general"].color, "warm-brown")
        # Inherited through two parent links (roleplay → continuation → prompt).
        self.assertEqual(schema.entry_types["prompt:roleplay"].color, "warm-brown")

    def test_counter_among_siblings_for_acts(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )
        third = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 3", entry_type="manuscript:act")
        )
        act_nodes = [
            child for child in third.root.children if child.type == "manuscript:act"
        ]

        scenes = [self.service.read_scene(node.scene_id) for node in act_nodes]

        self.assertEqual([s.computed_metadata.get("number") for s in scenes], [1, 2, 3])

    def test_counter_among_siblings_resets_per_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_one = next(
            child for child in structure.root.children if child.title == "Act 1"
        )
        act_two = next(
            child for child in structure.root.children if child.title == "Act 2"
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1", entry_type="manuscript:chapter", parent_id=act_one.id
            )
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 2", entry_type="manuscript:chapter", parent_id=act_one.id
            )
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1", entry_type="manuscript:chapter", parent_id=act_two.id
            )
        )

        structure = self.service.read_structure()
        act_one = next(
            child for child in structure.root.children if child.title == "Act 1"
        )
        act_two = next(
            child for child in structure.root.children if child.title == "Act 2"
        )
        ch_a1 = self.service.read_scene(act_one.children[0].scene_id)
        ch_a2 = self.service.read_scene(act_one.children[1].scene_id)
        ch_b1 = self.service.read_scene(act_two.children[0].scene_id)

        self.assertEqual(ch_a1.computed_metadata.get("number"), 1)
        self.assertEqual(ch_a2.computed_metadata.get("number"), 2)
        self.assertEqual(ch_b1.computed_metadata.get("number"), 1)

    def test_counter_in_manuscript_scope_is_global(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "number": {
                        "name": "Number",
                        "type": "computed",
                        "computed": {"function": "counter", "scope": "manuscript"},
                    },
                },
            },
        )

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_one = next(
            child for child in structure.root.children if child.title == "Act 1"
        )
        act_two = next(
            child for child in structure.root.children if child.title == "Act 2"
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1", entry_type="manuscript:chapter", parent_id=act_one.id
            )
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 2", entry_type="manuscript:chapter", parent_id=act_one.id
            )
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 3", entry_type="manuscript:chapter", parent_id=act_two.id
            )
        )

        structure = self.service.read_structure()
        act_one = next(
            child for child in structure.root.children if child.title == "Act 1"
        )
        act_two = next(
            child for child in structure.root.children if child.title == "Act 2"
        )
        first_in_a1 = self.service.read_scene(act_one.children[0].scene_id)
        second_in_a1 = self.service.read_scene(act_one.children[1].scene_id)
        first_in_a2 = self.service.read_scene(act_two.children[0].scene_id)

        self.assertEqual(first_in_a1.computed_metadata.get("number"), 1)
        self.assertEqual(second_in_a1.computed_metadata.get("number"), 2)
        self.assertEqual(first_in_a2.computed_metadata.get("number"), 3)

    def test_container_can_be_referenced_via_entity_ref(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            child for child in updated.root.children if child.type == "manuscript:act"
        )

        candidates = self.service.list_reference_candidates(entry_type="manuscript:act")

        ids = {candidate.id for candidate in candidates.candidates}
        self.assertIn(act_node.scene_id, ids)

    def test_create_structure_node_nests_under_specific_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            child for child in updated.root.children if child.type == "manuscript:act"
        )
        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1",
                entry_type="manuscript:chapter",
                parent_id=act_node.id,
            )
        )
        nested_act = next(
            child for child in updated.root.children if child.id == act_node.id
        )
        chapters = [
            child for child in nested_act.children if child.type == "manuscript:chapter"
        ]
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].title, "Chapter 1")

    def test_create_structure_node_rejects_abstract_type(self) -> None:
        from app.models import CreateStructureNodeRequest

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_structure_node(
                CreateStructureNodeRequest(title="Bad", entry_type="manuscript:base")
            )
        self.assertIn("abstract", ctx.exception.message)

    def test_rename_structure_node_updates_container_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            child for child in updated.root.children if child.type == "manuscript:act"
        )
        renamed = self.service.rename_structure_node(act_node.id, "The Departure")
        renamed_act = next(
            child for child in renamed.root.children if child.id == act_node.id
        )
        self.assertEqual(renamed_act.title, "The Departure")

    def test_rename_structure_node_updates_scene_file_for_leaf(self) -> None:
        scene_id = self.scene_id
        structure = self.service.read_structure()
        scene_node = next(
            child for child in structure.root.children if child.scene_id == scene_id
        )

        self.service.rename_structure_node(scene_node.id, "First Arrival")

        scene = self.service.read_scene(scene_id)
        self.assertEqual(scene.title, "First Arrival")
        structure = self.service.read_structure()
        refreshed = next(
            child for child in structure.root.children if child.id == scene_node.id
        )
        self.assertEqual(refreshed.title, "First Arrival")

    def _count_structure_writes(self):
        """Count `TreeStructureService.write` calls while still writing through.

        `_manuscript_tree` hands back a fresh service per call, so the count is
        pinned at the class method (in the spirit of test_node_index_memo.py's
        `_spy`) rather than on any one instance.
        """
        calls = [0]
        original = TreeStructureService.write

        def counting(inner_self, document):
            calls[0] += 1
            return original(inner_self, document)

        return calls, patch.object(TreeStructureService, "write", counting)

    def test_prose_only_save_writes_no_structure(self) -> None:
        """The common autosave changes only prose; the title in the structure
        YAML is unchanged, so the whole-file structure rewrite must be skipped
        (the dominant recurring per-autosave cost, #455)."""
        scene = self.service.read_scene(self.scene_id)

        calls, spy = self._count_structure_writes()
        with spy:
            self.service.save_scene(
                self.scene_id,
                SaveSceneRequest(
                    title=scene.title,  # unchanged
                    body=scene.body + "\n\nA new paragraph — prose only.",
                    status=scene.status,
                    entry_type=scene.entry_type,
                    metadata=scene.metadata,
                ),
            )

        self.assertEqual(calls[0], 0, "a prose-only save rewrote the structure YAML")

    def test_title_change_save_still_writes_and_reflects_in_structure(self) -> None:
        """The negative control: a save that changes the title must still write
        the structure, and the tree must carry the new title."""
        scene = self.service.read_scene(self.scene_id)
        structure = self.service.read_structure()
        scene_node = next(
            child for child in structure.root.children if child.scene_id == self.scene_id
        )

        calls, spy = self._count_structure_writes()
        with spy:
            self.service.save_scene(
                self.scene_id,
                SaveSceneRequest(
                    title="A Renamed Scene",
                    body=scene.body,
                    status=scene.status,
                    entry_type=scene.entry_type,
                    metadata=scene.metadata,
                ),
            )

        self.assertGreater(calls[0], 0, "a title change did not rewrite the structure")
        refreshed = next(
            child
            for child in self.service.read_structure().root.children
            if child.id == scene_node.id
        )
        self.assertEqual(refreshed.title, "A Renamed Scene")

    def test_rename_structure_node_rejects_unknown_id(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.rename_structure_node("node_does_not_exist", "Anything")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_structure_node_removes_container_and_scene_files(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_node = next(
            child for child in structure.root.children if child.type == "manuscript:act"
        )
        scene = self.service.create_scene(
            self._make_create_scene("Arrival", parent_id=act_node.id)
        )

        scene_path = self.service._path_for_node_id(scene.id, "manuscript")
        self.assertTrue(scene_path.exists())

        self.service.delete_structure_node(act_node.id)

        self.assertFalse(scene_path.exists())
        refreshed = self.service.read_structure()
        self.assertFalse(
            any(child.id == act_node.id for child in refreshed.root.children)
        )

    def test_cascade_delete_preview_counts_descendants_and_backlinks(self) -> None:
        from app.models import CreateStructureNodeRequest, SaveSceneRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_node = next(
            child for child in structure.root.children if child.type == "manuscript:act"
        )
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1",
                entry_type="manuscript:chapter",
                parent_id=act_node.id,
            )
        )
        refreshed_act = next(
            child for child in chapter_doc.root.children if child.id == act_node.id
        )
        chapter_node = next(
            grandchild
            for grandchild in refreshed_act.children
            if grandchild.type == "manuscript:chapter"
        )
        scene_a = self.service.create_scene(
            self._make_create_scene("Arrival", parent_id=chapter_node.id)
        )
        seren = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        # Outside-the-cascade entry that references one of the about-to-be-
        # deleted scenes — surfaces in the preview's backlinks. Uses the
        # scene's `characters` field pointing back to Seren so the cascade
        # picks up the inbound reference from the lore side.
        bystander = self.service.create_scene(
            self._make_create_scene("Bystander", parent_id=chapter_node.id)
        )
        self.service.save_scene(
            scene_a.id,
            SaveSceneRequest(
                title=scene_a.title,
                body=scene_a.body,
                base_revision=scene_a.revision,
                metadata={"characters": [seren.id]},
            ),
        )
        # Bystander stays — and references Seren. After the act is deleted,
        # Seren is orphaned only by the scene_a deletion; bystander does not
        # reference any descendant of the act being deleted, so it should
        # NOT appear as a backlink.
        self.service.save_scene(
            bystander.id,
            SaveSceneRequest(
                title=bystander.title,
                body=bystander.body,
                base_revision=bystander.revision,
                metadata={"characters": [seren.id]},
            ),
        )

        preview = self.service.cascade_delete_preview(act_node.id)

        self.assertEqual(preview.descendant_scene_count, 2)
        self.assertEqual(preview.descendant_container_count, 1)
        # No entries outside the cascade point at the deleted scenes — the
        # default schema's lore→scene field was removed (`appears_in_scenes`
        # collapsed into `related_entries`-style modelling), so nothing
        # surfaces here. Coverage for the backlinks-listing branch lives in
        # the lore cascade tests below.
        self.assertEqual(preview.backlinks, [])

    def test_cascade_delete_preview_skips_internal_backlinks(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_node = next(
            child for child in structure.root.children if child.type == "manuscript:act"
        )
        self.service.create_scene(
            self._make_create_scene("Arrival", parent_id=act_node.id)
        )
        scene_b = self.service.create_scene(
            self._make_create_scene("Departure", parent_id=act_node.id)
        )
        refreshed_b = self.service.read_scene(scene_b.id)
        self.service.save_scene(
            scene_b.id,
            SaveSceneRequest(
                title=refreshed_b.title,
                body=refreshed_b.body,
                base_revision=refreshed_b.revision,
                status=refreshed_b.status,
                entry_type=refreshed_b.entry_type,
                metadata={"characters": []},
            ),
        )

        preview = self.service.cascade_delete_preview(act_node.id)

        self.assertEqual(preview.backlinks, [])

    def test_move_structure_node_reorders_within_same_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        acts = [
            child for child in structure.root.children if child.type == "manuscript:act"
        ]
        act_1, act_2 = acts[0], acts[1]

        self.service.move_structure_node(act_2.id, structure.root.id, 0)
        refreshed = self.service.read_structure()
        reordered = [
            child for child in refreshed.root.children if child.type == "manuscript:act"
        ]
        self.assertEqual([n.id for n in reordered], [act_2.id, act_1.id])

    def test_move_structure_node_reparents_into_container(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 2", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        acts = [
            child for child in structure.root.children if child.type == "manuscript:act"
        ]
        act_1, act_2 = acts[0], acts[1]
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1", entry_type="manuscript:chapter", parent_id=act_1.id
            )
        )
        refreshed_act_1 = next(
            child for child in chapter_doc.root.children if child.id == act_1.id
        )
        chapter_node = refreshed_act_1.children[0]

        self.service.move_structure_node(chapter_node.id, act_2.id, 0)

        final = self.service.read_structure()
        final_act_1 = next(
            child for child in final.root.children if child.id == act_1.id
        )
        final_act_2 = next(
            child for child in final.root.children if child.id == act_2.id
        )
        self.assertEqual(len(final_act_1.children), 0)
        self.assertEqual([c.id for c in final_act_2.children], [chapter_node.id])

    def test_move_structure_node_rejects_self_into_descendant(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act 1", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act = next(
            child for child in structure.root.children if child.type == "manuscript:act"
        )
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(
                title="Chapter 1", entry_type="manuscript:chapter", parent_id=act.id
            )
        )
        refreshed_act = next(
            child for child in chapter_doc.root.children if child.id == act.id
        )
        chapter = refreshed_act.children[0]

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.move_structure_node(act.id, chapter.id, 0)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_move_structure_node_rejects_root(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.move_structure_node("root", "root", 0)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_delete_structure_node_rejects_root(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.delete_structure_node("root")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_new_scene_file_is_named_by_title(self) -> None:
        scene = self.service.create_scene(self._make_create_scene("First Light"))
        path = self.service._path_for_node_id(scene.id, "manuscript")
        self.assertEqual(path.name, "First Light.md")

    def test_new_lore_file_is_named_by_title(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren the Brave", entry_type="lore:character")
        )
        path = self.service._path_for_node_id(entry.id, "lore")
        self.assertEqual(path.name, "Seren the Brave.md")

    def test_title_with_illegal_chars_gets_sanitized(self) -> None:
        scene = self.service.create_scene(
            self._make_create_scene('Chapter 1: "Hello?"')
        )
        path = self.service._path_for_node_id(scene.id, "manuscript")
        for forbidden in '<>:"/\\|?*':
            self.assertNotIn(forbidden, path.stem)

    def test_collision_resolved_with_suffix(self) -> None:
        first = self.service.create_scene(self._make_create_scene("Departure"))
        second = self.service.create_scene(self._make_create_scene("Departure"))
        first_path = self.service._path_for_node_id(first.id, "manuscript")
        second_path = self.service._path_for_node_id(second.id, "manuscript")
        self.assertEqual(first_path.name, "Departure.md")
        self.assertEqual(second_path.name, "Departure (2).md")

    def test_rename_structure_node_renames_file_too(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        structure = self.service.read_structure()
        act_node = next(
            child for child in structure.root.children if child.type == "manuscript:act"
        )
        original_path = self.service._path_for_node_id(act_node.scene_id, "manuscript")
        self.assertEqual(original_path.name, "Act One.md")

        self.service.rename_structure_node(act_node.id, "The Departure")

        self.assertFalse(original_path.exists())
        new_path = self.service._path_for_node_id(act_node.scene_id, "manuscript")
        self.assertEqual(new_path.name, "The Departure.md")

    def test_rename_structure_node_rejects_empty_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
        )
        act_node = next(
            child for child in updated.root.children if child.type == "manuscript:act"
        )
        with self.assertRaises(ProjectServiceError):
            self.service.rename_structure_node(act_node.id, "   ")

    def test_create_structure_node_rejects_lore_type(self) -> None:
        from app.models import CreateStructureNodeRequest

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_structure_node(
                CreateStructureNodeRequest(title="Bad", entry_type="lore:character")
            )
        self.assertIn("not a manuscript type", ctx.exception.message)

    def test_structure_accepts_custom_container_type(self) -> None:
        structure = self.service.read_structure().root
        structure.children.insert(
            0,
            self.service.read_structure().root.model_validate(
                {
                    "id": "part_one",
                    "type": "part",
                    "title": "Part One",
                    "children": [],
                }
            ),
        )
        self.service._write_yaml(
            self.root / "manuscript.structure.yaml", {"root": structure.model_dump()}
        )
        round_tripped = self.service.read_structure()
        part = next(
            child for child in round_tripped.root.children if child.id == "part_one"
        )
        self.assertEqual(part.type, "part")
        self.assertEqual(part.scene_id, None)

    def test_scene_helpers_walk_custom_container_types(self) -> None:
        scene_id = self._first_scene_id()
        root_node = self.service.read_structure().root
        scene_child = root_node.children[0]
        custom_branch = root_node.model_validate(
            {
                "id": "custom_branch",
                "type": "part",
                "title": "Part One",
                "children": [scene_child.model_dump()],
            }
        )
        new_root = root_node.model_copy(update={"children": [custom_branch]})
        self.service._write_yaml(
            self.root / "manuscript.structure.yaml", {"root": new_root.model_dump()}
        )

        scene_ids = TreeStructureService.collect_leaf_ids(
            self.service.read_structure().root
        )
        self.assertIn(scene_id, scene_ids)
        display_paths = self.service._scene_display_paths()
        self.assertIn(scene_id, display_paths)
        self.assertTrue(display_paths[scene_id].startswith("Part One"))


if __name__ == "__main__":
    unittest.main()
