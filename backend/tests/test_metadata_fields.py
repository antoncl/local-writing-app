from __future__ import annotations

import unittest
from pathlib import Path

from layer_fixtures import set_projects_root
from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateLoreEntryRequest,
    DeleteMetadataFieldRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    SetFieldOrderRequest,
    SetGroupApplicationsRequest,
    UpdateProjectSettingsRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError


class MetadataFieldTests(MetadataValidationBase):
    def test_schema_layers_include_empty_intermediate_folders(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers

        self.assertEqual(
            [Path(layer.folder_path) for layer in layers],
            [self.base, self.universe, self.world, self.root],
        )
        self.assertFalse(layers[1].exists)
        self.assertFalse(layers[2].exists)

    def test_a_schema_file_above_the_configured_base_does_not_widen_the_walk(
        self,
    ) -> None:
        """#337, inverting the test that used to codify the widening.

        A `metadata.schema.yaml` in a grandparent used to *become* the base
        folder whenever the configured one happened to equal `root.parent` —
        which is what the project chooser writes on every create. The walk now
        stops where the setting says, and a file's presence changes nothing.
        """
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
            [self.root.parent, self.root],
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
                entry_type="manuscript:scene",
                metadata={
                    "summary": "Opening beat",
                },
            ),
        )

        self.assertEqual(saved.metadata["summary"], "Opening beat")
        self.assertEqual(saved.computed_metadata["word_count"], 5)

    def test_save_rejects_computed_metadata(self) -> None:
        scene = self.service.read_scene(self.scene_id)

        with self.assertRaisesRegex(
            ProjectServiceError, "computed metadata field word_count"
        ):
            self.service.save_scene(
                self.scene_id,
                SaveSceneRequest(
                    title=scene.title,
                    body=scene.body,
                    base_revision=scene.revision,
                    status="draft",
                    entry_type="manuscript:scene",
                    metadata={"word_count": 12},
                ),
            )

    def test_validation_reports_hand_edited_computed_metadata(self) -> None:
        path = self.service._path_for_node_id(self.scene_id, "manuscript")
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("metadata: {}", "metadata:\n  word_count: 12"),
            encoding="utf-8",
        )

        validation = self.service.validate_project()

        self.assertFalse(validation.valid)
        self.assertTrue(
            any(
                "computed metadata field word_count" in error
                for error in validation.errors
            ),
            validation.errors,
        )

    def test_owned_lore_save_clears_omitted_fields_per_type(self) -> None:
        # #522: reverting a field = deleting its sparse YAML key (unset ⇒ absent).
        # An owned save must persist an omitted scalar as ABSENT — never re-seed
        # the default, never coerce a missing boolean to False.
        self._add_clearable_fields(self.root, "lore:character")
        hero = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        # Create seeded the boolean default — the "stuck at a value" starting point.
        self.assertEqual(hero.metadata.get("flagged"), True)

        self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title=hero.title,
                body=hero.body,
                base_revision=hero.revision,
                entry_type="lore:character",
                metadata={"flagged": False, "rank": 3, "tier": "b"},
            ),
        )
        entry = self.service.read_lore_entry(hero.id)
        self.assertEqual(entry.metadata.get("flagged"), False)
        self.assertEqual(entry.metadata.get("rank"), 3)
        self.assertEqual(entry.metadata.get("tier"), "b")

        # Clear = omit the keys.
        self.service.save_lore_entry(
            hero.id,
            SaveLoreEntryRequest(
                title=entry.title,
                body=entry.body,
                base_revision=entry.revision,
                entry_type="lore:character",
                metadata={},
            ),
        )
        cleared = self.service.read_lore_entry(hero.id)
        self.assertNotIn(
            "flagged", cleared.metadata
        )  # not re-seeded to True, not coerced to False
        self.assertNotIn("rank", cleared.metadata)
        self.assertNotIn("tier", cleared.metadata)

    def test_owned_scene_save_clears_omitted_fields_per_type(self) -> None:
        # Scene parity for the same round-trip (#522).
        self._add_clearable_fields(self.root, "manuscript:scene")
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"flagged": False, "rank": 7, "tier": "a"},
            ),
        )
        scene = self.service.read_scene(self.scene_id)
        self.assertEqual(scene.metadata.get("flagged"), False)
        self.assertEqual(scene.metadata.get("rank"), 7)

        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={},
            ),
        )
        cleared = self.service.read_scene(self.scene_id)
        self.assertNotIn("flagged", cleared.metadata)
        self.assertNotIn("rank", cleared.metadata)
        self.assertNotIn("tier", cleared.metadata)

    def test_metadata_schema_layers_apply_from_base_to_project(self) -> None:
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "manuscript:scene": {
                        "name": "Base Scene",
                        "kind": "manuscript",
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
                    "manuscript:scene": {
                        "name": "World Scene",
                        "kind": "manuscript",
                        "fields": [
                            "status",
                            "summary",
                            "mood",
                            "tension",
                            "word_count",
                        ],
                    }
                },
                "fields": {
                    "tension": {"name": "Tension", "type": "number"},
                },
            },
        )

        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["manuscript:scene"].name, "World Scene")
        self.assertIn("mood", schema.fields)
        self.assertIn("tension", schema.fields)
        # Intrinsic identity fields (#116) lead every type's resolved list; a
        # body-bearing type carries `body` as the second intrinsic (ADR-0059 §B).
        self.assertEqual(
            schema.entry_types["manuscript:scene"].fields,
            [
                "title",
                "body",
                "entry_type",
                "id",
                "number",
                "summary",
                "color",
                "status",
                "pov",
                "characters",
                "location",
                "tags",
                "pov_mode",
                "tense",
                "dynamics",
                "word_count",
                "cost",
                "mood",
                "tension",
            ],
        )

        scene = self.service.read_scene(self.scene_id)
        saved = self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title=scene.title,
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="manuscript:scene",
                metadata={"mood": "tense", "tension": 3},
            ),
        )

        self.assertEqual(saved.metadata["mood"], "tense")
        self.assertEqual(saved.metadata["tension"], 3)

    def test_validation_warns_when_the_project_is_outside_the_machine_root(
        self,
    ) -> None:
        """The warning names the machine root now (#429) — that is where the
        author has to go to change it. Naming a per-project key sent them to a
        setting that no longer decides anything."""
        set_projects_root(Path(self.temp_dir.name).resolve() / "elsewhere")

        validation = self.service.validate_project()

        self.assertTrue(validation.valid)
        self.assertTrue(
            any(
                "outside the machine's projects folder" in warning
                for warning in validation.warnings
            ),
            validation.warnings,
        )

    def test_validation_warns_when_no_machine_root_is_set(self) -> None:
        """The state every project is in before a root is ever configured.
        Warned rather than failed: the project is fine, it just stands alone."""
        set_projects_root(None)

        validation = self.service.validate_project()

        self.assertTrue(validation.valid)
        self.assertTrue(
            any(
                "No projects folder is set for this machine" in warning
                for warning in validation.warnings
            ),
            validation.warnings,
        )

    def test_project_settings_unset_field_is_left_unchanged(self) -> None:
        # Partial update: a request that omits a field must not disturb the
        # previously-saved value (the Project pane sends only ai_policy).
        # The expectation is spelled out rather than read back from a prior
        # call's return value — comparing the service against itself would
        # pass even if both calls clobbered the setting identically.
        #
        # Paired against `inherits` since #429 removed `projects_base_folder`
        # from this request. The property under test is the partial update, not
        # the particular field, and `inherits` is now the other thing a save
        # can carry — so it is the one that can be clobbered.
        expected_inherits = ["../.."]
        self.service.update_project_settings(
            UpdateProjectSettingsRequest(inherits=[str(self.universe)])
        )

        project = self.service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )

        self.assertEqual(project.ai_policy, "cloud-allowed")
        # Assert the stored key too, not just the response: a derived field on
        # ProjectInfo can mask a manifest that lost the setting.
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertEqual(manifest["inherits"], expected_inherits)

    def test_schema_layers_are_listed_from_base_to_project(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers

        self.assertEqual(
            [layer.folder_path for layer in layers],
            [str(self.base), str(self.universe), str(self.world), str(self.root)],
        )
        # #309: a declared layer carries its own project title. "Base Folder"
        # survives only for a base that is not itself a project.
        self.assertEqual(layers[0].label, "writing")
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
                    "manuscript:scene": {
                        "name": "World Scene",
                        "kind": "manuscript",
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
        self.assertEqual(
            overview.entry_type_sources["manuscript:scene"].layer_label, "series"
        )

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
                entry_type="manuscript:scene",
            )
        )

        self.assertIn("pov_character", schema.fields)
        self.assertIn("pov_character", schema.entry_types["manuscript:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertIn("pov_character", world_schema["fields"])
        self.assertEqual(
            world_schema["entry_types"]["manuscript:scene"]["fields"], ["pov_character"]
        )
        self.assertNotIn(
            "status", world_schema["entry_types"]["manuscript:scene"]["fields"]
        )
        self.assertNotIn(
            "summary", world_schema["entry_types"]["manuscript:scene"]["fields"]
        )
        self.assertNotIn(
            "word_count", world_schema["entry_types"]["manuscript:scene"]["fields"]
        )
        self.assertNotIn(
            "pov_character",
            self.service._read_yaml(self.root / "metadata.schema.yaml").get(
                "fields", {}
            ),
        )

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
                entry_type=EntryTypeDefinition.model_validate(
                    {
                        "name": "Brainstorm",
                        "kind": "prompt",
                        "parent": "prompt:base",
                        "abstract": False,
                        "fields": [],
                    }
                ),
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
                field=MetadataFieldDefinition(
                    name="Background Color",
                    type="select",
                    options=["Red", "Green", "Blue"],
                ),
                entry_type="manuscript:scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.upsert_metadata_field(
                UpsertMetadataFieldRequest(
                    layer_id=world_layer.id,
                    field_id="color",
                    field=MetadataFieldDefinition(name="Color", type="text"),
                    entry_type="manuscript:scene",
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
                entry_type="manuscript:scene",
            )
        )

        self.assertEqual(schema.fields["scene_number"].type, "computed")
        self.assertEqual(
            schema.fields["scene_number"].computed,
            {"function": "counter", "scope": "manuscript"},
        )
        self.assertIn("scene_number", schema.entry_types["manuscript:scene"].fields)

    def test_create_computed_cost_field_with_scope(self) -> None:
        # The field editor now offers `cost` as an authorable computed function
        # (#353); this asserts the upsert path the editor drives accepts the
        # wire shape it produces — {function: "cost", scope: <scene|…>}.
        world_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.world)
        )
        schema = self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="scene_spend",
                field=MetadataFieldDefinition(
                    name="Scene spend",
                    type="computed",
                    computed={"function": "cost", "scope": "scene"},
                ),
                entry_type="manuscript:scene",
            )
        )

        self.assertEqual(schema.fields["scene_spend"].type, "computed")
        self.assertEqual(
            schema.fields["scene_spend"].computed,
            {"function": "cost", "scope": "scene"},
        )
        self.assertIn("scene_spend", schema.entry_types["manuscript:scene"].fields)

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
                    entry_type="manuscript:scene",
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
                    entry_type="manuscript:scene",
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
                entry_type=EntryTypeDefinition(
                    name="Faction", kind="lore", parent="lore:base", fields=[]
                ),
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
        self.assertEqual(
            self.service.read_metadata_schema().entry_types["lore:faction"].own_fields,
            ["alpha", "beta", "gamma"],
        )

        schema = self.service.set_entry_type_field_order(
            SetFieldOrderRequest(
                layer_id=project_layer.id,
                entry_type_id="lore:faction",
                field_order=["gamma", "alpha", "beta"],
            )
        )
        # Membership (own_fields) is untouched — a display-order overlay drives
        # the render order (#89), so the reordered ids lead the resolved list.
        self.assertEqual(
            schema.entry_types["lore:faction"].own_fields, ["alpha", "beta", "gamma"]
        )
        self.assertEqual(
            schema.entry_types["lore:faction"].fields[:3], ["gamma", "alpha", "beta"]
        )
        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertEqual(
            on_disk["entry_types"]["lore:faction"]["display_order"],
            ["gamma", "alpha", "beta"],
        )
        self.assertEqual(
            on_disk["entry_types"]["lore:faction"]["fields"], ["alpha", "beta", "gamma"]
        )

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
                entry_type=EntryTypeDefinition(
                    name="Faction", kind="lore", parent="lore:base", fields=[]
                ),
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
                SetFieldOrderRequest(
                    layer_id=project_layer.id,
                    entry_type_id="lore:faction",
                    field_order=["alpha", "ghost"],
                )
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_set_entry_type_field_order_allows_system_type_as_overlay(self) -> None:
        # ADR-0029 §A: display order is a pure per-layer overlay, so it now
        # applies to a built-in type — the narrowed guard no longer walls it
        # off — and the built-in stays built-in-sourced.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.set_entry_type_field_order(
            SetFieldOrderRequest(
                layer_id=project_layer.id,
                entry_type_id="manuscript:scene",
                field_order=["summary", "number"],
            )
        )
        fields = (
            self.service.read_metadata_schema().entry_types["manuscript:scene"].fields
        )
        self.assertLess(fields.index("summary"), fields.index("number"))
        overview = self.service.read_metadata_schema_overview()
        self.assertTrue(overview.entry_type_sources["manuscript:scene"].built_in)

    def test_set_entry_type_group_applications_allows_system_type_as_overlay(
        self,
    ) -> None:
        # ADR-0029 §A: group applications are a per-layer overlay too, so the
        # narrowed guard no longer rejects a built-in target (a plain no-op
        # overlay is enough to prove the wall is gone), and it stays sourced
        # as built-in.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.set_entry_type_group_applications(
            SetGroupApplicationsRequest(
                layer_id=project_layer.id,
                entry_type_id="manuscript:scene",
                applications=[],
            )
        )
        overview = self.service.read_metadata_schema_overview()
        self.assertTrue(overview.entry_type_sources["manuscript:scene"].built_in)

    def test_upsert_entry_type_overlays_builtin_without_forking_declaration(
        self,
    ) -> None:
        # ADR-0029 §A: "Save Type" on a built-in persists overlay data (here a
        # color) but never forks the shipped name/kind/parent declaration, and
        # the type stays built-in-sourced.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character", kind="lore", parent="lore:base", color="rose"
                ),
                allow_existing=True,
            )
        )
        schema = self.service.read_metadata_schema()
        character = schema.entry_types["lore:character"]
        self.assertEqual(character.color, "rose")
        self.assertEqual(character.name, "Character")
        self.assertEqual(character.parent, "lore:base")
        overview = self.service.read_metadata_schema_overview()
        self.assertTrue(overview.entry_type_sources["lore:character"].built_in)

    def test_display_order_can_lift_own_field_above_inherited(self) -> None:
        # The #89 capability the old single-`fields` list couldn't express:
        # place an own field ahead of an inherited one.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="realm",
                entry_type=EntryTypeDefinition(
                    name="Realm", kind="lore", parent="lore:base", fields=[]
                ),
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=project_layer.id,
                field_id="p1",
                field=MetadataFieldDefinition(name="P1", type="text"),
                entry_type="lore:realm",
            )
        )
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="kingdom",
                entry_type=EntryTypeDefinition(
                    name="Kingdom", kind="lore", parent="lore:realm", fields=[]
                ),
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=project_layer.id,
                field_id="c1",
                field=MetadataFieldDefinition(name="C1", type="text"),
                entry_type="lore:kingdom",
            )
        )
        default_fields = (
            self.service.read_metadata_schema().entry_types["lore:kingdom"].fields
        )
        self.assertLess(
            default_fields.index("p1"), default_fields.index("c1")
        )  # inherited leads by default

        self.service.set_entry_type_field_order(
            SetFieldOrderRequest(
                layer_id=project_layer.id,
                entry_type_id="lore:kingdom",
                field_order=["c1", "p1"],
            )
        )
        reordered = (
            self.service.read_metadata_schema().entry_types["lore:kingdom"].fields
        )
        self.assertEqual(reordered.index("c1"), 0)
        self.assertEqual(reordered.index("p1"), 1)
        # Membership is unchanged — c1 stays kingdom's only own field.
        self.assertEqual(
            self.service.read_metadata_schema().entry_types["lore:kingdom"].own_fields,
            ["c1"],
        )

    def test_move_metadata_field_removes_original_layer_definition(self) -> None:
        layers = self.service.read_metadata_schema_layers().layers
        world_layer = next(
            layer for layer in layers if layer.folder_path == str(self.world)
        )
        project_layer = next(
            layer for layer in layers if layer.folder_path == str(self.root)
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="techlevel",
                field=MetadataFieldDefinition(name="Techlevel", type="text"),
                entry_type="manuscript:scene",
            )
        )

        schema = self.service.move_metadata_field(
            MoveMetadataFieldRequest(
                field_id="techlevel",
                target_layer_id=project_layer.id,
                entry_type="manuscript:scene",
            )
        )

        self.assertIn("techlevel", schema.entry_types["manuscript:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema.get("fields", {}))
        self.assertNotIn(
            "techlevel", world_schema["entry_types"]["manuscript:scene"]["fields"]
        )
        self.assertIn("techlevel", project_schema["fields"])
        self.assertEqual(
            project_schema["entry_types"]["manuscript:scene"]["fields"], ["techlevel"]
        )

    def test_built_in_metadata_field_cannot_be_moved(self) -> None:
        # move/rename/delete field share one source-layer resolver
        # (`_field_source_layer_path`) whose guard blocks touching a shipped
        # field; `pov` is a built-in field on manuscript:scene.
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        with self.assertRaisesRegex(ProjectServiceError, "cannot be moved"):
            self.service.move_metadata_field(
                MoveMetadataFieldRequest(
                    field_id="pov",
                    target_layer_id=project_layer.id,
                    entry_type="manuscript:scene",
                )
            )

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
                entry_type="manuscript:scene",
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
            RenameMetadataFieldRequest(
                old_field_id="techlevel",
                new_field_id="technology_level",
                entry_type="manuscript:scene",
            )
        )

        self.assertNotIn("techlevel", schema.fields)
        self.assertIn("technology_level", schema.fields)
        self.assertIn("technology_level", schema.entry_types["manuscript:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertEqual(
            world_schema["entry_types"]["manuscript:scene"]["fields"],
            ["technology_level"],
        )
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
                field=MetadataFieldDefinition(
                    name="Color", type="select", options=["Red", "Green", "Blue"]
                ),
                entry_type="manuscript:scene",
            )
        )
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer.id,
                field_id="background_color",
                field=MetadataFieldDefinition(
                    name="Background Color",
                    type="select",
                    options=["Red", "Green", "Blue"],
                ),
                entry_type="manuscript:scene",
            )
        )

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.rename_metadata_field(
                RenameMetadataFieldRequest(
                    old_field_id="background_color",
                    new_field_id="color",
                    entry_type="manuscript:scene",
                )
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
                field=MetadataFieldDefinition(
                    name="Color", type="select", options=["Red", "Green", "Blue"]
                ),
                entry_type="manuscript:scene",
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
                field=MetadataFieldDefinition(
                    name="Background Color",
                    type="select",
                    options=["red", "green", "blue"],
                ),
                entry_type="manuscript:scene",
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
                field=MetadataFieldDefinition(
                    name="Rank", type="select", options=["a", "b", "c"]
                ),
                entry_type="manuscript:scene",
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
                field=MetadataFieldDefinition(
                    name="Rank", type="select", options=["b", "a", "c"]
                ),
                entry_type="manuscript:scene",
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
                field=MetadataFieldDefinition(
                    name="Faction",
                    type="multi_select",
                    options=["red", "blue", "green"],
                ),
                entry_type="manuscript:scene",
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
                field=MetadataFieldDefinition(
                    name="Faction", type="multi_select", options=["red", "green"]
                ),
                entry_type="manuscript:scene",
            )
        )
        self.assertEqual(
            self.service.read_scene(self.scene_id).metadata, {"faction": ["red"]}
        )

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
                entry_type="manuscript:scene",
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

        schema = self.service.delete_metadata_field(
            DeleteMetadataFieldRequest(
                field_id="techlevel", entry_type="manuscript:scene"
            )
        )

        self.assertNotIn("techlevel", schema.fields)
        self.assertNotIn("techlevel", schema.entry_types["manuscript:scene"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertNotIn("techlevel", world_schema["fields"])
        self.assertNotIn(
            "techlevel", world_schema["entry_types"]["manuscript:scene"]["fields"]
        )
        deleted_scene_metadata = self.service.read_scene(self.scene_id).metadata
        self.assertEqual(deleted_scene_metadata, {})


if __name__ == "__main__":
    unittest.main()
