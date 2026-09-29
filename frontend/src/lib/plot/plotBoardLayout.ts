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

import { get } from "svelte/store";
import type { CoordinateExtent, Node } from "@xyflow/svelte";
import type {
  BoardSize,
  BoardXY,
  MetadataFieldDefinition,
  PlotBoardCharacterArc,
  PlotBoardLayout,
  PlotBoardPlotlineBeat,
  PlotBoardProjection,
  PlotCardBeat,
} from "@/lib/types";
import { getSwatch, resolveColor, resolveColorForKind } from "@/lib/utils/colors";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";

// A container box: its title, how many cards it (transitively) holds, and its
// level (0 = a top-level act, 1 = a chapter inside it, 2 = a sequence inside that:
// one nested box per level, ADR-0094 §9). The box is structural, so it carries no
// colour — plotline is the card's colour axis.
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
  // Page status (Slice 5b): on_page (scene attached) / off_page / unwritten, a
  // sparse blank resolved to the schema default. Its label and swatch come from
  // the schema's `page_status` options (#1907) — the rail's words and colours,
  // spelled once — so the card renders what it is given.
  pageStatus: string;
  pageStatusLabel: string;
  pageStatusSwatch: string | null;
  // True when the status is the field's default (or there is no field): the card then
  // shows only the dot, not the label — the label is for the exceptional states.
  pageStatusIsDefault: boolean;
  // The resolved beats this card fulfils (Slice 5b) — the badges it wears, each
  // carrying its denormalised effective colour (ADR-0080 slice 3b-ii): an
  // event-beat's plotline swatch, or a change-beat's resolved arc colour.
  beats: PlotCardBeat[];
  // The ids of the cards this card leads to (Slice 6b) — the authored causal links,
  // seeding the "Leads to…" picker's checked state.
  causalLinks: string[];
};

/** A card's page status as the board shows it (#1907): the projected value
 *  (the backend already resolves a sparse blank to the schema default), with
 *  the label and swatch the schema's `page_status` options declare. Without
 *  the field in the schema (not loaded yet, or a layer without it) the value
 *  stands in for its label and there is no swatch. */
export function pageStatusOf(
  stored: string | null,
  field: MetadataFieldDefinition | undefined,
): Pick<PlotCardData, "pageStatus" | "pageStatusLabel" | "pageStatusSwatch" | "pageStatusIsDefault"> {
  const pageStatus = stored || (typeof field?.default === "string" ? field.default : "");
  const option = field?.options.find((o) => o.value === pageStatus);
  const isDefault = !field || pageStatus === (typeof field.default === "string" ? field.default : "");
  return {
    pageStatus,
    pageStatusLabel: option?.label ?? pageStatus,
    pageStatusSwatch: option?.color ?? null,
    pageStatusIsDefault: isDefault,
  };
}

// A plotline node (ADR-0053 §3): a plotline IS a plot-template instance, drawn as a
// free-floating board node holding its beat roster. `color` tints it (the #863
// swatch); `beats` render as its read-only roster in S2a (on-node editing is S2b).
export type PlotPlotlineData = {
  title: string;
  color: string | null;
  beats: PlotBoardPlotlineBeat[];
};

// A character-arc node (ADR-0080 §5 / Amendment 1): the plotline's sibling holder,
// drawn in its own band below the plotline band. `color` is the arc's OWN swatch id
// (null when unset — Amendment 1 §1: an unset arc previews the bound character's
// colour instead of reading colourless); `resolvedColorHex` is that whole resolution
// (own → character's → the lore kind default), computed ONCE here so PlotArcNode
// never re-resolves it. `characterId`/`characterName`/`characterInitial` are the
// bound character (each null when unbound).
export type PlotArcData = {
  title: string;
  color: string | null;
  beats: PlotBoardPlotlineBeat[];
  characterId: string | null;
  characterName: string | null;
  characterInitial: string | null;
  resolvedColorHex: string | null;
};

export type PlotBoardNode = Node<PlotContainerData | PlotCardData | PlotPlotlineData | PlotArcData>;

