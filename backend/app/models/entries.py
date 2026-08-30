from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.base import (
    MetadataValue,
)
from app.models.schema import PromptContextStrategy, PromptInputDefinition


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
    # Full scene front-matter `metadata` dict (pov, characters, location,
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
    entry_type: str = "manuscript:scene"
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


class _PlotFolderSummary(BaseModel):
    """A `plot/` folder node in a list (plotline, card): one shared shape — only
    the per-family `entry_type` default differs on the subclasses below."""

    id: str
    title: str
    body: str = ""
    entry_type: str = ""
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class _PlotFolderEntry(BaseModel):
    """A single `plot/` folder node (plotline, card): a book-local layered Node
    with schema-driven metadata + a prose body, so identity, the index,
    references, and layered schema all apply for free. Subclasses set only the
    per-family `entry_type` default."""

    id: str
    title: str
    body: str = ""
    revision: str = ""
    entry_type: str = ""
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class _PlotFolderCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = ""
    # A caller-supplied id (ADR-0053 §7): undo-of-delete / redo-of-create
    # recreate a node under its *original* id so refs in other cards'
    # beat_links / causal_links reconnect instead of dangling. Empty = mint a
    # fresh id (the normal create). A collision with an existing node is
    # rejected (409), so this can only ever restore an id, never overwrite one.
    id: str = ""


class _PlotFolderSaveRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    base_revision: str | None = None
    entry_type: str = ""
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class PlotlineSummary(_PlotFolderSummary):
    entry_type: str = "plot:plotline"


class PlotlineEntry(_PlotFolderEntry):
    """A plotline (ADR-0048 §2; ADR-0053 §1): a story thread that IS a plot-template
    instance — a name (the title), a color (metadata), a description (the body), and
    an ordered beat roster (`instance_beats` metadata) copied from a template at
    instantiate then specialized per book, or empty for an ad-hoc thread.
    `source_template_id` / `source_template_name` metadata snapshot its lineage (empty
    for ad-hoc). Cards reference one as their primary plotline and fulfil its beats."""

    entry_type: str = "plot:plotline"


class PlotlineList(BaseModel):
    entries: list[PlotlineSummary] = Field(default_factory=list)


class CreatePlotlineRequest(_PlotFolderCreateRequest):
    entry_type: str = "plot:plotline"


class SavePlotlineRequest(_PlotFolderSaveRequest):
    entry_type: str = "plot:plotline"


class PlotBoard(BaseModel):
    """The plot board (ADR-0048 §3): a per-project layout singleton.

    File `plot-board.md`. Presentation only — card positions, per-column
    ordering, collapsed groups, viewport; it owns no story data. One per open
    book in v1, addressed by path (not id, like the project node) and created
    on first open. The `layout` payload is an opaque dict the board canvas (S7)
    populates; S4a establishes the singleton, get-or-create, and round-trip.
    """

    id: str
    title: str = "Board"
    revision: str = ""
    entry_type: str = "plot:board"
    layout: dict[str, Any] = Field(default_factory=dict)


class SavePlotBoardRequest(BaseModel):
    base_revision: str | None = None
    layout: dict[str, Any] = Field(default_factory=dict)


class CardSummary(_PlotFolderSummary):
    entry_type: str = "plot:card"


class CardEntry(_PlotFolderEntry):
    """A card (ADR-0048 §1): a unit of story function — "this happens, and it
    does this job for the story." A synopsis (the body), a primary `plotline`
    reference, and an optional `scene` reference (0..1 scene per card, 0..n cards
    per scene). Claims (§4) are deferred to a workflow-driven slice — see the
    `plot:card` schema comment in default_schema.py for the reasoning."""

    entry_type: str = "plot:card"


class CardList(BaseModel):
    entries: list[CardSummary] = Field(default_factory=list)


class CreateCardRequest(_PlotFolderCreateRequest):
    entry_type: str = "plot:card"


class SaveCardRequest(_PlotFolderSaveRequest):
    entry_type: str = "plot:card"


