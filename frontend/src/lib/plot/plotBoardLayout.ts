// Plot-board layout (ADR-0048 S7 Slice 4) — the PURE projection → SvelteFlow-nodes
// transform. This is where the board's real logic lives and where it is tested:
// the canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the graph-building is verified here and the composition in a real browser.
//
// Slice 4 replaces the plotline swimlanes with the free-flow, structure-container
// layout the north-star calls for: cards lay out inside their scene's manuscript
// container (an act/chapter box), grouped by STRUCTURE, coloured by PLOTLINE — two
// orthogonal axes on a graph, not one dimension forced onto a grid axis. A card
// with no container (no scene, or a scene under the root) is HOMELESS and floats
// in a loose region below the boxes. Containers are SOFT: non-interactive backdrops
// sized to wrap their member cards (a dragged card stretches its box), nested so a
// chapter box sits inside its act box. Cards drag and their positions persist
// (S7c), exactly as before — a container carries no position and is never stored.
//
// `readBoardPositions` / `movableNodePositions` / `overriddenNodePositions` are
// the read/write ends of the board's opaque `layout` dict the PlotEditor round-trips;
// they key on the draggable node types (`plotCard` + `plotPlotline`), so the derived
// container boxes never enter the layout.

import type { CoordinateExtent, Node } from "@xyflow/svelte";
import type { BoardSize, BoardXY, PlotBoardBeat, PlotBoardLayout, PlotBoardPlotlineBeat, PlotBoardProjection } from "@/lib/types";

// A container box: an act/chapter's title, how many cards it (transitively) holds,
// and its nesting level (0 = a top-level act, 1 = a box nested inside one). The box
// is structural, so it carries no colour — plotline is the card's colour axis.
//
// The last three fields serve the resize handle (#878), which lives on the flow
// wrapper (PlotContainerNodeFlow), not the presentational node: `containerId` is the
// raw container id (the node id is `container:<id>`) the resize callback keys its
// stored size by, and `minWidth`/`minHeight` are the box's CURRENT auto-wrap size —
// the floor the handle can't drag below, so a container never shrinks past its content.
export type PlotContainerData = {
  title: string;
  count: number;
  level: number;
  containerId: string;
  minWidth: number;
  minHeight: number;
};

// A card node: its synopsis (the body), whether it is attached to a scene, and the
// owning plotline's swatch id (null for a colourless / unassigned plotline), drawn
// as the card's left stripe. Colour is independent of which container the card is in.
export type PlotCardData = {
  title: string;
  synopsis: string;
  attached: boolean;
  color: string | null;
  // The owning plotline's id + name (#863). id lets the card's "Set plotline" menu
  // mark the current selection; name is shown on the card so the plotline is legible
  // by more than its colour. Both null for the Unassigned lane.
  plotlineId: string | null;
  plotlineName: string | null;
  // Page status (Slice 5b): on_page (scene attached) / off_page / unwritten. null =
  // the sparse default, rendered as unwritten. Drives the card's 3-state marker.
  pageStatus: string | null;
  // The resolved beats this card fulfils (Slice 5b) — the badges it wears.
  beats: PlotBoardBeat[];
  // The ids of the cards this card leads to (Slice 6b) — the authored causal links,
  // seeding the "Leads to…" picker's checked state.
  causalLinks: string[];
};

// A plotline node (ADR-0053 §3): a plotline IS a plot-template instance, drawn as a
// free-floating board node holding its beat roster. `color` tints it (the #863
// swatch); `beats` render as its read-only roster in S2a (on-node editing is S2b).
export type PlotPlotlineData = {
  title: string;
  color: string | null;
  beats: PlotBoardPlotlineBeat[];
};

export type PlotBoardNode = Node<PlotContainerData | PlotCardData | PlotPlotlineData>;

