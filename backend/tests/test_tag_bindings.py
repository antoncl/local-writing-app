"""ADR-0082 slice 2 part A — `create_missing`, the built-in tag bindings, and
the assistant field rename (#1783 part 1).

Covers: the default schema's `tags`/`assistant_tags` fields are
`entity_ref_list` bound to a tag vocabulary with `create_missing`;
`assistant:assistant` lists `assistant_tags`, not `tags`; `_field_shape_errors`
accepts `create_missing` with exactly one concrete entry type and rejects it
otherwise (two entry types, an abstract type, two kinds); saving an assistant
or a prompt with `assistant_tags: [tag_id]` succeeds; the built-in assistant
view's TAG predicate is covered in test_views.py (golden fixture comparison).
The legacy `assistant-tags.yaml` registry itself is retired (ADR-0082 slice
2b) — its last reader (`TagManagerDialog`'s assistant half) went with it.

NOT covered here (part B / later slices, ADR-0082 §2 intent): `tagged:` by id,
the parity corpus, the project tag registry.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateAssistantEntryRequest,
    CreatePromptEntryRequest,
    CreateTagEntryRequest,
    NodePickerConfig,
    SaveAssistantEntryRequest,
    SavePromptEntryRequest,
)


class FromMembershipRoundTripTests(unittest.TestCase):
    """P7 (round 2 review): `create_missing` is a mechanic like `multiple` /
    `allow_target_marking` — `from_membership` must forward it, or any caller
    that rebuilds a config through the legacy (kinds, entry_types) constructor
    silently drops it."""

    def test_create_missing_forwards_through_from_membership(self) -> None:
        cfg = NodePickerConfig.from_membership(
            kinds=["tag"], entry_types={"tag": ["tag:tag"]}, create_missing=True
        )
        self.assertTrue(cfg.create_missing)

    def test_create_missing_defaults_to_none_when_omitted(self) -> None:
        cfg = NodePickerConfig.from_membership(kinds=["tag"], entry_types={"tag": ["tag:tag"]})
        self.assertIsNone(cfg.create_missing)


class DefaultSchemaTagBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Tag Binding Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_tags_field_is_entity_ref_list_bound_to_tag_tag_with_create_missing(self) -> None:
        schema = self.service.read_metadata_schema()
        field = schema.fields["tags"]
        self.assertEqual(field.type, "entity_ref_list")
        self.assertIsNotNone(field.picker_config)
        assert field.picker_config is not None
        self.assertEqual(field.picker_config.create_missing, True)
        self.assertEqual(field.picker_config.kinds, ["tag"])
        self.assertEqual(field.picker_config.entry_types, {"tag": ["tag:tag"]})

    def test_assistant_tags_field_is_entity_ref_list_bound_to_tag_assistant_tag_with_create_missing(self) -> None:
        schema = self.service.read_metadata_schema()
        field = schema.fields["assistant_tags"]
        self.assertEqual(field.type, "entity_ref_list")
        assert field.picker_config is not None
        self.assertEqual(field.picker_config.create_missing, True)
        self.assertEqual(field.picker_config.kinds, ["tag"])
        self.assertEqual(field.picker_config.entry_types, {"tag": ["tag:assistant_tag"]})

    def test_assistant_entry_type_lists_assistant_tags_not_tags(self) -> None:
        schema = self.service.read_metadata_schema()
        assistant_fields = schema.entry_types["assistant:assistant"].fields
        self.assertIn("assistant_tags", assistant_fields)
        self.assertNotIn("tags", assistant_fields)

    def test_prompt_base_still_lists_assistant_tags(self) -> None:
        schema = self.service.read_metadata_schema()
        self.assertIn("assistant_tags", schema.entry_types["prompt:base"].fields)

    def test_manuscript_lore_research_keep_the_tags_field(self) -> None:
        # Only the two-vocabulary convention (assistant vs. project) is
        # retired; the built-in `tags` binding itself still applies to the
        # three kinds that used it before (ADR-0082 §2's "built-in bindings").
        schema = self.service.read_metadata_schema()
        for entry_type in ("manuscript:scene", "lore:base", "research:note"):
            with self.subTest(entry_type=entry_type):
                self.assertIn("tags", schema.entry_types[entry_type].fields)


class CreateMissingShapeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Create Missing Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add_field(self, field_id: str, picker_config: dict) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("fields", {})[field_id] = {
            "name": field_id,
            "type": "entity_ref_list",
            "picker_config": picker_config,
        }
        character = data["entry_types"].get("lore:character") or {}
        member_fields = list(character.get("fields") or [])
        if field_id not in member_fields:
            member_fields.append(field_id)
        character["fields"] = member_fields
        data["entry_types"]["lore:character"] = character
        self.service._write_yaml(schema_path, data)

    def test_accepts_create_missing_with_one_concrete_entry_type(self) -> None:
        self._add_field(
            "motifs",
            {"sources": [{"kind": "tag", "expr": {"type": "tag:tag"}}], "create_missing": True},
        )
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertFalse(any("motifs" in error for error in errors), errors)

    def test_rejects_create_missing_with_two_entry_types(self) -> None:
        self._add_field(
            "motifs",
            {
                "sources": [
                    {"kind": "tag", "expr": {"union": [{"type": "tag:tag"}, {"type": "tag:assistant_tag"}]}}
                ],
                "create_missing": True,
            },
        )
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(
            any("motifs" in error and "create_missing" in error for error in errors), errors
        )

    def test_rejects_create_missing_with_an_abstract_entry_type(self) -> None:
        self._add_field(
            "motifs",
            {"sources": [{"kind": "tag", "expr": {"type": "tag:base"}}], "create_missing": True},
        )
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(
            any("motifs" in error and "create_missing" in error for error in errors), errors
        )

    def test_rejects_create_missing_with_two_kinds(self) -> None:
        self._add_field(
            "motifs",
            {
                "sources": [
                    {"kind": "tag", "expr": {"type": "tag:tag"}},
                    {"kind": "lore"},
                ],
                "create_missing": True,
            },
        )
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(
            any("motifs" in error and "create_missing" in error for error in errors), errors
        )

    def test_create_missing_false_is_never_flagged(self) -> None:
        # A closed (non-create_missing) config spanning several kinds is a
        # perfectly ordinary reference field — only create_missing narrows.
        self._add_field(
            "related",
            {"sources": [{"kind": "lore"}, {"kind": "manuscript"}]},
        )
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertFalse(any("related" in error for error in errors), errors)

    def test_group_member_create_missing_is_checked_the_same_way(self) -> None:
        schema_path = self.root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        data.setdefault("groups", {})["cast"] = {
            "name": "Cast",
            "members": [
                {
                    "key": "motif",
                    "name": "Motif",
                    "type": "entity_ref_list",
                    "picker_config": {
                        "sources": [
                            {"kind": "tag", "expr": {"union": [{"type": "tag:tag"}, {"type": "tag:assistant_tag"}]}}
                        ],
                        "create_missing": True,
                    },
                }
            ],
        }
        data.setdefault("fields", {})["cast_list"] = {
            "name": "Cast list",
            "type": "list",
            "item_group": "cast",
        }
        self.service._write_yaml(schema_path, data)
        errors = self.service._validate_metadata_schema_definition(self.service.read_metadata_schema())
        self.assertTrue(
            any("cast_list.motif" in error and "create_missing" in error for error in errors), errors
        )


class AssistantTagsRenameSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Assistant Rename Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_tag(self) -> str:
        return self.service.create_tag_entry(
            CreateTagEntryRequest(title="Editor", entry_type="tag:assistant_tag")
        ).id

    def test_saving_an_assistant_with_assistant_tags_ids_succeeds(self) -> None:
        # ADR-0082 §2: the value is a tag-id list now, not free-text names.
        tag_id = self._make_tag()
        entry = self.service.create_assistant_entry(
            CreateAssistantEntryRequest(title="Ed", entry_type="assistant:assistant", layer_id="")
        )
        saved = self.service.save_assistant_entry(
            entry.id,
            SaveAssistantEntryRequest(
                title="Ed",
                entry_type="assistant:assistant",
                metadata={"assistant_tags": [tag_id]},
            ),
        )
        self.assertEqual(saved.metadata.get("assistant_tags"), [tag_id])

    def test_saving_a_prompt_with_assistant_tags_ids_succeeds(self) -> None:
        tag_id = self._make_tag()
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Draft", entry_type="prompt:general")
        )
        saved = self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title="Draft",
                body="body",
                entry_type="prompt:general",
                metadata={"assistant_tags": [tag_id]},
            ),
        )
        self.assertEqual(saved.metadata.get("assistant_tags"), [tag_id])


class UserVocabularyEndToEndTests(unittest.TestCase):
    """ADR-0082 Acceptance steps 1-2, through the public API: a user-authored
    tag vocabulary (a custom `tag` sub-type, not a built-in), an
    `entity_ref_list` field with `create_missing` referencing it, a tag
    created through the tag-entry route, a scene saved with that tag, and a
    `tagged: <id>` selector picking the scene up — end-to-end, no built-in
    field or vocabulary involved."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "User Vocabulary Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_authored_vocabulary_tag_selects_the_scene_it_is_saved_on(self) -> None:
        from app.models import (
            EntryTypeDefinition,
            MetadataFieldDefinition,
            SaveSceneRequest,
            UpsertMetadataEntryTypeRequest,
            UpsertMetadataFieldRequest,
        )
        from app.services.ai.selector_eval import (
            SelectorNode,
            evaluate_selector_membership,
            selector_references,
        )

        layer_id = self.service.read_metadata_schema_layers().layers[-1].id

        # Step 1a: author the `tag:motifs` sub-type via the entry-type upsert route.
        self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="tag:motifs",
                entry_type=EntryTypeDefinition(name="Motif", kind="tag", parent="tag:base", has_body=False),
            )
        )
        # Step 1b: an entity_ref_list field on manuscript:scene, sourced from the
        # new vocabulary, with "create when missing" ticked.
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="motifs",
                field=MetadataFieldDefinition(
                    name="Motifs",
                    type="entity_ref_list",
                    picker_config={
                        "sources": [{"kind": "tag", "expr": {"type": "tag:motifs"}}],
                        "create_missing": True,
                    },
                ),
                entry_type="manuscript:scene",
            )
        )

        # Step 2a: create a tag via /api/tag-entries (create_tag_entry).
        tag_id = self.service.create_tag_entry(
            CreateTagEntryRequest(title="mirrors", entry_type="tag:motifs")
        ).id

        # Step 2b: save a scene referencing it.
        from app.models import CreateSceneRequest

        scene = self.service.create_scene(CreateSceneRequest(title="Reflections"))
        saved = self.service.save_scene(
            scene.id,
            SaveSceneRequest(
                title="Reflections",
                body="Mirrors everywhere.",
                base_revision=scene.revision,
                entry_type="manuscript:scene",
                metadata={"motifs": [tag_id]},
            ),
        )
        self.assertEqual(saved.metadata.get("motifs"), [tag_id])

        # A `tagged: <id>` selector over the manuscript roster selects the scene —
        # the same schema-free backlink test the picker's "By tag" axis relies on.
        node = SelectorNode(saved.id, "manuscript:scene", selector_references(saved.metadata), saved.metadata)
        member_ids = evaluate_selector_membership(
            {"tagged": tag_id}, [node], is_descendant=lambda et, target: et == target
        )
        self.assertEqual(member_ids, [saved.id])


if __name__ == "__main__":
    unittest.main()
