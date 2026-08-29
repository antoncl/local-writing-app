from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateLoreEntryRequest,
    CreatePromptEntryRequest,
    CreateSceneRequest,
    DeleteMetadataEntryTypeRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    PromptContextStrategy,
    PromptInputDefinition,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
    SavePromptEntryRequest,
    SearchRequest,
    SelectOption,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError
from app.services.project.node_index_gate import node_index_gate


class LoreAndPromptTests(MetadataValidationBase):
    def test_default_schema_includes_lore_entry_subtypes_and_reference_fields(
        self,
    ) -> None:
        schema = self.service.read_metadata_schema()

        self.assertEqual(schema.entry_types["lore:character"].kind, "lore")
        self.assertEqual(schema.entry_types["lore:location"].kind, "lore")
        self.assertTrue(schema.entry_types["lore:base"].abstract)
        self.assertEqual(schema.entry_types["lore:character"].parent, "lore:base")
        self.assertEqual(schema.entry_types["lore:note"].parent, "lore:base")
        self.assertNotIn("summary", schema.entry_types["lore:character"].fields)
        self.assertNotIn("summary", schema.entry_types["lore:note"].fields)
        self.assertNotIn("appears_in_scenes", schema.entry_types["lore:note"].fields)
        self.assertIn("aliases", schema.entry_types["lore:note"].fields)
        self.assertIn("tags", schema.entry_types["lore:note"].fields)
        self.assertEqual(
            schema.entry_types["lore:base"].own_fields,
            ["aliases", "tags", "related_entries", "color", "context_policy"],
        )
        # Character ships a reasonable out-of-the-box field set (#1316):
        # role + pronouns + home_place, plus character_cost (Phase C2
        # cross-kind cost dispatch).
        self.assertEqual(
            schema.entry_types["lore:character"].own_fields,
            ["role", "pronouns", "home_place", "character_cost"],
        )
        self.assertEqual(schema.fields["aliases"].type, "multi_select")
        self.assertEqual(schema.fields["tags"].type, "tags")
        self.assertEqual(schema.fields["related_entries"].type, "entity_ref_list")
        self.assertEqual(schema.fields["related_entries"].picker_config.kinds, ["lore"])
        self.assertEqual(schema.fields["related_entries"].picker_config.entry_types, {})
        self.assertEqual(
            schema.fields["characters"].picker_config.entry_types,
            {"lore": ["lore:character"]},
        )

    def test_default_schema_includes_research_kind_with_topic_and_note(self) -> None:
        schema = self.service.read_metadata_schema()

        # Research is the abstract parent for the research-kind tree —
        # like manuscript_structure for the manuscript tree.
        self.assertTrue(schema.entry_types["research:base"].abstract)
        self.assertEqual(schema.entry_types["research:base"].kind, "research")

        self.assertEqual(schema.entry_types["research:topic"].kind, "research")
        self.assertEqual(schema.entry_types["research:topic"].parent, "research:base")
        self.assertFalse(schema.entry_types["research:topic"].has_body)

        self.assertEqual(schema.entry_types["research:note"].kind, "research")
        self.assertEqual(schema.entry_types["research:note"].parent, "research:base")
        self.assertTrue(schema.entry_types["research:note"].has_body)
        # v1 ships notes with just tags (per decisions-research-strategy).
        # Aliases / related_entries / context_policy intentionally omitted.
        self.assertIn("tags", schema.entry_types["research:note"].fields)
        self.assertNotIn("aliases", schema.entry_types["research:note"].fields)
        self.assertNotIn("related_entries", schema.entry_types["research:note"].fields)
        self.assertNotIn("context_policy", schema.entry_types["research:note"].fields)

    def test_lore_note_is_creatable_not_deprecated(self) -> None:
        # The Note lore type was reinstated (#963) after an overeager research-era
        # deprecation. It must NOT be flagged deprecated (the create menus filter
        # that flag) and must be instantiable like any other concrete lore type.
        schema = self.service.read_metadata_schema()
        self.assertFalse(schema.entry_types["lore:note"].deprecated)
        self.assertFalse(schema.entry_types["lore:note"].abstract)
        self.assertFalse(schema.entry_types["lore:character"].deprecated)
        self.assertFalse(schema.entry_types["research:note"].deprecated)

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:note")
        )
        self.assertEqual(self.service.read_lore_entry(entry.id).entry_type, "lore:note")

    def test_metadata_rejects_fields_not_bound_to_entry_type(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )

        with self.assertRaisesRegex(
            ProjectServiceError,
            "metadata field summary is not defined for entry_type lore:character",
        ):
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
                field=MetadataFieldDefinition(
                    name="Importance", type="select", options=["Low", "High"]
                ),
                entry_type="lore:base",
            )
        )
        self.assertIn("importance", schema.entry_types["lore:character"].fields)
        self.assertIn("importance", schema.entry_types["lore:note"].fields)

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
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

    def test_custom_lore_subtype_can_be_created_and_inherits_parent_fields(
        self,
    ) -> None:
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
                    parent="lore:base",
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

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Pact", entry_type="lore:faction")
        )
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

    def test_entry_type_icon_inherits_like_color(self) -> None:
        """A type-level `icon` inherits down the parent chain (child wins),
        with `own_icon` carrying only what the type itself declared — the same
        semantics as `color` (#316)."""
        project_layer = next(
            layer
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
        # Parent declares an icon.
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="faction",
                entry_type=EntryTypeDefinition(
                    name="Faction",
                    kind="lore",
                    parent="lore:base",
                    fields=[],
                    icon="flag",
                ),
            )
        )
        # Child sets no icon → inherits the parent's.
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="lore:faction:guild",
                entry_type=EntryTypeDefinition(
                    name="Guild",
                    kind="lore",
                    parent="lore:faction",
                    fields=[],
                ),
            )
        )
        # Grandchild overrides with its own icon.
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=project_layer.id,
                entry_type_id="lore:faction:guild:secret",
                entry_type=EntryTypeDefinition(
                    name="Secret Guild",
                    kind="lore",
                    parent="lore:faction:guild",
                    fields=[],
                    icon="lock",
                ),
            )
        )

        parent = schema.entry_types["lore:faction"]
        self.assertEqual(parent.icon, "flag")
        self.assertEqual(parent.own_icon, "flag")

        child = schema.entry_types["lore:faction:guild"]
        self.assertEqual(child.icon, "flag")  # inherited
        self.assertIsNone(child.own_icon)  # not set on this type

        grandchild = schema.entry_types["lore:faction:guild:secret"]
        self.assertEqual(grandchild.icon, "lock")  # own override wins
        self.assertEqual(grandchild.own_icon, "lock")

        # `own_icon` is computed, never persisted to the layer file.
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("own_icon", project_schema["entry_types"]["lore:faction"])
        self.assertEqual(project_schema["entry_types"]["lore:faction"]["icon"], "flag")

    def test_abstract_entry_type_cannot_be_used_by_documents(self) -> None:
        with self.assertRaisesRegex(
            ProjectServiceError, "abstract entry_type lore:base"
        ):
            self.service.create_lore_entry(
                CreateLoreEntryRequest(title="Abstract", entry_type="lore:base")
            )

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
                entry_type=EntryTypeDefinition(
                    name="Faction", kind="lore", parent="lore:base", fields=[]
                ),
            )
        )
        self.service.create_lore_entry(
            CreateLoreEntryRequest(title="The Pact", entry_type="lore:faction")
        )

        with self.assertRaisesRegex(ProjectServiceError, "used by project documents"):
            self.service.delete_metadata_entry_type(
                DeleteMetadataEntryTypeRequest(entry_type_id="lore:faction")
            )

    def test_lore_entry_round_trips_metadata(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        place = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Taverna", entry_type="lore:location")
        )

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
        front_matter, _ = self.service._read_markdown_with_front_matter(
            self.service._path_for_node_id(entry.id, "lore"), strict=True
        )
        self.assertNotIn("status", front_matter)

    def test_lore_entry_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Robert Smith", entry_type="lore:character")
        )
        original_path = self.service._path_for_node_id(entry.id, "lore")
        renamed_path = self.root / "lore" / "robert-smith-renamed.md"
        original_path.rename(renamed_path)
        node_index_gate.invalidate()  # a raw rename is external; model the reopen (#392)

        loaded = self.service.read_lore_entry(entry.id)
        listed = self.service.list_lore_entries().entries

        self.assertEqual(loaded.id, entry.id)
        self.assertEqual(loaded.title, "Robert Smith")
        self.assertEqual([item.id for item in listed], [entry.id])

    def test_scene_can_be_read_after_file_rename_by_front_matter_id(self) -> None:
        scene = self.service.read_scene(self.scene_id)
        original_path = self.service._path_for_node_id(scene.id, "manuscript")
        renamed_path = self.root / "scenes" / "opening-scene-renamed.md"
        original_path.rename(renamed_path)
        node_index_gate.invalidate()  # a raw rename is external; model the reopen (#392)

        loaded = self.service.read_scene(scene.id)
        validation = self.service.validate_project()

        self.assertEqual(loaded.id, scene.id)
        self.assertFalse(
            any(
                "Structure references missing scene" in error
                for error in validation.errors
            ),
            validation.errors,
        )

    def test_validation_reports_missing_and_duplicate_front_matter_ids(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        path = self.service._path_for_node_id(entry.id, "lore")
        original_text = path.read_text(encoding="utf-8")
        path.write_text(
            original_text.replace(f"id: {entry.id}\n", ""), encoding="utf-8"
        )
        node_index_gate.invalidate()  # a raw file edit is external; model the reopen (#392)

        validation = self.service.validate_project()

        self.assertTrue(
            any(
                "missing front matter id" in warning for warning in validation.warnings
            ),
            validation.warnings,
        )

        path.write_text(original_text, encoding="utf-8")

        duplicate = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Other Seren", entry_type="lore:character")
        )
        duplicate_path = self.service._path_for_node_id(duplicate.id, "lore")
        duplicate_text = duplicate_path.read_text(encoding="utf-8")
        duplicate_path.write_text(
            duplicate_text.replace(f"id: {duplicate.id}\n", f"id: {entry.id}\n"),
            encoding="utf-8",
        )
        node_index_gate.invalidate()  # a raw file edit is external; model the reopen (#392)

        validation = self.service.validate_project()

        self.assertTrue(
            any("Duplicate front matter id" in error for error in validation.errors),
            validation.errors,
        )

    def test_reference_fields_validate_missing_and_wrong_targets(self) -> None:
        character = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
        other_character = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Aren", entry_type="lore:character")
        )

        with self.assertRaisesRegex(
            ProjectServiceError, "references unknown node missing_place"
        ):
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

        with self.assertRaisesRegex(
            ProjectServiceError, "expected entry_type in \\['lore:location'\\]"
        ):
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
        with self.assertRaisesRegex(
            ProjectServiceError, "non-lore entry_type manuscript:scene"
        ):
            self.service.create_lore_entry(
                CreateLoreEntryRequest(title="Wrong", entry_type="manuscript:scene")
            )

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
                field=MetadataFieldDefinition(
                    name="Faction", type="select", options=["A", "B"]
                ),
                entry_type="lore:character",
            )
        )
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
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
            RenameMetadataFieldRequest(
                old_field_id="faction",
                new_field_id="allegiance",
                entry_type="lore:character",
            )
        )
        renamed = self.service.read_lore_entry(entry.id)

        self.assertEqual(renamed.metadata, {"allegiance": "A"})

    def test_search_reports_lore_hit_kind(self) -> None:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )
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
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Seren", entry_type="lore:character")
        )

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
        self.assertEqual(
            [tag.name for tag in self.service.read_known_tags().tags], ["ALLY", "Crew"]
        )
        front_matter, _ = self.service._read_markdown_with_front_matter(
            self.service._path_for_node_id(entry.id, "lore"), strict=True
        )
        self.assertEqual(front_matter["metadata"]["tags"], ["Crew", "ALLY"])

    def test_aliases_do_not_populate_known_tags(self) -> None:
        self.service._write_yaml(self.root / "tags.yaml", {"tags": ["Crew"]})
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Robert Smith", entry_type="lore:character")
        )

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
        self.assertEqual(
            [tag.name for tag in self.service.read_known_tags().tags], ["Crew"]
        )

    def test_prompt_inputs_round_trip_entity_ref_with_target(self) -> None:
        # Per #40 / decisions-inputs-fields-uniformity: entity_ref and
        # entity_ref_list inputs carry their picker constraint as a
        # NodePickerConfig under `target` — same wire shape as context_pick
        # inputs and entity_ref metadata fields' `picker_config`. The legacy
        # `{kind, entry_type}` shape was dropped pre-1.0 per the no-migrations
        # policy. Inputs are instance-only (ADR-0065 Amendment 2), so this
        # round-trips through a prompt entry's own `inputs`, not the type.
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Character chat", entry_type="prompt:general")
        )
        saved = self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title="Character chat",
                body="",
                base_revision=entry.revision,
                entry_type="prompt:general",
                metadata={},
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
            ),
        )
        by_name = {i.name: i for i in saved.inputs}

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

        # Reload from disk to confirm the round-trip survives the file hop.
        reread = self.service.read_prompt_entry(entry.id)
        reread_by_name = {i.name: i for i in reread.inputs}
        self.assertEqual(reread_by_name["character"].type, "entity_ref")
        self.assertEqual(
            reread_by_name["character"].target,
            {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        )

    def test_default_schema_seeds_the_collapsed_prompt_bases(self) -> None:
        """ADR-0065 S3 collapsed continuation/roleplay/revise/revise:scene/
        revise:entry/revise:scene_summary into a single `prompt:general` type —
        only `base` (abstract), `general`, and `snippet` remain. The behavior
        contract (handler, commit, on_accept) that used to live on those
        sub-types now lives per-INSTANCE, on `context_strategy` (proven below by
        round-tripping the same shapes through create/save on `general`
        instances, exactly as the shipped built-ins carry them —
        test_builtin_library / test_offer_on pin the shipped shapes)."""
        schema = self.service.read_metadata_schema()
        for type_id in ("prompt:general", "prompt:snippet"):
            self.assertIn(type_id, schema.entry_types)
            self.assertEqual(schema.entry_types[type_id].kind, "prompt")
            self.assertEqual(schema.entry_types[type_id].parent, "prompt:base")
            self.assertFalse(schema.entry_types[type_id].abstract, msg=type_id)
        self.assertTrue(schema.entry_types["prompt:base"].abstract)

        # The `inline` handler (the old `continuation` disposition), reused on a
        # `general` instance.
        continuation = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Continuation", entry_type="prompt:general")
        )
        continuation = self.service.save_prompt_entry(
            continuation.id,
            SavePromptEntryRequest(
                title="Continuation",
                body="",
                base_revision=continuation.revision,
                entry_type="prompt:general",
                metadata={},
                context_strategy=PromptContextStrategy.model_validate(
                    {"output": {"handler": "inline"}}
                ),
            ),
        )
        assert continuation.context_strategy is not None
        continuation_output = continuation.context_strategy.output
        assert continuation_output is not None
        self.assertEqual(continuation_output.handler, "inline")
        self.assertIsNone(continuation_output.commit)  # the inline handler carries no commit

        # The `inline` + `selection` disposition (the old `revise:scene`).
        revise_scene = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Revise scene", entry_type="prompt:general")
        )
        revise_scene = self.service.save_prompt_entry(
            revise_scene.id,
            SavePromptEntryRequest(
                title="Revise scene",
                body="",
                base_revision=revise_scene.revision,
                entry_type="prompt:general",
                metadata={},
                context_strategy=PromptContextStrategy.model_validate(
                    {"output": {"handler": "inline", "destination": "selection"}}
                ),
            ),
        )
        assert revise_scene.context_strategy is not None
        revise_scene_output = revise_scene.context_strategy.output
        assert revise_scene_output is not None
        self.assertEqual(revise_scene_output.handler, "inline")
        self.assertEqual(revise_scene_output.destination, "selection")
        self.assertIsNone(revise_scene_output.commit)

        # The `extract_to_node` + `commit` disposition (the old `revise:entry`),
        # with the `entry`/`entry_type` inputs — moved from the deleted type's
        # `default_inputs` onto the instance's own `inputs` (ADR-0049 §7 shape,
        # pinned on the shipped node in test_prompt_metadata_wrapper).
        revise_entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Revise entry", entry_type="prompt:general")
        )
        revise_entry = self.service.save_prompt_entry(
            revise_entry.id,
            SavePromptEntryRequest(
                title="Revise entry",
                body="",
                base_revision=revise_entry.revision,
                entry_type="prompt:general",
                metadata={},
                inputs=[
                    PromptInputDefinition(
                        name="entry", type="context_pick", label="Entry", required=False
                    ),
                    PromptInputDefinition(
                        name="entry_type", type="text", label="Entry type", required=False, hidden=True
                    ),
                ],
                context_strategy=PromptContextStrategy.model_validate(
                    {"output": {"handler": "extract_to_node", "commit": {"review": "visual_diff"}}}
                ),
            ),
        )
        assert revise_entry.context_strategy is not None
        revise_entry_output = revise_entry.context_strategy.output
        assert revise_entry_output is not None and revise_entry_output.commit is not None
        self.assertEqual(revise_entry_output.handler, "extract_to_node")
        self.assertEqual(revise_entry_output.commit.review, "visual_diff")
        # The entry rides in as an `entry` input (loaded via entry(input.entry)) —
        # `context_strategy` carries no target field to drive scene resolution.
        inputs = {i.name: i for i in revise_entry.inputs}
        self.assertEqual(list(inputs), ["entry", "entry_type"])
        self.assertEqual(inputs["entry"].type, "context_pick")
        self.assertFalse(inputs["entry"].required)
        self.assertEqual(inputs["entry_type"].type, "text")
        self.assertTrue(inputs["entry_type"].hidden)

    def test_roleplay_declares_its_character_stamp_as_an_on_accept_capability(
        self,
    ) -> None:
        # #957 (Lever 2): roleplay DECLARES its accept-time character-stamp as a
        # capability (`output.on_accept`), not an `entry_type == roleplay` code
        # branch — ADR-0065 S3 moved that declaration onto the shipped node's own
        # instance `context_strategy`, since roleplay is now a `prompt:general`
        # instance (not its own sub-type).
        roleplay = self.service.read_prompt_entry("builtin-roleplay")
        self.assertEqual(roleplay.entry_type, "prompt:general")
        assert roleplay.context_strategy is not None
        roleplay_output = roleplay.context_strategy.output
        assert roleplay_output is not None and roleplay_output.on_accept is not None
        self.assertEqual(roleplay_output.handler, "inline")
        self.assertEqual(roleplay_output.on_accept.mark, "character")
        self.assertEqual(roleplay_output.on_accept.from_input, "character")

    def test_output_headless_round_trips_and_stays_off_disk_when_unset(self) -> None:
        # ADR-0062 D3: `headless` is a sibling axis of `handler`, modelled
        # three-valued (`bool | None`) so it never litters front matter when off —
        # `_prompt_front_matter_extra` dumps with `exclude_none`, so only
        # `headless: true` ever lands on disk.
        headless_entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Headless brainstorm", entry_type="prompt:general")
        )
        saved = self.service.save_prompt_entry(
            headless_entry.id,
            SavePromptEntryRequest(
                title="Headless brainstorm",
                body="",
                base_revision=headless_entry.revision,
                entry_type="prompt:general",
                metadata={},
                context_strategy=PromptContextStrategy.model_validate(
                    {"output": {"handler": "extract_to_node", "headless": True, "commit": {"review": "replace"}}}
                ),
            ),
        )
        assert saved.context_strategy is not None
        assert saved.context_strategy.output is not None
        self.assertTrue(saved.context_strategy.output.headless)
        reread = self.service.read_prompt_entry(headless_entry.id)
        assert reread.context_strategy is not None and reread.context_strategy.output is not None
        self.assertTrue(reread.context_strategy.output.headless)
        path = self.service._build_node_index().by_id[headless_entry.id].path
        self.assertIn("headless: true", path.read_text(encoding="utf-8"))

        # Unset (None) never lands on disk at all — an inline prompt with no
        # headless key given stays absent, not `headless: false`.
        plain_entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Plain inline", entry_type="prompt:general")
        )
        self.service.save_prompt_entry(
            plain_entry.id,
            SavePromptEntryRequest(
                title="Plain inline",
                body="",
                base_revision=plain_entry.revision,
                entry_type="prompt:general",
                metadata={},
                context_strategy=PromptContextStrategy.model_validate({"output": {"handler": "inline"}}),
            ),
        )
        plain_path = self.service._build_node_index().by_id[plain_entry.id].path
        self.assertNotIn("headless", plain_path.read_text(encoding="utf-8"))

    def _save_prompt(
        self,
        title: str,
        body: str,
        entry_type: str,
        inputs: list[PromptInputDefinition] | None = None,
    ) -> str:
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title=title, entry_type=entry_type)
        )
        self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title=title,
                body=body,
                base_revision=entry.revision,
                entry_type=entry_type,
                metadata={},
                inputs=inputs or [],
            ),
        )
        return entry.id

    def test_list_prompt_entries_populates_effective_inputs_from_includes(self) -> None:
        # ADR-0061 S1 end-to-end through the roster: a prompt that {% include %}s a
        # snippet gains the snippet's inputs in `effective_inputs` while its own
        # `inputs` stay as authored — the invoke surfaces read the former.
        self._save_prompt(
            "Villain Voice",
            "{{ input.menace }}",
            "prompt:snippet",
            inputs=[PromptInputDefinition(name="menace", type="select")],
        )
        including = self._save_prompt(
            "Revise Scene",
            '{% include "Villain Voice" %}\n{{ input.subject }}',
            "prompt:general",
            inputs=[PromptInputDefinition(name="subject", type="text")],
        )

        by_id = {e.id: e for e in self.service.list_prompt_entries().entries}
        entry = by_id[including]
        # Own inputs untouched; effective adds the snippet's, own-first.
        self.assertEqual([i.name for i in entry.inputs], ["subject"])
        self.assertEqual([i.name for i in entry.effective_inputs], ["subject", "menace"])
        self.assertEqual(
            {i.name: i.type for i in entry.effective_inputs},
            {"subject": "text", "menace": "select"},
        )

    def test_list_prompt_entries_effective_equals_own_without_includes(self) -> None:
        # A prompt with no snippet includes: effective_inputs mirrors own inputs
        # exactly, so every surface reading the effective set is unchanged.
        entry_id = self._save_prompt(
            "Plain",
            "{{ input.subject }}",
            "prompt:general",
            inputs=[PromptInputDefinition(name="subject", type="text")],
        )
        by_id = {e.id: e for e in self.service.list_prompt_entries().entries}
        entry = by_id[entry_id]
        self.assertEqual(
            [i.name for i in entry.effective_inputs], [i.name for i in entry.inputs]
        )

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
        self.assertEqual(
            schema.entry_types["prompt:house_voice"].parent, "prompt:snippet"
        )
        self.assertEqual(schema.entry_types["prompt:snippet"].kind, "prompt")
        self.assertEqual(schema.entry_types["prompt:snippet"].parent, "prompt:base")

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
                entry_type=EntryTypeDefinition.model_validate(
                    {
                        "name": "Brainstorm",
                        "kind": "prompt",
                        "parent": "prompt:general",
                        "abstract": False,
                        "fields": [],
                    }
                ),
            )
        )
        created = self.service.create_prompt_entry(
            CreatePromptEntryRequest(
                title="Brainstorm", entry_type="prompt:brainstorm"
            ),
        )
        saved = self.service.save_prompt_entry(
            created.id,
            SavePromptEntryRequest(
                title="Brainstorm",
                body='{% role "user" %}Talk about {{ inputs.topic }}.{% endrole %}',
                base_revision=created.revision,
                entry_type=created.entry_type,
                metadata={},
                inputs=[
                    PromptInputDefinition(
                        name="topic", type="text", label="Topic", required=True
                    ),
                    PromptInputDefinition(
                        name="depth",
                        type="select",
                        label="Depth",
                        options=["quick", "thorough"],
                        default="quick",
                    ),
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
        self.assertEqual(
            [opt.value for opt in reread.inputs[1].options], ["quick", "thorough"]
        )
        self.assertEqual(reread.inputs[1].default, "quick")

        # And the list endpoint should surface inputs too (used by the chat
        # composer when picking a prompt).
        listing = self.service.list_prompt_entries()
        match = next(e for e in listing.entries if e.id == created.id)
        self.assertEqual([i.name for i in match.inputs], ["topic", "depth"])

    def test_front_matter_body_round_trip_does_not_accumulate_leading_newlines(
        self,
    ) -> None:
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
                entry_type="lore:note",
                metadata={},
                body=self.service._read_markdown_with_front_matter(path)[1]
                if path.exists()
                else "hello",
            )
            front, body = self.service._read_markdown_with_front_matter(path)
            self.assertFalse(
                body.startswith("\n"),
                f"body should not gain leading newlines, got {body!r}",
            )
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
                field=MetadataFieldDefinition(
                    name="Active", type="boolean", default=True
                ),
                entry_type="lore:character",
            )
        )

        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title="Defaulted", entry_type="lore:character")
        )
        # A `select` default is NOT stamped into the file (#1421): it's the
        # evaluation-time terminal fallback, so front matter stays sparse and an
        # absent select resolves to its default at read. Non-select defaults still
        # seed to disk as before (#38).
        self.assertNotIn("mood", entry.metadata)
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
                entry_type="manuscript:scene",
            )
        )
        scene = self.service.create_scene(CreateSceneRequest(title="Defaulted scene"))
        self.assertEqual(scene.status, "revised")
        self.assertNotIn("status", scene.metadata)


if __name__ == "__main__":
    unittest.main()
