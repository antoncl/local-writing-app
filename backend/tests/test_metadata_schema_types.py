from __future__ import annotations

import unittest

from metadata_validation_base import MetadataValidationBase

from app.models import (
    EntryTypeDefinition,
    MetadataFieldDefinition,
    MetadataSchema,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError


class MetadataSchemaTypeTests(MetadataValidationBase):
    def test_default_schema_seeds_act_and_chapter(self) -> None:
        # ADR-0094 §7: a new project has one manuscript container type —
        # `manuscript:container` — and Act/Chapter are level names, not
        # entry types. `manuscript:act`/`manuscript:chapter` are no longer
        # built-in.
        schema = self.service.read_metadata_schema()
        self.assertIn("manuscript:container", schema.entry_types)
        self.assertEqual(schema.entry_types["manuscript:container"].kind, "manuscript")
        self.assertFalse(schema.entry_types["manuscript:container"].abstract)
        self.assertNotIn("manuscript:act", schema.entry_types)
        self.assertNotIn("manuscript:chapter", schema.entry_types)

    def test_act_and_chapter_carry_narration_fields(self) -> None:
        # ADR-0079: narration (pov_mode / pov / tense) is authorable at every
        # structure level so it can be overridden and cascade down to scenes.
        # The manuscript's one container type ships these (ADR-0094 §7).
        schema = self.service.read_metadata_schema()
        fields = schema.entry_types["manuscript:container"].fields
        self.assertIn("pov_mode", fields)
        self.assertIn("pov", fields)
        self.assertIn("tense", fields)  # #1737

    def test_new_project_seeds_narration_cascade_fields(self) -> None:
        # ADR-0079: cascade_fields is seeded into the scaffolded metadata.schema.yaml
        # (YAML on the project), not the built-in floor, so a fresh project cascades
        # narration out of the box.
        schema = self.service.read_metadata_schema()
        self.assertIn("pov_mode", schema.cascade_fields)
        self.assertIn("pov", schema.cascade_fields)
        self.assertIn("tense", schema.cascade_fields)  # #1737

    def test_cascade_fields_union_up_the_layer_chain(self) -> None:
        # A field declared cascading at an ancestor layer unions with the book's own
        # cascade_fields (ADR-0079) — a series can declare it once for every book.
        # Uses `dynamics` (not a built-in cascade field) so the union is what's
        # actually under test, not something the book already seeds.
        series_schema = self.world / "metadata.schema.yaml"
        data = self.service._read_yaml(series_schema) if series_schema.exists() else {}
        data["cascade_fields"] = [*(data.get("cascade_fields") or []), "dynamics"]
        self.service._write_yaml(series_schema, data)
        schema = self.service.read_metadata_schema()
        self.assertIn("pov_mode", schema.cascade_fields)  # the book's own seed
        self.assertIn("dynamics", schema.cascade_fields)  # inherited from the series

    def test_manuscript_structure_is_shared_abstract_parent(self) -> None:
        schema = self.service.read_metadata_schema()
        parent = schema.entry_types.get("manuscript:base")
        self.assertIsNotNone(parent)
        assert parent is not None
        self.assertTrue(parent.abstract)
        self.assertEqual(parent.kind, "manuscript")
        for type_id in ["manuscript:container", "manuscript:scene"]:
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
        self.assertTrue(overview.entry_type_sources["manuscript:container"].built_in)
        self.assertFalse(overview.field_sources["weather"].built_in)

    def test_builtin_entry_type_color_icon_override_persists(self) -> None:
        # #1644: a writer sets a color + glyph on a built-in type. The frontend
        # sends the whole draft with allow_existing=True (the type read-only, so
        # its name/kind/parent/abstract ride along but are stripped on write).
        # Only the color/icon overlay persists, and the type stays a system type.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character",
                    kind="lore",
                    parent="lore:base",
                    fields=[],
                    color="amber",
                    icon="star",
                ),
                allow_existing=True,
            )
        )

        character = schema.entry_types["lore:character"]
        # The overlay is the type's OWN (pre-inheritance) color/icon, and beats
        # the shipped default glyph (lore:character ships `user`, see #1646)...
        self.assertEqual(character.own_color, "amber")
        self.assertEqual(character.own_icon, "star")
        # ...and wins in the resolved values (own over lore:base's slate-blue).
        self.assertEqual(character.color, "amber")
        self.assertEqual(character.icon, "star")
        # Identity is untouched — the shipped declaration was never forked.
        self.assertEqual(character.name, "Character")
        self.assertEqual(character.parent, "lore:base")

        # A color/icon-only overlay carries none of name/kind/parent/abstract, so
        # the type is still reported as built-in (its identity stays locked).
        overview = self.service.read_metadata_schema_overview()
        self.assertTrue(overview.entry_type_sources["lore:character"].built_in)

    def test_builtin_entry_type_upsert_requires_allow_existing(self) -> None:
        # The contract the frontend's builtinOverlay flag rides on (#1644): the
        # FQN already exists in the effective schema, so without allow_existing
        # the upsert is the "already exists" 422 — not a silent no-op.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        with self.assertRaises(ProjectServiceError) as ctx:
            self.service.upsert_metadata_entry_type(
                UpsertMetadataEntryTypeRequest(
                    layer_id=layer_id,
                    entry_type_id="lore:character",
                    entry_type=EntryTypeDefinition(
                        name="Character", kind="lore", parent="lore:base", icon="user"
                    ),
                    allow_existing=False,
                )
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_builtin_color_icon_override_preserves_field_overlay(self) -> None:
        # Data-safety property (#1644): a writer who has customized a built-in's
        # fields must not lose them when they later set a glyph. The frontend
        # sends `fields: []` on a color/icon save (previousTypeId is null for a
        # read-only built-in), so the backend has to keep the existing layer
        # membership rather than overwrite it with the empty list.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="weather",
                field=MetadataFieldDefinition(name="Weather", type="text", options=[]),
                entry_type="lore:character",
                allow_existing=False,
            )
        )
        self.assertIn("weather", self.service.read_metadata_schema().entry_types["lore:character"].fields)

        # Now the glyph save, exactly as the editor sends it.
        schema = self.service.upsert_metadata_entry_type(
            UpsertMetadataEntryTypeRequest(
                layer_id=layer_id,
                entry_type_id="lore:character",
                entry_type=EntryTypeDefinition(
                    name="Character", kind="lore", parent="lore:base", fields=[], icon="star"
                ),
                allow_existing=True,
            )
        )

        character = schema.entry_types["lore:character"]
        self.assertEqual(character.own_icon, "star")
        # The user's field survived the empty-fields payload.
        self.assertIn("weather", character.fields)

    def test_builtin_types_ship_default_glyphs(self) -> None:
        # #1646: concrete built-in types ship a starting glyph so they don't
        # render blank — a per-type default (a glyph tells character from
        # location, unlike the per-kind color default). `own_icon` is the
        # type's own declared glyph, so it reads the seed directly.
        types = self.service.read_metadata_schema().entry_types
        self.assertEqual(types["lore:character"].own_icon, "user")
        self.assertEqual(types["lore:location"].own_icon, "map-pin")
        self.assertEqual(types["manuscript:scene"].own_icon, "feather")
        self.assertEqual(types["manuscript:container"].own_icon, "stack-2")
        self.assertEqual(types["plot:plotline"].own_icon, "route")
        self.assertEqual(types["assistant:assistant"].own_icon, "sparkles")
        self.assertEqual(types["chat:chat_session"].own_icon, "message-circle")
        # lore:item is the deliberate catch-all — no single object glyph fits
        # "any physical object", so it ships blank (a writer sets one per #1644).
        self.assertIsNone(types["lore:item"].own_icon)
        # Abstract bases carry no glyph — only the concrete types a writer sees.
        self.assertIsNone(types["lore:base"].own_icon)

    def test_summary_lives_on_parent_not_in_scene_own_fields(self) -> None:
        schema = self.service.read_metadata_schema()
        scene_definition = schema.entry_types["manuscript:scene"]
        self.assertNotIn("summary", scene_definition.own_fields)
        self.assertIn("summary", scene_definition.fields)
        self.assertIn("status", scene_definition.own_fields)

    def test_scene_body_renders_after_summary_and_dynamics(self) -> None:
        # ADR-0089 Amendment 1 (#2099): a scene reads brief→draft — the prose
        # body comes AFTER its long_text sections. Driven by scene's built-in
        # `display_order`, not a hardcoded "if scene" branch in the resolver.
        fields = self.service.read_metadata_schema().entry_types["manuscript:scene"].fields
        body_index = fields.index("body")
        self.assertGreater(body_index, fields.index("summary"))
        self.assertGreater(body_index, fields.index("dynamics"))

    def test_lore_body_still_precedes_a_long_text_field(self) -> None:
        # Unchanged behaviour: a lore (non-scene) body-bearing type keeps its
        # prose FIRST — `body` is spliced right after `title`, and only
        # scene's own `display_order` reorders it. Add a long_text field to
        # a lore type via a project layer (no display_order) and confirm body
        # still leads it.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:character": {
                        "name": "Character",
                        "kind": "lore",
                        "parent": "lore:base",
                        "fields": ["backstory"],
                    }
                },
                "fields": {
                    "backstory": {"name": "Backstory", "type": "long_text"},
                },
            },
        )
        fields = self.service.read_metadata_schema().entry_types["lore:character"].fields
        self.assertLess(fields.index("body"), fields.index("backstory"))

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

    def test_research_topic_opens_in_the_editor(self) -> None:
        # A research topic is a file since ADR-0094 §7, so it opens like any
        # node — it was a tree-only container before (#1199). The topic's
        # container type is `research:container`; "Topic" is its level name.
        schema = self.service.read_metadata_schema()
        topic = schema.entry_types["research:container"]
        self.assertEqual(topic.opens_in, "editor")

    def test_tag_types_opens_in_dialog(self) -> None:
        # A tag is minted from a picker, not authored through the
        # Conversations panel — kept out of the Offer-on picker's "editor"
        # host set (ADR-0082 slice 1 review fix; `offerOnTree.ts`).
        schema = self.service.read_metadata_schema()
        self.assertEqual(schema.entry_types["tag:tag"].opens_in, "dialog")
        self.assertEqual(schema.entry_types["tag:assistant_tag"].opens_in, "dialog")

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


class UnknownSchemaKeyWarningTests(MetadataValidationBase):
    """#2217: a hand-edited layer with a typo'd/retired key warns, never
    rejects — `validate_project` stays `valid` and the schema still loads."""

    def test_unknown_keys_warn_without_failing_validation(self) -> None:
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "mood": {
                        "name": "Mood",
                        "type": "select",
                        "optoins": ["tense", "calm"],
                    },
                    "companion": {
                        "name": "Companion",
                        "type": "entity_ref",
                        "picker_config": {"kinds": ["lore"]},
                    },
                },
            },
        )
        result = self.service.validate_project()
        self.assertTrue(result.valid)
        self.assertTrue(
            any(
                "fields.mood has an unknown key `optoins`" in w
                for w in result.warnings
            )
        )
        self.assertTrue(
            any(
                "fields.companion.picker_config has an unknown key `kinds`" in w
                and "Did you mean `sources`?" in w
                for w in result.warnings
            )
        )
        # Nothing rejected the load — the field (minus the unknown key) is
        # still in the effective schema.
        schema = self.service.read_metadata_schema()
        self.assertIn("mood", schema.fields)
        self.assertIn("companion", schema.fields)


if __name__ == "__main__":
    unittest.main()
