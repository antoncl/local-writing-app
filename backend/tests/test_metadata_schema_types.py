from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import (
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataSchema,
    PromptContextStrategy,
    PromptEntryTypeExtras,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError


class MetadataSchemaTypeTests(MetadataValidationBase):
    def test_output_handler_must_be_a_known_key(self) -> None:
        # ADR-0065: `context_strategy.output.handler` is a closed vocabulary,
        # validated on save. A bogus handler is a (soft) schema error.
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output_handler("not_a_handler")
        )
        self.assertTrue(any("not_a_handler" in e for e in errors), errors)

    def test_retired_disposition_kinds_are_now_rejected(self) -> None:
        # ADR-0065 retired the `output.kind` disposition enum for handler keys, so
        # the old disposition values (and ADR-0054's earlier `entry_patch`) are no
        # longer known handlers.
        for retired in ("append_to_body", "replace_selection", "chat_panel", "entry_patch"):
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output_handler(retired)
            )
            self.assertTrue(any(retired in e for e in errors), (retired, errors))

    def test_known_output_handlers_validate(self) -> None:
        # Every handler in the closed set passes.
        for handler in ("inline", "extract_to_node"):
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output_handler(handler)
            )
            self.assertFalse(any("output handler" in e for e in errors), (handler, errors))

    def test_destination_must_be_a_known_inline_destination(self) -> None:
        # ADR-0065: `destination` (the inline cursor-vs-selection sub-choice) is a
        # closed vocabulary.
        output = {"handler": "inline", "destination": "sideways"}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("output destination" in e for e in errors), errors)

    def test_destination_only_rides_on_the_inline_handler(self) -> None:
        # A destination is meaningless without the inline handler that streams to it.
        output = {"handler": "extract_to_node", "destination": "selection"}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("only the inline handler streams to a destination" in e for e in errors), errors
        )

    def test_inline_with_a_valid_destination_validates(self) -> None:
        for destination in ("cursor", "selection"):
            output = {"handler": "inline", "destination": destination}
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output(output)
            )
            self.assertFalse(any("destination" in e for e in errors), (destination, errors))

    def test_commit_only_rides_on_extract_to_node(self) -> None:
        # ADR-0054 §2 / ADR-0065: a commit is meaningful only under `extract_to_node` —
        # the inline handler streams to the prose directly, so a commit on it is a
        # (soft) error.
        output = {"handler": "inline", "commit": {"review": "visual_diff"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("only the extract_to_node handler can carry a commit" in e for e in errors), errors
        )

    def test_commit_review_must_be_a_known_mode(self) -> None:
        output = {"handler": "extract_to_node", "commit": {"review": "sideways"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("commit review" in e for e in errors), errors)

    def test_extract_to_node_with_a_valid_commit_validates(self) -> None:
        output = {
            "handler": "extract_to_node",
            "commit": {"review": "replace", "fields": ["summary"]},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertFalse(
            any("output handler" in e or "commit" in e for e in errors), errors
        )

    def test_commit_target_must_be_a_defined_entry_type(self) -> None:
        # ADR-0063 S1: commit.target names the entry_type the commit CREATES. A
        # well-formed but undefined target is a (soft) error — resolved against the
        # schema's known ids.
        output = {"handler": "extract_to_node", "commit": {"review": "visual_diff", "target": "lore:ghost"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("commit target" in e and "not a defined entry type" in e for e in errors), errors
        )

    def test_malformed_commit_target_is_flagged_as_a_bad_id(self) -> None:
        # A target that isn't a `kind:key` FQN is a typo, caught by shape alone.
        output = {"handler": "extract_to_node", "commit": {"review": "visual_diff", "target": "Not A Type"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("commit target" in e and "not a valid entry-type id" in e for e in errors), errors
        )

    def test_commit_target_to_a_defined_type_validates(self) -> None:
        # The declared target names a type that exists in the schema → no target
        # error. S1 validates existence, not kind-appropriateness.
        output = {"handler": "extract_to_node", "commit": {"review": "visual_diff", "target": "prompt:custom"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertFalse(any("commit target" in e for e in errors), errors)

    def test_commit_target_without_known_types_checks_shape_only(self) -> None:
        # The `known_entry_types=None` default (a caller with no schema to resolve
        # against) validates target SHAPE only — a well-formed but undefined target
        # is not flagged (existence is a lint the caller opts into), a malformed one
        # still is.
        from app.models.schema import PromptOutput
        from app.services.project.schema_validation import validate_prompt_output

        well_formed = PromptOutput.model_validate(
            {"handler": "extract_to_node", "commit": {"review": "visual_diff", "target": "lore:ghost"}}
        )
        self.assertEqual(validate_prompt_output("prompt:x", well_formed), [])
        malformed = PromptOutput.model_validate(
            {"handler": "extract_to_node", "commit": {"review": "visual_diff", "target": "Not A Type"}}
        )
        self.assertTrue(
            any("not a valid entry-type id" in e for e in validate_prompt_output("prompt:x", malformed)),
        )

    def test_on_accept_only_rides_on_the_inline_handler(self) -> None:
        # #954 (Lever 2): on_accept stamps a mark on an accepted INLINE suggestion, so
        # it is a (soft) error on extract_to_node, which has no accept gesture.
        output = {
            "handler": "extract_to_node",
            "on_accept": {"mark": "character", "from_input": "character"},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("only the inline handler stamps a mark on accept" in e for e in errors), errors)

    def test_on_accept_requires_a_mark_and_from_input(self) -> None:
        output = {"handler": "inline", "on_accept": {"mark": "character"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("on_accept" in e and "from_input" in e for e in errors), errors
        )

    def test_inline_handler_with_a_valid_on_accept_validates(self) -> None:
        output = {
            "handler": "inline",
            "on_accept": {"mark": "character", "from_input": "character"},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertFalse(
            any("on_accept" in e or "output handler" in e for e in errors), errors
        )

    def test_unset_output_handler_is_allowed(self) -> None:
        # No output handler (a `general` prompt whose response stays in the chat, or a
        # snippet) is legitimate — the check only fires on a non-empty unknown handler.
        for empty in (None, ""):
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output_handler(empty)
            )
            self.assertFalse(any("output handler" in e for e in errors), (empty, errors))

    def test_saving_a_prompt_type_with_an_unknown_output_handler_is_rejected(self) -> None:
        # End-to-end: a save resolves + validates, and an unknown handler blocks it
        # (the validator's errors are raised by the save path).
        layer_id = self.service._metadata_schema_layer_id(self.root)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="prompt:custom",
                    entry_type=EntryTypeDefinition(
                        name="Custom",
                        kind="prompt",
                        parent="prompt:base",
                        prompt=PromptEntryTypeExtras(
                            context_strategy=PromptContextStrategy(
                                output={"handler": "not_a_handler"}
                            )
                        ),
                    ),
                    allow_existing=False,
                )
            )
        self.assertIn("not_a_handler", str(ctx.exception))

    def test_output_handler_inherited_by_a_subtype_validates(self) -> None:
        # The validator runs on the RESOLVED schema, so a subtype that inherits
        # its handler from a base (the common shape) is validated through the
        # inherited value — a valid inherited handler must not be flagged.
        data = {
            "entry_types": {
                "prompt:base": {
                    "name": "Prompt",
                    "kind": "prompt",
                    "prompt": {"context_strategy": {"output": {"handler": "inline"}}},
                },
                "prompt:child": {
                    "name": "Child",
                    "kind": "prompt",
                    "parent": "prompt:base",
                },
            },
            "fields": {},
        }
        resolved = MetadataSchema.model_validate(
            self.service._resolve_metadata_schema_inheritance(data)
        )
        errors = self.service._validate_metadata_schema_definition(resolved)
        self.assertFalse(any("output handler" in e for e in errors), errors)

    def test_default_schema_seeds_act_and_chapter(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("manuscript:act", schema.entry_types)
        self.assertIn("manuscript:chapter", schema.entry_types)
        self.assertEqual(schema.entry_types["manuscript:act"].kind, "manuscript")
        self.assertEqual(schema.entry_types["manuscript:chapter"].kind, "manuscript")
        self.assertFalse(schema.entry_types["manuscript:act"].abstract)
        self.assertFalse(schema.entry_types["manuscript:chapter"].abstract)

    def test_manuscript_structure_is_shared_abstract_parent(self) -> None:
        schema = self.service.read_metadata_schema()
        parent = schema.entry_types.get("manuscript:base")
        self.assertIsNotNone(parent)
        assert parent is not None
        self.assertTrue(parent.abstract)
        self.assertEqual(parent.kind, "manuscript")
        for type_id in ["manuscript:act", "manuscript:chapter", "manuscript:scene"]:
            self.assertEqual(schema.entry_types[type_id].parent, "manuscript:base")
            self.assertIn("summary", schema.entry_types[type_id].fields)

    def test_same_local_key_under_two_kinds_coexists(self) -> None:
        # The point of FQN identity (#77): a bare local key may be reused
        # across kinds. Define `widget` under both lore and mutation_set; both
        # survive as distinct FQN-keyed types instead of clobbering.
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        entry_types = data.setdefault("entry_types", {})
        entry_types["lore:widget"] = {
            "name": "Widget",
            "kind": "lore",
            "parent": "lore:base",
            "fields": [],
        }
        entry_types["mutation_set:widget"] = {
            "name": "Widget Set",
            "kind": "mutation_set",
            "fields": [],
        }
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
                entry_type=EntryTypeDefinition(
                    name="Faction", kind="lore", parent="lore:base"
                ),
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
                    entry_type_id="manuscript:faction",
                    entry_type=EntryTypeDefinition(
                        name="Faction", kind="lore", parent="lore:base"
                    ),
                    allow_existing=False,
                )
            )
        self.assertIn("must match", str(ctx.exception))

    def test_upsert_entry_type_accepts_nested_fqn(self) -> None:
        # #600: the key may nest (`kind:seg:seg…`). The extra colon is a pure
        # naming separator with no tie to the parent chain — so a nested id is
        # legal even when its parent is not the id with the last segment removed.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:character:villain",
                entry_type=EntryTypeDefinition(
                    name="Villain", kind="lore", parent="lore:base"
                ),
                allow_existing=False,
            )
        )
        self.assertIn("lore:character:villain", schema.entry_types)
        self.assertEqual(schema.entry_types["lore:character:villain"].kind, "lore")
        self.assertEqual(
            schema.entry_types["lore:character:villain"].parent, "lore:base"
        )

    def test_upsert_entry_type_rejects_nested_fqn_with_wrong_kind(self) -> None:
        # The kind is the FIRST segment, and it must still match the declared
        # kind — a nested id does not weaken the cross-kind guard.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="prompt:revise:scene",
                    entry_type=EntryTypeDefinition(
                        name="Revise Scene", kind="lore", parent="lore:base"
                    ),
                    allow_existing=False,
                )
            )
        self.assertIn("must match", str(ctx.exception))

    def test_backstop_validator_handles_nested_fqn(self) -> None:
        # #600: the load-path backstop (`_validate_metadata_schema_definition`)
        # is what validates seed data and hand-edited layer schemas — the path
        # slice-2's nested seed types rely on. Assert it DIRECTLY (the upsert API
        # only exercises it transitively): a well-formed nested key is clean, a
        # malformed one is flagged, and a nested key whose first segment != kind
        # is flagged.
        clean = MetadataSchema(
            entry_types={
                "lore:base": EntryTypeDefinition(
                    name="Base", kind="lore", abstract=True
                ),
                "lore:character:villain": EntryTypeDefinition(
                    name="Villain", kind="lore", parent="lore:base"
                ),
            }
        )
        self.assertEqual(self.service._validate_metadata_schema_definition(clean), [])

        malformed = MetadataSchema(
            entry_types={"lore:bad:": EntryTypeDefinition(name="Bad", kind="lore")},
        )
        self.assertTrue(
            any(
                "must be kind-qualified" in e
                for e in self.service._validate_metadata_schema_definition(malformed)
            )
        )

        wrong_kind = MetadataSchema(
            entry_types={
                "prompt:revise:scene": EntryTypeDefinition(
                    name="Revise Scene", kind="lore"
                )
            },
        )
        self.assertTrue(
            any(
                "declares kind" in e
                for e in self.service._validate_metadata_schema_definition(wrong_kind)
            )
        )

    def test_builtin_entry_type_keeps_built_in_source_after_field_add(self) -> None:
        custom_field = MetadataFieldDefinition(name="Weather", type="text", options=[])
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=self.service._metadata_schema_layer_id(self.root),
                field_id="weather",
                field=custom_field,
                entry_type="manuscript:scene",
                allow_existing=False,
            )
        )

        overview = self.service.read_metadata_schema_overview()

        self.assertTrue(overview.entry_type_sources["manuscript:scene"].built_in)
        self.assertTrue(overview.entry_type_sources["manuscript:chapter"].built_in)
        self.assertTrue(overview.entry_type_sources["manuscript:act"].built_in)
        self.assertFalse(overview.field_sources["weather"].built_in)

    def test_summary_lives_on_parent_not_in_scene_own_fields(self) -> None:
        schema = self.service.read_metadata_schema()
        scene_definition = schema.entry_types["manuscript:scene"]
        self.assertNotIn("summary", scene_definition.own_fields)
        self.assertIn("summary", scene_definition.fields)
        self.assertIn("status", scene_definition.own_fields)

    def test_scene_entry_type_defaults_to_wysiwyg_markdown(self) -> None:
        schema = self.service.read_metadata_schema()
        scene = schema.entry_types["manuscript:scene"]
        self.assertEqual(scene.body_editor, "wysiwyg")
        self.assertEqual(scene.body_language, "markdown")

    def test_prompt_subtypes_inherit_code_and_jinja2(self) -> None:
        # ADR-0065 S3 collapsed the concrete sub-types (continuation/roleplay/
        # revise/revise:scene/revise:entry/revise:scene_summary) into instance
        # `context_strategy` — only these three remain.
        schema = self.service.read_metadata_schema()
        for type_id in (
            "prompt:base",
            "prompt:general",
            "prompt:snippet",
        ):
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
                        "parent": "lore:base",
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

    def test_research_topic_opens_in_tree_container(self) -> None:
        # research:topic is a tree container, not a NodeEditor target (#1199).
        schema = self.service.read_metadata_schema()
        topic = schema.entry_types["research:topic"]
        self.assertEqual(topic.opens_in, "tree_container")

    def test_concrete_type_inherits_default_opens_in_editor(self) -> None:
        # A concrete type that doesn't override opens_in inherits "editor"
        # from its base (mirrors has_body/body_shape inheritance).
        schema = self.service.read_metadata_schema()
        character = schema.entry_types["lore:character"]
        self.assertEqual(character.opens_in, "editor")

    def test_layer_can_override_opens_in(self) -> None:
        # A child type overriding a base's opens_in wins over the inherited
        # value.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:research_note": {
                        "name": "Research Note",
                        "kind": "lore",
                        "parent": "lore:base",
                        "fields": [],
                        "opens_in": "dialog",
                    }
                },
            },
        )
        schema = self.service.read_metadata_schema()
        note = schema.entry_types["lore:research_note"]
        self.assertEqual(note.opens_in, "dialog")


if __name__ == "__main__":
    unittest.main()