// A board is empty (show the hint, hide the canvas) only when it has NEITHER cards NOR
// plotlines. Since ADR-0053 a plotline is a first-class board node, so a card-less board
// with plotlines still has something to render — treating it as empty would hide an
// instantiated plotline (the S3 palette gesture). Pure + exported so the render decision
// is unit-tested against the SvelteFlow-gated PlotEditor.
export function boardIsEmpty(projection: PlotBoardProjection): boolean {
  return projection.cards.length === 0 && projection.plotlines.length === 0;
}

// The board's ephemeral per-plotline UI state: which thread is FOCUSED (S5b — its card
// chain lit, the rest dimmed) and which node is EXPANDED into its inline editor. Held on
// PlotEditor, not the projection, so it survives a board rebuild.
export type PlotlineUiState = { focusedPlotlineId: string | null; expandedPlotlineId: string | null };

// Reconcile that ephemeral state against the live projection (#928). A plotline can now
// be deleted from more than one place — its node's Delete AND the full-pane escape hatch's
// tab — and only the node path clears these ids directly. A delete from the pane just
// refreshes the board, so a focused/expanded id would dangle on a plotline that's gone,
// leaving the board dimmed (or logically expanded) with no node left to clear it. This is
// the path-independent backstop: after any refetch, drop an id the projection no longer
// contains. A NULL projection (loading / failed board) is left untouched so a transient
// refetch can't drop a still-live focus; and an unchanged state returns the SAME object so
// the caller can skip a no-op write.
export function reconcilePlotlineUiState(
  projection: PlotBoardProjection | null,
  state: PlotlineUiState,
): PlotlineUiState {
  if (!projection) return state;
  const live = new Set(projection.plotlines.map((plotline) => plotline.id));
  const focusedPlotlineId = state.focusedPlotlineId && live.has(state.focusedPlotlineId) ? state.focusedPlotlineId : null;
  const expandedPlotlineId =
    state.expandedPlotlineId && live.has(state.expandedPlotlineId) ? state.expandedPlotlineId : null;
  if (focusedPlotlineId === state.focusedPlotlineId && expandedPlotlineId === state.expandedPlotlineId) return state;
  return { focusedPlotlineId, expandedPlotlineId };
}

// Geometry (px). Exported so the unit test asserts against the same constants the
// layout uses rather than hard-coding magic numbers that could silently drift.
export const CARD_WIDTH = 210;
export const CARD_HEIGHT = 110;
export const CARD_GAP_X = 24; // between cards in a row
export const PLOTLINE_WIDTH = 240; // a plotline node is a touch wider than a card
export const CONTAINER_PAD = 20; // inner padding between a box edge and its content
export const CONTAINER_HEADER = 32; // the title-bar band at the top of a box
export const CONTAINER_GAP = 24; // between sibling boxes / rows / acts

// Base z-index for the interactive nodes (cards + plotlines), above their container
// boxes (level 0/1). PlotEditor lifts a node above this while its kebab menu is open
// so the menu isn't painted over by a sibling node (#1095), then restores it here.
export const NODE_Z_INDEX = 2;

// The class SvelteFlow's `dragHandle` targets so a container drags ONLY by its header
// band (#877), a window-titlebar affordance — the transparent interior stays a
// non-interactive backdrop, so card drags and the edge layers still pass through it
// (#833). Shared: the container node's `dragHandle` (buildBoardNodes) and the header
// element's class (PlotContainerNode) must name the same selector.
export const CONTAINER_DRAG_HANDLE_CLASS = "plot-container-drag-handle";

// The class SvelteFlow's `dragHandle` targets on the CARD-like nodes — story cards
// (plotCard) AND plotline nodes (plotPlotline) — so each drags ONLY by a small leading
// grip, not by its whole body (#876). Their bodies are dense with inline-edit controls
// (title, synopsis, kebab, focus, beats), so a whole-body drag surface left only slivers
// between the controls to grab; a dedicated grip is a clear, fixed handle. Shared by both
// card-like node types and both node components, exactly as the container handle above —
// the node's `dragHandle` selector and the grip element's class must never drift apart.
export const CARD_DRAG_HANDLE_CLASS = "plot-card-drag-handle";

