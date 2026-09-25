from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.snapshots import Snapshot

# ADR-0090 §2 / ADR-0091 §2: the route a change-candidate reason was found
# by. Defined here, ahead of `TodoSource`, because a review item's source
# names its FIRST reason's route (§3) and `ChangeCandidateReason` below
# reuses the same alias. `mentioned_by_source` (ADR-0091 S1) is the mirror of
# `mentions_source`: the source's own prose names the candidate, rather than
# the candidate's prose naming the source.
ChangeCandidateRoute = Literal[
    "references_source",
    "referenced_by_source",
    "mutates_source",
    "mentions_source",
    "mentioned_by_source",
]


class TodoSource(BaseModel):
    """Where a review item's change came from (ADR-0090 §3): the source
    entry, the baseline it was measured from (`""` = the whole entry, not a
    snapshot), the route of the candidate's first reason, and — only when
    that reason is `mutates_source` — the marker it names."""

    node_id: str
    snapshot_id: str = ""
    reason: ChangeCandidateRoute
    marker_id: str = ""


class TodoItem(BaseModel):
    id: str
    text: str
    status: Literal["open", "done"] = "open"
    scope: Literal["project", "scene", "node"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None
    # ADR-0090 §3: a `node`-scoped item's dependent, and the source block a
    # review item the app wrote carries (absent on a writer-authored todo).
    node_id: str | None = None
    source: TodoSource | None = None


class TodoDocument(BaseModel):
    items: list[TodoItem] = Field(default_factory=list)


class CreateTodoRequest(BaseModel):
    text: str = Field(min_length=1)
    scope: Literal["project", "scene", "node"] = "project"
    scene_id: str | None = None
    anchor_id: str | None = None
    node_id: str | None = None
    source: TodoSource | None = None


class UpdateTodoRequest(BaseModel):
    text: str | None = None
    status: Literal["open", "done"] | None = None
    scope: Literal["project", "scene", "node"] | None = None
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
    """One resolved mutation record — a mutation-set row joined at the scene
    anchor that places it (ADR-0095 §1/§3/§5):

        <!-- mutate:set=SET_ID;id=ANCHOR_ID -->

    Unlike a base metadata value, its effect is scoped to (scene, position) and
    later manuscript positions — it is the record the resolver (#51) slices. Like
    embedded todos these are a rebuildable index over scenes, never owned by a
    live editor pane.

    A record is one set row at one anchor (ADR-0095 §3): `marker_id =
    f"{anchor_id}.{row_id}"` is the `(anchor, row)` identity everything that
    keys on a record — closes, `exclude`, the change-candidate dedupe, review
    items, the scrubber's stops — keys on. `unit_id` is the anchor id (the
    authoring/presentation granularity the pill, timeline and scrubber group
    by); `unit_name` and `name` are the set's title (may be "")."""

    marker_id: str
    entity_id: str
    field: str
    # Collection operator (#58). `replace` (v1.0 default) sets the whole field;
    # `add`/`remove` accumulate/drop one collection element (gated to
    # multi_select / tags / entity_ref_list at validation time).
    op: str = "replace"
    value: str = ""
    # The set's title (may be ""), echoed onto `unit_name` too (ADR-0095 §1).
    name: str = ""
    group: str = ""
    # Mutation-unit tie (#69, ADR-0016; ADR-0095 §1): the anchor id — the
    # authoring/presentation granularity (pill, timeline, scrubber, close
    # picker group by it); each record's lifetime stays its own (ADR-0002).
    unit_id: str = ""
    unit_name: str = ""
    # ADR-0095 §3: the record's identity components. `anchor_id` is the scene
    # anchor's own id (same value as `unit_id`); `set_id` names the
    # `mutation_set` node the row came from; `row_id` is the row's own stable
    # id within that set.
    anchor_id: str = ""
    set_id: str = ""
    row_id: str = ""
    scene_id: str
    offset: int = 0  # char offset of the anchor in the scene body (position-granular)
    line: int = 1
    scene_path: str = ""


class MutationMarkerList(BaseModel):
    items: list[MutationMarker] = Field(default_factory=list)


ChangeCandidateTier = Literal["declared", "marker_untouched", "mention"]


class ChangeCandidateReason(BaseModel):
    """One route a `ChangeCandidate` was found by (ADR-0090 §2, ADR-0091 §2).
    `field_id` is the referencing field for the two reference routes and the
    marker's field for `mutates_source`; it is empty for both mention
    routes — `mentions_source` and `mentioned_by_source` — since the route
    itself names the direction and neither reason names a field. `marker_id`
    and `field_changed` are `mutates_source` only — `field_changed` is
    whether the marker's own field is among the diff's `changed_fields`
    (always True when there is no baseline)."""

    route: ChangeCandidateRoute
    field_id: str = ""
    marker_id: str = ""
    field_changed: bool = False


class ChangeCandidate(BaseModel):
    """One dependent of a settled change, with every route that found it
    (ADR-0090 §2). A node reachable by more than one route appears once."""

    id: str
    kind: str
    entry_type: str
    title: str
    tier: ChangeCandidateTier
    reasons: list[ChangeCandidateReason] = Field(default_factory=list)


class ChangeCandidateLayer(BaseModel):
    """One file that composes the source at the open layer (ADR-0090
    Amendment 3): the owning layer's file (`is_override=False`) or an
    override delta strictly between the owner and the open layer. Each is
    measured against its OWN baseline in its OWN snapshot lane —
    `baseline_snapshot_id=""` means this lane had no propagation baseline yet,
    so `whole=True` and `changed_fields` lists every field its current rows
    touch (a delta) or is empty with the caller's own whole-entry meaning (the
    owning file, when the top-level baseline is empty)."""

    layer_id: str
    layer_label: str
    is_override: bool
    baseline_snapshot_id: str = ""
    changed_fields: list[str] = Field(default_factory=list)
    whole: bool


class ChangeCandidateSet(BaseModel):
    """The candidate set for one settled lore change (ADR-0090 §2) — a list of
    `(node, reasons)` and nothing else; no score, no threshold, no cut.
    `whole_entry=True` (no baseline given) means every field counts as changed,
    so every `mutates_source` marker ranks as `declared`. `changed_fields` is
    the union over every composing file (Amendment 3); `layers` names each
    one's own lane so a surface can say "and the book's override" without
    re-deriving it."""

    source_id: str
    baseline_snapshot_id: str = ""
    changed_fields: list[str] = Field(default_factory=list)
    body_changed: bool
    whole_entry: bool
    items: list[ChangeCandidate] = Field(default_factory=list)
    layers: list[ChangeCandidateLayer] = Field(default_factory=list)


class ChangeMessage(BaseModel):
    """ADR-0090 §4 / ADR-0093 §4: the pre-filled first message for a review
    item's Propose conversation — the follow-up question alone. The change
    itself is not rendered here: it rides as the prompt's
    `use(node, snapshot=id)` pick, seeded into `Follow a change`'s hidden
    `source`/`baseline` inputs from the review item. `baseline_snapshot_id`
    echoes the baseline actually used (same tri-state as `change_candidates`:
    `""` means the whole entry, not a snapshot) — the same value the seeder
    hands to `baseline`. Never sent — only fills the chat composer; the
    writer still presses Send."""

    source_id: str
    baseline_snapshot_id: str = ""
    text: str


class PropagateRequest(BaseModel):
    """The confirm step's write (ADR-0090 §1/§3/§5): the candidates the
    writer kept, measured against the same baseline semantics as the
    read-only candidate endpoint. `kept` may not be empty — the service
    refuses a confirm that keeps nothing, before any write."""

    baseline_snapshot_id: str | None = None
    kept: list[str] = Field(default_factory=list)


class PropagateResponse(BaseModel):
    """What confirming a propagation writes, and nothing else (ADR-0090 §5):
    one review item per kept candidate, in candidate order, and the new
    baseline snapshot of the source. No dependent's file is touched.
    `layer_snapshots` (Amendment 3) is the same capture for every existing
    override delta between the owner and the open layer, one per lane;
    `snapshot` stays the owning capture."""

    todos: TodoDocument
    created: list[str] = Field(default_factory=list)
    snapshot: Snapshot
    layer_snapshots: list[Snapshot] = Field(default_factory=list)


class EffectiveStateResponse(BaseModel):
    """Effective mutation overrides for one lore entity as of a (scene,
    position) — the fields with a live mutation there, each mapped to its
    winning value. Drives the lore-card time-slider re-render (#33).

    Scalar fields resolve to a string; collection fields (multi_select /
    entity_ref_list) resolve to a `list[str]` — the datatype matches the field
    (ADR-0009). A reference-keyed list resolves to its folded items, a list of
    member maps; the member paths its records address never leave the resolver
    (ADR-0089 §3)."""

    entity_id: str
    scene_id: str
    position: int | None = None
    values: dict[str, str | list[str] | list[dict[str, Any]]] = Field(default_factory=dict)


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


class ReferenceGraphEdge(BaseModel):
    """One field-qualified forward edge (ADR-0089 §9): `src` references `dst`
    through `field_id`. Additive alongside `ReferenceGraphResponse.refs` — the
    frontend's keyed-referrer index (which entries hold a relationship item
    keyed by a given target) needs to know *which field* an edge came through,
    which the flattened `refs` dict deliberately discards."""

    src: str
    dst: str
    field_id: str


class ReferenceGraphResponse(BaseModel):
    """Forward reference adjacency for the whole project (#184 Phase 2): each
    node id → the ids it references through any entity_ref / entity_ref_list
    field. The frontend inverts this into a reverse index the view evaluator's
    computed `references` field projects over (`field_of(set, "references")`),
    so backlinks compose with set algebra instead of a bespoke per-node call.
    Only nodes that reference something appear as keys.

    `edges` carries the same forward adjacency field-qualified and undeduped
    across fields (ADR-0089 §9) — kept alongside `refs`, not instead of it, so
    existing consumers of `refs` are unaffected."""

    refs: dict[str, list[str]] = Field(default_factory=dict)
    edges: list[ReferenceGraphEdge] = Field(default_factory=list)


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
    # The excerpt is a window around the match (#1868); these say whether text
    # was clipped before/after it. The pane draws the ellipses itself, outside
    # the highlighted text, so a query of "…" can never mark them.
    clipped_before: bool = False
    clipped_after: bool = False
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
    "overlap" | "rejected"` for `not_replaceable`, `"changed"` for `stale`.
    `detail` carries the save's own human message when `reason == "rejected"`
    (e.g. a 422 from `validate_scene_markdown`), else `None`. `revision` is the
    node's new save revision after a `replaced` write, else `None`."""

    file_id: str
    start: int
    end: int
    status: ReplaceStatus
    reason: str | None = None
    detail: str | None = None
    revision: str | None = None


class ReplaceResponse(BaseModel):
    """Per-hit outcomes, always 200 (ADR-0085 §4) — a mixed batch has no single
    status to 409 on. `replaced_nodes` is the number of distinct nodes that
    actually got a write, for the pane's "twelve hits across seven nodes" tally."""

    outcomes: list[ReplaceOutcome] = Field(default_factory=list)
    replaced_nodes: int = 0
