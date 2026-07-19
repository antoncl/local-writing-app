from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models_views import NodePickerConfig


class ScopedTag(BaseModel):
    """A known tag with a scope (which kinds / sub-types it's suggested on).

    Scope reuses NodePickerConfig's kinds + per-kind entry_types vocabulary.
    An empty scope means "suggest everywhere" (legacy flat tags upgrade to
    this)."""

    name: str
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)


class KnownTags(BaseModel):
    tags: list[ScopedTag] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _accept_flat_tags(cls, value: Any) -> Any:
        # Defensive upgrade of the legacy flat shape (list[str]) and any
        # caller still passing bare strings → scoped entries with empty scope.
        if isinstance(value, list):
            return [
                {"name": item, "scope": {}} if isinstance(item, str) else item
                for item in value
            ]
        return value


class TagUsage(BaseModel):
    name: str
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)
    count: int = 0


class AssistantTag(BaseModel):
    """One entry in the machine-global assistant-tag vocabulary (#88). Assistants
    live machine-globally, so their tag vocabulary can't live in a project's
    per-project tags.yaml — it has its own store. `color` is a swatch id from the
    machine palette (reused by SwatchPicker/getSwatch), or None when unassigned."""

    name: str
    color: str | None = None


class AssistantTagList(BaseModel):
    tags: list[AssistantTag] = Field(default_factory=list)


class SetAssistantTagColorRequest(BaseModel):
    # A palette swatch id, or null to clear the color.
    color: str | None = None


class TagsOverview(BaseModel):
    tags: list[TagUsage] = Field(default_factory=list)


class UpdateTagScopeRequest(BaseModel):
    name: str = Field(min_length=1)
    scope: NodePickerConfig = Field(default_factory=NodePickerConfig)


class MergeTagsRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)
    target: str = Field(min_length=1)


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


class EmbeddedTodo(BaseModel):
    """An in-prose TODO marker, enumerated by scanning scene bodies. Unlike
    todo.yaml items these live inline in the markdown (status + note baked into
    an HTML-comment marker); this is a rebuildable index over scenes, never
    owned by a live editor pane (GH #45)."""

    todo_id: str
    scene_id: str
    status: Literal["open", "done"] = "open"
    note: str = ""
    text: str = ""
    line: int = 1
    scene_path: str = ""


class EmbeddedTodoList(BaseModel):
    items: list[EmbeddedTodo] = Field(default_factory=list)


class UpdateEmbeddedTodoRequest(BaseModel):
    status: Literal["open", "done"] | None = None
    note: str | None = None


class MutationMarker(BaseModel):
    """A mid-scene lore mutation (#33). A self-contained HTML-comment marker in a
    scene body that sets one field of one lore entry to a new value *at the
    marker's prose position*:

        <!-- mutate:entity=ID;field=KEY;value=ENCODED;id=MARKER_ID -->

    Unlike a base metadata value, its effect is scoped to (scene, position) and
    later manuscript positions — it is the record the resolver (#51) slices. Like
    embedded todos these are a rebuildable index over scenes, never owned by a
    live editor pane; the marker id is minted client-side at insertion (ADR-0001)."""

    marker_id: str
    entity_id: str
    field: str
    # Collection operator (#58). `replace` (v1.0 default, absent from the marker)
    # sets the whole field; `add`/`remove` accumulate/drop one collection element
    # (gated to multi_select / tags / entity_ref_list at validation time).
    op: str = "replace"
    value: str = ""
    # Optional human label for the change (#65), shared across a co-authored set
    # via `group`. Both are display/close-together conveniences, not lifetime
    # frames — each record's interval stays independent (ADR-0015).
    name: str = ""
    group: str = ""
    # Mutation-unit tie (#69, ADR-0016): the authored change this record belongs
    # to — the record's own id for a standalone single-line marker, the legacy
    # `group=` for old co-authored sets, the carrier head's id for multi-row
    # units. Authoring/presentation granularity only (pill, timeline, scrubber,
    # close picker group by it); each record's lifetime stays its own
    # (ADR-0002). `unit_name` is the unit's human label from the head.
    unit_id: str = ""
    unit_name: str = ""
    scene_id: str
    offset: int = 0  # char offset of the marker in the scene body (position-granular)
    line: int = 1
    scene_path: str = ""


class MutationMarkerList(BaseModel):
    items: list[MutationMarker] = Field(default_factory=list)


class UpdateMutationRequest(BaseModel):
    entity_id: str | None = None
    field: str | None = None
    op: str | None = None
    value: str | None = None
    name: str | None = None
    group: str | None = None


class EffectiveStateResponse(BaseModel):
    """Effective mutation overrides for one lore entity as of a (scene,
    position) — the fields with a live mutation there, each mapped to its
    winning value. Drives the lore-card time-slider re-render (#33).

    Scalar fields resolve to a string; collection fields (multi_select / tags /
    entity_ref_list) resolve to a `list[str]` — the datatype matches the field
    (ADR-0009)."""

    entity_id: str
    scene_id: str
    position: int | None = None
    values: dict[str, str | list[str]] = Field(default_factory=dict)


class ReferenceCandidate(BaseModel):
    id: str
    title: str
    kind: str
    entry_type: str
    summary: str = ""
    found: bool = True
    source_layer_id: str = ""
    source_layer_label: str = ""


class ReferenceResolveRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class ReferenceResolveResponse(BaseModel):
    candidates: list[ReferenceCandidate] = Field(default_factory=list)


class ReferenceCandidatesResponse(BaseModel):
    candidates: list[ReferenceCandidate] = Field(default_factory=list)


class Backlink(BaseModel):
    id: str
    title: str
    kind: str
    entry_type: str
    field_id: str
    field_name: str


class ReferenceGraphResponse(BaseModel):
    """Forward reference adjacency for the whole project (#184 Phase 2): each
    node id → the ids it references through any entity_ref / entity_ref_list
    field. The frontend inverts this into a reverse index the view evaluator's
    computed `references` field projects over (`field_of(set, "references")`),
    so backlinks compose with set algebra instead of a bespoke per-node call.
    Only nodes that reference something appear as keys."""

    refs: dict[str, list[str]] = Field(default_factory=dict)


class StructureNodeDeletePreview(BaseModel):
    target_id: str
    target_title: str
    target_type: str
    descendant_scene_count: int = 0
    descendant_container_count: int = 0
    backlinks: list[Backlink] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = ""
    include_scenes: bool = True
    include_lore: bool = True
    include_open_todos: bool = False


class SearchHit(BaseModel):
    kind: Literal["scene", "lore", "project"] = "scene"
    file_id: str
    path: str
    line: int
    excerpt: str
    todo_id: str | None = None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)