class RealizeCardRequest(BaseModel):
    """Body for POST /api/plot/cards/{id}/realize (ADR-0048 §1, *realize*): where
    the scene minted from the card lands in the manuscript. `parent_id` is an
    optional container node; absent (or unknown) drops the scene into the first
    container, matching create_scene's placement fallback. Send `{}` for the
    default placement. Seed-from-manuscript takes no body."""

    parent_id: str | None = None


class PlotBoardPlotlineBeat(BaseModel):
    """A beat on a plotline node as the board renders it (ADR-0053 §3): its stable
    `beat_id` (the card→beat link target), `title`, and `use_count` — how many story
    cards fulfil this beat (ADR-0053 §6 / S5a). A `0` count is a gap the structure
    exposes; a high one an over-loaded beat. The plotline node lists these to render
    its roster (with the count) and to drag beats onto cards."""

    beat_id: str
    title: str = ""
    use_count: int = 0


class PlotBoardPlotline(BaseModel):
    """A plotline as the board sees it (ADR-0048 S7a; ADR-0053 §1): a thread that is
    a plot-template instance — id, title, a colour for its chip/tint, and its ordered
    beat roster. The board renders the plotline as a node holding these beats (S2),
    and a card's beat badges resolve against them."""

    id: str
    title: str
    color: str | None = None
    beats: list[PlotBoardPlotlineBeat] = Field(default_factory=list)


class PlotBoardContainer(BaseModel):
    """A manuscript container (an act, a chapter — whatever container types the
    project declares) as the board renders it (ADR-0048 S7 Slice 4): a soft,
    free-flow box that holds the cards whose scenes live under it. `parent` is
    the enclosing container's id, or None when its parent is the manuscript root
    (a top-level act) — so the board can nest a chapter box inside its act. Only
    containers that transitively hold a placed card (plus their ancestors) are
    projected, in manuscript reading order; an empty container is not a board
    concern. Structure, not thread: a container carries no colour (plotline is
    the colour axis, orthogonal to this structural one)."""

    id: str
    title: str
    parent: str | None = None


class PlotBoardBeat(BaseModel):
    """A card→beat link resolved for the board (ADR-0048 S7 Slice 5b; ADR-0053): a
    beat the card fulfils, with its title and owning plotline title for the badge +
    tooltip. The stored link (`beat_links`) carries only ids (`plotline` + `beat_id`);
    the projection resolves the titles against the live plotlines so the frontend
    renders labels without its own join. A link whose plotline or beat no longer
    exists is dropped, never projected (the display side of `_heal_beat_links`).

    `plotline_color` is the owning plotline's colour swatch id (None when it has none),
    resolved here so the board can tint a card's beat badges by their plotline — beats
    sharing a plotline share a colour, disambiguating collisions between same-named
    beats of different plotlines (ADR-0048 usability pass)."""

    plotline_id: str
    plotline_title: str
    plotline_color: str | None = None
    beat_id: str
    title: str
    # The beat's 1-based position in its plotline's roster (#941) — a stable per-plotline
    # number the board shows on the badge, so two same-titled beats are tellable apart.
    number: int


class PlotBoardCard(BaseModel):
    """A card as the board renders it (ADR-0048 S7a): identity, the synopsis (the
    card body), and the plotline and scene it points at (each None when unset).
    Deleting a scene or a plotline purges the referencing cards
    (`delete_scene` / `delete_plotline` → `_purge_references_to`), so a ref here
    is always either live or already blanked — an attachment is live or gone,
    never a dangling pointer (ADR §S5). The board renders a gone scene as an
    unattached card, nothing more.

    `container` (Slice 4) is the card's scene's innermost manuscript container id
    (the box it lays out inside), or None when the card is homeless — no scene, or
    a scene directly under the root. Derived from the scene, never authored: a
    card's structural home follows its attachment, so dragging never changes it.

    `page_status` (Slice 5b) is whether the card is realized in prose: `on_page`
    (derived — a scene is attached), or the authored `off_page` / `unwritten`. None
    is the sparse default and reads as `unwritten`. Derived here from the current
    scene attachment, so a stale stored `on_page` on a since-detached card never
    projects. `beats` (Slice 5b) are the card's resolved beat links — the badges it
    wears.

    `sequence` (Slice 6) is the card's scene's manuscript reading-order rank
    (0-based, pre-order), or None when the card has no scene — an off-page /
    unwritten card holds no reveal-order position. Derived from the current scene,
    so it tracks re-attachment. The board's manuscript-order edge layer chains
    cards by this rank; the beat-sequence layer orders a beat's cards by it.

    `causal_links` (Slice 6b) are the ids of the cards this card *leads to* — the
    author-drawn causal edges, each a live card id (self-references and dead / gone
    targets dropped, the display side of `_heal_causal_links`). The board's causal
    edge layer draws one directed edge per id."""

    id: str
    title: str
    synopsis: str = ""
    plotline: str | None = None
    scene: str | None = None
    container: str | None = None
    page_status: str | None = None
    beats: list[PlotBoardBeat] = Field(default_factory=list)
    sequence: int | None = None
    causal_links: list[str] = Field(default_factory=list)


