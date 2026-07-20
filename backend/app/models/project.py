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


class UpdateProjectSettingsRequest(BaseModel):
    projects_base_folder: str | None = None
    ai_policy: AIPolicy | None = None


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


# The project node's file name is the same word at every layer — which is why the
# id must not be (#343): the name is an address, the front-matter id is the
# identity, and the index reads the latter off the file like it does for every
# other node.
PROJECT_NODE_FILENAME = "project.md"


class ProjectNode(BaseModel):
    """The project's own node (file: project.md). Singleton per folder.

    For a flat (single-book) project, this carries the book's metadata
    and blurb. Per decisions_project_nesting, when nesting lands the same
    model represents universe/series/book by different field values —
    no separate "book" kind needed.
    """

    # Minted like every other node (#343). The project node is *addressed*
    # without an id — one singleton per folder, resolved by path — but a
    # stable address is not an identity: under nesting (#7) every layer has
    # a project node, and a constant id would collide by construction.
    id: str
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
