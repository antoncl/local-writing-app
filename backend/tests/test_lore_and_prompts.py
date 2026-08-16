from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    DeleteMetadataEntryTypeRequest,
    EntryTypeDefinition,
    MetadataFieldDefinition,
    PromptContextStrategy,
    PromptEntryTypeExtras,
    PromptInputDefinition,
    RenameMetadataFieldRequest,
    SaveLoreEntryRequest,
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

    def test_prompt_subtype_round_trips_with_inputs_and_context_strategy(self) -> None:
        layer_id = self._project_layer_id()
        extras = PromptEntryTypeExtras(
            system_prompt="You are a careful continuation engine.",
            model_class="balanced",
            provider_policy="cloud-allowed",
            inputs=[
                PromptInputDefinition(
                    name="words", type="number", default=300, label="Words"
                ),
                PromptInputDefinition(
                    name="beat", type="long_text", label="Beat instruction"
                ),
            ],
            context_strategy=PromptContextStrategy(
                target={"required": True, "kind": "manuscript"},
                scan_surface=["_text_before", "_selection"],
                output={"kind": "append_to_body"},
            ),
        )
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="continue_scene",
                entry_type=EntryTypeDefinition(
                    name="Continue Scene",
                    kind="prompt",
                    parent="prompt:base",
                    prompt=extras,
                ),
            )
        )

        stored = schema.entry_types["prompt:continue_scene"]
        assert stored.prompt is not None
        self.assertEqual(
            stored.prompt.system_prompt, "You are a careful continuation engine."
        )
        self.assertEqual(stored.prompt.model_class, "balanced")
        self.assertEqual(stored.prompt.provider_policy, "cloud-allowed")
        self.assertEqual([i.name for i in stored.prompt.inputs], ["words", "beat"])
        assert stored.prompt.context_strategy is not None
        self.assertEqual(
            stored.prompt.context_strategy.scan_surface, ["_text_before", "_selection"]
        )
        self.assertEqual(
            stored.prompt.context_strategy.target,
            {"required": True, "kind": "manuscript"},
        )

        on_disk = self.service._read_yaml(self.root / "metadata.schema.yaml")
        disk_entry = on_disk["entry_types"]["prompt:continue_scene"]
        self.assertEqual(disk_entry["kind"], "prompt")
        self.assertEqual(disk_entry["prompt"]["model_class"], "balanced")
        self.assertEqual(disk_entry["prompt"]["inputs"][0]["name"], "words")

        reread = self.service.read_metadata_schema()
        rer = reread.entry_types["prompt:continue_scene"]
        assert rer.prompt is not None
        self.assertEqual(
            rer.prompt.system_prompt, "You are a careful continuation engine."
        )
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
        disk_inputs = on_disk["entry_types"]["prompt:character_chat"]["prompt"][
            "inputs"
        ]
        disk_by_name = {i["name"]: i for i in disk_inputs}
        self.assertEqual(disk_by_name["character"]["type"], "entity_ref")
        self.assertEqual(
            disk_by_name["character"]["target"],
            {"kinds": ["lore"], "entry_types": {"lore": ["character"]}},
        )

    def test_default_schema_seeds_four_prompt_bases(self) -> None:
        """continuation/general/snippet are concrete bases with preset output
        kinds; users instantiate them directly or sub-type them to add
        personality. `revise` is abstract (ADR-0046 §5) and splits symmetrically
        into `revise:scene` (today's scene revise) + `revise:entry` (the lore
        brainstorm commit) — the dispositions differ (`revise:scene` is
        `replace_selection`; `revise:entry` is `chat_panel` + a `commit`), so
        nothing is hoisted onto the base. Inputs live on the instance (not the type)."""
        schema = self.service.read_metadata_schema()
        for type_id in ("prompt:continuation", "prompt:general", "prompt:snippet"):
            self.assertIn(type_id, schema.entry_types)
            self.assertEqual(schema.entry_types[type_id].kind, "prompt")
            self.assertEqual(schema.entry_types[type_id].parent, "prompt:base")
            self.assertFalse(schema.entry_types[type_id].abstract, msg=type_id)

        continuation_prompt = schema.entry_types["prompt:continuation"].prompt
        assert continuation_prompt is not None
        assert continuation_prompt.context_strategy is not None
        continuation_output = continuation_prompt.context_strategy.output
        assert continuation_output is not None
        self.assertEqual(continuation_output.kind, "append_to_body")
        self.assertIsNone(
            continuation_output.commit
        )  # an inline disposition carries no commit

        # `revise` is now the abstract parent of the two concrete flavours.
        revise = schema.entry_types["prompt:revise"]
        self.assertTrue(revise.abstract)
        self.assertEqual(revise.parent, "prompt:base")
        self.assertIsNone(revise.prompt)

        revise_scene = schema.entry_types["prompt:revise:scene"]
        self.assertFalse(revise_scene.abstract)
        self.assertEqual(revise_scene.parent, "prompt:revise")
        assert (
            revise_scene.prompt is not None
            and revise_scene.prompt.context_strategy is not None
        )
        revise_scene_output = revise_scene.prompt.context_strategy.output
        assert revise_scene_output is not None
        self.assertEqual(revise_scene_output.kind, "replace_selection")
        self.assertIsNone(revise_scene_output.commit)
        self.assertEqual(
            revise_scene.prompt.context_strategy.target,
            {"required": True, "kind": "manuscript"},
        )

        revise_entry = schema.entry_types["prompt:revise:entry"]
        self.assertFalse(revise_entry.abstract)
        self.assertEqual(revise_entry.parent, "prompt:revise")
        assert (
            revise_entry.prompt is not None
            and revise_entry.prompt.context_strategy is not None
        )
        revise_entry_output = revise_entry.prompt.context_strategy.output
        assert (
            revise_entry_output is not None and revise_entry_output.commit is not None
        )
        self.assertEqual(revise_entry_output.kind, "chat_panel")
        self.assertEqual(revise_entry_output.commit.review, "visual_diff")
        # The entry rides in as an `entry` input (loaded via entry(input.entry)),
        # NOT as context_strategy.target — a lore id there would drive a scene
        # resolution (read_scene) and 404. The shipped body itself lives in the
        # built-in Library now (ADR-0049 §7), so the body-wiring assertions moved
        # to test_builtin_library; here we pin the type's shape and default_inputs.
        self.assertIsNone(revise_entry.prompt.context_strategy.target)
        # Slice 4 (§6.4): the prompt has both a revise and a create mode. `entry`
        # is OPTIONAL (present ⇒ revise, absent ⇒ create) and a hidden `entry_type`
        # names the kind to draft; the shipped body branches on `input.entry`.
        inputs = {i.name: i for i in revise_entry.default_inputs}
        self.assertEqual(list(inputs), ["entry", "entry_type"])
        self.assertEqual(inputs["entry"].type, "context_pick")
        self.assertFalse(inputs["entry"].required)
        self.assertEqual(inputs["entry_type"].type, "text")
        self.assertTrue(inputs["entry_type"].hidden)

        general_prompt = schema.entry_types["prompt:general"].prompt
        assert general_prompt is not None
        assert general_prompt.context_strategy is not None
        general_output = general_prompt.context_strategy.output
        assert general_output is not None
        self.assertEqual(general_output.kind, "chat_panel")
        self.assertIsNone(general_output.commit)  # a plain chat, no commit

        self.assertIsNone(schema.entry_types["prompt:snippet"].prompt)

    def test_roleplay_declares_its_character_stamp_as_an_on_accept_capability(
        self,
    ) -> None:
        # #957 (Lever 2): roleplay is a continuation that DECLARES its accept-time
        # character-stamp as a capability (`output.on_accept`), not an
        # `entry_type == roleplay` code branch. It redeclares its full context
        # strategy (the parent-merge is shallow), so it stays append_to_body.
        schema = self.service.read_metadata_schema()
        roleplay = schema.entry_types["prompt:roleplay"]
        self.assertFalse(roleplay.abstract)
        self.assertEqual(roleplay.parent, "prompt:continuation")
        assert (
            roleplay.prompt is not None and roleplay.prompt.context_strategy is not None
        )
        roleplay_output = roleplay.prompt.context_strategy.output
        assert roleplay_output is not None and roleplay_output.on_accept is not None
        self.assertEqual(roleplay_output.kind, "append_to_body")
        self.assertEqual(roleplay_output.on_accept.mark, "character")
        self.assertEqual(roleplay_output.on_accept.from_input, "character")

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
        bob_output = bob_prompt.context_strategy.output
        assert bob_output is not None
        self.assertEqual(bob_output.kind, "chat_panel")
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
                        parent="lore:base",
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
                        parent="prompt:base",
                        prompt=PromptEntryTypeExtras(
                            inputs=[
                                PromptInputDefinition(
                                    name="tone", type="select", options=[]
                                )
                            ],
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
                        parent="prompt:base",
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
                    parent="prompt:base",
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
                        inputs=[
                            PromptInputDefinition(
                                name="words", type="number", default=200
                            )
                        ],
                    ),
                ),
            )
        )

        child = schema.entry_types["prompt:house_continue"]
        assert child.prompt is not None
        self.assertEqual(
            child.prompt.system_prompt, "House style: terse, no purple prose."
        )
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
                    parent="prompt:base",
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
                    parent="prompt:base",
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
                body='{% role "user" %}Talk about {{ input.topic }}.{% endrole %}',
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
                entry_type="manuscript:scene",
            )
        )
        scene = self.service.create_scene(CreateSceneRequest(title="Defaulted scene"))
        self.assertEqual(scene.status, "revised")
        self.assertNotIn("status", scene.metadata)


if __name__ == "__main__":
    unittest.main()