class PlotDiagnosticEdge(BaseModel):
    """The directed causal edge a `causal_inversion` finding points at — `source`
    *leads to* `target`. The board highlights this exact edge (matched against the id
    `buildBoardEdges` mints per causal link)."""

    source: str
    target: str


class PlotDiagnosticCard(BaseModel):
    """A card a diagnostic names: its id (to light on the canvas) and title (for the
    finding's prose). Denormalised so the panel renders the message and drives the
    highlight without re-joining against the card list."""

    id: str
    title: str


class PlotDiagnostic(BaseModel):
    """One cross-dimension finding (ADR-0048 S7 — the payoff): a place where two plot
    layers disagree, or a beat the structure leaves unfilled. Deterministic — derived
    from the projection's reveal order, beat rosters, and causal edges, with no LLM
    (the AI diagnostic pass is S7b). A finding reports the disagreement and the nodes
    it involves; it never prescribes a fix (the writer acts on it or dismisses it), and
    it never nags — off-page and unwritten cards are legitimate, so an off-page card is
    never asked to become a scene and a merely-unwritten beat tail is never a gap.

    `kind` is one of:
      - `causal_inversion` — a card sets up (`causal_links`) a card revealed *earlier*:
        the payoff is read before its setup. `cards` = [setup, payoff]; `edge` = that
        causal edge (both cards on-page, or there is no reveal order to invert).
      - `beat_inversion` — within one plotline, a later beat is *fully* revealed before
        an earlier beat *begins* (strict — braided beats do not flag). `cards` = the
        cards involved; `plotline_id` + `beat_ids` name the two beats.
      - `beat_gap` — an interior beat no card fulfils, with a fulfilled beat still after
        it (a hole, not the merely-unwritten tail). `plotline_id` + `beat_ids` name it;
        `cards` is empty — a gap has no card.

    `id` is a stable key derived from the finding's participants (kind + ids) so the
    frontend keys the list and keeps a selection across refetches."""

    id: str
    kind: str
    message: str
    cards: list[PlotDiagnosticCard] = Field(default_factory=list)
    edge: PlotDiagnosticEdge | None = None
    plotline_id: str | None = None
    beat_ids: list[str] = Field(default_factory=list)


class PlotBoardProjection(BaseModel):
    """The read model the PlotEditor board renders from (ADR-0048 S7a; ADR-0053): the
    plotlines (with their beat rosters), the manuscript containers (Slice 4), the
    cards with their refs, and the board's opaque `layout` payload (card positions —
    its shape is the canvas's, S7c). Computed and read-only; defined over card +
    plotline + structure + board data only, never the read-only Library templates."""

    board_id: str = ""
    board_revision: str = ""
    layout: dict[str, Any] = Field(default_factory=dict)
    plotlines: list[PlotBoardPlotline] = Field(default_factory=list)
    containers: list[PlotBoardContainer] = Field(default_factory=list)
    cards: list[PlotBoardCard] = Field(default_factory=list)
    # Cross-dimension findings (ADR-0048 S7) — a derived facet of the board, computed
    # over the fields above (no extra I/O) and refreshed with every projection read, so
    # the diagnostics panel is live. Empty when the layers agree.
    diagnostics: list[PlotDiagnostic] = Field(default_factory=list)