// A container node's id is prefixed so it can never collide with a card id (card
// ids are `plot_…`, container ids are `node_…`), mirroring the old `lane:` prefix.
const containerNodeId = (id: string) => `container:${id}`;

type Rect = { minX: number; minY: number; maxX: number; maxY: number };
export type Box = { x: number; y: number; w: number; h: number };

const cardRect = (p: BoardXY): Rect => ({ minX: p.x, minY: p.y, maxX: p.x + CARD_WIDTH, maxY: p.y + CARD_HEIGHT });

const unionRects = (rects: Rect[]): Rect =>
  rects.reduce((a, r) => ({
    minX: Math.min(a.minX, r.minX),
    minY: Math.min(a.minY, r.minY),
    maxX: Math.max(a.maxX, r.maxX),
    maxY: Math.max(a.maxY, r.maxY),
  }));

// Grow a content rect into a box: pad on every side, plus a header band on top for
// the title. A box wraps its contents' FINAL positions, so a dragged card stretches
// (and can drag its box with it) — the "soft container" behaviour.
const boxFromContent = (r: Rect): Box => ({
  x: r.minX - CONTAINER_PAD,
  y: r.minY - CONTAINER_PAD - CONTAINER_HEADER,
  w: r.maxX - r.minX + 2 * CONTAINER_PAD,
  h: r.maxY - r.minY + 2 * CONTAINER_PAD + CONTAINER_HEADER,
});

const rectOfBox = (b: Box): Rect => ({ minX: b.x, minY: b.y, maxX: b.x + b.w, maxY: b.y + b.h });

// --- Container lock (#873): the drag extent a card is confined to. Kept pure +
// exported so it is unit-tested (the SvelteFlow drag that consumes it is not
// headless-testable). Set as each card node's `extent` in buildBoardNodes; xyflow
// clamps the drag into it every frame (a hard wall, no snap-back), subtracting the
// card's own size itself — so this returns the box's INNER CONTENT REGION (inside the
// side padding, below the header band), NOT pre-shrunk by the card. A container that
// hugs a single card yields a region the card exactly fills → xyflow pins it. Homeless
// cards get no extent and drag free.
export function containerExtent(box: Box): CoordinateExtent {
  return [
    [box.x + CONTAINER_PAD, box.y + CONTAINER_HEADER + CONTAINER_PAD],
    [box.x + box.w - CONTAINER_PAD, box.y + box.h - CONTAINER_PAD],
  ];
}