// A board is empty (show the hint, hide the canvas) only when it has NEITHER cards NOR
// plotlines NOR arcs. Since ADR-0053 a plotline is a first-class board node (and
// ADR-0080 an arc is its sibling), so a card-less board with a thread still has
// something to render — treating it as empty would hide an instantiated plotline/arc
// (the S3 palette gesture). Pure + exported so the render decision is unit-tested
// against the SvelteFlow-gated PlotEditor.
export function boardIsEmpty(projection: PlotBoardProjection): boolean {
  return projection.cards.length === 0 && projection.plotlines.length === 0 && projection.arcs.length === 0;
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

// The board's ephemeral per-arc UI state: which arc node is EXPANDED into its inline
// editor. A SEPARATE id from `expandedPlotlineId` (ADR-0080 §5 / #3b-i correctness
// point) — an arc and a plotline are different node kinds with distinct id spaces, so
// overloading one field would let an arc's id clear (or be cleared by) a plotline's.
export type ArcUiState = { expandedArcId: string | null };

// Reconcile that state against the live projection, mirroring `reconcilePlotlineUiState`
// (#928) for arcs: after any refetch, drop an id the projection no longer contains (an
// arc deleted from elsewhere must not strand an "expanded" id on a dead node). A NULL
// projection is left untouched; an unchanged state returns the SAME object.
export function reconcileArcUiState(projection: PlotBoardProjection | null, state: ArcUiState): ArcUiState {
  if (!projection) return state;
  const live = new Set(projection.arcs.map((arc) => arc.id));
  const expandedArcId = state.expandedArcId && live.has(state.expandedArcId) ? state.expandedArcId : null;
  if (expandedArcId === state.expandedArcId) return state;
  return { expandedArcId };
}

// The board's ephemeral revealed-card state (#1920): which card a search hit / backlink
// lit. Reconciled like the plotline/arc state — a card deleted elsewhere must not leave
// the board dimmed around a card that is gone.
export type CardUiState = { revealedCardId: string | null };

export function reconcileCardUiState(projection: PlotBoardProjection | null, state: CardUiState): CardUiState {
  if (!projection) return state;
  const live = new Set(projection.cards.map((card) => card.id));
  const revealedCardId = state.revealedCardId && live.has(state.revealedCardId) ? state.revealedCardId : null;
  if (revealedCardId === state.revealedCardId) return state;
  return { revealedCardId };
}

// Geometry (px). Exported so the unit test asserts against the same constants the
// layout uses rather than hard-coding magic numbers that could silently drift.
export const CARD_WIDTH = 280;
// A card's height is ESTIMATED from its content (#2354): the synopsis is the card —
// the board exists to read synopses in sequence — so a card grows to show it. Size is
// single-sourced here (never DOM-measured), so the estimate is tuned to slightly
// OVER-estimate: an extra gap is harmless, clipped text is the bug. Beyond
// CARD_SYNOPSIS_MAX_LINES the synopsis scrolls inside the card instead of growing it.
export const CARD_PAD_Y = 20; // top + bottom padding of the card
export const CARD_HEAD_MIN_H = 22; // grip / kebab band, the floor of the head
export const CARD_TITLE_LINE_H = 17; // one wrapped title line (--fs-sm, ~1.3)
export const CARD_TITLE_MAX_LINES = 2;
export const CARD_TITLE_CHARS_PER_LINE = 36;
export const CARD_SYNOPSIS_LINE_H = 20; // one synopsis line (--fs-md, 1.45)
export const CARD_SYNOPSIS_CHARS_PER_LINE = 38;
export const CARD_SYNOPSIS_MAX_LINES = 14;
export const CARD_SECTION_GAP = 6; // between head / synopsis / foot
export const CARD_FOOT_MIN_H = 22; // the foot row: status dots, plus at least one pill row
export const CARD_PILL_ROW_H = 22; // one wrapped row of beat pills
export const CARD_PILLS_PER_ROW = 2; // a conservative pills-per-row (over-estimates)
export function estCardHeight(title: string, synopsis: string, beatCount: number): number {
  const titleLines = Math.min(CARD_TITLE_MAX_LINES, Math.max(1, Math.ceil(title.length / CARD_TITLE_CHARS_PER_LINE)));
  const head = Math.max(CARD_HEAD_MIN_H, titleLines * CARD_TITLE_LINE_H);
  const synopsisLines = Math.min(
    CARD_SYNOPSIS_MAX_LINES,
    // Trimmed: the projection's synopsis is the raw body, stored with a trailing newline.
    synopsis
      .trim()
      .split("\n")
      .reduce((n, para) => n + Math.max(1, Math.ceil(para.length / CARD_SYNOPSIS_CHARS_PER_LINE)), 0),
  );
  const pillRows = beatCount > 0 ? Math.ceil(beatCount / CARD_PILLS_PER_ROW) : 0;
  const foot = pillRows > 0 ? pillRows * CARD_PILL_ROW_H : CARD_FOOT_MIN_H;
  return CARD_PAD_Y + head + CARD_SECTION_GAP + synopsisLines * CARD_SYNOPSIS_LINE_H + CARD_SECTION_GAP + foot;
}
// The minimum / default card height: what an empty, beat-less card measures.
export const CARD_HEIGHT = estCardHeight("", "", 0);
export const CARD_GAP_X = 24; // between cards in a row
export const PLOTLINE_WIDTH = 240; // a plotline node is a touch wider than a card
// A plot holder node (plotline or arc) is variable-height — SvelteFlow sizes it to its
// content, and a collapsed beat roster runs one row per beat — so the arc band clears the
// plotline band by ESTIMATING each plotline's height from its beat count (a flat one-row
// nominal overlapped a multi-beat plotline: a 7-beat node measures ~210px, not ~110).
// Header + one row per beat, tuned to slightly OVER-estimate so the bands never collide;
// a small extra gap is harmless, an overlap is not.
export const PLOT_NODE_HEADER_H = 64; // header band above the collapsed beat roster
export const PLOT_NODE_BEAT_ROW_H = 24; // one beat row in that roster
export function estPlotNodeHeight(beatCount: number): number {
  return PLOT_NODE_HEADER_H + beatCount * PLOT_NODE_BEAT_ROW_H;
}
export const CONTAINER_PAD = 20; // inner padding between a box edge and its content
export const CONTAINER_HEADER = 32; // the title-bar band at the top of a box
export const CONTAINER_GAP = 24; // between sibling boxes / rows / acts
// Auto-laid-out cards wrap into a grid this many cards wide (#2348) — a single
// unwrapped row put the n-th loose card n card-widths away (card 40 ≈ 9400px).
export const CARDS_PER_ROW = 5;
const CARD_STEP_X = CARD_WIDTH + CARD_GAP_X;
// Auto-laid-out cards wrap into rows of CARDS_PER_ROW; a row is as tall as its tallest
// card. Given the cards' heights in order, returns each card's slot relative to the
// grid's top-left plus the grid's total height (including the trailing gap to what
// follows).
const layoutGrid = (heights: number[]): { offsets: BoardXY[]; height: number } => {
  const offsets: BoardXY[] = [];
  let y = 0;
  for (let start = 0; start < heights.length; start += CARDS_PER_ROW) {
    const row = heights.slice(start, start + CARDS_PER_ROW);
    row.forEach((_, j) => offsets.push({ x: j * CARD_STEP_X, y }));
    y += Math.max(...row) + CONTAINER_GAP;
  }
  return { offsets, height: y };
};

// Base z-index for the interactive nodes (cards + plotlines), above their container
// boxes (one z step per level, ADR-0094 §9, capped just below this). A node with an
// open kebab menu is lifted above its siblings by a CSS `:has()` rule in PlotEditor
// (#1095/#1100, at 900+), not by changing this value.
export const NODE_Z_INDEX = 50;

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

const cardRect = (p: BoardXY, h: number): Rect => ({ minX: p.x, minY: p.y, maxX: p.x + CARD_WIDTH, maxY: p.y + h });

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

// #2348: the boxes every OTHER node will occupy once `newId` is pinned. While a new
// card is still unpinned it holds an auto-grid slot, and pinning it lets the other
// unpinned cards close ranks — so free space must be read from the layout AFTER the
// pin (the new node parked off-board), or a spot it frees gets refilled by a card
// sliding back into it. `measured` supplies a rendered node's size where the layout
// doesn't fix one (a plotline's variable height).
export function occupiedAfterPin(
  projection: PlotBoardProjection,
  saved: Record<string, BoardXY>,
  savedSizes: Record<string, BoardSize>,
  newId: string,
  measured: ReadonlyMap<string, { width?: number; height?: number } | undefined> = new Map(),
): Box[] {
  const parked = { ...saved, [newId]: { x: -1e6, y: -1e6 } };
  return buildBoardNodes(projection, parked, savedSizes)
    .filter((n) => n.id !== newId)
    .map((n) => ({
      x: n.position.x,
      y: n.position.y,
      w: n.width ?? measured.get(n.id)?.width ?? CARD_WIDTH,
      h: n.height ?? measured.get(n.id)?.height ?? CARD_HEIGHT,
    }));
}

// #2348: where a NEW node goes — near the centre of what the author is looking
// at, not at the end of an ever-growing row. Returns the top-left for a node of
// `size` as close to `center` as possible without overlapping (with a gap) any of
// `occupied`: the centred spot first, then rings of card-sized steps around it.
// Pure, so the placement is unit-tested (the SvelteFlow canvas is not headless-
// testable); the caller supplies the view centre and the nodes on the board.
export function freeSpotNear(
  center: BoardXY,
  size: { w: number; h: number },
  occupied: readonly Box[],
  maxRings = 12,
): BoardXY {
  const origin = { x: Math.round(center.x - size.w / 2), y: Math.round(center.y - size.h / 2) };
  const fits = (at: BoardXY) =>
    occupied.every(
      (b) =>
        at.x + size.w + CARD_GAP_X <= b.x ||
        b.x + b.w + CARD_GAP_X <= at.x ||
        at.y + size.h + CARD_GAP_X <= b.y ||
        b.y + b.h + CARD_GAP_X <= at.y,
    );
  if (fits(origin)) return origin;
  const stepX = size.w + CARD_GAP_X;
  const stepY = size.h + CARD_GAP_X;
  for (let ring = 1; ring <= maxRings; ring++) {
    // Nearest candidates first within a ring: sort the ring's cells by distance.
    const cells: BoardXY[] = [];
    for (let dy = -ring; dy <= ring; dy++) {
      for (let dx = -ring; dx <= ring; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== ring) continue;
        cells.push({ x: origin.x + dx * stepX, y: origin.y + dy * stepY });
      }
    }
    cells.sort((a, b) => Math.hypot(a.x - origin.x, a.y - origin.y) - Math.hypot(b.x - origin.x, b.y - origin.y));
    const free = cells.find(fits);
    if (free) return free;
  }
  // A board packed solid around the view: fall back to the centred spot (the
  // author sees the new node on top and can drag it) rather than somewhere far.
  return origin;
}

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
// (`card.container`); every projected container renders as a box nested in its
// parent's, one per level (ADR-0094 §9). Homeless cards (no container) lay out loose
// below every box.
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

  // A container whose parent is not projected is laid out at the top.
  type Container = PlotBoardProjection["containers"][number];
  const isTop = (c: Container) => c.parent == null || !containerById.has(c.parent);

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

  // The container tree, one box per level (ADR-0094 §9). The projection holds only
  // containers with cards at some depth, plus their ancestors, so every projected
  // container draws a box: a sequence with cards nests inside its chapter's box,
  // inside its act's. `projection.containers` is in reading order, so each
  // container's children come out in reading order too.
  const tops = projection.containers.filter(isTop);
  const childrenOf = new Map<string, Container[]>();
  for (const c of projection.containers) {
    if (isTop(c)) continue;
    (childrenOf.get(c.parent!) ?? childrenOf.set(c.parent!, []).get(c.parent!)!).push(c);
  }
  // A box's level, 0 at the top: the tree's level when the projection carries it,
  // else its depth among the projected containers (the same number).
  const boxLevel = new Map<string, number>();
  const assignLevels = (c: Container, depth: number): void => {
    boxLevel.set(c.id, c.level != null ? c.level - 1 : depth);
    for (const child of childrenOf.get(c.id) ?? []) assignLevels(child, depth + 1);
  };
  tops.forEach((c) => assignLevels(c, 0));

  // --- Derived (pre-drag) positions: a tidy, non-overlapping default layout that a
  // pinned position then overrides. Top-level boxes stack top-to-bottom; inside a
  // box, its child boxes stack first, then a grid of its own direct cards. `place`
  // returns the y below the box plus the gap to whatever follows it.
  // #2348: only UNPINNED cards take a grid slot — a card the author dragged keeps
  // its own spot, so it must not also hold a slot open (a hole in the grid).
  const unpinned = (card: { id: string }) => !(card.id in saved);
  const heightOf = (card: { title: string; synopsis: string; beats: unknown[] }) =>
    estCardHeight(card.title, card.synopsis, card.beats.length);
  const derived = new Map<string, BoardXY>();
  const place = (container: Container, left: number, top: number): number => {
    const contentX = left + CONTAINER_PAD;
    let cursorY = top + CONTAINER_HEADER + CONTAINER_PAD;
    for (const child of childrenOf.get(container.id) ?? []) cursorY = place(child, contentX, cursorY);
    const autoCards = (cardsByInner.get(container.id) ?? []).filter(unpinned);
    const grid = layoutGrid(autoCards.map(heightOf));
    autoCards.forEach((card, i) => {
      const at = grid.offsets[i];
      derived.set(card.id, { x: contentX + at.x, y: cursorY + at.y });
    });
    cursorY += grid.height;
    // The last child already advanced cursorY by a trailing CONTAINER_GAP, which
    // serves as the gap to the next box; add this box's own bottom padding to it.
    return cursorY + CONTAINER_PAD;
  };
  let actY = 0;
  for (const top of tops) actY = place(top, 0, actY);
  // Homeless cards: a loose grid below every box, outside any box (they float).
  const homelessAuto = homeless.filter(unpinned);
  const homelessGrid = layoutGrid(homelessAuto.map(heightOf));
  homelessAuto.forEach((card, i) => {
    const at = homelessGrid.offsets[i];
    derived.set(card.id, { x: at.x, y: actY + CONTAINER_HEADER + at.y });
  });

  // Every projection card is either pinned (`saved`) or given a derived slot above
  // (in its container or homeless), so one of the two is non-null for any real card
  // id — the `!` states that invariant rather than silently defaulting to the origin.
  const positionOf = (id: string): BoardXY => saved[id] ?? derived.get(id)!;

  // --- Box geometry from FINAL positions (pins applied), computed inner-first so a
  // box wraps its child boxes and its direct cards. Each auto-wrap box is then grown
  // to any stored manual size (#878): min-not-override, so content still wins when it
  // is larger. The grown box drives BOTH the rendered size AND the member cards' drag
  // extent (#874), and a parent wraps its GROWN child boxes, so enlarging a chapter
  // enlarges its act too. The pre-grow (auto-wrap) size is retained per container as
  // the resize floor the handle can't drag below.
  const contentSize = new Map<string, BoardSize>();
  const grow = (id: string, box: Box): Box => {
    contentSize.set(id, { w: box.w, h: box.h });
    const manual = savedSizes[id];
    if (!manual) return box;
    return { ...box, w: Math.max(box.w, manual.w), h: Math.max(box.h, manual.h) };
  };
  const boxOf = new Map<string, Box>();
  const wrap = (container: Container): Box => {
    const rects: Rect[] = [];
    for (const child of childrenOf.get(container.id) ?? []) rects.push(rectOfBox(wrap(child)));
    for (const card of cardsByInner.get(container.id) ?? []) rects.push(cardRect(positionOf(card.id), heightOf(card)));
    const box = grow(container.id, boxFromContent(unionRects(rects)));
    boxOf.set(container.id, box);
    return box;
  };
  tops.forEach(wrap);

  // --- Emit: boxes outermost first (reading order is pre-order, so a parent always
  // precedes its children), then cards on top — both array order and explicit
  // zIndex, so a card is always clickable above every box.
  const nodes: PlotBoardNode[] = [];
  for (const container of projection.containers) {
    const box = boxOf.get(container.id);
    if (!box) continue; // not under any top-level box (a parent cycle): nothing to draw
    const level = boxLevel.get(container.id) ?? 0;
    // The auto-wrap size is the resize floor (data.minWidth/minHeight); it is always
    // set for a container that renders a box, since `grow` recorded it just above.
    const content = contentSize.get(container.id)!;
    nodes.push({
      id: containerNodeId(container.id),
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
      // A deeper box stacks above its parent; every box stays below the cards.
      zIndex: Math.min(level, NODE_Z_INDEX - 1),
      data: {
        title: container.title,
        count: containerCount.get(container.id) ?? 0,
        level,
        containerId: container.id,
        minWidth: content.w,
        minHeight: content.h,
      },
    });
  }

  // Arc colour resolution (Amendment 1 §1) — ONE site, used both to denormalise a
  // card's change-beats below and to seed the arc node's own `resolvedColorHex`
  // further down: own colour → the bound character's (lore) colour → the lore-kind
  // default, never the generic `plot` kind default (an arc's colour echoes the
  // CHARACTER it's about). Reads the lore roster + schema stores directly (the
  // ReferencePicker/plotline-roster precedent — a global roster is read where
  // needed, not threaded as a prop through every layer).
  const schema = get(metadataSchemaStore);
  const loreById = new Map(get(loreEntriesStore).map((entry) => [entry.id, entry] as const));
  const resolveArcHex = (arc: PlotBoardCharacterArc): string | null => {
    const character = arc.character_id ? loreById.get(arc.character_id) : undefined;
    const characterColorId = typeof character?.metadata?.color === "string" ? character.metadata.color : null;
    const characterHex = character ? resolveColor(characterColorId, character.entry_type, "lore", schema)?.hex : null;
    return (arc.color ? (getSwatch(arc.color)?.hex ?? null) : null) ?? characterHex ?? resolveColorForKind("lore")?.hex ?? null;
  };
  const arcResolvedHexById = new Map(projection.arcs.map((arc) => [arc.id, resolveArcHex(arc)]));

  for (const card of projection.cards) {
    const line = card.plotline ? plotlineById.get(card.plotline) : undefined;
    // Container lock (#873): confine the card's drag to its innermost container box
    // (the same box the card lays out in), so it can be rearranged inside it but
    // never dragged out. Homeless cards (no rendered box) get no extent and drag free.
    const cid = card.container != null && containerById.has(card.container) ? card.container : null;
    const box = cid ? boxOf.get(cid) : undefined;
    nodes.push({
      id: card.id,
      type: "plotCard",
      position: positionOf(card.id),
      width: CARD_WIDTH,
      height: heightOf(card),
      // Seed `measured` from our own geometry (size is single-sourced here, not
      // DOM-measured): xyflow only draws an edge once BOTH endpoint nodes are
      // measured, and its ResizeObserver may not have run yet (never does in a
      // 0-size / headless pane) — so without this the edge layers render nothing.
      // Only card nodes carry it: the edge layers connect cards, never containers.
      measured: { width: CARD_WIDTH, height: heightOf(card) },
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
        ...pageStatusOf(card.page_status, schema?.fields?.page_status),
        beats: card.beats.map((beat) => ({
          ...beat,
          resolvedColorHex:
            beat.holder_kind === "plot:character_arc"
              ? (arcResolvedHexById.get(beat.plotline_id) ?? null) // change-beat: the arc's effective colour
              : (getSwatch(beat.plotline_color)?.hex ?? null), // event-beat: the plotline swatch
        })),
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
  const plotlineBandY = actY + CONTAINER_HEADER + homelessGrid.height + CONTAINER_GAP;
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

  // Character-arc nodes (ADR-0080 §5 / Amendment 1): a SIBLING band below the
  // plotline band — an arc is a distinct holder kind, not merged into the plotline
  // row, so a writer scanning bands sees "the events" and "the internal changes" as
  // two registers. Same per-node x-spacing + saved-override model as plotlines; empty
  // when there are no plotlines, so an arc-only board doesn't leave a dead gap above it.
  // Clear the TALLEST plotline (nodes are variable-height; estimate from beat count),
  // so the arc band never lands inside a multi-beat plotline node.
  const maxPlotlineHeight = projection.plotlines.length
    ? Math.max(...projection.plotlines.map((line) => estPlotNodeHeight(line.beats.length)))
    : 0;
  const arcBandY = plotlineBandY + (maxPlotlineHeight ? maxPlotlineHeight + CONTAINER_GAP : 0);
  projection.arcs.forEach((arc, i) => {
    // Already resolved once above (the single arc-colour-resolution site), so the
    // node just reads its own entry back out of the map.
    const resolvedColorHex = arcResolvedHexById.get(arc.id) ?? null;
    nodes.push({
      id: arc.id,
      type: "plotArc",
      position: saved[arc.id] ?? { x: i * (PLOTLINE_WIDTH + CARD_GAP_X), y: arcBandY },
      width: PLOTLINE_WIDTH,
      // Same leading-grip handle as a card/plotline (#876).
      draggable: true,
      dragHandle: `.${CARD_DRAG_HANDLE_CLASS}`,
      selectable: false,
      zIndex: NODE_Z_INDEX,
      data: {
        title: arc.title,
        color: arc.color,
        beats: arc.beats,
        characterId: arc.character_id,
        characterName: arc.character_name,
        characterInitial: arc.character_initial,
        resolvedColorHex,
      },
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
// draggable node types — plotCard, plotPlotline, AND plotArc (ADR-0080 §5; all keyed by
// their own id in the shared `positions` map) — but never container boxes, which are
// derived. Positions are stored raw (not rounded) so the persist threshold matches
// moveNodesCommand's raw-inequality drag record: rounding here would let a sub-pixel
// drag record an undo step that saved nothing, so a later Ctrl+Z would reverse an
// invisible move.
export function movableNodePositions(nodes: PlotBoardNode[]): Record<string, BoardXY> {
  const out: Record<string, BoardXY> = {};
  for (const n of nodes) {
    if (n.type === "plotCard" || n.type === "plotPlotline" || n.type === "plotArc") {
      out[n.id] = { x: n.position.x, y: n.position.y };
    }
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
      // `holder_kind`/`character_id` (ADR-0080 §5) so a card's beat pill can distinguish
      // an event-beat from a change-beat and (in the next slice) show the right avatar —
      // rehydrated the moment either changes.
      c.beats.map((b) => [b.plotline_id, b.beat_id, b.title, b.plotline_color, b.holder_kind, b.character_id]),
      c.causal_links,
    ]),
    p.plotlines.map((l) => [l.id, l.title, l.color, l.beats.map((b) => [b.beat_id, b.title, b.use_count])]),
    // ADR-0080 §5: an arc's own colour AND its bound character (a rebind changes which
    // colour it falls back to, and the character name/avatar it shows) — a rebind or
    // recolour must rebuild the board so the node's resolved colour rehydrates.
    p.arcs.map((a) => [
      a.id,
      a.title,
      a.color,
      a.character_id,
      a.beats.map((b) => [b.beat_id, b.title, b.use_count]),
    ]),
    p.containers.map((c) => [c.id, c.title, c.parent]),
  ]);
}
