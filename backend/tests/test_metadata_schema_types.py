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
    def test_output_kind_must_be_a_known_disposition(self) -> None:
        # ADR-0054: `context_strategy.output.kind` is a closed vocabulary,
        # validated on save. A bogus kind is a (soft) schema error.
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output_kind("not_a_kind")
        )
        self.assertTrue(any("not_a_kind" in e for e in errors), errors)

    def test_retired_entry_patch_kind_is_now_rejected(self) -> None:
        # ADR-0054 S2 retired `entry_patch` into `chat_panel` + `commit`, so the
        # old value is no longer a known disposition.
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output_kind("entry_patch")
        )
        self.assertTrue(any("entry_patch" in e for e in errors), errors)

    def test_known_output_kinds_validate(self) -> None:
        # Every disposition in the (post-S2) closed set passes.
        for kind in ("append_to_body", "replace_selection", "chat_panel"):
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output_kind(kind)
            )
            self.assertFalse(any("output kind" in e for e in errors), (kind, errors))

    def test_commit_only_rides_on_chat_panel(self) -> None:
        # ADR-0054 §2: a commit is meaningful only under `chat_panel` — append /
        # replace target the body directly, so a commit on them is a (soft) error.
        output = {"kind": "append_to_body", "commit": {"review": "visual_diff"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("only chat_panel" in e for e in errors), errors)

    def test_commit_review_must_be_a_known_mode(self) -> None:
        output = {"kind": "chat_panel", "commit": {"review": "sideways"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("commit review" in e for e in errors), errors)

    def test_chat_panel_with_a_valid_commit_validates(self) -> None:
        output = {
            "kind": "chat_panel",
            "commit": {"review": "replace", "fields": ["summary"]},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertFalse(
            any("output kind" in e or "commit" in e for e in errors), errors
        )

    def test_on_accept_only_rides_on_an_inline_disposition(self) -> None:
        # #954 (Lever 2): on_accept stamps a mark on an accepted INLINE suggestion, so
        # it is a (soft) error on chat_panel, which has no accept gesture.
        output = {
            "kind": "chat_panel",
            "on_accept": {"mark": "character", "from_input": "character"},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(any("inline disposition" in e for e in errors), errors)

    def test_on_accept_requires_a_mark_and_from_input(self) -> None:
        output = {"kind": "append_to_body", "on_accept": {"mark": "character"}}
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertTrue(
            any("on_accept" in e and "from_input" in e for e in errors), errors
        )

    def test_inline_disposition_with_a_valid_on_accept_validates(self) -> None:
        output = {
            "kind": "append_to_body",
            "on_accept": {"mark": "character", "from_input": "character"},
        }
        errors = self.service._validate_metadata_schema_definition(
            self._schema_with_output(output)
        )
        self.assertFalse(
            any("on_accept" in e or "output kind" in e for e in errors), errors
        )

    def test_unset_output_kind_is_allowed(self) -> None:
        # No output disposition (a snippet, or a prompt that produces none) is
        # legitimate — the check only fires on a non-empty unknown kind.
        for empty in (None, ""):
            errors = self.service._validate_metadata_schema_definition(
                self._schema_with_output_kind(empty)
            )
            self.assertFalse(any("output kind" in e for e in errors), (empty, errors))

    def test_saving_a_prompt_type_with_an_unknown_output_kind_is_rejected(self) -> None:
        # End-to-end: a save resolves + validates, and an unknown disposition
        # blocks it (the validator's errors are raised by the save path).
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
                                output={"kind": "not_a_kind"}
                            )
                        ),
                    ),
                    allow_existing=False,
                )
            )
        self.assertIn("not_a_kind", str(ctx.exception))

    def test_output_kind_inherited_by_a_subtype_validates(self) -> None:
        # The validator runs on the RESOLVED schema, so a subtype that inherits
        # its disposition from a base (the common shape) is validated through the
        # inherited value — a valid inherited kind must not be flagged.
        data = {
            "entry_types": {
                "prompt:base": {
                    "name": "Prompt",
                    "kind": "prompt",
                    "prompt": {"context_strategy": {"output": {"kind": "chat_panel"}}},
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
        self.assertFalse(any("output kind" in e for e in errors), errors)

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
        schema = self.service.read_metadata_schema()
        for type_id in (
            "prompt:base",
            "prompt:continuation",
            "prompt:revise",
            "prompt:revise:scene",
            "prompt:revise:entry",
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


if __name__ == "__main__":
    unittest.main()
