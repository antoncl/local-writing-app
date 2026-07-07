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
from app.runtime import service, translate_errors

router = APIRouter()


@router.get("/api/metadata/schema", response_model=MetadataSchema)
def get_metadata_schema() -> MetadataSchema:
    with translate_errors():
        return service.read_metadata_schema()


@router.get("/api/metadata/schema/layers", response_model=MetadataSchemaLayers)
def get_metadata_schema_layers() -> MetadataSchemaLayers:
    with translate_errors():
        return service.read_metadata_schema_layers()


@router.get("/api/metadata/schema/overview", response_model=MetadataSchemaOverview)
def get_metadata_schema_overview() -> MetadataSchemaOverview:
    with translate_errors():
        return service.read_metadata_schema_overview()


@router.get("/api/tags", response_model=KnownTags)
def get_known_tags() -> KnownTags:
    with translate_errors():
        return service.read_known_tags()


@router.get("/api/tags/overview", response_model=TagsOverview)
def get_tags_overview() -> TagsOverview:
    with translate_errors():
        return service.read_tags_overview()


@router.put("/api/tags/scope", response_model=KnownTags)
def update_tag_scope(request: UpdateTagScopeRequest) -> KnownTags:
    with translate_errors():
        return service.update_tag_scope(request)


@router.post("/api/tags/merge", response_model=KnownTags)
def merge_tags(request: MergeTagsRequest) -> KnownTags:
    with translate_errors():
        return service.merge_tags(request)


@router.put("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def upsert_metadata_entry_type(request: UpsertMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return service.upsert_metadata_entry_type(request)


@router.delete("/api/metadata/schema/entry-types", response_model=MetadataSchema)
def delete_metadata_entry_type(request: DeleteMetadataEntryTypeRequest) -> MetadataSchema:
    with translate_errors():
        return service.delete_metadata_entry_type(request)


@router.put("/api/metadata/schema/fields", response_model=MetadataSchema)
def upsert_metadata_field(request: UpsertMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.upsert_metadata_field(request)


@router.post("/api/metadata/schema/fields/move", response_model=MetadataSchema)
def move_metadata_field(request: MoveMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.move_metadata_field(request)


@router.post("/api/metadata/schema/fields/rename", response_model=MetadataSchema)
def rename_metadata_field(request: RenameMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.rename_metadata_field(request)


@router.delete("/api/metadata/schema/fields", response_model=MetadataSchema)
def delete_metadata_field(request: DeleteMetadataFieldRequest) -> MetadataSchema:
    with translate_errors():
        return service.delete_metadata_field(request)


@router.put("/api/metadata/schema/groups", response_model=MetadataSchema)
def upsert_metadata_group(request: UpsertMetadataGroupRequest) -> MetadataSchema:
    with translate_errors():
        return service.upsert_metadata_group(request)


@router.delete("/api/metadata/schema/groups", response_model=MetadataSchema)
def delete_metadata_group(request: DeleteMetadataGroupRequest) -> MetadataSchema:
    with translate_errors():
        return service.delete_metadata_group(request)


@router.put("/api/metadata/schema/entry-types/group-applications", response_model=MetadataSchema)
def set_entry_type_group_applications(request: SetGroupApplicationsRequest) -> MetadataSchema:
    with translate_errors():
        return service.set_entry_type_group_applications(request)


@router.put("/api/metadata/schema/entry-types/field-order", response_model=MetadataSchema)
def set_entry_type_field_order(request: SetFieldOrderRequest) -> MetadataSchema:
    with translate_errors():
        return service.set_entry_type_field_order(request)


@router.put("/api/metadata/schema/entry-types/field-override", response_model=MetadataSchema)
def set_metadata_field_override(request: SetFieldOverrideRequest) -> MetadataSchema:
    with translate_errors():
        return service.set_metadata_field_override(request)


