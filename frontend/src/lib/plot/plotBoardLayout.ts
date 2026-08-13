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
// `readBoardPositions` / `cardPositionsFromNodes` / `overriddenCardPositions` are
// the read/write ends of the board's opaque `layout` dict the PlotEditor round-trips;
// they key on the `plotCard` node type, so container boxes never enter the layout.

import type { CoordinateExtent, Node } from "@xyflow/svelte";
import type { BoardXY, PlotBoardBeat, PlotBoardLayout, PlotBoardProjection } from "@/lib/types";

// A container box: an act/chapter's title, how many cards it (transitively) holds,
// and its nesting level (0 = a top-level act, 1 = a box nested inside one). The box
// is structural, so it carries no colour — plotline is the card's colour axis.
export type PlotContainerData = {
  title: string;
  count: number;
  level: number;
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

export type PlotBoardNode = Node<PlotContainerData | PlotCardData>;

// Geometry (px). Exported so the unit test asserts against the same constants the
// layout uses rather than hard-coding magic numbers that could silently drift.
export const CARD_WIDTH = 210;
export const CARD_HEIGHT = 110;
export const CARD_GAP_X = 24; // between cards in a row
export const CONTAINER_PAD = 20; // inner padding between a box edge and its content
export const CONTAINER_HEADER = 32; // the title-bar band at the top of a box
export const CONTAINER_GAP = 24; // between sibling boxes / rows / acts

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
export function buildBoardNodes(
  projection: PlotBoardProjection,
  saved: Record<string, BoardXY> = {},
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
  // act box wraps its chapter boxes and its direct cards.
  const innerBox = new Map<string, Box>();
  for (const boxes of innerBoxesByAct.values()) {
    for (const box of boxes) {
      const cards = cardsByInner.get(box.id)!;
      innerBox.set(box.id, boxFromContent(unionRects(cards.map((c) => cardRect(positionOf(c.id))))));
    }
  }
  const actBox = new Map<string, Box>();
  for (const act of acts) {
    const rects: Rect[] = [];
    for (const box of innerBoxesByAct.get(act.id) ?? []) rects.push(rectOfBox(innerBox.get(box.id)!));
    for (const card of cardsByInner.get(act.id) ?? []) rects.push(cardRect(positionOf(card.id)));
    actBox.set(act.id, boxFromContent(unionRects(rects)));
  }

  // --- Emit: act boxes behind, then inner boxes, then cards on top (both array
  // order and explicit zIndex, so a card is always clickable above its container).
  const nodes: PlotBoardNode[] = [];
  const pushContainer = (id: string, title: string, level: number, box: Box) =>
    nodes.push({
      id: containerNodeId(id),
      type: "plotContainer",
      position: { x: box.x, y: box.y },
      width: box.w,
      height: box.h,
      draggable: false,
      selectable: false,
      connectable: false,
      zIndex: level,
      data: { title, count: containerCount.get(id) ?? 0, level },
    });

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
      draggable: true,
      selectable: false,
      extent: box ? containerExtent(box) : undefined,
      zIndex: 2,
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

// Serialize the current card positions for persistence (S7c). Only plotCard nodes —
// container boxes are derived (never stored). Positions are stored raw (not rounded)
// so the persist threshold matches moveNodesCommand's raw-inequality drag record:
// rounding here would let a sub-pixel drag record an undo step that saved nothing, so
// a later Ctrl+Z would reverse an invisible move.
export function cardPositionsFromNodes(nodes: PlotBoardNode[]): Record<string, BoardXY> {
  const out: Record<string, BoardXY> = {};
  for (const n of nodes) {
    if (n.type === "plotCard") out[n.id] = { x: n.position.x, y: n.position.y };
  }
  return out;
}

// The sparse persist (S7d reflow): store a position ONLY for cards the writer has
// explicitly placed (dragged this session or already in the saved layout). An
// un-placed card is absent, so it derives from its container — which is what lets a
// re-attachment reflow it into its new container. Pinning every card (the S7c
// behaviour) would strand a re-homed card in its old container's band.
export function overriddenCardPositions(nodes: PlotBoardNode[], overridden: Set<string>): Record<string, BoardXY> {
  const all = cardPositionsFromNodes(nodes);
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
      c.beats.map((b) => [b.instance_id, b.beat_id, b.title, b.instance_color]),
      c.causal_links,
    ]),
    p.plotlines.map((l) => [l.id, l.title, l.color]),
    p.containers.map((c) => [c.id, c.title, c.parent]),
  ]);
}