class PlotContextBeat(BaseModel):
    """A beat in a plotline's roster as the AI reads it (ADR-0048 S8a): the
    requirement a card is measured against — its title, the story `function` it
    serves, and the writer's `guidance`. Carried for EVERY beat in the roster,
    including beats no card fulfils yet, so the AI can name the gaps."""

    beat_id: str
    title: str
    function: str = ""
    guidance: str = ""


class PlotContextPlotline(BaseModel):
    """A plotline as the AI reads it (ADR-0048 S8a; ADR-0053 §1): the thread the
    board colours cards by AND the plot structure the cards are measured against —
    one concept. Never gated by reveal order (it is the writer's own scaffolding, not
    manuscript content), so its full beat roster is always present, including beats no
    card fulfils yet (the gaps). `source_template_name` is the lineage snapshot (the
    named structure it was rolled from), blank for an ad-hoc plotline. `ai_guidance`
    (how to use this structure as a diagnostic lens) and `diagnostic_questions` (what
    to ask of the draft) are the template's guidance, snapshotted at instantiate — the
    structural intent the AI reasons with beyond per-beat one-liners; blank/empty for
    an ad-hoc plotline. `weak_spots` are the structure's characteristic failure modes,
    fed as things to check the draft against."""

    id: str
    title: str
    color: str | None = None
    source_template_name: str = ""
    ai_guidance: str = ""
    diagnostic_questions: list[str] = Field(default_factory=list)
    weak_spots: list[str] = Field(default_factory=list)
    beats: list[PlotContextBeat] = Field(default_factory=list)


class PlotContextCard(BaseModel):
    """A card as the AI reads it (ADR-0048 S8a): its `synopsis` (the prose
    stand-in a beat's fulfilment is reasoned from), its plotline, its reveal-order
    `sequence`, its `page_status`, the beats it fulfils, and the cards it *leads
    to* (`causal_out`). Only cards the spoiler gate ADMITS appear — a card past
    the `as_of` anchor is withheld (counted in `PlotContext.omitted_cards`), and
    `causal_out` is filtered to admitted targets so a withheld card never leaks
    through an edge."""

    id: str
    title: str
    synopsis: str = ""
    plotline_id: str | None = None
    plotline_title: str | None = None
    scene_id: str | None = None
    sequence: int | None = None
    page_status: str | None = None
    beats: list[PlotBoardBeat] = Field(default_factory=list)
    causal_out: list[str] = Field(default_factory=list)


class PlotContext(BaseModel):
    """What the AI sees to reason about the plot (ADR-0048 S8a): the board's plot
    state assembled into one packet, spoiler-gated by manuscript reveal order.

    Given an `as_of` anchor (a card or a scene), cards are included up to and
    including its reveal `sequence`; later cards are withheld and only COUNTED
    (`omitted_cards`), so the AI knows more exists without seeing it — a pantser
    can ask "what's next" without the model reading ahead and railroading them.
    With no anchor the whole board is present (`completeness == "whole_board"`):
    plotter mode, nothing to spoil. Plotlines are never gated — they are the writer's
    own scaffolding, not manuscript content, and the full beat roster is what lets the
    AI name a beat no card fulfils yet.

    Assembled read-only from card + plotline + structure data (ADR-0048 S4–S6; ADR-0053),
    reusing the board projection's resolve helpers. This is context assembly (prompt
    INPUT); none of the quarry's claims/evidence apparatus is carried (migration
    principle 2), and the AI writes back through the JSON node-patch loop, not an XML
    suggestion protocol (Slice 8b)."""

    board_id: str = ""
    completeness: str = "whole_board"
    as_of_scene_id: str | None = None
    as_of_sequence: int | None = None
    omitted_cards: int = 0
    plotlines: list[PlotContextPlotline] = Field(default_factory=list)
    cards: list[PlotContextCard] = Field(default_factory=list)


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
    entry_type: str = "manuscript:scene"
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


class FinalizeSceneRequest(BaseModel):
    """Commit the finalize/cleanup projection (ADR-0070 S3): the AI-produced
    clean prose replaces the scene body in place. The backend snapshots first
    (`kept`) then writes; everything but the body is preserved. `dynamic_context`
    is passed through to that safety-net snapshot, same semantics as a save."""

    body: str
    dynamic_context: list[str] | None = None