// Build the board layout. Cards group by their innermost manuscript container
// (`card.container`); a container with direct cards renders as a box nested in its
// top-level act. Homeless cards (no container) lay out loose below every box.
// `saved` carries per-card position overrides (S7c): a card present there keeps
// that spot, otherwise it falls to its derived slot inside its container.
// `savedSizes` carries per-container manual sizes (#878): a container present there
// grows to at least that size (min-not-override — content still wins if larger), which
// also widens its member cards' drag extent (#874). Absent → the box auto-wraps.
export function buildBoardNodes(
  projection: PlotBoardProjection,
  saved: Record<string, BoardXY> = {},
  savedSizes: Record<string, BoardSize> = {},
): PlotBoardNode[] {
  const plotlineById = new Map(projection.plotlines.map((line) => [line.id, line]));
  const containerById = new Map(projection.containers.map((c) => [c.id, c]));

  // The top-most ancestor container ("act") of a projected container, walking the
  // parent chain. A top-level container is its own act.
  const topAncestor = (id: string): string => {
    let cur = id;
    for (;;) {
      const c = containerById.get(cur);
      if (!c || c.parent == null || !containerById.has(c.parent)) return cur;
      cur = c.parent;
    }
  };

  // Bucket cards by their innermost container, preserving projection order within a
  // bucket. A card with no (resolvable) container is homeless.
  const cardsByInner = new Map<string, PlotBoardProjection["cards"]>();
  const homeless: PlotBoardProjection["cards"] = [];
  for (const card of projection.cards) {
    if (card.container != null && containerById.has(card.container)) {
      (cardsByInner.get(card.container) ?? cardsByInner.set(card.container, []).get(card.container)!).push(card);
    } else {
      homeless.push(card);
    }
  }

  // Transitive card count per container (a card counts for its container and every
  // ancestor), so an act's header shows the whole act's total.
  const containerCount = new Map<string, number>();
  for (const [innerId, cards] of cardsByInner) {
    let cur: string | null = innerId;
    while (cur != null && containerById.has(cur)) {
      containerCount.set(cur, (containerCount.get(cur) ?? 0) + cards.length);
      cur = containerById.get(cur)!.parent;
    }
  }

  // Acts = top-level containers, in reading order (projection.containers is ordered).
  const acts = projection.containers.filter((c) => c.parent == null);
  // Inner boxes per act = projected non-top-level containers that hold direct cards,
  // in reading order. A middle "part" container with no direct cards draws no box —
  // its chapters render directly in the act (two visible levels for Slice 4).
  const innerBoxesByAct = new Map<string, PlotBoardProjection["containers"]>();
  for (const c of projection.containers) {
    if (c.parent == null) continue;
    if (!cardsByInner.get(c.id)?.length) continue;
    const act = topAncestor(c.id);
    (innerBoxesByAct.get(act) ?? innerBoxesByAct.set(act, []).get(act)!).push(c);
  }

  // --- Derived (pre-drag) positions: a tidy, non-overlapping default layout that a
  // pinned position then overrides. Acts stack top-to-bottom; within an act, its
  // chapter boxes stack, each a single row of cards, then the act's own direct cards.
  const derived = new Map<string, BoardXY>();
  let actY = 0;
  for (const act of acts) {
    const innerBoxes = innerBoxesByAct.get(act.id) ?? [];
    const directCards = cardsByInner.get(act.id) ?? [];
    const contentX = CONTAINER_PAD; // the act box sits at x = 0; its content is padded in
    let cursorY = actY + CONTAINER_HEADER + CONTAINER_PAD;
    for (const box of innerBoxes) {
      const cards = cardsByInner.get(box.id)!;
      const cardsX = contentX + CONTAINER_PAD;
      const cardsY = cursorY + CONTAINER_HEADER + CONTAINER_PAD;
      cards.forEach((card, i) => derived.set(card.id, { x: cardsX + i * (CARD_WIDTH + CARD_GAP_X), y: cardsY }));
      cursorY += CONTAINER_HEADER + CONTAINER_PAD + CARD_HEIGHT + CONTAINER_PAD + CONTAINER_GAP;
    }
    directCards.forEach((card, i) => derived.set(card.id, { x: contentX + i * (CARD_WIDTH + CARD_GAP_X), y: cursorY }));
    if (directCards.length) cursorY += CARD_HEIGHT + CONTAINER_GAP;
    // Each child already advanced cursorY by a trailing CONTAINER_GAP, which serves
    // as the gap to the next act; add the act box's own bottom padding on top of it.
    actY = cursorY + CONTAINER_PAD;
  }
  // Homeless cards: a loose row below every act, outside any box (they float).
  homeless.forEach((card, i) => derived.set(card.id, { x: i * (CARD_WIDTH + CARD_GAP_X), y: actY + CONTAINER_HEADER }));

  // Every projection card is assigned a derived slot above (inner-box, direct-act, or
  // homeless), so `derived.get` is non-null for any real card id — the `!` states that
  // invariant rather than silently defaulting a missing card to the origin.
  const positionOf = (id: string): BoardXY => saved[id] ?? derived.get(id)!;

  // --- Box geometry from FINAL positions (pins applied), computed inner-first so an
  // act box wraps its chapter boxes and its direct cards. Each auto-wrap box is then
  // grown to any stored manual size (#878): min-not-override, so content still wins when
  // it is larger. The grown box drives BOTH the rendered size AND the member cards' drag
  // extent (#874) — and an act wraps the GROWN chapter boxes (rectOfBox reads innerBox
  // post-grow), so enlarging a chapter enlarges its act too. The pre-grow (auto-wrap)
  // size is retained per container as the resize floor the handle can't drag below.
  const contentSize = new Map<string, BoardSize>();
  const grow = (id: string, box: Box): Box => {
    contentSize.set(id, { w: box.w, h: box.h });
    const manual = savedSizes[id];
    if (!manual) return box;
    return { ...box, w: Math.max(box.w, manual.w), h: Math.max(box.h, manual.h) };
  };
  const innerBox = new Map<string, Box>();
  for (const boxes of innerBoxesByAct.values()) {
    for (const box of boxes) {
      const cards = cardsByInner.get(box.id)!;
      innerBox.set(box.id, grow(box.id, boxFromContent(unionRects(cards.map((c) => cardRect(positionOf(c.id)))))));
    }
  }
  const actBox = new Map<string, Box>();
  for (const act of acts) {
    const rects: Rect[] = [];
    for (const box of innerBoxesByAct.get(act.id) ?? []) rects.push(rectOfBox(innerBox.get(box.id)!));
    for (const card of cardsByInner.get(act.id) ?? []) rects.push(cardRect(positionOf(card.id)));
    actBox.set(act.id, grow(act.id, boxFromContent(unionRects(rects))));
  }

  // --- Emit: act boxes behind, then inner boxes, then cards on top (both array
  // order and explicit zIndex, so a card is always clickable above its container).
  const nodes: PlotBoardNode[] = [];
  const pushContainer = (id: string, title: string, level: number, box: Box) => {
    // The auto-wrap size is the resize floor (data.minWidth/minHeight); it is always
    // set for a container that renders a box, since `grow` recorded it just above.
    const content = contentSize.get(id)!;
    nodes.push({
      id: containerNodeId(id),
      type: "plotContainer",
      position: { x: box.x, y: box.y },
      width: box.w,
      height: box.h,
      // Draggable (#877), but ONLY by the header band (`dragHandle`) — the box moves its
      // member cards, the derived box re-wraps them (PlotEditor's container-drag path).
      // The transparent interior stays inert so card drags + edges pass through (#833).
      draggable: true,
      dragHandle: `.${CONTAINER_DRAG_HANDLE_CLASS}`,
      selectable: false,
      connectable: false,
      zIndex: level,
      data: { title, count: containerCount.get(id) ?? 0, level, containerId: id, minWidth: content.w, minHeight: content.h },
    });
  };

  for (const act of acts) pushContainer(act.id, act.title, 0, actBox.get(act.id)!);
  for (const act of acts) {
    for (const box of innerBoxesByAct.get(act.id) ?? []) pushContainer(box.id, box.title, 1, innerBox.get(box.id)!);
  }
  for (const card of projection.cards) {
    const line = card.plotline ? plotlineById.get(card.plotline) : undefined;
    // Container lock (#873): confine the card's drag to its innermost container box
    // (the same box the card lays out in), so it can be rearranged inside its act/
    // chapter but never dragged out. Homeless cards (no rendered box) get no extent
    // and drag free. The box is looked up where it was computed — inner box for a
    // chapter card, act box for a card directly in an act.
    const cid = card.container != null && containerById.has(card.container) ? card.container : null;
    const box = cid ? (innerBox.get(cid) ?? actBox.get(cid)) : undefined;
    nodes.push({
      id: card.id,
      type: "plotCard",
      position: positionOf(card.id),
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      // Seed `measured` from our own geometry (size is single-sourced here, not
      // DOM-measured): xyflow only draws an edge once BOTH endpoint nodes are
      // measured, and its ResizeObserver may not have run yet (never does in a
      // 0-size / headless pane) — so without this the edge layers render nothing.
      // Only card nodes carry it: the edge layers connect cards, never containers.
      measured: { width: CARD_WIDTH, height: CARD_HEIGHT },
      // Draggable, but ONLY by the leading grip (`dragHandle`, #876) — the card body is
      // full of inline-edit controls, so a whole-body drag surface was near-ungrabbable.
      draggable: true,
      dragHandle: `.${CARD_DRAG_HANDLE_CLASS}`,
      selectable: false,
      extent: box ? containerExtent(box) : undefined,
      zIndex: NODE_Z_INDEX,
      data: {
        title: card.title,
        synopsis: card.synopsis,
        attached: card.scene != null,
        color: line?.color ?? null,
        plotlineId: line?.id ?? null,
        plotlineName: line?.title ?? null,
        pageStatus: card.page_status,
        beats: card.beats,
        causalLinks: card.causal_links,
      },
    });
  }

  // Plotline nodes (ADR-0053 §3): a plotline is a first-class board node holding its
  // beat roster, NOT a lane the cards sit in — so it floats free (draggable anywhere),
  // laid out by default in a loose row in a band below every act + the homeless cards.
  // Once dragged its position persists like a card's (same saved-override model). The
  // node id IS the plotline id; card + plotline ids are distinct, so one `saved` map
  // (keyed by node id) holds both without collision.
  const plotlineBandY =
    actY + CONTAINER_HEADER + (homeless.length ? CARD_HEIGHT + CONTAINER_GAP : 0) + CONTAINER_GAP;
  projection.plotlines.forEach((line, i) => {
    nodes.push({
      id: line.id,
      type: "plotPlotline",
      position: saved[line.id] ?? { x: i * (PLOTLINE_WIDTH + CARD_GAP_X), y: plotlineBandY },
      width: PLOTLINE_WIDTH,
      // Same leading-grip handle as a card (#876): a plotline node's header carries a
      // focus toggle + a click-to-expand title, so it drags by the grip, never the header.
      draggable: true,
      dragHandle: `.${CARD_DRAG_HANDLE_CLASS}`,
      selectable: false,
      zIndex: NODE_Z_INDEX,
      data: { title: line.title, color: line.color, beats: line.beats },
    });
  });
  return nodes;
}

