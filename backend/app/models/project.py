from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.base import (
    AIPolicy,
    MetadataValue,
)


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="Untitled Project", min_length=1)
    # Optional — when omitted, the project's parent folder is used. The
    # frontend no longer surfaces this; kept on the request for back-compat
    # and to keep the validation path open for tooling.
    projects_base_folder: str | None = None


class OpenProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    projects_base_folder: str | None = None


class ProjectInfo(BaseModel):
    title: str
    root_path: str
    projects_base_folder: str | None = None
    ai_policy: AIPolicy = "off"
    ai_default_provider: str | None = None
    ai_default_model_class: str | None = None


class UpdateProjectSettingsRequest(BaseModel):
    projects_base_folder: str | None = None
    ai_policy: AIPolicy | None = None
    ai_default_provider: str | None = None
    ai_default_model_class: str | None = None


class ProjectValidation(BaseModel):
    valid: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    migrations_applied: list[str] = Field(default_factory=list)


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    path: str
    parent_path: str | None = None
    directories: list[DirectoryEntry] = Field(default_factory=list)


class ProjectNode(BaseModel):
    """The project's own node (file: project.md). Singleton per folder.

    For a flat (single-book) project, this carries the book's metadata
    and blurb. Per decisions_project_nesting, when nesting lands the same
    model represents universe/series/book by different field values —
    no separate "book" kind needed.
    """

    id: str = "project"
    title: str
    body: str = ""
    revision: str = ""
    entry_type: str = "project:project"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class SaveProjectNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    base_revision: str | None = None
    entry_type: str = "project:project"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