class LoreEntrySummary(BaseModel):
    id: str
    title: str
    body: str = ""
    entry_type: str = "lore:note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""


class LoreEntry(BaseModel):
    id: str
    title: str
    body: str
    revision: str
    entry_type: str = "lore:note"
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


class PromotionTarget(BaseModel):
    """A layer a node may be promoted INTO — a declared ancestor project of the
    open project (ADR-0078 §2). Offered by `GET /api/promotion/targets`. Generic
    across kinds so slices 3/4 (prompts, mutation sets) reuse it."""

    layer_id: str
    label: str


class PromotionStayItem(BaseModel):
    """A field value that will NOT travel with a promoted node — it stays in the
    origin as a layer override because it would leak origin-local structure into
    the destination (ADR-0078 §4): an `entity_ref` whose target the destination
    cannot see, or a tag the destination does not know."""

    field: str
    # Human-readable reason it stays — names the origin-local target or tag.
    reason: str


class PromotionPlan(BaseModel):
    """The dry-run preview of a promotion (ADR-0078 §9). The same partition backs
    both preview and commit, so what the author confirms is what runs."""

    destination: PromotionTarget
    # Field ids that travel with the node and resolve at the destination.
    travels: list[str] = Field(default_factory=list)
    # Values left behind as an origin override (ADR-0078 §4), each with its reason.
    stays_in_origin: list[PromotionStayItem] = Field(default_factory=list)
    # Fields that travel on the file but whose *definition* is origin-only, so they
    # render only below the destination until the definition is itself promoted
    # (ADR-0078 §3/§8) — informational, not acted on in this slice.
    invisible_at_destination: list[str] = Field(default_factory=list)
    # The hard-dependency closure cascaded up with the node (ADR-0078 §6): a
    # prompt's `{% include %}`d snippets promoted together. Titles, in id order.
    # Always empty for lore (no hard dependencies).
    also_promoted: list[str] = Field(default_factory=list)
    # Dynamic references that travel and re-resolve against the destination scope
    # rather than move (ADR-0078 §5): a prompt's `context_pick` / `scene_ref`
    # inputs, named. Empty for lore (its metadata carries no selector).
    resolves_differently: list[str] = Field(default_factory=list)
    # Set when the promotion is REFUSED (ADR-0078 §6): a dynamic `{% include %}`
    # the cascade cannot follow, or a hard dependency (a prompt's include, a
    # mutation set's pinned entity) owned by an intermediate ancestor that cannot
    # be lifted from this scope. The dialogue shows it and disables commit; a
    # commit call raises. `None` = the plan is promotable.
    blocked_reason: str | None = None
    # Nodes that are RELATED but not moved by this promotion (ADR-0078 §7): staged
    # mutation sets pinned to the node being promoted. They keep working from the
    # origin (keep-id) and are promoted separately, not cascaded. Titles; empty
    # unless the promoted node has pinned staged sets.
    related: list[str] = Field(default_factory=list)


class PromoteLoreEntryRequest(BaseModel):
    target_layer_id: str = Field(min_length=1)


class PromotePromptEntryRequest(BaseModel):
    target_layer_id: str = Field(min_length=1)


class PromoteMutationSetEntryRequest(BaseModel):
    target_layer_id: str = Field(min_length=1)


class CreateLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "lore:note"


class SaveLoreEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str
    base_revision: str | None = None
    entry_type: str = "lore:note"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # ADR-0042's authoring layer L, as a layer id (#314 / ADR-0045). The save
    # *is* the 0042 edit unit, so L rides its request body rather than an ambient
    # header. `None` = no explicit write target: a save of an *inherited* entry
    # then fails loudly rather than silently choosing one (ADR-0039). When set,
    # `L == owning layer` writes the owning file (direct edit) and `L < owning`
    # writes a sparse override delta at L. The frontend rail picker (PR 2) sends
    # it, defaulting to the open project (the rest-position override).
    authoring_layer_id: str | None = None
    # Clear-to-inherit (#517 / create-project-wizard.md §8): the fields whose
    # override row(s) this save should DROP at L, reverting them to the inherited
    # value. This is the explicit "unset ⇒ inherit" signal — needed because
    # omitting a field is read as a deliberate clear-to-empty override, not a
    # revert, and the client has no way to name the above-L value to echo back.
    # Only meaningful on the override path (`L < owning`); a no-op otherwise.
    clear_override_fields: list[str] = Field(default_factory=list)


