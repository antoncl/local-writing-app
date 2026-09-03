"""Metadata schema, fields, and groups routes (#170 main.py split).

The tag-registry routes (`/api/tags*`) retired with `TagsMixin` (ADR-0082
slice 3, #1784) — the `tag` kind's own CRUD lives at `/api/tag-entries`
(`routers/tag_nodes.py`)."""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    DeleteMetadataGroupRequest,
    MetadataSchema,
    MetadataSchemaLayers,
    MetadataSchemaOverview,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SetFieldOrderRequest,
    SetFieldOverrideRequest,
    SetGroupApplicationsRequest,
    UpsertMetadataEntryTypeRequest,
    UpsertMetadataFieldRequest,
    UpsertMetadataGroupRequest,
)
from app.runtime import CurrentProject, translate_errors

router = APIRouter()


@router.get("/api/metadata/schema", response_model=MetadataSchema)
def get_metadata_schema(project: CurrentProject) -> MetadataSchema:
    with translate_errors():
        return project.read_metadata_schema()


@router.get("/api/metadata/schema/layers", response_model=MetadataSchemaLayers)
def get_metadata_schema_layers(project: CurrentProject) -> MetadataSchemaLayers:
    with translate_errors():
        return project.read_metadata_schema_layers()


@router.get("/api/metadata/schema/overview", response_model=MetadataSchemaOverview)
def get_metadata_schema_overview(project: CurrentProject) -> MetadataSchemaOverview:
    with translate_errors():
        return project.read_metadata_schema_overview()


@router.put("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def upsert_metadata_entry_type(project: CurrentProject, request: UpsertMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return project.upsert_metadata_entry_type(request)


@router.delete("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def delete_metadata_entry_type(project: CurrentProject, request: DeleteMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return project.delete_metadata_entry_type(request)


@router.put("/api/metadata/schema/fields", response_model=MetadataSchema)
def upsert_metadata_field(project: CurrentProject, request: UpsertMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return project.upsert_metadata_field(request)


@router.post("/api/metadata/schema/fields/move", response_model=MetadataSchema)
def move_metadata_field(project: CurrentProject, request: MoveMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return project.move_metadata_field(request)


@router.post("/api/metadata/schema/fields/rename", response_model=MetadataSchema)
def rename_metadata_field(project: CurrentProject, request: RenameMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return project.rename_metadata_field(request)


@router.delete("/api/metadata/schema/fields", response_model=MetadataSchema)
def delete_metadata_field(project: CurrentProject, request: DeleteMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return project.delete_metadata_field(request)


@router.put("/api/metadata/schema/groups", response_model=MetadataSchema)
def upsert_metadata_group(project: CurrentProject, request: UpsertMetadataGroupRequest) -> MetadataSchema:
    with translate_errors():
        return project.upsert_metadata_group(request)


@router.delete("/api/metadata/schema/groups", response_model=MetadataSchema)
def delete_metadata_group(project: CurrentProject, request: DeleteMetadataGroupRequest) -> MetadataSchema:
    with translate_errors():
        return project.delete_metadata_group(request)


@router.put("/api/metadata/schema/entry-types/group-applications", response_model=MetadataSchema)
def set_entry_type_group_applications(project: CurrentProject, request: SetGroupApplicationsRequest) -> MetadataSchema:
    with translate_errors():
        return project.set_entry_type_group_applications(request)


@router.put("/api/metadata/schema/entry-types/field-order", response_model=MetadataSchema)
def set_entry_type_field_order(project: CurrentProject, request: SetFieldOrderRequest) -> MetadataSchema:
    with translate_errors():
        return project.set_entry_type_field_order(request)


@router.put("/api/metadata/schema/entry-types/field-override", response_model=MetadataSchema)
def set_metadata_field_override(project: CurrentProject, request: SetFieldOverrideRequest) -> MetadataSchema:
    with translate_errors():
        return project.set_metadata_field_override(request)


