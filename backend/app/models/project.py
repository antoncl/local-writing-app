from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.base import (
    AIPolicy,
    MetadataValue,
)


class CreateProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str = Field(default="Untitled Project", min_length=1)
    # What the new project inherits from (#425). **Unset is not "nothing"
    # here** — it means "take the default", which is *every ancestor project*
    # between the machine root and this folder. That asymmetry with the stored
    # key (where absent genuinely means nothing, #309) is the point: a
    # declaration nobody wrote should follow the folder layout the author just
    # chose, while a declaration someone *did* write must be honoured verbatim.
    # `[]` says so explicitly and creates a flat project.
    inherits: list[str] | None = None


class OpenProjectRequest(BaseModel):
    root_path: str = Field(min_length=1)


class AncestorCandidate(BaseModel):
    """One folder between the configured base and the open project (#309).

    **Every** ancestor folder is reported, not only the ones that could be
    layers, and that is deliberate: a folder silently missing from this list
    reads as a bug, while a folder present and marked `is_project: false` both
    explains itself and warns that something up there may not be what the
    author thought it was.

    So a row is in one of three states:

    - `is_project` and `inherited` — a declared layer;
    - `is_project` and not `inherited` — available, and the wizard offers it;
    - not `is_project` — an organisational folder, shown and not offerable.
    """

    path: str
    name: str
    is_project: bool = False
    inherited: bool = False
    # The manifest title, when there is one to read — `None` otherwise, and
    # never a fallback to `name`. #311's breadcrumb renders one path whose leaf
    # is the open project's title, so labelling an ancestor by its folder would
    # mix two naming schemes in a single line; #309's own layer-label rule
    # ("a layer's name follows the project, not its position") already settled
    # which one wins.
    #
    # **`None` does not mean "not a project" — read `is_project` for that.**
    # Three different states arrive here as null: a folder with no manifest, a
    # project whose manifest has a blank or missing `title`, and a project whose
    # manifest could not be read at all. Only the first is "not a project", and
    # conflating them is a live hazard for #318's wizard, which must decide
    # whether a row is offerable: keyed on `title` it would refuse a perfectly
    # declarable ancestor that simply has no title.
    title: str | None = None


class ProjectChild(BaseModel):
    """A project folder directly inside this one — the roster #310 renders."""

    path: str
    name: str
    title: str


class ProjectInfo(BaseModel):
    title: str
    root_path: str
    # The machine root — the outer bound of this project's layer walk (#429).
    # Reported, never accepted: it is machine settings, one folder for every
    # project. `None` when no root is configured, which means no bound and so a
    # chain of length one.
    projects_base_folder: str | None = None
    ai_policy: AIPolicy = "off"
    # Outermost first, matching layer rank. Carries the whole enumeration with
    # a flag rather than the declared subset: #311's switcher filters this,
    # while #318's wizard needs the *un*declared rows to offer them, and one
    # shape serving both is what stops the second endpoint asking the same
    # question a different way.
    ancestors: list[AncestorCandidate] = Field(default_factory=list)
    children: list[ProjectChild] = Field(default_factory=list)


class UpdateProjectSettingsRequest(BaseModel):
    # No `projects_base_folder` (#429): the walk's bound is the machine root,
    # so it is changed in machine settings, once, for every project — not per
    # project, which is what let two levels of one chain disagree.
    ai_policy: AIPolicy | None = None
    # The declaration (#309). Partial update like the rest: `None` leaves it
    # alone, `[]` clears it. Entries may be absolute or relative to the
    # project; they are stored relative so a renamed shelf does not invalidate
    # every book beneath it.
    inherits: list[str] | None = None


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