class PromptEntrySummary(BaseModel):
    id: str
    title: str
    body: str = ""
    entry_type: str = "prompt:base"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    # Per-entry input declarations. Each prompt declares the parameters its
    # template body references via `{{ input.<name> }}`. Instance-level only
    # (ADR-0065 Amendment 2) — there is no type-level `inputs` to fall back to.
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # The prompt's EFFECTIVE inputs (ADR-0061): its own `inputs` plus,
    # transitively, the inputs of every `prompt:snippet` it pulls in with a
    # literal `{% include "<name>" %}`. Computed by the one backend resolver
    # (`services/ai/effective_inputs.py`) so every invocation surface reads the
    # SAME set — the run/invocation dialog and chat's inputs strip. Equals
    # `inputs` for a prompt with no snippet includes. The editor still edits
    # `inputs` (own); the two-tier own-vs-inherited view is S3. Read-only egress:
    # saves round-trip `inputs`, never this.
    effective_inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # Subject entry_types this prompt is offered on as a "＋New" conversation in a
    # node's Conversations panel (ADR-0054 §4/S4). A per-prompt, instance-level
    # allow-list — the author's explicit "show this prompt on…" declaration, read
    # off the node's front-matter exactly like `inputs`. A prompt is offered on a
    # subject iff one of these is an ancestor-or-self of the subject's entry_type;
    # an empty list means "offered nowhere" (opt-in, no implicit everywhere-match).
    # Only meaningful on conversation prompts (those with no `inline` output
    # handler — the only ones launched from that menu); inert on the others.
    # Intentionally lenient — unknown ids simply never match.
    offer_on: list[str] = Field(default_factory=list)
    # The prompt's behavior contract (ADR-0065 S3): which OutputHandler runs its
    # result, plus the optional commit / on_accept capability. Instance-level
    # only (ADR-0065 Amendment 2) — the type carries no behavior bundle, so the
    # sub-type taxonomy collapses to {base, general, snippet}. Its `output`
    # picks the handler; absent (or no handler) = a plain conversation.
    # Invocability itself is the entry_type — a
    # `prompt:snippet` is import-only — not the presence of this key (the writer
    # drops an empty one). Dispatch (frontend-owned, ADR-0065) reads it here,
    # never off the type; round-tripped through front-matter on save exactly
    # like `inputs`/`offer_on`.
    context_strategy: PromptContextStrategy | None = None
    source_layer_id: str = ""
    source_layer_label: str = ""
    # Whether this prompt is shipped by the app-owned built-in Library (#674 /
    # ADR-0049 §5). The frontend branches clone (and, later, hide) on this rather
    # than on `source_layer_label`, so a writer's ancestor project titled
    # "Library" is never mistaken for shipped material.
    is_library: bool = False
    # Whether this prompt may be edited in place here, vs being read-only because
    # it is inherited (a built-in Library node or an ancestor project's prompt).
    # This is the backend's OWN answer — the exact condition `save_prompt_entry`
    # refuses with a 409 (`_reject_inherited_library_write`) — surfaced as a
    # read-model flag so the editor's read-only lock and the "Clone to edit"
    # banner read it instead of re-deriving ownership from the async schema
    # layers. That re-derivation drifting from this truth is what caused #676
    # (#689). The two builders always set it from `_node_is_owned_here` (the
    # shared Library-tenant predicate, ADR-0048 S4b); the
    # default is fail-CLOSED (locked) to match the read-only invariant — a path
    # that ever forgot to set it would lock, never silently unlock an inherited
    # prompt into the 409 dead-end.
    editable: bool = False