// Read the typed position overrides out of the projection's opaque `layout` dict.
// An unknown / malformed shape degrades to no overrides (every card keeps its
// derived slot) rather than throwing — the board must always render.
export function readBoardPositions(layout: Record<string, unknown>): Record<string, BoardXY> {
  const positions = (layout as PlotBoardLayout).positions;
  if (!positions || typeof positions !== "object") return {};
  const out: Record<string, BoardXY> = {};
  for (const [id, p] of Object.entries(positions)) {
    // Number.isFinite (not typeof === "number", which admits NaN/Infinity): a
    // non-finite coordinate can't be placed by SvelteFlow, and the board must render.
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) out[id] = { x: p.x, y: p.y };
  }
  return out;
}

// Read the typed per-container manual sizes out of the opaque `layout` dict (#878).
// Same fail-soft contract as readBoardPositions: an unknown / malformed shape or a
// non-finite / non-positive dimension is dropped (the box just falls back to auto-wrap)
// rather than throwing — a bad size must never keep the board from rendering.
export function readBoardSizes(layout: Record<string, unknown>): Record<string, BoardSize> {
  const sizes = (layout as PlotBoardLayout).sizes;
  if (!sizes || typeof sizes !== "object") return {};
  const out: Record<string, BoardSize> = {};
  for (const [id, s] of Object.entries(sizes)) {
    if (s && Number.isFinite(s.w) && Number.isFinite(s.h) && s.w > 0 && s.h > 0) out[id] = { w: s.w, h: s.h };
  }
  return out;
}

