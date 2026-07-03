from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MoveMetadataFieldRequest,
    PromptContextStrategy,
    PromptEntryTypeExtras,
    PromptInputDefinition,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    SearchRequest,
    SelectOption,
    SetFieldOrderRequest,
    UpdateProjectSettingsRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService, ProjectServiceError
from app.services.tree_structure import TreeStructureService


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
        # Several tests use `home_place` as a single-ref field on
        # Character to exercise validation + ref-graph behaviour. The
        # seed no longer ships it (was cruft polluting real entries);
        # re-add it locally so tests stay hermetic.
        self._add_home_place_to_character_schema(self.root)
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        self.scene_id = self.service._read_front_matter_only(first_scene_path, strict=True)["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_projects_base_folder(self, path: Path) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(path)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def _add_home_place_to_character_schema(self, root: Path) -> None:
        schema_path = root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["home_place"] = {
            "name": "Home Place",
            "type": "entity_ref",
            "target": {"entry_type": "lore:place"},
        }
        character = data["entry_types"].get("lore:character") or {}
        fields = list(character.get("fields") or [])
        if "home_place" not in fields:
            fields.insert(0, "home_place")
            character["fields"] = fields
            data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def test_default_schema_seeds_act_and_chapter(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("scene:act", schema.entry_types)
        self.assertIn("scene:chapter", schema.entry_types)
        self.assertEqual(schema.entry_types["scene:act"].kind, "scene")
        self.assertEqual(schema.entry_types["scene:chapter"].kind, "scene")
        self.assertFalse(schema.entry_types["scene:act"].abstract)
        self.assertFalse(schema.entry_types["scene:chapter"].abstract)

    def test_manuscript_structure_is_shared_abstract_parent(self) -> None:
        schema = self.service.read_metadata_schema()
        parent = schema.entry_types.get("scene:manuscript_structure")
        self.assertIsNotNone(parent)
        assert parent is not None
        self.assertTrue(parent.abstract)
        self.assertEqual(parent.kind, "scene")
        for type_id in ["scene:act", "scene:chapter", "scene:scene"]:
            self.assertEqual(schema.entry_types[type_id].parent, "scene:manuscript_structure")
            self.assertIn("summary", schema.entry_types[type_id].fields)

    def test_same_local_key_under_two_kinds_coexists(self) -> None:
        # The point of FQN identity (#77): a bare local key may be reused
        # across kinds. Define `widget` under both lore and mutation_set; both
        # survive as distinct FQN-keyed types instead of clobbering.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        entry_types = data.setdefault("entry_types", {})
        entry_types["lore:widget"] = {"name": "Widget", "kind": "lore", "parent": "lore:lore_entry", "fields": []}
        entry_types["mutation_set:widget"] = {"name": "Widget Set", "kind": "mutation_set", "fields": []}
        self.service._write_yaml(schema_path, data)
        schema = self.service.read_metadata_schema()
        self.assertEqual(schema.entry_types["lore:widget"].kind, "lore")
        self.assertEqual(schema.entry_types["mutation_set:widget"].kind, "mutation_set")

    def test_upsert_entry_type_qualifies_bare_id_with_kind(self) -> None:
        # A caller may send a bare local id + kind; the backend stores it under
        # the kind-qualified FQN key.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore:lore_entry"),
                allow_existing=False,
            )
        )
        self.assertIn("lore:faction", schema.entry_types)
        self.assertNotIn("faction", schema.entry_types)
        self.assertEqual(schema.entry_types["lore:faction"].kind, "lore")

    def test_upsert_entry_type_rejects_kind_prefix_mismatch(self) -> None:
        # An explicit FQN id whose prefix disagrees with the declared kind is a
        # cross-kind identity error and must be rejected.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="scene:faction",
                    entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore:lore_entry"),
                    allow_existing=False,
                )
            )
        self.assertIn("must match", str(ctx.exception))

    def test_builtin_entry_type_keeps_built_in_source_after_field_add(self) -> None:
        custom_field = MetadataFieldDefinition(name="Weather", type="text", options=[])
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                field_id="weather",
                field=custom_field,
                entry_type="scene:scene",
                allow_existing=False,
            )
        )

        overview = self.service.read_metadata_schema_overview()

        self.assertTrue(overview.entry_type_sources["scene:scene"].built_in)
        self.assertTrue(overview.entry_type_sources["scene:chapter"].built_in)
        self.assertTrue(overview.entry_type_sources["scene:act"].built_in)
        self.assertFalse(overview.field_sources["weather"].built_in)

    def test_summary_lives_on_parent_not_in_scene_own_fields(self) -> None:
        schema = self.service.read_metadata_schema()
        scene_definition = schema.entry_types["scene:scene"]
        self.assertNotIn("summary", scene_definition.own_fields)
        self.assertIn("summary", scene_definition.fields)
        self.assertIn("status", scene_definition.own_fields)

    def test_scene_entry_type_defaults_to_wysiwyg_markdown(self) -> None:
        schema = self.service.read_metadata_schema()
        scene = schema.entry_types["scene:scene"]
        self.assertEqual(scene.body_editor, "wysiwyg")
        self.assertEqual(scene.body_language, "markdown")

    def test_prompt_subtypes_inherit_code_and_jinja2(self) -> None:
        schema = self.service.read_metadata_schema()
        for type_id in ("prompt:prompt", "prompt:continuation", "prompt:revise", "prompt:general", "prompt:snippet"):
            definition = schema.entry_types[type_id]
            self.assertEqual(definition.body_editor, "code", msg=type_id)
            self.assertEqual(definition.body_language, "jinja2", msg=type_id)

    def test_layer_can_override_body_editor(self) -> None:
        # A project layer can override an inherited body_editor / body_language.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:research_note": {
                        "name": "Research Note",
                        "kind": "lore",
                        "parent": "lore:lore_entry",
                        "fields": [],
                        "body_editor": "code",
                        "body_language": "plain",
                    }
                },
            },
        )
        schema = self.service.read_metadata_schema()
        note = schema.entry_types["lore:research_note"]
        self.assertEqual(note.body_editor, "code")
        self.assertEqual(note.body_language, "plain")

    def test_new_project_drops_sequence_from_container_types(self) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        types = [item["type"] for item in manifest["manuscript_structure"]["container_types"]]
        self.assertEqual(types, ["scene:act", "scene:chapter"])

    def test_create_structure_node_inserts_container_under_root(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_nodes = [child for child in updated.root.children if child.type == "scene:act"]
        self.assertEqual(len(act_nodes), 1)
        self.assertEqual(act_nodes[0].title, "Act One")
        self.assertIsNotNone(act_nodes[0].scene_id)
        backing_file = self.service._path_for_node_id(act_nodes[0].scene_id, "scene")
        self.assertTrue(backing_file.exists())
        self.assertEqual(backing_file.stem, "Act One")

    def test_container_is_loadable_as_scene(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(child for child in updated.root.children if child.type == "scene:act")

        scene = self.service.read_scene(act_node.scene_id)

        self.assertEqual(scene.id, act_node.scene_id)
        self.assertEqual(scene.title, "Act One")
        self.assertEqual(scene.entry_type, "scene:act")

    def test_structure_carries_counter_in_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))

        structure = self.service.read_structure()
        act_nodes = [child for child in structure.root.children if child.type == "scene:act"]
        numbers = [node.computed_metadata.get("number") for node in act_nodes]
        self.assertEqual(numbers, [1, 2])

    def test_structure_yaml_does_not_persist_computed_metadata(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))

        raw = self.service._read_yaml(self.root / "manuscript.structure.yaml")

        def has_computed(node: dict) -> bool:
            if "computed_metadata" in node:
                return True
            return any(has_computed(child) for child in node.get("children", []))

        self.assertFalse(has_computed(raw["root"]))

    def test_display_template_inherits_from_manuscript_structure(self) -> None:
        schema = self.service.read_metadata_schema()
        for type_id in ("scene:act", "scene:chapter", "scene:scene"):
            self.assertEqual(schema.entry_types[type_id].display_template, "{number}. {title}")
        self.assertEqual(schema.entry_types["lore:character"].display_template, "{title}")

    def test_has_body_inherits_false_for_containers_true_for_scene(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertFalse(schema.entry_types["scene:manuscript_structure"].has_body)
        self.assertFalse(schema.entry_types["scene:act"].has_body)
        self.assertFalse(schema.entry_types["scene:chapter"].has_body)
        self.assertTrue(schema.entry_types["scene:scene"].has_body)
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
        from app.models import MetadataFieldDefinition

        field = MetadataFieldDefinition.model_validate({
            "name": "Tier",
            "type": "select",
            "options": ["cheap", "balanced", "best"],
        })
        self.assertEqual([o.value for o in field.options], ["cheap", "balanced", "best"])
        self.assertTrue(all(o.color is None for o in field.options))

    def test_color_inherits_through_parent_chain(self) -> None:
        """Built-in seeds set color on scene/lore_entry/prompt/assistant; child
        types inherit unless they override. Verifies the inheritance list in
        _resolve_metadata_schema_inheritance picks up `color`."""
        schema = self.service.read_metadata_schema()
        # Direct seeds.
        self.assertEqual(schema.entry_types["scene:scene"].color, "forest")
        self.assertEqual(schema.entry_types["lore:lore_entry"].color, "slate-blue")
        self.assertEqual(schema.entry_types["prompt:prompt"].color, "warm-brown")
        self.assertEqual(schema.entry_types["assistant:assistant"].color, "graphite")
        # Inherited through one parent link.
        self.assertEqual(schema.entry_types["lore:character"].color, "slate-blue")
        self.assertEqual(schema.entry_types["lore:place"].color, "slate-blue")
        self.assertEqual(schema.entry_types["lore:item"].color, "slate-blue")
        self.assertEqual(schema.entry_types["prompt:continuation"].color, "warm-brown")
        self.assertEqual(schema.entry_types["prompt:general"].color, "warm-brown")
        # Inherited through two parent links (roleplay → continuation → prompt).
        self.assertEqual(schema.entry_types["prompt:roleplay"].color, "warm-brown")

    def test_counter_among_siblings_for_acts(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))
        third = self.service.create_structure_node(CreateStructureNodeRequest(title="Act 3", entry_type="scene:act"))
        act_nodes = [child for child in third.root.children if child.type == "scene:act"]

        scenes = [self.service.read_scene(node.scene_id) for node in act_nodes]

        self.assertEqual([s.computed_metadata.get("number") for s in scenes], [1, 2, 3])

    def test_counter_among_siblings_resets_per_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))
        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 2", entry_type="scene:chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_two.id))

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

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))
        structure = self.service.read_structure()
        act_one = next(child for child in structure.root.children if child.title == "Act 1")
        act_two = next(child for child in structure.root.children if child.title == "Act 2")
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 2", entry_type="scene:chapter", parent_id=act_one.id))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Chapter 3", entry_type="scene:chapter", parent_id=act_two.id))

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
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(child for child in updated.root.children if child.type == "scene:act")

        candidates = self.service.list_reference_candidates(entry_type="scene:act")

        ids = {candidate.id for candidate in candidates.candidates}
        self.assertIn(act_node.scene_id, ids)

    def test_create_structure_node_nests_under_specific_parent(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(child for child in updated.root.children if child.type == "scene:act")
        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_node.id)
        )
        nested_act = next(child for child in updated.root.children if child.id == act_node.id)
        chapters = [child for child in nested_act.children if child.type == "scene:chapter"]
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].title, "Chapter 1")

    def test_create_structure_node_rejects_abstract_type(self) -> None:
        from app.models import CreateStructureNodeRequest

        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.create_structure_node(
                CreateStructureNodeRequest(title="Bad", entry_type="scene:manuscript_structure")
            )
        self.assertIn("abstract", ctx.exception.message)

    def test_rename_structure_node_updates_container_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(child for child in updated.root.children if child.type == "scene:act")
        renamed = self.service.rename_structure_node(act_node.id, "The Departure")
        renamed_act = next(child for child in renamed.root.children if child.id == act_node.id)
        self.assertEqual(renamed_act.title, "The Departure")

    def test_rename_structure_node_updates_scene_file_for_leaf(self) -> None:
        scene_id = self.scene_id
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
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "scene:act")
        scene = self.service.create_scene(
            self._make_create_scene("Arrival", parent_id=act_node.id)
        )

        scene_path = self.service._path_for_node_id(scene.id, "scene")
        self.assertTrue(scene_path.exists())

        self.service.delete_structure_node(act_node.id)

        self.assertFalse(scene_path.exists())
        refreshed = self.service.read_structure()
        self.assertFalse(any(child.id == act_node.id for child in refreshed.root.children))

    def test_cascade_delete_preview_counts_descendants_and_backlinks(self) -> None:
        from app.models import CreateStructureNodeRequest, SaveSceneRequest

        self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "scene:act")
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_node.id)
        )
        refreshed_act = next(child for child in chapter_doc.root.children if child.id == act_node.id)
        chapter_node = next(grandchild for grandchild in refreshed_act.children if grandchild.type == "scene:chapter")
        scene_a = self.service.create_scene(self._make_create_scene("Arrival", parent_id=chapter_node.id))
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
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
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "scene:act")
        self.service.create_scene(self._make_create_scene("Arrival", parent_id=act_node.id))
        scene_b = self.service.create_scene(self._make_create_scene("Departure", parent_id=act_node.id))
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

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))
        structure = self.service.read_structure()
        acts = [child for child in structure.root.children if child.type == "scene:act"]
        act_1, act_2 = acts[0], acts[1]

        self.service.move_structure_node(act_2.id, structure.root.id, 0)
        refreshed = self.service.read_structure()
        reordered = [child for child in refreshed.root.children if child.type == "scene:act"]
        self.assertEqual([n.id for n in reordered], [act_2.id, act_1.id])

    def test_move_structure_node_reparents_into_container(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 2", entry_type="scene:act"))
        structure = self.service.read_structure()
        acts = [child for child in structure.root.children if child.type == "scene:act"]
        act_1, act_2 = acts[0], acts[1]
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act_1.id)
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

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act 1", entry_type="scene:act"))
        structure = self.service.read_structure()
        act = next(child for child in structure.root.children if child.type == "scene:act")
        chapter_doc = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Chapter 1", entry_type="scene:chapter", parent_id=act.id)
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

    def _first_scene_id(self) -> str:
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        return self.service._read_front_matter_only(first_scene_path, strict=True)["id"]

    def test_new_scene_file_is_named_by_title(self) -> None:
        scene = self.service.create_scene(self._make_create_scene("First Light"))
        path = self.service._path_for_node_id(scene.id, "scene")
        self.assertEqual(path.name, "First Light.md")

    def test_new_lore_file_is_named_by_title(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren the Brave", entry_type="lore:character"))
        path = self.service._path_for_node_id(entry.id, "lore")
        self.assertEqual(path.name, "Seren the Brave.md")

    def test_title_with_illegal_chars_gets_sanitized(self) -> None:
        scene = self.service.create_scene(self._make_create_scene('Chapter 1: "Hello?"'))
        path = self.service._path_for_node_id(scene.id, "scene")
        for forbidden in '<>:"/\\|?*':
            self.assertNotIn(forbidden, path.stem)

    def test_collision_resolved_with_suffix(self) -> None:
        first = self.service.create_scene(self._make_create_scene("Departure"))
        second = self.service.create_scene(self._make_create_scene("Departure"))
        first_path = self.service._path_for_node_id(first.id, "scene")
        second_path = self.service._path_for_node_id(second.id, "scene")
        self.assertEqual(first_path.name, "Departure.md")
        self.assertEqual(second_path.name, "Departure (2).md")

    def test_rename_structure_node_renames_file_too(self) -> None:
        from app.models import CreateStructureNodeRequest

        self.service.create_structure_node(CreateStructureNodeRequest(title="Act One", entry_type="scene:act"))
        structure = self.service.read_structure()
        act_node = next(child for child in structure.root.children if child.type == "scene:act")
        original_path = self.service._path_for_node_id(act_node.scene_id, "scene")
        self.assertEqual(original_path.name, "Act One.md")

        self.service.rename_structure_node(act_node.id, "The Departure")

        self.assertFalse(original_path.exists())
        new_path = self.service._path_for_node_id(act_node.scene_id, "scene")
        self.assertEqual(new_path.name, "The Departure.md")

    def _make_create_scene(self, title: str, parent_id: str | None = None):
        from app.models import CreateSceneRequest

        return CreateSceneRequest(title=title, parent_id=parent_id)

    def test_rename_structure_node_rejects_empty_title(self) -> None:
        from app.models import CreateStructureNodeRequest

        updated = self.service.create_structure_node(
            CreateStructureNodeRequest(title="Act One", entry_type="scene:act")
        )
        act_node = next(child for child in updated.root.children if child.type == "scene:act")
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
        self.service._write_yaml(self.root / "manuscript.structure.yaml", {"root": structure.model_dump()})
        round_tripped = self.service.read_structure()
        part = next(child for child in round_tripped.root.children if child.id == "part_one")
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
        self.service._write_yaml(self.root / "manuscript.structure.yaml", {"root": new_root.model_dump()})

        scene_ids = TreeStructureService.collect_leaf_ids(self.service.read_structure().root)
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
                body="Seren waits at the taverna.",
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
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
                    body=scene.body,
                    base_revision=scene.revision,
                    status="draft",
                    entry_type="scene:scene",
                    metadata={"word_count": 12},
                ),
            )

    def test_validation_reports_hand_edited_computed_metadata(self) -> None:
        path = self.service._path_for_node_id(self.scene_id, "scene")
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
                    "scene:scene": {
                        "name": "Base Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "mood", "word_count"],
                    }
                },
                "fields": {
                    "mood": {"name": "Mood", "type": "text"},
                },
            },
        )
        self.service._write_yaml(
            self.world / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "scene:scene": {
                        "name": "World Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "mood", "tension", "word_count"],
                    }
                },
                "fields": {
                    "tension": {"name": "Tension", "type": "number"},
                },
            },
        )

        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["scene:scene"].name, "World Scene")
        self.assertIn("mood", schema.fields)
        self.assertIn("tension", schema.fields)
        self.assertEqual(
            schema.entry_types["scene:scene"].fields,
            ["number", "summary", "color", "status", "pov", "characters", "locations", "dynamics", "word_count", "cost", "mood", "tension"],
        )

        scene = self.service.read_scene(self.scene_id)
        saved = self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata={"mood": "tense", "tension": 3},
            ),
        )

        self.assertEqual(saved.metadata["mood"], "tense")
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

    def test_project_settings_clear_ai_provider_and_class_to_default(self) -> None:
        # Set concrete values, then clear them back to "(machine default)".
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(
                ai_default_provider="anthropic",
                ai_default_model_class="balanced",
            )
        )
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertEqual(manifest["settings"]["ai"]["default_provider"], "anthropic")
        self.assertEqual(manifest["settings"]["ai"]["default_model_class"], "balanced")

        # An explicit null (what the frontend sends for "(machine default)" /
        # "(unset)") clears the value rather than being treated as no-change.
        project = self.service.update_project_settings(
            UpdateProjectSettingsRequest(
                ai_default_provider=None,
                ai_default_model_class=None,
            )
        )
        self.assertIsNone(project.ai_default_provider)
        self.assertIsNone(project.ai_default_model_class)
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertIsNone(manifest["settings"]["ai"]["default_provider"])
        self.assertIsNone(manifest["settings"]["ai"]["default_model_class"])

    def test_project_settings_unset_ai_field_is_left_unchanged(self) -> None:
        # Partial update: a request that omits the AI provider/class fields must
        # not disturb previously-saved values (existing callers pass only
        # ai_policy and rely on this).
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(
                ai_default_provider="anthropic",
                ai_default_model_class="balanced",
            )
        )

        project = self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

        self.assertEqual(project.ai_policy, "cloud-allowed")
        self.assertEqual(project.ai_default_provider, "anthropic")
        self.assertEqual(project.ai_default_model_class, "balanced")

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
                    "mood": {"name": "Mood", "type": "text"},
                },
                "entry_types": {
                    "scene:scene": {
                        "name": "World Scene",
                        "kind": "scene",
                        "fields": ["status", "summary", "mood", "word_count"],
                    }
                },
            },
        )

        overview = self.service.read_metadata_schema_overview()

        self.assertTrue(overview.field_sources["status"].built_in)
        self.assertTrue(overview.field_sources["summary"].built_in)
        self.assertTrue(overview.field_sources["word_count"].built_in)
        self.assertEqual(overview.field_sources["mood"].layer_label, "series")
        self.assertEqual(overview.entry_type_sources["scene:scene"].layer_label, "series")

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
                entry_type="scene:scene",
            )
        )

        self.assertIn("pov_character", schema.fields)
        self.assertIn("pov_character", schema.entry_types["scene:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertIn("pov_character", world_schema["fields"])
        self.assertEqual(world_schema["entry_types"]["scene:scene"]["fields"], ["pov_character"])
        self.assertNotIn("status", world_schema["entry_types"]["scene:scene"]["fields"])
        self.assertNotIn("summary", world_schema["entry_types"]["scene:scene"]["fields"])
        self.assertNotIn("word_count", world_schema["entry_types"]["scene:scene"]["fields"])
        self.assertNotIn("pov_character", self.service._read_yaml(self.root / "metadata.schema.yaml").get("fields", {}))

    def test_upsert_entry_type_does_not_leak_pydantic_defaults_to_disk(self) -> None:
        # Regression: previously model_dump(exclude_none=True) wrote
        # body_editor='wysiwyg' and body_language='markdown' to disk even
        # though the frontend never sent them. That explicit value then
        # overrode the parent prompt type's body_editor='code' during
        # inheritance, so user-defined prompt sub-types opened in the
        # WYSIWYG editor instead of the Jinja2 code editor.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )

        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="brainstorm",
                allow_existing=False,
                entry_type=EntryTypeDefinition.model_validate({
                    "name": "Brainstorm",
                    "kind": "prompt",
                    "parent": "prompt:prompt",
                    "abstract": False,
                    "fields": [],
                }),
            )
        )

        # On disk: the sparse form — no body_editor/body_language pollution.
        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        brain_on_disk = on_disk["entry_types"]["prompt:brainstorm"]
        self.assertNotIn("body_editor", brain_on_disk)
        self.assertNotIn("body_language", brain_on_disk)

        # Resolved: inheritance from the parent `prompt` fills these in.
        schema = self.service.read_metadata_schema()
        brain_resolved = schema.entry_types["prompt:brainstorm"]
        self.assertEqual(brain_resolved.body_editor, "code")
        self.assertEqual(brain_resolved.body_language, "jinja2")

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
                entry_type="scene:scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=world_layer.id,
                    field_id="color",
                    field=MetadataFieldDefinition(name="Color", type="text"),
                    entry_type="scene:scene",
                    allow_existing=False,
                )
            )

        self.assertEqual(raised.exception.status_code, 422)
        schema = self.service.read_metadata_schema()
        self.assertEqual(schema.fields["color"].name, "Background Color")
        self.assertEqual(schema.fields["color"].type, "select")

    def test_create_computed_field_with_supported_function(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        schema = self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="scene_number",
                field=MetadataFieldDefinition(
                    name="Scene Number",
                    type="computed",
                    computed={"function": "counter", "scope": "manuscript"},
                ),
                entry_type="scene:scene",
            )
        )

        self.assertEqual(schema.fields["scene_number"].type, "computed")
        self.assertEqual(
            schema.fields["scene_number"].computed,
            {"function": "counter", "scope": "manuscript"},
        )
        self.assertIn("scene_number", schema.entry_types["scene:scene"].fields)

    def test_create_computed_field_rejects_unknown_function(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        with self.assertRaises(ProjectServiceError) as raised:
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=world_layer.id,
                    field_id="bogus_computed",
                    field=MetadataFieldDefinition(
                        name="Bogus",
                        type="computed",
                        computed={"function": "made_up"},
                    ),
                    entry_type="scene:scene",
                )
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertNotIn("bogus_computed", self.service.read_metadata_schema().fields)

    def test_create_computed_counter_rejects_bad_scope(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        with self.assertRaises(ProjectServiceError) as raised:
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=world_layer.id,
                    field_id="bad_scope",
                    field=MetadataFieldDefinition(
                        name="Bad Scope",
                        type="computed",
                        computed={"function": "counter", "scope": "galaxy"},
                    ),
                    entry_type="scene:scene",
                )
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_set_entry_type_field_order_reorders_own_fields(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore:lore_entry", fields=[]),
            )
        )
        for fid in ("alpha", "beta", "gamma"):
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=project_layer.id,
                    field_id=fid,
                    field=MetadataFieldDefinition(name=fid.title(), type="text"),
                    entry_type="lore:faction",
                )
            )
        self.assertEqual(self.service.read_metadata_schema().entry_types["lore:faction"].own_fields, ["alpha", "beta", "gamma"])

        schema = self.service.set_entry_type_field_order(
            SetFieldOrderRequest(layer_id=project_layer.id, entry_type_id="lore:faction", field_order=["gamma", "alpha", "beta"])
        )
        self.assertEqual(schema.entry_types["lore:faction"].own_fields, ["gamma", "alpha", "beta"])
        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertEqual(on_disk["entry_types"]["lore:faction"]["fields"], ["gamma", "alpha", "beta"])

    def test_set_entry_type_field_order_rejects_non_permutation(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore:lore_entry", fields=[]),
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=project_layer.id,
                field_id="alpha",
                field=MetadataFieldDefinition(name="Alpha", type="text"),
                entry_type="lore:faction",
            )
        )
        with self.assertRaises(ProjectServiceError) as raised:
            self.service.set_entry_type_field_order(
                SetFieldOrderRequest(layer_id=project_layer.id, entry_type_id="lore:faction", field_order=["alpha", "ghost"])
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_set_entry_type_field_order_rejects_system_type(self) -> None:
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        with self.assertRaises(ProjectServiceError) as raised:
            self.service.set_entry_type_field_order(
                SetFieldOrderRequest(layer_id=project_layer.id, entry_type_id="scene:scene", field_order=[])
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_move_metadata_field_removes_original_layer_definition(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers
        world_layer = next(layer for layer in layers if layer.folder_path == str(self.world))
        project_layer = next(layer for layer in layers if layer.folder_path == str(self.root))
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="techlevel",
                field=MetadataFieldDefinition(name="Techlevel", type="text"),
                entry_type="scene:scene",
            )
        )

        schema = self.service.move_metadata_field(
            MoveMetadataFieldRequest(
                field_id="techlevel",
                target_layer_id=project_layer.id,
                entry_type="scene:scene",
            )
        )

        self.assertIn("techlevel", schema.entry_types["scene:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema.get("fields", {}))
        self.assertNotIn("techlevel", world_schema["entry_types"]["scene:scene"]["fields"])
        self.assertIn("techlevel", project_schema["fields"])
        self.assertEqual(project_schema["entry_types"]["scene:scene"]["fields"], ["techlevel"])

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
                entry_type="scene:scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"techlevel": "steam"},
            ),
        )

        schema = self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="techlevel", new_field_id="technology_level", entry_type="scene:scene")
        )

        self.assertNotIn("techlevel", schema.fields)
        self.assertIn("technology_level", schema.fields)
        self.assertIn("technology_level", schema.entry_types["scene:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertEqual(world_schema["entry_types"]["scene:scene"]["fields"], ["technology_level"])
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
                entry_type="scene:scene",
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="background_color",
                field=MetadataFieldDefinition(name="Background Color", type="select", options=["Red", "Green", "Blue"]),
                entry_type="scene:scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.rename_metadata_field(
                RenameMetadataFieldRequest(old_field_id="background_color", new_field_id="color", entry_type="scene:scene")
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
                entry_type="scene:scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
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
                entry_type="scene:scene",
                option_migration={"Red": "red", "Green": "green", "Blue": "blue"},
            )
        )

        updated_scene = self.service.read_scene(self.scene_id)
        self.assertEqual(updated_scene.metadata, {"color": "green"})

    def test_reordering_options_does_not_rewrite_entry_values(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="select", options=["a", "b", "c"]),
                entry_type="scene:scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"rank": "a"},
            ),
        )
        # Reorder only (no rename map) — value must be untouched, not swapped.
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="rank",
                field=MetadataFieldDefinition(name="Rank", type="select", options=["b", "a", "c"]),
                entry_type="scene:scene",
            )
        )
        self.assertEqual(self.service.read_scene(self.scene_id).metadata, {"rank": "a"})

    def test_removing_option_clears_value_from_entries(self) -> None:
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="faction",
                field=MetadataFieldDefinition(name="Faction", type="multi_select", options=["red", "blue", "green"]),
                entry_type="scene:scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"faction": ["red", "blue"]},
            ),
        )
        # Remove "blue" — it should be dropped from the entry's list.
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="faction",
                field=MetadataFieldDefinition(name="Faction", type="multi_select", options=["red", "green"]),
                entry_type="scene:scene",
            )
        )
        self.assertEqual(self.service.read_scene(self.scene_id).metadata, {"faction": ["red"]})

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
                entry_type="scene:scene",
            )
        )
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type=scene.entry_type,
                metadata={"techlevel": "steam"},
            ),
        )

        schema = self.service.delete_metadata_field(DeleteMetadataFieldRequest(field_id="techlevel", entry_type="scene:scene"))

        self.assertNotIn("techlevel", schema.fields)
        self.assertNotIn("techlevel", schema.entry_types["scene:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertNotIn("techlevel", world_schema["entry_types"]["scene:scene"]["fields"])
        deleted_scene_metadata = self.service.read_scene(self.scene_id).metadata
        self.assertEqual(deleted_scene_metadata, {})

    def test_default_schema_includes_lore_entry_subtypes_and_reference_fields(self) -> None:
        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["lore:character"].kind, "lore")
        self.assertEqual(schema.entry_types["lore:place"].kind, "lore")
        self.assertTrue(schema.entry_types["lore:lore_entry"].abstract)
        self.assertEqual(schema.entry_types["lore:character"].parent, "lore:lore_entry")
        self.assertEqual(schema.entry_types["lore:lore_note"].parent, "lore:lore_entry")
        self.assertNotIn("summary", schema.entry_types["lore:character"].fields)
        self.assertNotIn("summary", schema.entry_types["lore:lore_note"].fields)
        self.assertNotIn("appears_in_scenes", schema.entry_types["lore:lore_note"].fields)
        self.assertIn("aliases", schema.entry_types["lore:lore_note"].fields)
        self.assertIn("tags", schema.entry_types["lore:lore_note"].fields)
        self.assertEqual(schema.entry_types["lore:lore_entry"].own_fields, ["aliases", "tags", "related_entries", "color", "context_policy"])
        # Test fixture adds home_place to character (see _add_home_place_to_character_schema).
        # The seed ships character with `character_cost` (Phase C2 cross-kind
        # cost dispatch); the fixture layer adds home_place on top.
        self.assertEqual(
            schema.entry_types["lore:character"].own_fields,
            ["character_cost", "home_place"],
        )
        self.assertEqual(schema.fields["aliases"].type, "multi_select")
        self.assertEqual(schema.fields["tags"].type, "tags")
        self.assertEqual(schema.fields["related_entries"].type, "entity_ref_list")
        self.assertEqual(schema.fields["related_entries"].picker_config.kinds, ["lore"])
        self.assertEqual(schema.fields["related_entries"].picker_config.entry_types, {})
        self.assertEqual(schema.fields["characters"].picker_config.entry_types, {"lore": ["lore:character"]})

    def test_default_schema_includes_research_kind_with_topic_and_note(self) -> None:
        schema = self.service.read_metadata_schema()

        # Research is the abstract parent for the research-kind tree —
        # like manuscript_structure for the manuscript tree.
        self.assertTrue(schema.entry_types["research:research"].abstract)
        self.assertEqual(schema.entry_types["research:research"].kind, "research")

        self.assertEqual(schema.entry_types["research:topic"].kind, "research")
        self.assertEqual(schema.entry_types["research:topic"].parent, "research:research")
        self.assertFalse(schema.entry_types["research:topic"].has_body)

        self.assertEqual(schema.entry_types["research:note"].kind, "research")
        self.assertEqual(schema.entry_types["research:note"].parent, "research:research")
        self.assertTrue(schema.entry_types["research:note"].has_body)
        # v1 ships notes with just tags (per decisions-research-strategy).
        # Aliases / related_entries / context_policy intentionally omitted.
        self.assertIn("tags", schema.entry_types["research:note"].fields)
        self.assertNotIn("aliases", schema.entry_types["research:note"].fields)
        self.assertNotIn("related_entries", schema.entry_types["research:note"].fields)
        self.assertNotIn("context_policy", schema.entry_types["research:note"].fields)

    def test_lore_note_is_marked_deprecated(self) -> None:
        # lore_note stays readable for legacy projects but is soft-deprecated
        # in favor of research/note. UI hides deprecated types from creation
        # menus; reads keep working.
        schema = self.service.read_metadata_schema()
        self.assertTrue(schema.entry_types["lore:lore_note"].deprecated)
        self.assertFalse(schema.entry_types["lore:character"].deprecated)
        self.assertFalse(schema.entry_types["research:note"].deprecated)

    def test_metadata_rejects_fields_not_bound_to_entry_type(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))

        with self.assertRaisesRegex(ProjectServiceError, "metadata field summary is not defined for entry_type lore:character"):
            self.service.save_lore_entry(
                entry.id,
                SaveLoreEntryRequest(
                    title="Seren",
                    body="A captain with a secret.",
                    base_revision=entry.revision,
                    entry_type="lore:character",
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
                entry_type="lore:lore_entry",
            )
        )
        self.assertIn("importance", schema.entry_types["lore:character"].fields)
        self.assertIn("importance", schema.entry_types["lore:lore_note"].fields)

        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body="A captain with a secret.",
                base_revision=entry.revision,
                entry_type="lore:character",
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
                    parent="lore:lore_entry",
                    fields=[],
                ),
            )
        )

        self.assertIn("lore:faction", schema.entry_types)
        self.assertIn("aliases", schema.entry_types["lore:faction"].fields)
        self.assertIn("tags", schema.entry_types["lore:faction"].fields)
        self.assertEqual(schema.entry_types["lore:faction"].own_fields, [])
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("own_fields", project_schema["entry_types"]["lore:faction"])

        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="The Pact", entry_type="lore:faction"))
        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="The Pact",
                body="A secret faction.",
                base_revision=entry.revision,
                entry_type="lore:faction",
                metadata={"tags": ["Politics"]},
            ),
        )

        self.assertEqual(saved.entry_type, "lore:faction")
        self.assertEqual(saved.metadata["tags"], ["Politics"])

    def test_abstract_entry_type_cannot_be_used_by_documents(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "abstract entry_type lore:lore_entry"):
            self.service.create_lore_entry(CreateLoreEntryRequest(title="Abstract", entry_type="lore:lore_entry"))

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
                entry_type=EntryTypeDefinition(name="Faction", kind="lore", parent="lore:lore_entry", fields=[]),
            )
        )
        self.service.create_lore_entry(CreateLoreEntryRequest(title="The Pact", entry_type="lore:faction"))

        with self.assertRaisesRegex(ProjectServiceError, "used by project documents"):
            self.service.delete_metadata_entry_type(DeleteMetadataEntryTypeRequest(entry_type_id="lore:faction"))

    def test_lore_entry_round_trips_metadata(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        place = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="lore:place"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body="A captain with a secret.",
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={
                    "aliases": ["Ren"],
                    "tags": ["crew"],
                    "home_place": place.id,
                    "related_entries": [place.id],
                },
            ),
        )

        self.assertEqual(saved.entry_type, "lore:character")
        self.assertEqual(saved.metadata["aliases"], ["Ren"])
        self.assertEqual(saved.metadata["tags"], ["crew"])
        self.assertFalse(hasattr(saved, "status"))
        listed_entry = self.service.list_lore_entries().entries[0]
        self.assertEqual(listed_entry.title, "Seren")
        self.assertIn("captain with a secret", listed_entry.body)
        front_matter, _ = self.service._read_markdown_with_front_matter(self.service._path_for_node_id(entry.id, "lore"), strict=True)
        self.assertNotIn("status", front_matter)

    def test_lore_entry_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Robert Smith", entry_type="lore:character"))
        original_path = self.service._path_for_node_id(entry.id, "lore")
        renamed_path = self.root / "lore" / "robert-smith-renamed.md"
        original_path.rename(renamed_path)

        loaded = self.service.read_lore_entry(entry.id)
        listed = self.service.list_lore_entries().entries

        self.assertEqual(loaded.id, entry.id)
        self.assertEqual(loaded.title, "Robert Smith")
        self.assertEqual([item.id for item in listed], [entry.id])

    def test_scene_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        scene = self.service.read_scene(self.scene_id)
        original_path = self.service._path_for_node_id(scene.id, "scene")
        renamed_path = self.root / "scenes" / "opening-scene-renamed.md"
        original_path.rename(renamed_path)

        loaded = self.service.read_scene(scene.id)
        validation = self.service.validate_project()

        self.assertEqual(loaded.id, scene.id)
        self.assertFalse(any("Structure references missing scene" in error for error in validation.errors), validation.errors)

    def test_validation_reports_missing_and_duplicate_front_matter_ids(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        path = self.service._path_for_node_id(entry.id, "lore")
        original_text = path.read_text(encoding="utf-8")
        path.write_text(original_text.replace(f"id: {entry.id}\n", ""), encoding="utf-8")

        validation = self.service.validate_project()

        self.assertTrue(any("missing front matter id" in warning for warning in validation.warnings), validation.warnings)

        path.write_text(original_text, encoding="utf-8")

        duplicate = self.service.create_lore_entry(CreateLoreEntryRequest(title="Other Seren", entry_type="lore:character"))
        duplicate_path = self.service._path_for_node_id(duplicate.id, "lore")
        duplicate_text = duplicate_path.read_text(encoding="utf-8")
        duplicate_path.write_text(duplicate_text.replace(f"id: {duplicate.id}\n", f"id: {entry.id}\n"), encoding="utf-8")

        validation = self.service.validate_project()

        self.assertTrue(any("Duplicate front matter id" in error for error in validation.errors), validation.errors)

    def test_reference_fields_validate_missing_and_wrong_targets(self) -> None:
        character = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        other_character = self.service.create_lore_entry(CreateLoreEntryRequest(title="Aren", entry_type="lore:character"))

        with self.assertRaisesRegex(ProjectServiceError, "references unknown node missing_place"):
            self.service.save_lore_entry(
                character.id,
                SaveLoreEntryRequest(
                    title=character.title,
                    body=character.body,
                    base_revision=character.revision,
                    entry_type=character.entry_type,
                    metadata={"home_place": "missing_place"},
                ),
            )

        with self.assertRaisesRegex(ProjectServiceError, "expected entry_type in \\['lore:place'\\]"):
            self.service.save_lore_entry(
                character.id,
                SaveLoreEntryRequest(
                    title=character.title,
                    body=character.body,
                    base_revision=character.revision,
                    entry_type=character.entry_type,
                    metadata={"home_place": other_character.id},
                ),
            )

    def test_lore_entry_rejects_scene_entry_type(self) -> None:
        with self.assertRaisesRegex(ProjectServiceError, "non-lore entry_type scene:scene"):
            self.service.create_lore_entry(CreateLoreEntryRequest(title="Wrong", entry_type="scene:scene"))

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
                entry_type="lore:character",
            )
        )
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type=entry.entry_type,
                metadata={"faction": "A"},
            ),
        )

        self.service.rename_metadata_field(
            RenameMetadataFieldRequest(old_field_id="faction", new_field_id="allegiance", entry_type="lore:character")
        )
        renamed = self.service.read_lore_entry(entry.id)

        self.assertEqual(renamed.metadata, {"allegiance": "A"})

    def test_search_reports_lore_hit_kind(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body="Keeps the ember map.",
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"tags": ["Navigator"]},
            ),
        )

        result = self.service.search(SearchRequest(query="ember"))

        self.assertEqual(result.hits[0].kind, "lore")
        self.assertEqual(result.hits[0].file_id, entry.id)

    def test_tag_registry_canonicalizes_lore_tags_case_insensitively(self) -> None:
        self.service._write_yaml(self.root / "tags.yaml", {"tags": ["Crew"]})
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Seren",
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"tags": ["crew", "ALLY", "ally"]},
            ),
        )

        self.assertEqual(saved.metadata["tags"], ["Crew", "ALLY"])
        self.assertEqual([tag.name for tag in self.service.read_known_tags().tags], ["ALLY", "Crew"])
        front_matter, _ = self.service._read_markdown_with_front_matter(self.service._path_for_node_id(entry.id, "lore"), strict=True)
        self.assertEqual(front_matter["metadata"]["tags"], ["Crew", "ALLY"])

    def test_aliases_do_not_populate_known_tags(self) -> None:
        self.service._write_yaml(self.root / "tags.yaml", {"tags": ["Crew"]})
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Robert Smith", entry_type="lore:character"))

        saved = self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title="Robert Smith",
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={"aliases": ["Mr. Smith", "Bob"], "tags": ["crew"]},
            ),
        )

        self.assertEqual(saved.metadata["aliases"], ["Mr. Smith", "Bob"])
        self.assertEqual(saved.metadata["tags"], ["Crew"])
        self.assertEqual([tag.name for tag in self.service.read_known_tags().tags], ["Crew"])

    def _project_layer_id(self) -> str:
        return next(
            layer.id
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )

    def test_prompt_subtype_round_trips_with_inputs_and_context_strategy(self) -> None:
        layer_id = self._project_layer_id()
        extras = PromptEntryTypeExtras(
            system_prompt="You are a careful continuation engine.",
            model_class="balanced",
            provider_policy="cloud-allowed",
            inputs=[
                PromptInputDefinition(name="words", type="number", default=300, label="Words"),
                PromptInputDefinition(name="beat", type="long_text", label="Beat instruction"),
            ],
            context_strategy=PromptContextStrategy(
                target={"required": True, "kind": "scene"},
                scan_surface=["_text_before", "_selection"],
                output={"kind": "append_to_body", "review": "visual_diff"},
            ),
        )
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="continue_scene",
                entry_type=EntryTypeDefinition(
                    name="Continue Scene",
                    kind="prompt",
                    parent="prompt:prompt",
                    prompt=extras,
                ),
            )
        )

        stored = schema.entry_types["prompt:continue_scene"]
        assert stored.prompt is not None
        self.assertEqual(stored.prompt.system_prompt, "You are a careful continuation engine.")
        self.assertEqual(stored.prompt.model_class, "balanced")
        self.assertEqual(stored.prompt.provider_policy, "cloud-allowed")
        self.assertEqual([i.name for i in stored.prompt.inputs], ["words", "beat"])
        assert stored.prompt.context_strategy is not None
        self.assertEqual(stored.prompt.context_strategy.scan_surface, ["_text_before", "_selection"])
        self.assertEqual(stored.prompt.context_strategy.target, {"required": True, "kind": "scene"})

        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        disk_entry = on_disk["entry_types"]["prompt:continue_scene"]
        self.assertEqual(disk_entry["kind"], "prompt")
        self.assertEqual(disk_entry["prompt"]["model_class"], "balanced")
        self.assertEqual(disk_entry["prompt"]["inputs"][0]["name"], "words")

        reread = self.service.read_metadata_schema()
        rer = reread.entry_types["prompt:continue_scene"]
        assert rer.prompt is not None
        self.assertEqual(rer.prompt.system_prompt, "You are a careful continuation engine.")
        self.assertEqual([i.name for i in rer.prompt.inputs], ["words", "beat"])

    def test_prompt_inputs_round_trip_entity_ref_with_target(self) -> None:
        # Per #40 / decisions-inputs-fields-uniformity: entity_ref and
        # entity_ref_list inputs carry their picker constraint as a
        # NodePickerConfig under `target` — same wire shape as context_pick
        # inputs and entity_ref metadata fields' `picker_config`. The legacy
        # `{kind, entry_type}` shape was dropped pre-1.0 per the no-migrations
        # policy.
        layer_id = self._project_layer_id()
        extras = PromptEntryTypeExtras(
            inputs=[
                PromptInputDefinition(
                    name="character",
                    type="entity_ref",
                    label="Speaking character",
                    target={"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
                    required=True,
                ),
                PromptInputDefinition(
                    name="related",
                    type="entity_ref_list",
                    label="Related entries",
                    target={"kinds": ["lore"]},
                ),
                PromptInputDefinition(
                    name="words",
                    type="number",
                    default=300,
                ),
            ],
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="character_chat",
                entry_type=EntryTypeDefinition(
                    name="Character chat",
                    kind="prompt",
                    parent="prompt:general",
                    prompt=extras,
                ),
            )
        )

        schema = self.service.read_metadata_schema()
        inputs = schema.entry_types["prompt:character_chat"].prompt.inputs
        by_name = {i.name: i for i in inputs}

        self.assertEqual(by_name["character"].type, "entity_ref")
        self.assertEqual(
            by_name["character"].target,
            {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        )
        self.assertTrue(by_name["character"].required)

        self.assertEqual(by_name["related"].type, "entity_ref_list")
        self.assertEqual(by_name["related"].target, {"kinds": ["lore"]})

        # Non-ref inputs untouched: target stays None.
        self.assertEqual(by_name["words"].type, "number")
        self.assertIsNone(by_name["words"].target)

        # Reload from YAML to confirm the round-trip survives the disk hop.
        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        disk_inputs = on_disk["entry_types"]["prompt:character_chat"]["prompt"]["inputs"]
        disk_by_name = {i["name"]: i for i in disk_inputs}
        self.assertEqual(disk_by_name["character"]["type"], "entity_ref")
        self.assertEqual(
            disk_by_name["character"]["target"],
            {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        )

    def test_default_schema_seeds_four_prompt_bases(self) -> None:
        """continuation/revise/general/snippet are concrete bases with preset
        output kinds; users instantiate them directly or sub-type them to add
        personality. Inputs live on the instance (not the type) so the bases
        no longer need to be abstract."""
        schema = self.service.read_metadata_schema()
        for type_id in ("prompt:continuation", "prompt:revise", "prompt:general", "prompt:snippet"):
            self.assertIn(type_id, schema.entry_types)
            self.assertEqual(schema.entry_types[type_id].kind, "prompt")
            self.assertEqual(schema.entry_types[type_id].parent, "prompt:prompt")
            self.assertFalse(schema.entry_types[type_id].abstract, msg=type_id)

        continuation_prompt = schema.entry_types["prompt:continuation"].prompt
        assert continuation_prompt is not None
        assert continuation_prompt.context_strategy is not None
        self.assertEqual(continuation_prompt.context_strategy.output, {"kind": "append_to_body", "review": "visual_diff"})

        revise_prompt = schema.entry_types["prompt:revise"].prompt
        assert revise_prompt is not None
        assert revise_prompt.context_strategy is not None
        self.assertEqual(revise_prompt.context_strategy.output, {"kind": "replace_selection", "review": "visual_diff"})

        general_prompt = schema.entry_types["prompt:general"].prompt
        assert general_prompt is not None
        assert general_prompt.context_strategy is not None
        self.assertEqual(general_prompt.context_strategy.output, {"kind": "chat_panel"})

        self.assertIsNone(schema.entry_types["prompt:snippet"].prompt)

    def test_concrete_subtype_inherits_output_kind_from_abstract_base(self) -> None:
        """A user creates `bob extends general`; the output disposition is inherited."""
        layer_id = self._project_layer_id()
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="bob",
                entry_type=EntryTypeDefinition(
                    name="Bob",
                    kind="prompt",
                    parent="prompt:general",
                    prompt=PromptEntryTypeExtras(system_prompt="You are Bob."),
                ),
            )
        )

        bob_prompt = schema.entry_types["prompt:bob"].prompt
        assert bob_prompt is not None
        assert bob_prompt.context_strategy is not None
        self.assertEqual(bob_prompt.context_strategy.output, {"kind": "chat_panel"})
        self.assertEqual(bob_prompt.system_prompt, "You are Bob.")

    def test_snippet_subtype_inherits_from_prompt_kind(self) -> None:
        layer_id = self._project_layer_id()
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="house_voice",
                entry_type=EntryTypeDefinition(
                    name="House Voice",
                    kind="prompt",
                    parent="prompt:snippet",
                ),
            )
        )

        self.assertIn("prompt:house_voice", schema.entry_types)
        self.assertEqual(schema.entry_types["prompt:house_voice"].kind, "prompt")
        self.assertEqual(schema.entry_types["prompt:house_voice"].parent, "prompt:snippet")
        self.assertEqual(schema.entry_types["prompt:snippet"].kind, "prompt")
        self.assertEqual(schema.entry_types["prompt:snippet"].parent, "prompt:prompt")

    def test_unknown_kind_is_rejected(self) -> None:
        layer_id = self._project_layer_id()
        with self.assertRaisesRegex(ProjectServiceError, "kind must be"):
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="bogus",
                    entry_type=EntryTypeDefinition(name="Bogus", kind="bogus"),
                )
            )

    def test_prompt_extras_rejected_on_non_prompt_kind(self) -> None:
        layer_id = self._project_layer_id()
        with self.assertRaisesRegex(ProjectServiceError, "only valid on prompt"):
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="faction",
                    entry_type=EntryTypeDefinition(
                        name="Faction",
                        kind="lore",
                        parent="lore:lore_entry",
                        prompt=PromptEntryTypeExtras(system_prompt="Nope"),
                    ),
                )
            )

    def test_prompt_input_select_requires_options(self) -> None:
        layer_id = self._project_layer_id()
        with self.assertRaisesRegex(ProjectServiceError, "no options"):
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="bad_prompt",
                    entry_type=EntryTypeDefinition(
                        name="Bad Prompt",
                        kind="prompt",
                        parent="prompt:prompt",
                        prompt=PromptEntryTypeExtras(
                            inputs=[PromptInputDefinition(name="tone", type="select", options=[])],
                        ),
                    ),
                )
            )

    def test_prompt_duplicate_input_name_rejected(self) -> None:
        layer_id = self._project_layer_id()
        with self.assertRaisesRegex(ProjectServiceError, "duplicate prompt input"):
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="dup_prompt",
                    entry_type=EntryTypeDefinition(
                        name="Dup Prompt",
                        kind="prompt",
                        parent="prompt:prompt",
                        prompt=PromptEntryTypeExtras(
                            inputs=[
                                PromptInputDefinition(name="x"),
                                PromptInputDefinition(name="x"),
                            ],
                        ),
                    ),
                )
            )

    def test_prompt_child_inherits_system_prompt_from_parent(self) -> None:
        layer_id = self._project_layer_id()
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="house_prompt",
                entry_type=EntryTypeDefinition(
                    name="House Prompt",
                    kind="prompt",
                    parent="prompt:prompt",
                    abstract=True,
                    prompt=PromptEntryTypeExtras(
                        system_prompt="House style: terse, no purple prose.",
                        model_class="balanced",
                    ),
                ),
            )
        )
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="house_continue",
                entry_type=EntryTypeDefinition(
                    name="House Continue",
                    kind="prompt",
                    parent="prompt:house_prompt",
                    prompt=PromptEntryTypeExtras(
                        inputs=[PromptInputDefinition(name="words", type="number", default=200)],
                    ),
                ),
            )
        )

        child = schema.entry_types["prompt:house_continue"]
        assert child.prompt is not None
        self.assertEqual(child.prompt.system_prompt, "House style: terse, no purple prose.")
        self.assertEqual(child.prompt.model_class, "balanced")
        self.assertEqual([i.name for i in child.prompt.inputs], ["words"])

    def test_prompt_extras_preserved_on_partial_update(self) -> None:
        layer_id = self._project_layer_id()
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="my_prompt",
                entry_type=EntryTypeDefinition(
                    name="My Prompt",
                    kind="prompt",
                    parent="prompt:prompt",
                    prompt=PromptEntryTypeExtras(
                        system_prompt="Keep it short.",
                        inputs=[PromptInputDefinition(name="topic")],
                    ),
                ),
            )
        )
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="my_prompt",
                entry_type=EntryTypeDefinition(
                    name="Renamed Prompt",
                    kind="prompt",
                    parent="prompt:prompt",
                ),
            )
        )

        stored = schema.entry_types["prompt:my_prompt"]
        self.assertEqual(stored.name, "Renamed Prompt")
        assert stored.prompt is not None
        self.assertEqual(stored.prompt.system_prompt, "Keep it short.")
        self.assertEqual([i.name for i in stored.prompt.inputs], ["topic"])

    def test_prompt_entry_inputs_round_trip(self) -> None:
        # Inputs live on the prompt entry (not the entry-type) — declared and
        # used in the same scope as the template body. Regression for a bug
        # where a missing PromptInputDefinition import in project_service
        # caused _parse_prompt_inputs's broad `except Exception` to swallow
        # the resulting NameError, silently discarding every input on read.
        from app.models import (
            CreatePromptEntryRequest,
            EntryTypeDefinition,
            PromptInputDefinition,
            SavePromptEntryRequest,
            UpsertMetadataEntryTypeRequest,
        )

        # Concrete prompt sub-type for the test. The seeded `general` base is
        # now concrete and could be used directly, but we keep a named sub-type
        # here so the test exercises the inheritance path explicitly.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="brainstorm",
                allow_existing=False,
                entry_type=EntryTypeDefinition.model_validate({
                    "name": "Brainstorm",
                    "kind": "prompt",
                    "parent": "prompt:general",
                    "abstract": False,
                    "fields": [],
                }),
            )
        )
        created = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Brainstorm", entry_type="prompt:brainstorm"),
        )
        saved = self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Brainstorm",
                body='{% role "user" %}Talk about {{ input.topic }}.{% endrole %}',
                base_revision=created.revision,
                entry_type=created.entry_type,
                metadata={},
                inputs=[
                    PromptInputDefinition(name="topic", type="text", label="Topic", required=True),
                    PromptInputDefinition(name="depth", type="select", label="Depth", options=["quick", "thorough"], default="quick"),
                ],
            ),
        )
        self.assertEqual(len(saved.inputs), 2)

        # Re-read from disk — the bug surfaced here as inputs=[].
        reread = self.service.read_prompt_entry(created.id)
        self.assertEqual(len(reread.inputs), 2)
        self.assertEqual(reread.inputs[0].name, "topic")
        self.assertTrue(reread.inputs[0].required)
        self.assertEqual(reread.inputs[1].type, "select")
        # Options round-trip as SelectOption objects (with `value` /
        # optional label / optional color). Bare strings are still
        # accepted on the wire via the back-compat validator.
        self.assertEqual([opt.value for opt in reread.inputs[1].options], ["quick", "thorough"])
        self.assertEqual(reread.inputs[1].default, "quick")

        # And the list endpoint should surface inputs too (used by the chat
        # composer when picking a prompt).
        listing = self.service.list_prompt_entries()
        match = next(e for e in listing.entries if e.id == created.id)
        self.assertEqual([i.name for i in match.inputs], ["topic", "depth"])

    def test_front_matter_body_round_trip_does_not_accumulate_leading_newlines(self) -> None:
        # Regression: the writer emitted `---\n\n{body}` and the reader split
        # on `\n---\n`, leaving the separator `\n` attached to the body. A
        # save/read cycle therefore added one leading newline each time the
        # user opened and re-saved a prompt entry.
        path = self.root / "scratch.md"
        for _ in range(5):
            self.service._write_node_entry_file(
                path,
                node_id="scratch_001",
                title="Round-trip scratch",
                entry_type="lore:lore_note",
                metadata={},
                body=self.service._read_markdown_with_front_matter(path)[1] if path.exists() else "hello",
            )
            front, body = self.service._read_markdown_with_front_matter(path)
            self.assertFalse(body.startswith("\n"), f"body should not gain leading newlines, got {body!r}")
            self.assertEqual(body.strip(), "hello")

    def test_field_default_seeds_new_entries_and_round_trips(self) -> None:
        # #38: a field with `default` set seeds new entries on creation
        # (computed fields excluded; the wire shape is type-matched). The
        # default also round-trips through the schema YAML.
        layer_id = self._project_layer_id()

        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="mood",
                field=MetadataFieldDefinition(
                    name="Mood",
                    type="select",
                    options=[
                        SelectOption(value="calm"),
                        SelectOption(value="tense"),
                    ],
                    default="calm",
                ),
                entry_type="lore:character",
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="age",
                field=MetadataFieldDefinition(name="Age", type="number", default=30),
                entry_type="lore:character",
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="active",
                field=MetadataFieldDefinition(name="Active", type="boolean", default=True),
                entry_type="lore:character",
            )
        )

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Defaulted", entry_type="lore:character")
        )
        self.assertEqual(entry.metadata.get("mood"), "calm")
        self.assertEqual(entry.metadata.get("age"), 30)
        self.assertEqual(entry.metadata.get("active"), True)

        # Schema YAML round-trip preserves the default.
        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertEqual(on_disk["fields"]["mood"]["default"], "calm")
        self.assertEqual(on_disk["fields"]["age"]["default"], 30)
        self.assertEqual(on_disk["fields"]["active"]["default"], True)

        # Fields without a default keep entries blank (the historic
        # behaviour) — only opted-in fields seed.
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="hometown",
                field=MetadataFieldDefinition(name="Hometown", type="text"),
                entry_type="lore:character",
            )
        )
        blank = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Blanky", entry_type="lore:character")
        )
        self.assertNotIn("hometown", blank.metadata)

    def test_scene_status_field_default_promotes_to_top_level(self) -> None:
        # `status` is a top-level Scene attribute (not in metadata). When
        # the schema field "status" carries a default, create_scene picks
        # it up via the Scene model's `status` field rather than leaving
        # the default stuck in metadata where the UI wouldn't surface it.
        layer_id = self._project_layer_id()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="status",
                field=MetadataFieldDefinition(
                    name="Status",
                    type="select",
                    options=[
                        SelectOption(value="draft"),
                        SelectOption(value="revised"),
                        SelectOption(value="complete"),
                    ],
                    default="revised",
                ),
                entry_type="scene:scene",
            )
        )
        scene = self.service.create_scene(CreateSceneRequest(title="Defaulted scene"))
        self.assertEqual(scene.status, "revised")
        self.assertNotIn("status", scene.metadata)


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
        # See MetadataValidationTests for the rationale — home_place is
        # a test-only field on Character.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})["home_place"] = {
            "name": "Home Place",
            "type": "entity_ref",
            "target": {"entry_type": "lore:place"},
        }
        character = data["entry_types"].get("lore:character") or {}
        fields = list(character.get("fields") or [])
        if "home_place" not in fields:
            fields.insert(0, "home_place")
            character["fields"] = fields
            data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _first_scene_id(self) -> str:
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        return self.service._read_front_matter_only(first_scene_path, strict=True)["id"]

    def _save_body(self, entry_id: str, body: str) -> None:
        entry = self.service.read_lore_entry(entry_id)
        self.service.save_lore_entry(
            entry_id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=body,
                base_revision=entry.revision,
                entry_type=entry.entry_type,
                metadata=entry.metadata,
            ),
        )

    def test_resolve_returns_titles_for_known_ids(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        taverna = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="lore:place"))

        response = self.service.resolve_references([seren.id, taverna.id])

        ids = {candidate.id: candidate for candidate in response.candidates}
        self.assertEqual(ids[seren.id].title, "Seren")
        self.assertEqual(ids[seren.id].entry_type, "lore:character")
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
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        self._save_body(seren.id, "# Seren\n\nA brave caravan guard.\n")

        response = self.service.resolve_references([seren.id])

        self.assertEqual(response.candidates[0].summary, "A brave caravan guard.")

    def test_candidates_filter_by_kind(self) -> None:
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        scene_id = self._first_scene_id()

        response = self.service.list_reference_candidates(kind="lore")

        ids = {candidate.id for candidate in response.candidates}
        self.assertNotIn(scene_id, ids)
        self.assertTrue(any(candidate.title == "Seren" for candidate in response.candidates))

    def test_candidates_filter_by_entry_type_with_inheritance(self) -> None:
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="lore:place"))

        characters_only = self.service.list_reference_candidates(entry_type="lore:character")
        titles = {candidate.title for candidate in characters_only.candidates}
        self.assertEqual(titles, {"Seren"})

        all_lore = self.service.list_reference_candidates(entry_type="lore:lore_entry")
        titles = {candidate.title for candidate in all_lore.candidates}
        self.assertEqual(titles, {"Seren", "Taverna"})

    def test_candidates_exclude_id(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        aren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Aren", entry_type="lore:character"))

        response = self.service.list_reference_candidates(entry_type="lore:character", exclude_id=seren.id)

        ids = {candidate.id for candidate in response.candidates}
        self.assertIn(aren.id, ids)
        self.assertNotIn(seren.id, ids)

    def test_backlinks_finds_references(self) -> None:
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        taverna = self.service.create_lore_entry(CreateLoreEntryRequest(title="Taverna", entry_type="lore:place"))
        self.service.save_lore_entry(
            seren.id,
            SaveLoreEntryRequest(
                title="Seren",
                body=seren.body,
                base_revision=seren.revision,
                entry_type="lore:character",
                metadata={"home_place": taverna.id},
            ),
        )
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="scene:scene",
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
        seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))
        scene_id = self._first_scene_id()
        scene = self.service.read_scene(scene_id)
        self.service.save_scene(
            scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status=scene.status,
                entry_type="scene:scene",
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
            seren = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="lore:character"))

            resolve_response = client.post("/api/references/resolve", json={"ids": [seren.id, "missing"]})
            self.assertEqual(resolve_response.status_code, 200)
            payload = resolve_response.json()
            ids_by = {candidate["id"]: candidate for candidate in payload["candidates"]}
            self.assertEqual(ids_by[seren.id]["title"], "Seren")
            self.assertFalse(ids_by["missing"]["found"])

            candidates_response = client.get("/api/references/candidates", params={"entry_type": "lore:character"})
            self.assertEqual(candidates_response.status_code, 200)
            titles = {candidate["title"] for candidate in candidates_response.json()["candidates"]}
            self.assertIn("Seren", titles)
        finally:
            app_main.service = original_service


class LayeredEntryIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book 1")
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(self.base)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_lore_at(self, layer_folder: Path, entry_id: str, title: str, entry_type: str = "lore:lore_note") -> None:
        from app.models import LoreEntry

        (layer_folder / "lore").mkdir(parents=True, exist_ok=True)
        entry = LoreEntry(
            id=entry_id,
            title=title,
            body=f"# {title}",
            revision="",
            entry_type=entry_type,
            metadata={},
        )
        self.service._write_lore_entry_file(layer_folder / "lore" / f"{entry_id}.md", entry)

    def _write_prompt_at(self, layer_folder: Path, entry_id: str, title: str) -> None:
        (layer_folder / "prompts").mkdir(parents=True, exist_ok=True)
        self.service._write_node_entry_file(
            layer_folder / "prompts" / f"{entry_id}.md",
            entry_id,
            title,
            "prompt",
            {},
            f"# {title}",
        )

    def test_lore_index_includes_ancestor_entries(self) -> None:
        self._write_lore_at(self.universe, "manticore", "Manticore", entry_type="lore:lore_note")
        self._write_lore_at(self.series, "honor", "Honor Harrington", entry_type="lore:lore_note")
        self._write_lore_at(self.root, "nimitz", "Nimitz", entry_type="lore:lore_note")

        entries = self.service.list_lore_entries().entries
        ids_by = {entry.id: entry for entry in entries}

        self.assertEqual(ids_by["manticore"].source_layer_label, "honorverse")
        self.assertEqual(ids_by["honor"].source_layer_label, "honor-harrington")
        self.assertEqual(ids_by["nimitz"].source_layer_label, "Book 1")

    def test_prompt_index_includes_ancestor_entries(self) -> None:
        self._write_prompt_at(self.universe, "continue_voice", "Continue in voice")
        self._write_prompt_at(self.root, "book_specific", "Book-specific prompt")

        entries = self.service.list_prompt_entries().entries
        ids = {entry.id for entry in entries}

        self.assertIn("continue_voice", ids)
        self.assertIn("book_specific", ids)

    def test_descendant_wins_on_id_collision_with_warning(self) -> None:
        self._write_lore_at(self.universe, "duplicated", "Universe Version")
        self._write_lore_at(self.root, "duplicated", "Book Version")

        index = self.service._build_node_index()
        entry = index.by_id["duplicated"]

        self.assertEqual(entry.source_layer_label, "Book 1")
        self.assertTrue(any("shadows" in warning for warning in index.warnings))

    def test_scenes_stay_book_scoped(self) -> None:
        (self.universe / "scenes").mkdir(parents=True, exist_ok=True)
        from app.models import Scene

        ancestor_scene = Scene(
            id="ghost_scene",
            title="Should not appear",
            body="",
            revision="",
            status="draft",
            entry_type="scene:scene",
            metadata={},
        )
        self.service._write_scene_file(self.universe / "scenes" / "ghost_scene.md", ancestor_scene)

        index = self.service._build_node_index()

        self.assertNotIn("ghost_scene", index.by_id)

    def test_ancestor_lore_read_carries_source_layer(self) -> None:
        self._write_lore_at(self.universe, "manticore", "Manticore")

        entry = self.service.read_lore_entry("manticore")

        self.assertEqual(entry.title, "Manticore")
        self.assertEqual(entry.source_layer_label, "honorverse")
        self.assertNotEqual(entry.source_layer_id, "")

    def test_reference_candidate_carries_source_layer(self) -> None:
        self._write_lore_at(self.universe, "manticore", "Manticore")

        response = self.service.list_reference_candidates(kind="lore")
        candidate = next(c for c in response.candidates if c.id == "manticore")

        self.assertEqual(candidate.source_layer_label, "honorverse")


if __name__ == "__main__":
    unittest.main()
