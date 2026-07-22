"""Metadata schema, fields, groups, and tags routes (#170 main.py split)."""
from __future__ import annotations

from fastapi import APIRouter

from app.models import (
    DeleteMetadataEntryTypeRequest,
    DeleteMetadataFieldRequest,
    DeleteMetadataGroupRequest,
    KnownTags,
    MergeTagsRequest,
    MetadataSchema,
    MetadataSchemaLayers,
    MetadataSchemaOverview,
    MoveMetadataFieldRequest,
    RenameMetadataFieldRequest,
    SetFieldOrderRequest,
    SetFieldOverrideRequest,
    SetGroupApplicationsRequest,
    TagsOverview,
    UpdateTagScopeRequest,
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


@router.get("/api/tags", response_model=KnownTags)
def get_known_tags(project: CurrentProject, layer: str | None = None) -> KnownTags:
    """The merged vocabulary. `layer` reads it as of an authoring level instead
    of the open project (#339) — ancestors of that layer stay visible, layers
    below it drop out."""
    with translate_errors():
        return project.read_known_tags(up_to_layer_id=layer)


@router.get("/api/tags/overview", response_model=TagsOverview)
def get_tags_overview(project: CurrentProject) -> TagsOverview:
    with translate_errors():
        return project.read_tags_overview()


@router.put("/api/tags/scope", response_model=KnownTags)
def update_tag_scope(project: CurrentProject, request: UpdateTagScopeRequest) -> KnownTags:
    with translate_errors():
        return project.update_tag_scope(request)


@router.post("/api/tags/merge", response_model=KnownTags)
def merge_tags(project: CurrentProject, request: MergeTagsRequest) -> KnownTags:
    with translate_errors():
        return project.merge_tags(request)


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


