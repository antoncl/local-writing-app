from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.base import (
    MetadataValue,
)
from app.models.schema import PromptInputDefinition


class StructureNode(BaseModel):
    id: str
    type: str
    title: str
    scene_id: str | None = None
    # Scene's current status value (the select-option value, e.g. "draft").
    # Surfaced here so the manuscript tree can render a colored stripe
    # without the frontend doing a per-scene fetch. None for non-leaf
    # nodes (acts/chapters/etc.) and for scenes without a status set.
    status: str | None = None
    # Scene's instance-level color override (metadata.color, a palette
    # swatch id) — lets the tree row reflect per-scene color tweaks.
    color: str | None = None
    # Full scene front-matter `metadata` dict (pov, characters, locations,
    # color, …) surfaced onto the roster so the view evaluator can filter the
    # Draft pane by scene fields (status/pov/…) in one pass, no per-scene fetch
    # (#184 Phase 3). A projection of leaf front-matter like status/color —
    # None for non-scene nodes; stripped on write so it never drifts on disk.
    metadata: dict[str, Any] | None = None
    computed_metadata: dict[str, Any] = Field(default_factory=dict)
    children: list[StructureNode] = Field(default_factory=list)


class StructureDocument(BaseModel):
    root: StructureNode


class Scene(BaseModel):
    id: str
    title: str
    body: str
    revision: str
    status: str = "draft"
    entry_type: str = "scene:scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class CreateSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    parent_id: str | None = None


class CreateStructureNodeRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = Field(min_length=1)
    parent_id: str | None = None


class RenameStructureNodeRequest(BaseModel):
    title: str = Field(min_length=1)


class MoveStructureNodeRequest(BaseModel):
    target_parent_id: str = Field(min_length=1)
    position: int = Field(default=0, ge=0)


class ResearchNote(BaseModel):
    """A single research note file.

    Parallels Scene/LoreEntry. Storage at `research/notes/<slug>.md`
    with YAML front matter (id, title, entry_type, metadata) and a
    markdown body. v1 schema: `tags` is the only metadata field; no
    status, aliases, or related_entries (per
    decisions-research-strategy).
    """

    id: str
    title: str
    body: str = ""
    revision: str = ""
    entry_type: str = "research:note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class SaveResearchNoteRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    base_revision: str | None = None
    entry_type: str = "research:note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class MoveLoreNoteToResearchResponse(BaseModel):
    """Result of POST /api/lore/{id}/move-to-research.

    Carries the new note's id, the updated research tree, the dropped
    metadata field ids (intentional data loss from the v1 minimal note
    schema — surfaced so the UI can warn), and the refreshed lore list
    so callers can update both panes in one round-trip.
    """

    note_id: str
    tree: StructureDocument
    dropped_fields: list[str] = Field(default_factory=list)
    lore: LoreEntryList


class SaveSceneRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str
    base_revision: str | None = None
    status: str = "draft"
    entry_type: str = "scene:scene"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # The lore entries the prose editor detected in this body — the *dynamic
    # context*, one of the three sources a snapshot witness records (ADR-0043,
    # `docs/design/snapshots-and-the-witness.md` §4). The frontend owns the
    # alias matcher, so the ids the author sees underlined are the ids that
    # reach the backend; nothing here rescans the prose.
    #
    # Read only by the automatic capture inside this save. It is derived data
    # about an authored file and never enters the scene's front matter.
    #
    # **`None` is "not observed", `[]` is "observed and empty".** A caller with
    # no prose editor behind it — the acts/chapters save path, a script — says
    # nothing rather than claiming emptiness, and the witness then records two
    # sources instead of three so membership drift narrows accordingly.
    dynamic_context: list[str] | None = None


class LoreEntrySummary(BaseModel):
    id: str
    title: str
    body: str = ""
    entry_type: str = "lore:lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class LoreEntry(BaseModel):
    id: str
    title: str
    body: str
    revision: str
    entry_type: str = "lore:lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""
    # Set when this entry was fork-to-here'd (#313 / ADR-0039): the relative path
    # from the base folder to the layer it was copied down from. It severs
    # inheritance and silences the shadow warning for the copied id. `None` for
    # an ordinary entry that never forked.
    forked_from: str | None = None
    # The metadata fields whose effective value comes from a layer override in
    # this project's chain rather than from inherited canon (#314 / ADR-0039).
    # The backend computes it during the fold; the frontend renders the
    # `ti-versions` override mark against these fields (deferred to #314 slice-E
    # PR 2). Empty for an entry with no overrides above its owning layer.
    overridden_fields: list[str] = Field(default_factory=list)


class LoreEntryList(BaseModel):
    entries: list[LoreEntrySummary] = Field(default_factory=list)


class CreateLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "lore:lore_note"


class SaveLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str
    base_revision: str | None = None
    entry_type: str = "lore:lore_note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # ADR-0042's authoring layer L, as a layer id (#314 / ADR-0045). The save
    # *is* the 0042 edit unit, so L rides its request body rather than an ambient
    # header. `None` = no explicit write target: a save of an *inherited* entry
    # then fails loudly rather than silently choosing one (ADR-0039). When set,
    # `L == owning layer` writes the owning file (direct edit) and `L < owning`
    # writes a sparse override delta at L. The frontend rail picker (PR 2) sends
    # it, defaulting to the open project (the rest-position override).
    authoring_layer_id: str | None = None


class PromptEntrySummary(BaseModel):
    id: str
    title: str
    body: str = ""
    entry_type: str = "prompt:base"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # Per-entry input declarations. Each prompt declares the parameters its
    # template body references via `{{ input.<name> }}`. Used to be on the
    # entry-type's PromptEntryTypeExtras; now lives where the template that
    # uses it lives. The Type-level inputs field stays in the model for
    # backwards-compatibility on read but is no longer consulted at runtime.
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    source_layer_id: str = ""
    source_layer_label: str = ""


class PromptEntry(BaseModel):
    id: str
    title: str
    body: str
    revision: str
    entry_type: str = "prompt:base"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class PromptEntryList(BaseModel):
    entries: list[PromptEntrySummary] = Field(default_factory=list)


class CreatePromptEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "prompt:base"


class SavePromptEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str
    base_revision: str | None = None
    entry_type: str = "prompt:base"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    inputs: list[PromptInputDefinition] = Field(default_factory=list)


class MutationSetRow(BaseModel):
    """One field-change row of a reusable mutation set (#62): a
    `(field, op, value)` triple applied to a chosen entity at apply time. The
    entity is NOT stored — the set is a template bound to an entity on use. Op is
    the collection operator (replace / add / remove) shared with #58 markers."""

    field: str
    op: str = "replace"
    value: str = ""


class MutationSetEntrySummary(BaseModel):
    id: str
    title: str
    entry_type: str = "mutation_set:mutation_set"
    # The lore entry-type the rows target (e.g. "character"); scopes the apply
    # picker so only matching sets are offered for a given entity (#62).
    target_entry_type: str = ""
    row_count: int = 0
    source_layer_id: str = ""
    source_layer_label: str = ""


class MutationSetEntry(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    rows: list[MutationSetRow] = Field(default_factory=list)
    source_layer_id: str = ""
    source_layer_label: str = ""


class MutationSetEntryList(BaseModel):
    entries: list[MutationSetEntrySummary] = Field(default_factory=list)


class CreateMutationSetEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    rows: list[MutationSetRow] = Field(default_factory=list)


class SaveMutationSetEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    rows: list[MutationSetRow] = Field(default_factory=list)


class AssistantEntrySummary(BaseModel):
    """One assistant, as the merged roster presents it (#332).

    Curation — is this in the author's roster, and where in it — is the layer
    traversal's answer, not the file's, so it rides in `computed_metadata`
    (`listed`, `position`) as declared computed fields rather than as top-level
    projections. That keeps it out of `metadata`, which round-trips to disk on
    save, and lets every surface read it through the ordinary field machinery
    instead of special-casing a key — the mistake `source_layer_*` makes and
    #232 tracks.

    `position` is unset exactly when `listed` is false: an assistant no layer
    has listed has no priority to report — it trails in the unlisted tail, whose
    order is a fallback rather than an expressed one.
    """

    id: str
    title: str
    entry_type: str = "assistant:assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class AssistantEntry(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "assistant:assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # Same curation pair the roster stamps (see AssistantEntrySummary). Carried
    # here too because the editor reads the single entry, and a computed field
    # that only some read paths fill renders as a permanently blank locked row.
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class AssistantEntryList(BaseModel):
    entries: list[AssistantEntrySummary] = Field(default_factory=list)


class CreateAssistantEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "assistant:assistant"
    # "" → machine layer (the default). Otherwise the layer-id (project root
    # hash) where the file should land.
    layer_id: str = ""


class SaveAssistantEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "assistant:assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class ReorderAssistantsRequest(BaseModel):
    # "" → machine layer. Otherwise the layer id (hash of folder path) as
    # returned in source_layer_id on each entry.
    #
    # This is the layer whose `.order.yaml` gets REWRITTEN, which since #332 is
    # not necessarily where the listed assistants live: dragging an inherited
    # assistant names its id in the local file. `ordered_ids` is therefore the
    # local layer's whole opinion, not a per-layer slice of the roster.
    #
    # Omit it (None) to mean the LOCAL layer — the normal case for a curation
    # gesture, and what lets the pane drag without resolving layer ids (#318).
    layer_id: str | None = None
    ordered_ids: list[str] = Field(default_factory=list)


class UnlistAssistantRequest(BaseModel):
    # The layer that stops showing the assistant, from here inward (#332). The
    # assistant's own file is never touched, so un-listing an inherited entry
    # cannot remove it from the ancestor that owns it. Omit it (None) for the
    # local layer — see ReorderAssistantsRequest.
    layer_id: str | None = None
    entry_id: str = Field(min_length=1)


StructureNode.model_rebuild()
