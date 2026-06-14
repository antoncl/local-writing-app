from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="Untitled Project", min_length=1)


class OpenProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)


class ProjectInfo(BaseModel):
    title: str
    root_path: str
    projects_base_folder: str | None = None


class UpdateProjectSettingsRequest(BaseModel):
    projects_base_folder: str | None = None


class ProjectValidation(BaseModel):
    valid: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    path: str
    parent_path: str | None = None
    directories: list[DirectoryEntry] = Field(default_factory=list)


class StructureNode(BaseModel):
    id: str
    type: Literal["root", "act", "chapter", "sequence", "scene"]
    title: str
    scene_id: str | None = None
    children: list["StructureNode"] = Field(default_factory=list)


class StructureDocument(BaseModel):
    root: StructureNode


MetadataValue = str | int | float | bool | None | list[Any] | dict[str, Any]


class MetadataFieldDefinition(BaseModel):
    name: str
    type: Literal[
        "text",
        "long_text",
        "number",
        "boolean",
        "date",
        "select",
        "multi_select",
        "entity_ref",
        "entity_ref_list",
        "tags",
        "computed",
    ]
    options: list[str] = Field(default_factory=list)
    target: dict[str, str] | None = None
    computed: dict[str, str] | None = None


class EntryTypeDefinition(BaseModel):
    name: str
    kind: str
    parent: str | None = None
    fields: list[str] = Field(default_factory=list)


class MetadataSchema(BaseModel):
    version: int = 1
    entry_types: dict[str, EntryTypeDefinition] = Field(default_factory=dict)
    fields: dict[str, MetadataFieldDefinition] = Field(default_factory=dict)


class MetadataSchemaLayer(BaseModel):
    id: str
    label: str
    folder_path: str
    schema_path: str
    exists: bool = False


class MetadataSchemaLayers(BaseModel):
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)


class MetadataDefinitionSource(BaseModel):
    layer_id: str
    layer_label: str
    schema_path: str | None = None
    built_in: bool = False


class MetadataSchemaOverview(BaseModel):
    effective_schema: MetadataSchema
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)
    entry_type_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)
    field_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)


class UpsertMetadataFieldRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    field: MetadataFieldDefinition
    entry_type: str = "scene"
    allow_existing: bool = True


class MoveMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    target_layer_id: str = Field(min_length=1)
    entry_type: str = "scene"


class RenameMetadataFieldRequest(BaseModel):
    old_field_id: str = Field(min_length=1)
    new_field_id: str = Field(min_length=1)
    entry_type: str = "scene"


class DeleteMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    entry_type: str = "scene"


class Scene(BaseModel):
    id: str
    title: str
    body_markdown: str
    revision: str
    status: str = "draft"
    entry_type: str = "scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class CreateSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    parent_id: str | None = None


class SaveSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str
    base_revision: str | None = None
    status: str = "draft"
    entry_type: str = "scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class TodoItem(BaseModel):
    id: str
    text: str
    status: Literal["open", "done"] = "open"
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None


class TodoDocument(BaseModel):
    items: list[TodoItem] = Field(default_factory=list)


class CreateTodoRequest(BaseModel):
    text: str = Field(min_length=1)
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None


class UpdateTodoRequest(BaseModel):
    text: str | None = None
    status: Literal["open", "done"] | None = None
    scope: Literal["project", "scene"] | None = None
    scene_id: str | None = None


class SearchRequest(BaseModel):
    query: str = ""
    include_scenes: bool = True
    include_lore: bool = True
    include_open_todos: bool = False


class SearchHit(BaseModel):
    file_id: str
    path: str
    line: int
    excerpt: str
    todo_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)


StructureNode.model_rebuild()
