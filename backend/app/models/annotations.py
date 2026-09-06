from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    """ADR-0085 §3. Literal substring query (never regex); `match_case` and
    `whole_word` are the only options; `kinds` filters hits to those node kinds
    (None = every kind the corpus holds)."""

    query: str = ""
    match_case: bool = False
    whole_word: bool = False
    kinds: list[str] | None = None
    include_open_todos: bool = False


class SearchHit(BaseModel):
    """One search result (ADR-0085 §2): a node, a field, and — for a body hit
    — the anchored character range a future replace writes through. `kind` is
    the index's kind (or the synthetic `"project"` bucket for a TODO not tied
    to a scene), not the closed `manuscript|lore|project` set of before, so a
    hit always opens through the node's own kind."""

    kind: str = "manuscript"
    entry_type: str = ""
    file_id: str
    path: str
    line: int
    excerpt: str
    todo_id: str | None = None
    field: Literal["body", "metadata"] = "body"
    start: int = 0
    end: int = 0
    revision: str = ""
    owned: bool = True
    # The matched text itself (ADR-0085 §4 rule 2): `body[start:end]` for a body
    # hit, so a replace can verify the range still matches what the query found
    # before writing through it. Empty for a metadata hit — those never replace.
    text: str = ""


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)


class ReplaceHitRef(BaseModel):
    """One hit the pane asks to replace — the anchor a `SearchHit` carried back
    to it (ADR-0085 §4). `field` is carried so a metadata hit sent by mistake
    (or a stale client) reports `not_replaceable/metadata` rather than being
    silently dropped."""

    file_id: str
    field: Literal["body", "metadata"] = "body"
    start: int
    end: int
    text: str
    revision: str


class ReplaceRequest(BaseModel):
    """ADR-0085 §4. `replacement` is the literal text every hit is replaced
    with; empty deletes the matches. `hits` may span many nodes — one write per
    node, through that node's own save."""

    replacement: str = ""
    hits: list[ReplaceHitRef] = Field(default_factory=list)


ReplaceStatus = Literal["replaced", "stale", "not_replaceable"]


class ReplaceOutcome(BaseModel):
    """One hit's fate (ADR-0085 §4): `reason` names why a `not_replaceable` or
    `stale` hit didn't write — `"inherited" | "metadata" | "kind" | "unknown" |
    "overlap"` for `not_replaceable`, `"changed"` for `stale`. `revision` is the
    node's new save revision after a `replaced` write, else `None`."""

    file_id: str
    start: int
    end: int
    status: ReplaceStatus
    reason: str | None = None
    revision: str | None = None


class ReplaceResponse(BaseModel):
    """Per-hit outcomes, always 200 (ADR-0085 §4) — a mixed batch has no single
    status to 409 on. `replaced_nodes` is the number of distinct nodes that
    actually got a write, for the pane's "twelve hits across seven nodes" tally."""

    outcomes: list[ReplaceOutcome] = Field(default_factory=list)
    replaced_nodes: int = 0
