from __future__ import annotations

from fastapi.testclient import TestClient
from metadata_validation_base import MetadataValidationBase
from project_fixtures import bind_test_project

from app.main import app
from app.models import (
    AttachMetadataFieldRequest,
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)
from app.services.project.errors import ProjectServiceError


class AttachMetadataFieldTests(MetadataValidationBase):
    def _layer_id(self, folder) -> str:
        return next(
            layer.id
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(folder)
        )

    def test_attach_field_defined_on_another_type_same_layer(self) -> None:
        world_layer_id = self._layer_id(self.world)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer_id,
                field_id="physical_description",
                field=MetadataFieldDefinition(name="Physical description", type="long_text"),
                entry_type="lore:character",
            )
        )
        definition_before = self.service._read_yaml(self.world / "metadata.schema.yaml")["fields"][
            "physical_description"
        ]

        schema = self.service.attach_metadata_field(
            AttachMetadataFieldRequest(
                layer_id=world_layer_id,
                field_id="physical_description",
                entry_type_id="lore:location",
            )
        )

        self.assertIn("physical_description", schema.entry_types["lore:location"].fields)
        self.assertIn("physical_description", schema.entry_types["lore:character"].fields)
        world_schema = self.service._read_yaml(self.world / "metadata.schema.yaml")
        self.assertIn(
            "physical_description", world_schema["entry_types"]["lore:location"]["fields"]
        )
        # The shared definition itself is untouched by the attach — only
        # membership on `lore:location` changed, not the `fields:` entry.
        self.assertEqual(world_schema["fields"]["physical_description"], definition_before)

    def test_attach_field_from_ancestor_layer_at_project_layer(self) -> None:
        world_layer_id = self._layer_id(self.world)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer_id,
                field_id="eye_color",
                field=MetadataFieldDefinition(name="Eye color", type="text"),
                entry_type="lore:character",
            )
        )
        ancestor_bytes_before = (self.world / "metadata.schema.yaml").read_bytes()
        project_layer_id = self._layer_id(self.root)

        schema = self.service.attach_metadata_field(
            AttachMetadataFieldRequest(
                layer_id=project_layer_id,
                field_id="eye_color",
                entry_type_id="lore:location",
            )
        )

        self.assertIn("eye_color", schema.entry_types["lore:location"].fields)
        project_schema = self.service._read_yaml(self.root / "metadata.schema.yaml")
        self.assertIn("eye_color", project_schema["entry_types"]["lore:location"]["fields"])
        # The project layer never writes to `fields:` — attach is membership-only.
        self.assertNotIn("eye_color", project_schema.get("fields", {}))
        # The ancestor (world) layer that owns the definition is untouched.
        self.assertEqual(
            ancestor_bytes_before, (self.world / "metadata.schema.yaml").read_bytes()
        )

    def test_attach_field_only_defined_deeper_is_rejected_at_ancestor_layer(self) -> None:
        project_layer_id = self._layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=project_layer_id,
                field_id="hair_color",
                field=MetadataFieldDefinition(name="Hair color", type="text"),
                entry_type="lore:character",
            )
        )
        world_layer_id = self._layer_id(self.world)

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.attach_metadata_field(
                AttachMetadataFieldRequest(
                    layer_id=world_layer_id,
                    field_id="hair_color",
                    entry_type_id="lore:location",
                )
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("not defined at or above this layer", raised.exception.message)

    def test_attach_unknown_field_404(self) -> None:
        project_layer_id = self._layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.attach_metadata_field(
                AttachMetadataFieldRequest(
                    layer_id=project_layer_id,
                    field_id="not_a_real_field",
                    entry_type_id="lore:location",
                )
            )

        self.assertEqual(raised.exception.status_code, 404)

    def test_attach_unknown_entry_type_404(self) -> None:
        project_layer_id = self._layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.attach_metadata_field(
                AttachMetadataFieldRequest(
                    layer_id=project_layer_id,
                    field_id="summary",
                    entry_type_id="lore:not_a_real_type",
                )
            )

        self.assertEqual(raised.exception.status_code, 404)

    def test_attach_intrinsic_field_rejected(self) -> None:
        project_layer_id = self._layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.attach_metadata_field(
                AttachMetadataFieldRequest(
                    layer_id=project_layer_id,
                    field_id="title",
                    entry_type_id="lore:location",
                )
            )

        self.assertEqual(raised.exception.status_code, 422)

    def test_attach_builtin_computed_field_rejected(self) -> None:
        project_layer_id = self._layer_id(self.root)

        with self.assertRaises(ProjectServiceError) as raised:
            self.service.attach_metadata_field(
                AttachMetadataFieldRequest(
                    layer_id=project_layer_id,
                    field_id="references",
                    entry_type_id="lore:location",
                )
            )

        self.assertEqual(raised.exception.status_code, 422)

    def test_attach_builtin_stored_field_allowed(self) -> None:
        project_layer_id = self._layer_id(self.root)

        schema = self.service.attach_metadata_field(
            AttachMetadataFieldRequest(
                layer_id=project_layer_id,
                field_id="summary",
                entry_type_id="lore:location",
            )
        )

        self.assertIn("summary", schema.entry_types["lore:location"].fields)

    def test_attach_is_idempotent(self) -> None:
        project_layer_id = self._layer_id(self.root)
        self.service.attach_metadata_field(
            AttachMetadataFieldRequest(
                layer_id=project_layer_id,
                field_id="summary",
                entry_type_id="lore:location",
            )
        )
        project_bytes_before = (self.root / "metadata.schema.yaml").read_bytes()

        schema = self.service.attach_metadata_field(
            AttachMetadataFieldRequest(
                layer_id=project_layer_id,
                field_id="summary",
                entry_type_id="lore:location",
            )
        )

        self.assertIn("summary", schema.entry_types["lore:location"].fields)
        self.assertEqual(
            project_bytes_before, (self.root / "metadata.schema.yaml").read_bytes()
        )

    def test_attach_route(self) -> None:
        world_layer_id = self._layer_id(self.world)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=world_layer_id,
                field_id="favorite_food",
                field=MetadataFieldDefinition(name="Favorite food", type="text"),
                entry_type="lore:character",
            )
        )
        bind_test_project(self.service)
        client = TestClient(app)
        response = client.post(
            "/api/metadata/schema/entry-types/fields",
            json={
                "layer_id": world_layer_id,
                "field_id": "favorite_food",
                "entry_type_id": "lore:location",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            "favorite_food", response.json()["entry_types"]["lore:location"]["fields"]
        )
