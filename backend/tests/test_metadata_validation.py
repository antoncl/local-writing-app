from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.models import (
    CreateLoreEntryRequest,
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    SearchRequest,
    UpdateProjectSettingsRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService, ProjectServiceError


class MetadataValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.universe = self.base / "universe"
        self.world = self.universe / "series"
        self.root = self.world / "test"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")
        self._set_projects_base_folder(self.base)
        self.scene_id = next((self.root / "scenes").glob("*.md")).stem

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_projects_base_folder(self, path: Path) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(path)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def test_default_schema_seeds_act_and_chapter(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("act", schema.entry_types)
        self.assertIn("chapter", schema.entry_types)
        self.assertEqual(schema.entry_types["act"].kind, "scene")
        self.assertEqual(schema.entry_types["chapter"].kind, "scene")
        self.assertFalse(schema.entry_types["act"].abstract)
        self.assertFalse(schema.entry_types["chapter"].abstract)

    def test_manuscript_structure_is_shared_abstract_parent(self) -> None:
        schema = self.service.read_metadata_schema()
        parent = schema.entry_types.get("manuscript_structure")
        self.assertIsNotNone(parent)
        assert parent is not None
        self.assertTrue(parent.abstract)
        self.assertEqual(parent.kind, "scene")
        for type_id in ["act", "chapter", "scene"]:
            self.assertEqual(schema.entry_types[type_id].parent, "manuscript_structure")
            self.assertIn("summary", schema.entry_types[type_id].fields)

    def test_builtin_entry_type_keeps_built_in_source_after_field_add(self) -> None:
        custom_field = MetadataFieldDefinition(name="POV", type="text", options=[])
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                field_id="pov",
                field=custom_field,
                entry_type="scene",
                allow_existing=False,
            )
        )

        overview = self.service.read_metadata_schema_overview()

        self.assertTrue(overview.entry_type_sources["scene"].built_in)
        self.assertTrue(overview.entry_type_sources["chapter"].built_in)
        self.assertTrue(overview.entry_type_sources["act"].built_in)
        self.assertFalse(overview.field_sources["pov"].built_in)

    def test_summary_lives_on_parent_not_in_scene_own_fields(self) -> None:
        schema = self.service.read_metadata_schema()
        scene_definition = schema.entry_types["scene"]
        self.assertNotIn("summary", scene_definition.own_fields)
        self.assertIn("summary", scene_definition.fields)
        self.assertIn("status", scene_definition.own_fields)

    def test_new_project_drops_sequence_from_container_types(self) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        types = [item["type"] for item in manifest["manuscript_structure"]["container_types"]]
        self.assertEqual(types, ["act", "chapter"])

    def test_create_structure_node_inserts_container_under_root(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_nodes = [child for child in updated.root.children if child.type == "act"]
        self.assertEqual(len(act_nodes), 1)
        self.assertEqual(act_nodes[0].title, "Act One")
        self.assertIsNotNone(act_nodes[0].scene_id)
        backing_file = self.root / "scenes" / f"{act_nodes[0].scene_id}.md"
        self.assertTrue(backing_file.exists())

    def test_container_is_loadable_as_scene(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(child for child in updated.root.children if child.type == "act")

        scene = self.service.read_scene(act_node.scene_id)

        self.assertEqual(scene.id, act_node.scene_id)
        self.assertEqual(scene.title, "Act One")
        self.assertEqual(scene.entry_type, "act")

    def test_structure_carries_counter_in_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))

        structure = self.service.read_structure()
        act_nodes = [child for child in structure.root.children if child.type == "act"]
        numbers = [node.computed_metadata.get("number") for node in act_nodes]
        self.assertEqual(numbers, [1, 2])

    def test_structure_yaml_does_not_persist_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))

        raw = self.service._read_yaml(self.root / "manuscript.structure.yaml")

        def has_computed(node: dict) -> bool:
            if "computed_metadata" in node:
                return True
            return any(has_computed(child) for child in node.get("children", []))

        self.assertFalse(has_computed(raw["root"]))

    def test_display_template_inherits_from_manuscript_structure(self) -> None:
        schema = self.service.read_metadata_schema()
        for type_id in ("act", "chapter", "scene"):
            self.assertEqual(schema.entry_types[type_id].display_template, "{number}. {title}")
        self.assertEqual(schema.entry_types["character"].display_template, "{title}")

    def test_has_body_inherits_false_for_containers_true_for_scene(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertFalse(schema.entry_types["manuscript_structure"].has_body)
        self.assertFalse(schema.entry_types["act"].has_body)
        self.assertFalse(schema.entry_types["chapter"].has_body)
        self.assertTrue(schema.entry_types["scene"].has_body)
        self.assertTrue(schema.entry_types["character"].has_body)

    def test_counter_among_siblings_for_acts(self) -> None:
        from app.models import CreateStructureNodeRequest

        first = self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))
        third = self.service.create_structure_node(CreateStructureNodeRequest(title="Act 3", entry_type="act"))
        act_nodes = [child for child in third.root.children if child.type == "act"]

        scenes = [self.service.read_scene(node.scene_id) for node in act_nodes]

        self.assertEqual([s.computed_metadata.get("number") for s in scenes], [1, 2, 3])

    def test_counter_among_siblings_resets_per_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))
        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 2", entry_type="chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_two.id))

        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
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

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))
        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 2", entry_type="chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 3", entry_type="chapter", parent_id=act_two.id))

        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
        first_in_a1 = self.service.read_scene(act_one.children[0].scene_id)
        second_in_a1 = self.service.read_scene(act_one.children[1].scene_id)
        first_in_a2 = self.service.read_scene(act_two.children[0].scene_id)

        self.assertEqual(first_in_a1.computed_metadata.get("number"), 1)
        self.assertEqual(second_in_a1.computed_metadata.get("number"), 2)
        self.assertEqual(first_in_a2.computed_metadata.get("number"), 3)

    def test_container_can_be_referenced_via_entity_ref(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(child for child in updated.root.children if child.type == "act")

        candidates = self.service.list_reference_candidates(entry_type="act")

        ids = {candidate.id for candidate in candidates.candidates}
        self.assertIn(act_node.scene_id, ids)

    def test_create_structure_node_nests_under_specific_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(child for child in updated.root.children if child.type == "act")
        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_node.id)
        )
        nested_act = next(child for child in updated.root.children if child.id == act_node.id)
        chapters = [child for child in nested_act.children if child.type == "chapter"]
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].title, "Chapter 1")

    def test_create_structure_node_rejects_abstract_type(self) -> None:
        from app.models import CreateStructureNodeRequest

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_structure_node(
                CreateStructureNodeRequest(title="Bad", entry_type="manuscript_structure")
            )
        self.assertIn("abstract", ctx.exception.message)

    def test_rename_structure_node_updates_container_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(child for child in updated.root.children if child.type == "act")
        renamed = self.service.rename_structure_node(act_node.id, "The Departure")
        renamed_act = next(child for child in renamed.root.children if child.id == act_node.id)
        self.assertEqual(renamed_act.title, "The Departure")

    def test_rename_structure_node_updates_scene_file_for_leaf(self) -> None:
        scene_id = next((self.root / "scenes").glob("*.md")).stem
        structure = self.service.read_structure()
        scene_node = next(child for child in structure.root.children if child.scene_id == scene_id)

        self.service.rename_structure_node(scene_node.id, "First Arrival")

        scene = self.service.read_scene(scene_id)
        self.assertEqual(scene.title, "First Arrival")
        structure = self.service.read_structure()
        refreshed = next(child for child in structure.root.children if child.id == scene_node.id)
        self.assertEqual(refreshed.title, "First Arrival")

    def test_rename_structure_node_rejects_unknown_id(self) -> None:
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.rename_structure_node("node_does_not_exist", "Anything")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_delete_structure_node_removes_container_and_scene_files(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "act")
        scene = self.service.create_scene(
            self._make_create_scene("Arrival", parent_id=act_node.id)
        )

        scene_path = next((self.root / "scenes").glob(f"{scene.id}.md"))
        self.assertTrue(scene_path.exists())

        self.service.delete_structure_node(act_node.id)

        self.assertFalse(scene_path.exists())
        refreshed = self.service.read_structure()
        self.assertFalse(any(child.id == act_node.id for child in refreshed.root.children))

    def test_cascade_delete_preview_counts_descendants_and_backlinks(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "act")
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_node.id)
        )
        refreshed_act = next(child for child in chapter_doc.root.children if child.id == act_node.id)
        chapter_node = next(grandchild for grandchild in refreshed_act.children if grandchild.type == "chapter")
        scene_a = self.service.create_scene(self._make_create_scene("Arrival", parent_id=chapter_node.id))
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        self.service.save_lore_entry(
            seren.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown=seren.body_markdown,
                base_revision=seren.revision,
                entry_type="character",
                metadata={"appears_in_scenes": [scene_a.id]},
            ),
        )

        preview = self.service.cascade_delete_preview(act_node.id)

        self.assertEqual(preview.descendant_scene_count, 1)
        self.assertEqual(preview.descendant_container_count, 1)
        self.assertEqual(len(preview.backlinks), 1)
        self.assertEqual(preview.backlinks[0].id, seren.id)
        self.assertEqual(preview.backlinks[0].field_id, "appears_in_scenes")

    def test_cascade_delete_preview_skips_internal_backlinks(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "act")
        scene_a = self.service.create_scene(self._make_create_scene("Arrival", parent_id=act_node.id))
        scene_b = self.service.create_scene(self._make_create_scene("Departure", parent_id=act_node.id))
        refreshed_b = self.service.read_scene(scene_b.id)
        self.service.save_scene(
            scene_b.id,
            SaveSceneRequest(
                title=refreshed_b.title,
                body_markdown=refreshed_b.body_markdown,
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

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))
        structure = self.service.read_structure()
        acts = [child for child in structure.root.children if child.type == "act"]
        act_1, act_2 = acts[0], acts[1]

        self.service.move_structure_node(act_2.id, structure.root.id, 0)
        refreshed = self.service.read_structure()
        reordered = [child for child in refreshed.root.children if child.type == "act"]
        self.assertEqual([n.id for n in reordered], [act_2.id, act_1.id])

    def test_move_structure_node_reparents_into_container(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="act"))
        structure = self.service.read_structure()
        acts = [child for child in structure.root.children if child.type == "act"]
        act_1, act_2 = acts[0], acts[1]
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act_1.id)
        )
        refreshed_act_1 = next(child for child in chapter_doc.root.children if child.id == act_1.id)
        chapter_node = refreshed_act_1.children[0]

        self.service.move_structure_node(chapter_node.id, act_2.id, 0)

        final = self.service.read_structure()
        final_act_1 = next(child for child in final.root.children if child.id == act_1.id)
        final_act_2 = next(child for child in final.root.children if child.id == act_2.id)
        self.assertEqual(len(final_act_1.children), 0)
        self.assertEqual([c.id for c in final_act_2.children], [chapter_node.id])

    def test_move_structure_node_rejects_self_into_descendant(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="act"))
        structure = self.service.read_structure()
        act = next(child for child in structure.root.children if child.type == "act")
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="chapter", parent_id=act.id)
        )
        refreshed_act = next(child for child in chapter_doc.root.children if child.id == act.id)
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

    def _make_create_scene(self, title: str, parent_id: str | None = None):
        from app.models import CreateSceneRequest

        return CreateSceneRequest(title=title, parent_id=parent_id)

    def test_rename_structure_node_rejects_empty_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="act")
        )
        act_node = next(child for child in updated.root.children if child.type == "act")
        with self.assertRaises(ProjectServiceError):
            self.service.rename_structure_node(act_node.id, "   ")

    def test_create_structure_node_rejects_lore_type(self) -> None:
        from app.models import CreateStructureNodeRequest

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_structure_node(
                CreateStructureNodeRequest(title="Bad", entry_type="character")
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
        self.service._write_yaml(self.root / "manuscript.structure.yaml", {"root": structure.model_dump()})
        round_tripped = self.service.read_structure()
        part = next(child for child in round_tripped.root.children if child.id == "part_one")
        self.assertEqual(part.type, "part")
        self.assertEqual(part.scene_id, None)

    def test_scene_helpers_walk_custom_container_types(self) -> None:
        scene_id = next((self.root / "scenes").glob("*.md")).stem
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
        self.service._write_yaml(self.root / "manuscript.structure.yaml", {"root": new_root.model_dump()})

        scene_ids = self.service._collect_scene_ids(self.service.read_structure().root)
        self.assertIn(scene_id, scene_ids)
        display_paths = self.service._scene_display_paths()
        self.assertIn(scene_id, display_paths)
        self.assertTrue(display_paths[scene_id].startswith("Part One"))

    def test_schema_layers_include_empty_intermediate_folders(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers

        self.assertEqual(
            [Path(layer.folder_path) for layer in layers],
            [self.base, self.universe, self.world, self.root],
        )
        self.assertFalse(layers[1].exists)
        self.assertFalse(layers[2].exists)

    def test_schema_layers_infer_base_schema_above_default_project_parent(self) -> None:
        self._set_projects_base_folder(self.root.parent)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {},
                "fields": {},
            },
        )

        layers = self.service.read_metadata_schema_layers().layers

        self.assertEqual(
            [Path(layer.folder_path) for layer in layers],
            [self.base, self.universe, self.world, self.root],
        )

    def test_valid_scene_metadata_saves(self) -> None:
        scene = self.service.read_scene(self.scene_id)

        saved = self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown="Seren waits at the taverna.",
                base_revision=scene.revision,
                status="draft",
                entry_type="scene",
                metadata={
                    "summary": "Opening beat",
                },
            ),
        )

        self.assertEqual(saved.metadata["summary"], "Opening beat")
        self.assertEqual(saved.computed_metadata["word_count"], 5)

    def test_save_rejects_computed_metadata(self) -> None:
        scene = self.service.read_scene(self.scene_id)

        with self.assertRaisesRegex(ProjectServiceError, "computed metadata field word_count"):
            self.service.save_scene(
                self.scene_id,
                SaveSceneRequest(
                    title=scene.title,
                    body_markdown=scene.body_markdown,
                    base_revision=scene.revision,
                    status="draft",
                    entry_type="scene",
                    metadata={"word_count": 12},
                ),
            )

    def test_validation_reports_hand_edited_computed_metadata(self) -> None:
        path = self.root / "scenes" / f"{self.scene_id}.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("metadata: {}", "metadata:\n  word_count: 12"), encoding="utf-8")

        validation = self.service.validate_project()

        self.assertFalse(validation.valid)
        self.assertTrue(
            any("computed metadata field word_count" in error for error in validation.errors),
            validation.errors,
        )

    def test_metadata_schema_layers_apply_from_base_to_project(self) -> None:
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "scene": {
                        "name": "Base Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "pov", "word_count"],
                    }
                },
                "fields": {
                    "pov": {"name": "Point of View", "type": "text"},
                },
            },
        )
        self.service._write_yaml(
            self.world / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "scene": {
                        "name": "World Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "pov", "tension", "word_count"],
                    }
                },
                "fields": {
                    "tension": {"name": "Tension", "type": "number"},
                },
            },
        )

        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["scene"].name, "World Scene")
        self.assertIn("pov", schema.fields)
        self.assertIn("tension", schema.fields)
        self.assertEqual(schema.entry_types["scene"].fields, ["number", "summary", "status", "characters", "locations", "word_count", "pov", "tension"])

        scene = self.service.read_scene(self.scene_id)
        saved = self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status="draft",
                entry_type="scene",
                metadata={"pov": "Seren", "tension": 3},
            ),
        )

        self.assertEqual(saved.metadata["pov"], "Seren")
        self.assertEqual(saved.metadata["tension"], 3)

    def test_validation_warns_when_base_folder_is_not_an_ancestor(self) -> None:
        self._set_projects_base_folder(Path(self.temp_dir.name) / "elsewhere")

        validation = self.service.validate_project()

        self.assertTrue(validation.valid)
        self.assertTrue(
            any("not inside settings.projects_base_folder" in warning for warning in validation.warnings),
            validation.warnings,
        )

    def test_project_settings_update_sets_base_folder(self) -> None:
        updated_base = self.universe

        project = self.service.update_project_settings(UpdateProjectSettingsRequest(projects_base_folder=str(updated_base)))

        self.assertEqual(project.projects_base_folder, str(updated_base.resolve()))
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertEqual(manifest["settings"]["projects_base_folder"], str(updated_base.resolve()))

    def test_project_settings_rejects_base_folder_outside_project_ancestry(self) -> None:
        updated_base = Path(self.temp_dir.name) / "new-base"
        updated_base.mkdir()

        with self.assertRaisesRegex(ProjectServiceError, "inside the projects base folder"):
            self.service.update_project_settings(UpdateProjectSettingsRequest(projects_base_folder=str(updated_base)))

    def test_schema_layers_are_listed_from_base_to_project(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers

        self.assertEqual([layer.folder_path for layer in layers], [str(self.base), str(self.universe), str(self.world), str(self.root)])
        self.assertEqual(layers[0].label, "Base Folder")
        self.assertEqual(layers[1].label, "universe")
        self.assertEqual(layers[2].label, "series")
        self.assertEqual(layers[-1].label, "Test Project")

    def test_metadata_schema_overview_reports_definition_sources(self) -> None:
        self.service._write_yaml(
            self.world / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "pov": {"name": "Point of View", "type": "text"},
                },
                "entry_types": {
                    "scene": {
                        "name": "World Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "pov", "word_count"],
                    }
                },
            },
        )

        overview = self.service.read_metadata_schema_overview()

        self.assertTrue(overview.field_sources["status"].built_in)
        self.assertTrue(overview.field_sources["summary"].built_in)
        self.assertTrue(overview.field_sources["word_count"].built_in)
        self.assertEqual(overview.field_sources["pov"].layer_label, "series")
        self.assertEqual(overview.entry_type_sources["scene"].layer_label, "series")

    def test_upsert_metadata_field_writes_selected_layer(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )

        schema = self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="pov_character",
                field=MetadataFieldDefinition(name="POV Character", type="text"),
                entry_type="scene",
            )
        )

        self.assertIn("pov_character", schema.fields)
        self.assertIn("pov_character", schema.entry_types["scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertIn("pov_character", world_schema["fields"])
        self.assertEqual(world_schema["entry_types"]["scene"]["fields"], ["pov_character"])
        self.assertNotIn("status", world_schema["entry_types"]["scene"]["fields"])
        self.assertNotIn("summary", world_schema["entry_types"]["scene"]["fields"])
        self.assertNotIn("word_count", world_schema["entry_types"]["scene"]["fields"])
        self.assertNotIn("pov_character", self.service._read_yaml(self.root / "metadata.schema.yaml").get("fields", {}))

    def test_create_metadata_field_rejects_duplicate_field_id(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="color",
                field=MetadataFieldDefinition(name="Background Color", type="select", options=["Red", "Green", "Blue"]),
                entry_type="scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=world_layer.id,
                    field_id="color",
                    field=MetadataFieldDefinition(name="Color", type="text"),
                    entry_type="scene",
                    allow_existing=False,
                )
            )

        self.assertEqual(raised.exception.status_code, 422)
        schema = self.service.read_metadata_schema()
        self.assertEqual(schema.fields["color"].name, "Background Color")
        self.assertEqual(schema.fields["color"].type, "select")

    def test_move_metadata_field_removes_original_layer_definition(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers
        world_layer = next(layer for layer in layers if layer.folder_path == str(self.world))
        project_layer = next(layer for layer in layers if layer.folder_path == str(self.root))
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="techlevel",
                field=MetadataFieldDefinition(name="Techlevel", type="text"),
                entry_type="scene",
            )
        )

        schema = self.service.move_metadata_field(
            MoveMetadataFieldRequest(
                field_id="techlevel",
                target_layer_id=project_layer.id,
                entry_type="scene",
            )
        )

        self.assertIn("techlevel", schema.entry_types["scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema.get("fields", {}))
        self.assertNotIn("techlevel", world_schema["entry_types"]["scene"]["fields"])
        self.assertIn("techlevel", project_schema["fields"])
        self.assertEqual(project_schema["entry_types"]["scene"]["fields"], ["techlevel"])

    def test_rename_metadata_field_updates_schema_and_scene_metadata(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="techlevel",
                field=MetadataFieldDefinition(name="Techlevel", type="text"),
                entry_type="scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"techlevel": "steam"},
            ),
        )

        schema = self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="techlevel", new_field_id="technology_level", entry_type="scene")
        )

        self.assertNotIn("techlevel", schema.fields)
        self.assertIn("technology_level", schema.fields)
        self.assertIn("technology_level", schema.entry_types["scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertEqual(world_schema["entry_types"]["scene"]["fields"], ["technology_level"])
        renamed_scene = self.service.read_scene(self.scene_id)
        self.assertEqual(renamed_scene.metadata, {"technology_level": "steam"})

    def test_rename_metadata_field_rejects_duplicate_field_id(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="color",
                field=MetadataFieldDefinition(name="Color", type="select", options=["Red", "Green", "Blue"]),
                entry_type="scene",
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="background_color",
                field=MetadataFieldDefinition(name="Background Color", type="select", options=["Red", "Green", "Blue"]),
                entry_type="scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.rename_metadata_field(
                RenameMetadataFieldRequest(old_field_id="background_color", new_field_id="color", entry_type="scene")
            )

        self.assertEqual(raised.exception.status_code, 422)
        schema = self.service.read_metadata_schema()
        self.assertIn("background_color", schema.fields)
        self.assertEqual(schema.fields["background_color"].name, "Background Color")

    def test_upsert_metadata_field_migrates_renamed_select_options(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="color",
                field=MetadataFieldDefinition(name="Color", type="select", options=["Red", "Green", "Blue"]),
                entry_type="scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"color": "Green"},
            ),
        )

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="color",
                field=MetadataFieldDefinition(name="Background Color", type="select", options=["red", "green", "blue"]),
                entry_type="scene",
            )
        )

        updated_scene = self.service.read_scene(self.scene_id)
        self.assertEqual(updated_scene.metadata, {"color": "green"})

    def test_delete_metadata_field_removes_schema_and_scene_metadata(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="techlevel",
                field=MetadataFieldDefinition(name="Techlevel", type="text"),
                entry_type="scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"techlevel": "steam"},
            ),
        )

        schema = self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="techlevel", entry_type="scene"))

        self.assertNotIn("techlevel", schema.fields)
        self.assertNotIn("techlevel", schema.entry_types["scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertNotIn("techlevel", world_schema["entry_types"]["scene"]["fields"])
        deleted_scene_metadata = self.service.read_scene(self.scene_id).metadata
        self.assertEqual(deleted_scene_metadata, {})

    def test_default_schema_includes_lore_entry_subtypes_and_reference_fields(self) -> None:
        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["character"].kind, "lore")
        self.assertEqual(schema.entry_types["place"].kind, "lore")
        self.assertTrue(schema.entry_types["lore_entry"].abstract)
        self.assertEqual(schema.entry_types["character"].parent, "lore_entry")
        self.assertEqual(schema.entry_types["lore_note"].parent, "lore_entry")
        self.assertNotIn("summary", schema.entry_types["character"].fields)
        self.assertNotIn("summary", schema.entry_types["lore_note"].fields)
        self.assertNotIn("appears_in_scenes", schema.entry_types["lore_note"].fields)
        self.assertIn("aliases", schema.entry_types["lore_note"].fields)
        self.assertIn("tags", schema.entry_types["lore_note"].fields)
        self.assertEqual(schema.entry_types["lore_entry"].own_fields, ["aliases", "tags", "related_entries"])
        self.assertEqual(schema.entry_types["character"].own_fields, ["home_place", "appears_in_scenes"])
        self.assertEqual(schema.fields["aliases"].type, "multi_select")
        self.assertEqual(schema.fields["tags"].type, "tags")
        self.assertEqual(schema.fields["related_entries"].type, "entity_ref_list")
        self.assertEqual(schema.fields["related_entries"].target, {"kind": "lore"})
        self.assertEqual(schema.fields["characters"].target, {"entry_type": "character"})

    def test_metadata_rejects_fields_not_bound_to_entry_type(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))

        with self.assertRaisesRegex(ProjectServiceError, "metadata field summary is not defined for entry_type character"):
            self.service.save_lore_entry(
                entry.id,
                SaveLoreEntryRequest(
                    title="Seren",
                    body_markdown="A captain with a secret.",
                    base_revision=entry.revision,
                    entry_type="character",
                    metadata={"summary": "Scene-only field"},
                ),
            )

    def test_lore_subtypes_inherit_custom_fields_from_lore_entry_base(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        schema = self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=project_layer.id,
                field_id="importance",
                field=MetadataFieldDefinition(name="Importance", type="select", options=["Low", "High"]),
                entry_type="lore_entry",
            )
        )
        self.assertIn("importance", schema.entry_types["character"].fields)
        self.assertIn("importance", schema.entry_types["lore_note"].fields)

        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown="A captain with a secret.",
                base_revision=entry.revision,
                entry_type="character",
                metadata={"importance": "High"},
            ),
        )

        self.assertEqual(saved.metadata["importance"], "High")

    def test_custom_lore_subtype_can_be_created_and_inherits_parent_fields(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(
                    name="Faction",
                    kind="lore",
                    parent="lore_entry",
                    fields=[],
                ),
            )
        )

        self.assertIn("faction", schema.entry_types)
        self.assertIn("aliases", schema.entry_types["faction"].fields)
        self.assertIn("tags", schema.entry_types["faction"].fields)
        self.assertEqual(schema.entry_types["faction"].own_fields, [])
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("own_fields", project_schema["entry_types"]["faction"])

        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="The Pact", entry_type="faction"))
        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="The Pact",
                body_markdown="A secret faction.",
                base_revision=entry.revision,
                entry_type="faction",
                metadata={"tags": ["Politics"]},
            ),
        )

        self.assertEqual(saved.entry_type, "faction")
        self.assertEqual(saved.metadata["tags"], ["Politics"])

    def test_abstract_entry_type_cannot_be_used_by_documents(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "abstract entry_type lore_entry"):
            self.service.create_lore_entry(CreateLoreEntryRequest(title="Abstract", entry_type="lore_entry"))

    def test_used_custom_entry_type_cannot_be_deleted(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore_entry", fields=[]),
            )
        )
        self.service.create_lore_entry(CreateLoreEntryRequest(title="The Pact", entry_type="faction"))

        with self.assertRaisesRegex(ProjectServiceError, "used by project documents"):
            self.service.delete_metadata_entry_type(DeleteMetadataEntryTypeRequest(entry_type_id="faction"))

    def test_lore_entry_round_trips_metadata(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        place = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="place"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown="A captain with a secret.",
                base_revision=entry.revision,
                entry_type="character",
                metadata={
                    "aliases": ["Ren"],
                    "tags": ["crew"],
                    "home_place": place.id,
                    "appears_in_scenes": [self.scene_id],
                },
            ),
        )

        self.assertEqual(saved.entry_type, "character")
        self.assertEqual(saved.metadata["aliases"], ["Ren"])
        self.assertEqual(saved.metadata["tags"], ["crew"])
        self.assertFalse(hasattr(saved, "status"))
        listed_entry = self.service.list_lore_entries().entries[0]
        self.assertEqual(listed_entry.title, "Seren")
        self.assertIn("captain with a secret", listed_entry.body_markdown)
        front_matter, _ = self.service._read_markdown_with_front_matter(self.root / "lore" / f"{entry.id}.md", strict=True)
        self.assertNotIn("status", front_matter)

    def test_lore_entry_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Robert Smith", entry_type="character"))
        original_path = self.root / "lore" / f"{entry.id}.md"
        renamed_path = self.root / "lore" / "robert-smith.md"
        original_path.rename(renamed_path)

        loaded = self.service.read_lore_entry(entry.id)
        listed = self.service.list_lore_entries().entries

        self.assertEqual(loaded.id, entry.id)
        self.assertEqual(loaded.title, "Robert Smith")
        self.assertEqual([item.id for item in listed], [entry.id])

    def test_scene_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        scene = self.service.read_scene(self.scene_id)
        original_path = self.root / "scenes" / f"{scene.id}.md"
        renamed_path = self.root / "scenes" / "opening-scene.md"
        original_path.rename(renamed_path)

        loaded = self.service.read_scene(scene.id)
        validation = self.service.validate_project()

        self.assertEqual(loaded.id, scene.id)
        self.assertFalse(any("Structure references missing scene" in error for error in validation.errors), validation.errors)

    def test_validation_reports_missing_and_duplicate_front_matter_ids(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        path = self.root / "lore" / f"{entry.id}.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(f"id: {entry.id}\n", ""), encoding="utf-8")

        validation = self.service.validate_project()

        self.assertTrue(any("missing front matter id" in warning for warning in validation.warnings), validation.warnings)

        duplicate = self.service.create_lore_entry(CreateLoreEntryRequest(title="Other Seren", entry_type="character"))
        duplicate_path = self.root / "lore" / f"{duplicate.id}.md"
        duplicate_text = duplicate_path.read_text(encoding="utf-8")
        duplicate_path.write_text(duplicate_text.replace(f"id: {duplicate.id}\n", f"id: {entry.id}\n"), encoding="utf-8")

        validation = self.service.validate_project()

        self.assertTrue(any("Duplicate front matter id" in error for error in validation.errors), validation.errors)

    def test_reference_fields_validate_missing_and_wrong_targets(self) -> None:
        character = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        other_character = self.service.create_lore_entry(CreateLoreEntryRequest(title="Aren", entry_type="character"))

        with self.assertRaisesRegex(ProjectServiceError, "references unknown node missing_place"):
            self.service.save_lore_entry(
                character.id,
                SaveLoreEntryRequest(
                    title=character.title,
                    body_markdown=character.body_markdown,
                    base_revision=character.revision,
                    entry_type=character.entry_type,
                    metadata={"home_place": "missing_place"},
                ),
            )

        with self.assertRaisesRegex(ProjectServiceError, "expected entry_type place"):
            self.service.save_lore_entry(
                character.id,
                SaveLoreEntryRequest(
                    title=character.title,
                    body_markdown=character.body_markdown,
                    base_revision=character.revision,
                    entry_type=character.entry_type,
                    metadata={"home_place": other_character.id},
                ),
            )

    def test_lore_entry_rejects_scene_entry_type(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "non-lore entry_type scene"):
            self.service.create_lore_entry(CreateLoreEntryRequest(title="Wrong", entry_type="scene"))

    def test_lore_metadata_field_mutations_update_lore_files(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="faction",
                field=MetadataFieldDefinition(name="Faction", type="select", options=["A", "B"]),
                entry_type="character",
            )
        )
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=entry.title,
                body_markdown=entry.body_markdown,
                base_revision=entry.revision,
                entry_type=entry.entry_type,
                metadata={"faction": "A"},
            ),
        )

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="faction", new_field_id="allegiance", entry_type="character")
        )
        renamed = self.service.read_lore_entry(entry.id)

        self.assertEqual(renamed.metadata, {"allegiance": "A"})

    def test_search_reports_lore_hit_kind(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown="Keeps the ember map.",
                base_revision=entry.revision,
                entry_type="character",
                metadata={"tags": ["Navigator"]},
            ),
        )

        result = self.service.search(SearchRequest(query="ember"))

        self.assertEqual(result.hits[0].kind, "lore")
        self.assertEqual(result.hits[0].file_id, entry.id)

    def test_tag_registry_canonicalizes_lore_tags_case_insensitively(self) -> None:
        self.service._write_yaml(self.root / "tags.yaml", {"tags": ["Crew"]})
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown=entry.body_markdown,
                base_revision=entry.revision,
                entry_type="character",
                metadata={"tags": ["crew", "ALLY", "ally"]},
            ),
        )

        self.assertEqual(saved.metadata["tags"], ["Crew", "ALLY"])
        self.assertEqual(self.service.read_known_tags().tags, ["ALLY", "Crew"])
        front_matter, _ = self.service._read_markdown_with_front_matter(self.root / "lore" / f"{entry.id}.md", strict=True)
        self.assertEqual(front_matter["metadata"]["tags"], ["Crew", "ALLY"])

    def test_aliases_do_not_populate_known_tags(self) -> None:
        self.service._write_yaml(self.root / "tags.yaml", {"tags": ["Crew"]})
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Robert Smith", entry_type="character"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Robert Smith",
                body_markdown=entry.body_markdown,
                base_revision=entry.revision,
                entry_type="character",
                metadata={"aliases": ["Mr. Smith", "Bob"], "tags": ["crew"]},
            ),
        )

        self.assertEqual(saved.metadata["aliases"], ["Mr. Smith", "Bob"])
        self.assertEqual(saved.metadata["tags"], ["Crew"])
        self.assertEqual(self.service.read_known_tags().tags, ["Crew"])


class ReferenceResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.root = self.base / "test"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_body(self, entry_id: str, body: str) -> None:
        entry = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body_markdown=body,
                base_revision=entry.revision,
                entry_type=entry.entry_type,
                metadata=entry.metadata,
            ),
        )

    def test_resolve_returns_titles_for_known_ids(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        taverna = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="place"))

        response = self.service.resolve_references([seren.id, taverna.id])

        ids = {candidate.id: candidate for candidate in response.candidates}
        self.assertEqual(ids[seren.id].title, "Seren")
        self.assertEqual(ids[seren.id].entry_type, "character")
        self.assertTrue(ids[seren.id].found)
        self.assertEqual(ids[taverna.id].title, "Taverna")
        self.assertEqual(ids[taverna.id].kind, "lore")

    def test_resolve_marks_unknown_ids_as_not_found(self) -> None:
        response = self.service.resolve_references(["lore_does_not_exist"])

        self.assertEqual(len(response.candidates), 1)
        candidate = response.candidates[0]
        self.assertFalse(candidate.found)
        self.assertEqual(candidate.id, "lore_does_not_exist")

    def test_resolve_includes_body_summary(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        self._save_body(seren.id, "# Seren\n\nA brave caravan guard.\n")

        response = self.service.resolve_references([seren.id])

        self.assertEqual(response.candidates[0].summary, "A brave caravan guard.")

    def test_candidates_filter_by_kind(self) -> None:
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        scene_id = next((self.root / "scenes").glob("*.md")).stem

        response = self.service.list_reference_candidates(kind="lore")

        ids = {candidate.id for candidate in response.candidates}
        self.assertNotIn(scene_id, ids)
        self.assertTrue(any(candidate.title == "Seren" for candidate in response.candidates))

    def test_candidates_filter_by_entry_type_with_inheritance(self) -> None:
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="place"))

        characters_only = self.service.list_reference_candidates(entry_type="character")
        titles = {candidate.title for candidate in characters_only.candidates}
        self.assertEqual(titles, {"Seren"})

        all_lore = self.service.list_reference_candidates(entry_type="lore_entry")
        titles = {candidate.title for candidate in all_lore.candidates}
        self.assertEqual(titles, {"Seren", "Taverna"})

    def test_candidates_exclude_id(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        aren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Aren", entry_type="character"))

        response = self.service.list_reference_candidates(entry_type="character", exclude_id=seren.id)

        ids = {candidate.id for candidate in response.candidates}
        self.assertIn(aren.id, ids)
        self.assertNotIn(seren.id, ids)

    def test_backlinks_finds_references(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        taverna = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="place"))
        self.service.save_lore_entry(
            seren.id,
            SaveLoreEntryRequest(
                title="Seren",
                body_markdown=seren.body_markdown,
                base_revision=seren.revision,
                entry_type="character",
                metadata={"home_place": taverna.id},
            ),
        )
        scene_id = next((self.root / "scenes").glob("*.md")).stem
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="scene",
                metadata={"characters": [seren.id], "locations": [taverna.id]},
            ),
        )

        seren_backlinks = self.service.list_backlinks(seren.id)
        self.assertEqual(len(seren_backlinks.backlinks), 1)
        link = seren_backlinks.backlinks[0]
        self.assertEqual(link.id, scene_id)
        self.assertEqual(link.field_id, "characters")

        taverna_backlinks = self.service.list_backlinks(taverna.id)
        sources = {(link.id, link.field_id) for link in taverna_backlinks.backlinks}
        self.assertEqual(sources, {(seren.id, "home_place"), (scene_id, "locations")})

    def test_backlinks_returns_empty_for_unknown_id(self) -> None:
        response = self.service.list_backlinks("lore_does_not_exist")
        self.assertEqual(response.backlinks, [])

    def test_search_resolves_reference_titles_in_excerpts(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))
        scene_id = next((self.root / "scenes").glob("*.md")).stem
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body_markdown=scene.body_markdown,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="scene",
                metadata={"characters": [seren.id]},
            ),
        )

        by_title = self.service.search(SearchRequest(query="Seren"))
        excerpts = [hit.excerpt for hit in by_title.hits if hit.kind == "scene"]
        self.assertTrue(any("Seren" in excerpt for excerpt in excerpts))
        self.assertFalse(any(seren.id in excerpt for excerpt in excerpts))

    def test_http_reference_routes(self) -> None:
        from fastapi.testclient import TestClient
        import app.main as app_main

        original_service = app_main.service
        app_main.service = self.service
        try:
            client = TestClient(app_main.app)
            seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))

            resolve_response = client.post("/api/references/resolve", json={"ids": [seren.id, "missing"]})
            self.assertEqual(resolve_response.status_code, 200)
            payload = resolve_response.json()
            ids_by = {candidate["id"]: candidate for candidate in payload["candidates"]}
            self.assertEqual(ids_by[seren.id]["title"], "Seren")
            self.assertFalse(ids_by["missing"]["found"])

            candidates_response = client.get("/api/references/candidates", params={"entry_type": "character"})
            self.assertEqual(candidates_response.status_code, 200)
            titles = {candidate["title"] for candidate in candidates_response.json()["candidates"]}
            self.assertIn("Seren", titles)
        finally:
            app_main.service = original_service


if __name__ == "__main__":
    unittest.main()
