"""Intrinsic identity fields (#116).

`id`, `title`, and `entry_type` live in a node's top-level front matter, not in
`metadata`. The schema resolver injects them into every entry_type's resolved
`fields` list so they are visible to the field-inheritance hierarchy and
filterable/sortable in Views — without moving storage into `metadata`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import SaveSceneRequest, SetFieldOverrideRequest
from app.services.project.default_schema import INTRINSIC_FIELD_KEYS
from app.services.project_service import ProjectService, ProjectServiceError


class IntrinsicFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")
        self.scene_id = self.service._read_front_matter_only(
            next((self.root / "scenes").glob("*.md")), strict=True
        )["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_every_entry_type_carries_the_intrinsic_triple(self) -> None:
        schema = self.service.read_metadata_schema()
        for entry_type_id, definition in schema.entry_types.items():
            for key in INTRINSIC_FIELD_KEYS:
                self.assertIn(
                    key,
                    definition.fields,
                    f"{entry_type_id} is missing intrinsic field {key}",
                )

    def test_intrinsic_fields_lead_and_are_not_owned(self) -> None:
        # Injected leading (title first), and NOT counted as own_fields so the
        # editor renders them as built-in rather than type-owned.
        scene = self.service.read_metadata_schema().entry_types["scene:scene"]
        self.assertEqual(scene.fields[:3], ["title", "entry_type", "id"])
        for key in INTRINSIC_FIELD_KEYS:
            self.assertNotIn(key, scene.own_fields)

    def test_intrinsic_field_defs_are_marked(self) -> None:
        fields = self.service.read_metadata_schema().fields
        self.assertTrue(fields["title"].intrinsic)
        self.assertTrue(fields["entry_type"].intrinsic)
        self.assertTrue(fields["id"].intrinsic)
        # `id` is hidden by default; title/entry_type are shown.
        self.assertTrue(fields["id"].hidden)
        self.assertFalse(fields["title"].hidden)

    def test_intrinsic_injection_does_not_duplicate(self) -> None:
        # A type that already lists an intrinsic key must not get a duplicate.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "scene:scene": {
                        "name": "Scene",
                        "kind": "scene",
                        "fields": ["title", "status"],
                    }
                },
            },
        )
        fields = self.service.read_metadata_schema().entry_types["scene:scene"].fields
        self.assertEqual(fields.count("title"), 1)

    def test_resolver_stamps_authorship_category(self) -> None:
        # ADR-0029 §D: every resolved field carries a `category` derived by the
        # resolver — intrinsic (identity triple), computed (app-produced), else
        # stored. This is the single source of truth the surfaces consult.
        fields = self.service.read_metadata_schema().fields
        self.assertEqual(fields["title"].category, "intrinsic")
        self.assertEqual(fields["entry_type"].category, "intrinsic")
        self.assertEqual(fields["id"].category, "intrinsic")
        self.assertEqual(fields["word_count"].category, "computed")
        self.assertEqual(fields["status"].category, "stored")
        self.assertEqual(fields["color"].category, "stored")

    def test_references_is_a_builtin_node_set_computed_field(self) -> None:
        # #184 Phase 2b (ADR-0031 §G): `references` (any-field backlinks) is a
        # built-in catalog computed field. It carries no stored value (resolved
        # at view-eval time from the reverse index) but DECLARES its node-set
        # output payload via `computed.value_type` so the view designer can type
        # its `field_of` handles. It is NOT seeded into any type's membership.
        schema = self.service.read_metadata_schema()
        references = schema.fields.get("references")
        self.assertIsNotNone(references, "references catalog field is missing")
        assert references is not None  # narrow for the type checker
        self.assertEqual(references.category, "computed")
        self.assertEqual(references.type, "computed")
        self.assertEqual(references.name, "References")
        self.assertEqual((references.computed or {}).get("value_type"), "node_set")
        for entry_type_id, definition in schema.entry_types.items():
            self.assertNotIn(
                "references",
                definition.fields,
                f"references should not be seeded into {entry_type_id} membership",
            )

    def test_title_is_not_stored_in_metadata_after_save(self) -> None:
        # Declaring title/id/entry_type as fields must not cause them to be
        # persisted into the metadata dict — storage stays in front matter.
        scene = self.service.read_scene(self.scene_id)
        self.service.save_scene(
            self.scene_id,
            SaveSceneRequest(
                title="A New Title",
                body=scene.body,
                base_revision=scene.revision,
                status="draft",
                entry_type="scene:scene",
                metadata=dict(scene.metadata),
            ),
        )
        reloaded = self.service.read_scene(self.scene_id)
        self.assertEqual(reloaded.title, "A New Title")
        self.assertNotIn("title", reloaded.metadata)
        self.assertNotIn("id", reloaded.metadata)
        self.assertNotIn("entry_type", reloaded.metadata)


class FieldOverrideTests(unittest.TestCase):
    """Per-type field presentation overrides (#116): relabel / hide."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService()
        self.service.create_project(self.root, "Test Project")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _project_layer_id(self) -> str:
        return self.service.read_metadata_schema_layers().layers[-1].id

    def test_overrides_merge_down_the_parent_chain(self) -> None:
        # Parent relabels `tags`; child relabels `title` — the child sees both.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:base": {"field_overrides": {"tags": {"label": "Labels"}}},
                    "lore:character": {"field_overrides": {"title": {"label": "Name"}}},
                },
            },
        )
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        self.assertEqual(character.field_overrides["tags"].label, "Labels")
        self.assertEqual(character.field_overrides["title"].label, "Name")

    def test_lore_relabels_title_to_name_by_default(self) -> None:
        # The built-in schema ships a per-type override so lore entries call
        # their title a "Name" (replaces the old hardcoded editor ternary).
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        self.assertEqual(character.field_overrides["title"].label, "Name")
        # Scenes keep the plain "Title" — no override.
        scene = self.service.read_metadata_schema().entry_types["scene:scene"]
        self.assertNotIn("title", scene.field_overrides)

    def test_hidden_false_override_can_unhide_a_def_hidden_field(self) -> None:
        # `id` is hidden at the def level; a per-type hidden:false overrides it.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {"lore:character": {"field_overrides": {"id": {"hidden": False}}}},
            },
        )
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        self.assertIs(character.field_overrides["id"].hidden, False)

    def test_set_override_round_trips_via_the_endpoint(self) -> None:
        # `aliases` is inherited with no built-in override, so a clear drops it
        # cleanly (unlike `title`, which lore relabels to "Name" by default).
        layer = self._project_layer_id()
        self.service.set_metadata_field_override(
            SetFieldOverrideRequest(
                layer_id=layer, entry_type_id="lore:character", field_key="aliases", label="Also known as"
            )
        )
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        self.assertEqual(character.field_overrides["aliases"].label, "Also known as")
        # Clearing (empty overlay) drops the entry again.
        self.service.set_metadata_field_override(
            SetFieldOverrideRequest(
                layer_id=layer, entry_type_id="lore:character", field_key="aliases", label=None
            )
        )
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        self.assertNotIn("aliases", character.field_overrides)

    def test_clearing_last_override_leaves_no_empty_stub(self) -> None:
        # Set then clear the only override on a built-in type: the type must not
        # be left as an empty `{}` entry in the layer (which would flip its
        # source from built-in to this layer).
        layer = self._project_layer_id()
        before = self.service.read_metadata_schema_overview().entry_type_sources["lore:character"]
        self.assertTrue(before.built_in)
        for label in ("Also known as", None):
            self.service.set_metadata_field_override(
                SetFieldOverrideRequest(
                    layer_id=layer, entry_type_id="lore:character", field_key="aliases", label=label
                )
            )
        layer_yaml = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertNotIn("lore:character", layer_yaml.get("entry_types", {}))
        after = self.service.read_metadata_schema_overview().entry_type_sources["lore:character"]
        self.assertTrue(after.built_in)

    def test_own_field_overrides_are_pre_merge(self) -> None:
        # ADR-0029 §I: the resolver ships each type's OWN (pre-merge) overrides
        # in parallel to the merged `field_overrides`. The parent hides `tags`
        # and the child relabels it — the child's MERGED view carries both, but
        # its OWN overlay carries only the aspect it authored (label), so
        # editing one aspect never freezes the inherited other into the child.
        self.service._write_yaml(
            self.root / "metadata.schema.yaml",
            {
                "version": 1,
                "entry_types": {
                    "lore:base": {"field_overrides": {"tags": {"hidden": True}}},
                    "lore:character": {"field_overrides": {"tags": {"label": "Labels"}}},
                },
            },
        )
        character = self.service.read_metadata_schema().entry_types["lore:character"]
        # Merged view: both aspects present.
        self.assertEqual(character.field_overrides["tags"].label, "Labels")
        self.assertIs(character.field_overrides["tags"].hidden, True)
        # Own overlay: only the authored aspect (label); hidden stays inherited.
        self.assertEqual(character.own_field_overrides["tags"].label, "Labels")
        self.assertIsNone(character.own_field_overrides["tags"].hidden)

    def test_override_rejects_a_non_member_field(self) -> None:
        with self.assertRaises(ProjectServiceError):
            self.service.set_metadata_field_override(
                SetFieldOverrideRequest(
                    layer_id=self._project_layer_id(),
                    entry_type_id="lore:character",
                    field_key="not_a_field",
                    label="X",
                )
            )


if __name__ == "__main__":
    unittest.main()
