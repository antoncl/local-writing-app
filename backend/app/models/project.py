from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.base import (
    AIPolicy,
    MetadataValue,
)
from app.models.schema import MetadataSchema


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


class ProjectChainLayer(BaseModel):
    """One layer of the RESOLVED chain — what this project is actually built
    from, outermost first, the open project last (#432).

    The twin of `AncestorCandidate`, and the distinction is the point.
    `ancestors` is the *enumeration*: every folder the walk crossed, flagged
    rather than filtered, because the declaration editor (#426) has to offer
    the undeclared rows and mark the non-project ones. This is the *chain*:
    only the layers that contribute, already selected and already named.

    It exists because the frontend was re-deriving it — filtering `ancestors`
    on `inherited && is_project` and labelling with `title || name`, a
    transcription of `_project_layer_folders` and `_layer_label_for_folder`
    that the walker had already computed. Two implementations of one traversal,
    and they disagreed. `id` and `label` are read straight off `IndexLayer`,
    so a consumer cannot drift from the walk again.
    """

    id: str
    label: str
    path: str
    # The open project itself, always the innermost entry. Flagged rather than
    # dropped: the breadcrumb renders the ancestors and lets the project
    # switcher be the last crumb, while the schema-layers view wants the whole
    # sequence. Filtering here would just move the re-derivation.
    is_root: bool = False


class ProjectInfo(BaseModel):
    title: str
    root_path: str
    # The machine root — the outer bound of this project's layer walk (#429).
    # Reported, never accepted: it is machine settings, one folder for every
    # project. `None` when no root is configured, which means no bound and so a
    # chain of length one.
    projects_base_folder: str | None = None
    ai_policy: AIPolicy = "off"
    # Whether this project states no policy of its own, so `ai_policy` above is
    # inherited from an ancestor rather than set here (#471). The Project pane's
    # "Inherit" option needs it to show the deferred state as selected: without
    # it, clearing a policy would appear to snap the radio to whatever the chain
    # resolves to, with no sign the clear took. This is only the on/off of
    # "has an opinion here" — *which* ancestor supplied the value is provenance
    # (#313), deliberately not surfaced by this field.
    ai_policy_inherited: bool = False
    # Outermost first, matching layer rank. Carries the whole enumeration with
    # a flag rather than the declared subset: #311's switcher filters this,
    # while #318's wizard needs the *un*declared rows to offer them, and one
    # shape serving both is what stops the second endpoint asking the same
    # question a different way.
    ancestors: list[AncestorCandidate] = Field(default_factory=list)
    # The resolved chain over the same walk (#432) — the declared subset, named
    # by the walker. Ships beside `ancestors`, not instead of it: they answer
    # different questions and both have a consumer.
    chain: list[ProjectChainLayer] = Field(default_factory=list)
    children: list[ProjectChild] = Field(default_factory=list)
    # The project node's authored fields (project.md), resolved nearest-explicit-
    # wins over the layer chain (#317) — the same fold as `ai_policy`, applied to
    # the node's metadata rather than the manifest's policy. This is the *channel
    # to the model*: it is what makes `{{ project.metadata.measurement_system }}`
    # resolve in a prompt template, with a value set on an ancestor (measurement
    # is world canon) reaching every book beneath it. A key no layer authors is
    # simply absent — templates guard with `{% if %}`. Provenance (which layer
    # supplied each value) is deliberately not carried here; the editor's
    # inherited/override display is the wizard's review pane (#318, slice 4).
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class UpdateProjectSettingsRequest(BaseModel):
    # No `projects_base_folder` (#429): the walk's bound is the machine root,
    # so it is changed in machine settings, once, for every project — not per
    # project, which is what let two levels of one chain disagree.
    # `None` leaves it unchanged (partial update, like `inherits`); one of the
    # three policies sets it explicitly; `"inherit"` *clears* it back to no
    # opinion so the chain resolves it (#471) — the only way back once a radio
    # has been clicked. `"inherit"` is a wire-only signal: the stored and
    # resolved type stays the three real policies, because inheriting is the
    # *absence* of a stated policy on disk, not a fourth value of it.
    ai_policy: AIPolicy | Literal["inherit"] | None = None
    # The declaration (#309). Partial update like the rest: `None` leaves it
    # alone, `[]` clears it. Entries may be absolute or relative to the
    # project; they are stored relative so a renamed shelf does not invalidate
    # every book beneath it.
    inherits: list[str] | None = None


class ProspectiveProjectNodeRequest(BaseModel):
    """The wizard's review-pane query for a not-yet-created project (#318 slice
    4). `inherits` is the ticked candidates from the location step — absolute
    ancestor folder paths (`AncestorCandidate.path`), not the project-relative
    form the manifest stores, because the project has no manifest yet."""

    root_path: str = Field(min_length=1)
    inherits: list[str] = Field(default_factory=list)


class ProspectiveProjectNode(BaseModel):
    """What the review pane renders for a not-yet-created project (#318 slice 4).

    The prospective twin of `ProjectInfo.metadata` (#317) plus the provenance
    that field omits. `metadata_schema` is the merged schema over the ticked
    chain (so a `select` shows the real vocabulary); `metadata` is the inherited
    values, nearest-explicit-wins (a key no ancestor states is absent, and the
    pane falls to the schema default); `field_sources` names, per resolved key,
    the ancestor layer that supplied it — the "Reset to <source>" label (§8).
    """

    metadata_schema: MetadataSchema
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    field_sources: dict[str, str] = Field(default_factory=dict)


class ProjectValidation(BaseModel):
    valid: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    migrations_applied: list[str] = Field(default_factory=list)


class DirectoryEntry(BaseModel):
    name: str
    path: str
    # Picker hints (#530): `is_project` marks a folder that already holds a
    # project (`project.yaml`); `is_empty` marks a safe create target.
    is_project: bool = False
    is_empty: bool = False


class DirectoryListing(BaseModel):
    path: str
    parent_path: str | None = None
    directories: list[DirectoryEntry] = Field(default_factory=list)
    # Whether the folder being *shown* already holds a project (drives the
    # "Already a project" note above "Select this folder").
    is_project: bool = False


class DirectoryRoot(BaseModel):
    """A jump-off point for the picker: a drive letter, the home folder, or
    the Documents folder (#530)."""

    label: str
    path: str
    kind: str  # "drive" | "home" | "documents"


class PathProbe(BaseModel):
    """Non-throwing validation of a typed path, for the picker's path field
    (#530). Unlike `list_directories`, a missing or bad path yields
    `is_dir=False` rather than a 404, so the field can validate on every
    keystroke. `input` echoes the query so the client can ignore results that
    a later keystroke has superseded."""

    input: str
    is_dir: bool = False
    is_project: bool = False


class CreateDirectoryRequest(BaseModel):
    parent: str
    name: str


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
