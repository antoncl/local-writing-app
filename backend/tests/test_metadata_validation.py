from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.models import (
    CreateLoreEntryRequest,
    DeleteMetadataFieldRequest,
    MetadataFieldDefinition,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    SearchRequest,
    UpdateProjectSettingsRequest,
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
        self.assertEqual(schema.entry_types["scene"].fields, ["status", "summary", "characters", "locations", "word_count", "pov", "tension"])

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
        updated_base = Path(self.temp_dir.name) / "new-base"
        updated_base.mkdir()

        project = self.service.update_project_settings(UpdateProjectSettingsRequest(projects_base_folder=str(updated_base)))

        self.assertEqual(project.projects_base_folder, str(updated_base.resolve()))
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertEqual(manifest["settings"]["projects_base_folder"], str(updated_base.resolve()))

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
        self.assertNotIn("summary", schema.entry_types["character"].fields)
        self.assertNotIn("summary", schema.entry_types["lore_note"].fields)
        self.assertNotIn("appears_in_scenes", schema.entry_types["lore_note"].fields)
        self.assertIn("aliases", schema.entry_types["lore_note"].fields)
        self.assertIn("tags", schema.entry_types["lore_note"].fields)
        self.assertEqual(schema.fields["aliases"].type, "multi_select")
        self.assertEqual(schema.fields["tags"].type, "tags")
        self.assertEqual(schema.fields["related_entries"].type, "entity_ref_list")
        self.assertEqual(schema.fields["related_entries"].target, {"kind": "lore"})
        self.assertEqual(schema.fields["characters"].target, {"entry_type": "character"})

    def test_lore_entry_round_trips_metadata(self) -> None:
        entry = self.service.create_lore_entry(CreateLoreEntryRequest(title="Seren", entry_type="character"))

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
                    "home_place": "lore_home",
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


if __name__ == "__main__":
    unittest.main()
