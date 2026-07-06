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
    id: str
    title: str
    entry_type: str = "assistant:assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class AssistantEntry(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "assistant:assistant"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
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
    layer_id: str = ""
    ordered_ids: list[str] = Field(default_factory=list)


StructureNode.model_rebuild()