// The ids of every card TRANSITIVELY inside a container (#877): the card itself if the
// container is its own container or any ancestor of it. Dragging a container translates
// exactly this set (an act carries its chapters' cards too, a chapter just its own), so
// the derived box re-wraps them. A homeless card, or one under a different container, is
// excluded; an unknown container id yields none. Pure + unit-tested — the drag that
// consumes it lives in PlotEditor and isn't headless-testable.
export function containerMemberCardIds(projection: PlotBoardProjection, containerId: string): string[] {
  const byId = new Map(projection.containers.map((c) => [c.id, c]));
  const isInside = (cid: string | null): boolean => {
    for (let cur = cid; cur != null; cur = byId.get(cur)?.parent ?? null) {
      if (cur === containerId) return true;
    }
    return false;
  };
  return projection.cards.filter((c) => c.container != null && byId.has(c.container) && isInside(c.container)).map((c) => c.id);
}

// The ids of the containers STRICTLY inside a container (its descendant boxes; #877) —
// e.g. an act's chapters. A container drag translates these boxes live alongside its
// member cards so a nested act moves as one piece; they still re-derive on drop, so
// this is purely visual cohesion during the gesture. Pure + unit-tested.
export function containerDescendantIds(projection: PlotBoardProjection, containerId: string): string[] {
  const byId = new Map(projection.containers.map((c) => [c.id, c]));
  const isInside = (cid: string): boolean => {
    for (let cur: string | null = cid; cur != null; cur = byId.get(cur)?.parent ?? null) {
      if (cur === containerId) return true;
    }
    return false;
  };
  return projection.containers.filter((c) => c.id !== containerId && isInside(c.id)).map((c) => c.id);
}