class SnippetDependents(BaseModel):
    """How many nodes depend on a `prompt:snippet`'s fields (ADR-0061 §5), for
    the editor's advisory *"used by N prompts / M chats"* shown on a snippet.

    `prompt_count` is the reverse-transitive closure over `{% include %}` edges
    (a prompt that includes a snippet that includes this one counts too);
    `chat_count` is the chat sessions whose locked prompt is in that closure.
    Advisory only — it never blocks the edit; its obligation is a truthful
    count."""

    prompt_count: int = 0
    chat_count: int = 0


class PromptEntry(BaseModel):
    id: str
    title: str
    body: str
    revision: str
    entry_type: str = "prompt:base"
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # See PromptEntrySummary.offer_on (ADR-0054 §4/S4) — carried on the open
    # document so a clone/save round-trips it verbatim.
    offer_on: list[str] = Field(default_factory=list)
    # See PromptEntrySummary.context_strategy (ADR-0065 S3) — the instance behavior
    # contract, carried on the open document so a clone/save round-trips it.
    context_strategy: PromptContextStrategy | None = None
    computed_metadata: dict[str, MetadataValue] = Field(default_factory=dict)
    source_layer_id: str = ""
    source_layer_label: str = ""
    is_library: bool = False
    # See PromptEntrySummary.editable (#689): the backend's own read-only-in-place
    # verdict, carried on the open document so NodeEditor keys its lock on it.
    # Fail-closed default (see above).
    editable: bool = False


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
    # ADR-0054 §4/S4: carried on save so an edit does not strip the prompt's
    # "show this prompt on…" allow-list (a field with no authoring UI yet, S4b).
    offer_on: list[str] = Field(default_factory=list)
    # ADR-0065 S3 / ADR-0062 D3: carried on save so an edit does not strip the
    # prompt's behavior contract (the instance context_strategy). The Setup tab's
    # `PromptOutputEditor` authors `output`; anything else on the block (e.g. the
    # unauthored `target`) still round-trips verbatim.
    context_strategy: PromptContextStrategy | None = None


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
    # ADR-0055 §3: the OPTIONAL entity pin. "" = a reusable template; set = an
    # entity-pinned one-off (offered only for its own entity, stamped on apply).
    # Stored as the `target_entity` entity_ref in `metadata` so it rides the
    # kind-neutral edge machinery (§3), unlike top-level `target_entry_type`.
    target_entity: str = ""
    row_count: int = 0
    # ADR-0055 §5: a PINNED set is a one-off — once the writer places it in a
    # scene it is marked `placed` and drops from the card's *pending* list (kept,
    # not deleted, so the chat→set edge is never stranded). Always False for a
    # reusable (un-pinned) set, which apply never marks.
    placed: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class MutationSetEntry(BaseModel):
    id: str
    title: str
    revision: str
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    # ADR-0055 §3 entity pin — see MutationSetEntrySummary.target_entity.
    target_entity: str = ""
    rows: list[MutationSetRow] = Field(default_factory=list)
    # ADR-0055 §5 placement state — see MutationSetEntrySummary.placed.
    placed: bool = False
    source_layer_id: str = ""
    source_layer_label: str = ""


class MutationSetEntryList(BaseModel):
    entries: list[MutationSetEntrySummary] = Field(default_factory=list)


class CreateMutationSetEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    # ADR-0055 §3: optional entity pin ("" = reusable template).
    target_entity: str = ""
    rows: list[MutationSetRow] = Field(default_factory=list)


class SaveMutationSetEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    base_revision: str | None = None
    entry_type: str = "mutation_set:mutation_set"
    target_entry_type: str = ""
    # ADR-0055 §3: optional entity pin ("" = reusable template).
    target_entity: str = ""
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
    # Where the new assistant's file lands (see
    # ProjectService._assistant_layer_folder_for_id):
    #   None → the local (innermost) layer, i.e. the open project — degenerates
    #          to the machine layer when no project is open. The app's "+" sends
    #          this so a new assistant is authored in the current project (#1452).
    #   ""   → the machine config dir explicitly (a cross-project roster hire,
    #          e.g. the create-project wizard). The default, so a caller that
    #          omits the field keeps the historical machine-layer behaviour.
    #   else → that layer by id.
    layer_id: str | None = ""


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
