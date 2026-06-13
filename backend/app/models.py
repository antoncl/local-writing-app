from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="Untitled Project", min_length=1)


class OpenProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)


class ProjectInfo(BaseModel):
    title: str
    root_path: str


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


class Scene(BaseModel):
    id: str
    title: str
    body_markdown: str
    revision: str
    status: str = "draft"


class CreateSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    parent_id: str | None = None


class SaveSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    body_markdown: str
    base_revision: str | None = None
    status: str = "draft"


class TodoItem(BaseModel):
    id: str
    text: str
    status: Literal["open", "done"] = "open"
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None


class TodoDocument(BaseModel):
    items: list[TodoItem] = Field(default_factory=list)


class CreateTodoRequest(BaseModel):
    text: str = Field(min_length=1)
    scope: Literal["project", "scene"] = "project"
    scene_id: str | None = None


class UpdateTodoRequest(BaseModel):
    text: str | None = None
    status: Literal["open", "done"] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    include_scenes: bool = True
    include_lore: bool = True


class SearchHit(BaseModel):
    file_id: str
    path: str
    line: int
    excerpt: str


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)


StructureNode.model_rebuild()