// Serialize the current movable-node positions for persistence (S7c; ADR-0053): the
// draggable node types — plotCard AND plotPlotline (both keyed by their own id in the
// shared `positions` map) — but never container boxes, which are derived. Positions
// are stored raw (not rounded) so the persist threshold matches moveNodesCommand's
// raw-inequality drag record: rounding here would let a sub-pixel drag record an undo
// step that saved nothing, so a later Ctrl+Z would reverse an invisible move.
export function movableNodePositions(nodes: PlotBoardNode[]): Record<string, BoardXY> {
  const out: Record<string, BoardXY> = {};
  for (const n of nodes) {
    if (n.type === "plotCard" || n.type === "plotPlotline") out[n.id] = { x: n.position.x, y: n.position.y };
  }
  return out;
}

// The sparse persist (S7d reflow): store a position ONLY for cards the writer has
// explicitly placed (dragged this session or already in the saved layout). An
// un-placed card is absent, so it derives from its container — which is what lets a
// re-attachment reflow it into its new container. Pinning every card (the S7c
// behaviour) would strand a re-homed card in its old container's band.
export function overriddenNodePositions(nodes: PlotBoardNode[], overridden: Set<string>): Record<string, BoardXY> {
  const all = movableNodePositions(nodes);
  const out: Record<string, BoardXY> = {};
  for (const id of Object.keys(all)) {
    if (overridden.has(id)) out[id] = all[id];
  }
  return out;
}

// A content-identity key over the projection's DATA — board id + each card's fields
// (including its container) + each plotline + each container — deliberately EXCLUDING
// the layout (positions). The board rehydrates only when this changes: a content op
// (a plotline reassignment, a scene re-attachment that moves the card's container, a
// chapter rename) changes a field here, so the board rebuilds and an un-pinned card
// reflows; a re-open of the SAME data leaves the key unchanged, so an in-progress
// layout edit is not discarded.
export function projectionDataKey(p: PlotBoardProjection): string {
  return JSON.stringify([
    p.board_id,
    p.cards.map((c) => [
      c.id,
      c.title,
      c.synopsis,
      c.plotline,
      c.scene,
      c.container,
      c.page_status,
      c.beats.map((b) => [b.plotline_id, b.beat_id, b.title, b.plotline_color]),
      c.causal_links,
    ]),
    p.plotlines.map((l) => [l.id, l.title, l.color, l.beats.map((b) => [b.beat_id, b.title, b.use_count])]),
    p.containers.map((c) => [c.id, c.title, c.parent]),
  ]);
}
