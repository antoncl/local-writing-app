// Plot-board layout (ADR-0048 S7 Slice 4; ADR-0097 §8, §9) — the PURE projection →
// SvelteFlow-nodes transform. This is where the board's real logic lives and where it is
// tested: the canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the graph-building is verified here and the composition in a real browser.
//
// The board is BOXES with cards flowing inside them. A box is a manuscript container
// (every one, empty or not), a deck (a plot-only box of cards), or the "Loose cards" box;
// `boxLayout.ts` reads the projection into that tree and lays it out. Cards are never
// positioned — each takes its slot in its box, in the box's own order — so a box sizes to
// its contents and only the TOP-LEVEL boxes (plus the plotline / arc nodes) carry a stored
// position, keyed by node id in the board's opaque `layout`.
//
// `readBoardPositions` / `movableNodePositions` / `overriddenNodePositions` are the
// read/write ends of that layout the PlotEditor round-trips.

import { get } from "svelte/store";
import type { Node } from "@xyflow/svelte";
import type {
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
import type { StoryAnchor } from "@/lib/api/plot";
import { inStoryOrder, lateCausesByEffect, storySwapAnchors } from "@/lib/plot/storyTime";
import {
  CARD_GAP_X,
  CARD_HEIGHT,
  CARD_WIDTH,
  CONTAINER_GAP,
  CONTAINER_HEADER,
  PLOTLINE_WIDTH,
  estCardHeight,
  estPlotNodeHeight,
  type Box,
} from "./boardGeometry";
import { LOOSE_NODE_ID, boardBoxes, layoutBoxes, type BoxKind } from "./boxLayout";

export * from "./boardGeometry";
export { LOOSE_NODE_ID, containerNodeId, deckNodeId } from "./boxLayout";

// What every box node carries: its kind, how deeply it nests (`topLevel` boxes are the
// ones placed and dragged), the height of its title band, the ids of its own cards in order (the drop hit-test reads
// them), every node inside it (a box drag carries those along), and how many cards it
// holds, transitively. A box is structural, so it carries no colour — plotline is the
// card's colour axis.
export type PlotBoxData = {
  boxKind: BoxKind;
  depth: number;
  topLevel: boolean;
  headerH: number;
  cardIds: string[];
  memberIds: string[];
  count: number;
};

// A manuscript container's box (or the loose box: `boxKind` "loose", an empty
// `containerId`). `level` is the container's level in the tree (0 = a top-level act, 1 = a
// chapter inside it, …: one nested box per level, ADR-0094 §9); `containerId` is the raw
// container id (the node id is `container:<id>`).
export type PlotContainerData = PlotBoxData & {
  title: string;
  level: number;
  containerId: string;
  // The deck realized as this container (ADR-0097 §7), when there is one: the box stands for
  // it and carries its menu.
  deckId?: string | null;
};

// A deck's box (ADR-0097 §2): its title, synopsis (the node shows the first lines), the raw
// deck id (the node id is `deck:<id>`), and whether the open layer owns it — an inherited
// deck can be opened but not renamed, nested into, or deleted.
export type PlotDeckData = PlotBoxData & {
  title: string;
  synopsis: string;
  deckId: string;
  movable: boolean;
  // The level a "Realize as …" would create at (null: none allowed here), ADR-0097 §7.
  realizeLevel?: string | null;
};

// A card node: its synopsis (the body), whether it is attached to a scene, and the
// owning plotline's swatch id (null for a colourless / unassigned plotline), drawn
// as the card's left stripe. Colour is independent of which container the card is in.
export type PlotCardData = {
  title: string;
  synopsis: string;
  attached: boolean;
  // Planned in a chapter without a scene (ADR-0097 §6): drawn dashed, with a "Planned" pill.
  planned: boolean;
  // The card's scene id (null = unwritten) and, for a planned card, the scene it follows in
  // its chapter — what a drop onto a chapter anchors on (ADR-0097 §6, §8).
  sceneId: string | null;
  plannedAfter: string | null;
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
  // The same links with the target cards' titles (#2402), for the menu's "Leads to…"
  // page — the removal fallback when the edge's × is out of reach. Derived from titles +
  // causal_links (both already in `projectionDataKey`).
  leadsTo: { id: string; title: string }[];
  // Story time (ADR-0097 §5, §8). `storyEarlier` / `storyLater` are what the menu's
  // "Earlier / Later in story time" would do — null (item hidden) for an inherited card
  // or at an end. `lateCauses` names the cards that lead to this one yet happen after
  // it: non-empty ⇒ the "Cause is later" pill.
  storyMovable: boolean;
  storyEarlier: StoryAnchor | null;
  storyLater: StoryAnchor | null;
  lateCauses: string[];
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

export type PlotBoardNode = Node<PlotContainerData | PlotDeckData | PlotCardData | PlotPlotlineData | PlotArcData>;

// A board is empty (show the hint, hide the canvas) only when it has NEITHER cards NOR
// plotlines NOR arcs NOR decks. Since ADR-0053 a plotline is a first-class board node (and
// ADR-0080 an arc is its sibling), so a card-less board with a thread still has
// something to render — treating it as empty would hide an instantiated plotline/arc
// (the S3 palette gesture). Pure + exported so the render decision is unit-tested
// against the SvelteFlow-gated PlotEditor.
export function boardIsEmpty(projection: PlotBoardProjection): boolean {
  return (
    projection.cards.length === 0 &&
    projection.plotlines.length === 0 &&
    projection.arcs.length === 0 &&
    projection.decks.length === 0
  );
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

// #2348: the boxes every OTHER node will occupy once `newId` is pinned. While a new
// top-level box is still unpinned it holds a slot in the stack, and pinning it lets the
// other unpinned boxes close ranks — so free space must be read from the layout AFTER the
// pin (the new node parked off-board), or a spot it frees gets refilled by a box
// sliding back into it. `measured` supplies a rendered node's size where the layout
// doesn't fix one (a plotline's variable height).
export function occupiedAfterPin(
  projection: PlotBoardProjection,
  saved: Record<string, BoardXY>,
  newId: string,
  measured: ReadonlyMap<string, { width?: number; height?: number } | undefined> = new Map(),
): Box[] {
  const parked = { ...saved, [newId]: { x: -1e6, y: -1e6 } };
  return buildBoardNodes(projection, parked)
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

// Base z-index for the interactive nodes (cards + plotlines), above their boxes (one z
// step per nesting level, capped just below this). A node with an open kebab menu is
// lifted above its siblings by a CSS `:has()` rule in PlotEditor (#1095/#1100, at 900+),
// not by changing this value.
export const NODE_Z_INDEX = 50;

// The class SvelteFlow's `dragHandle` targets so a top-level box drags ONLY by its header
// band (#877), a window-titlebar affordance — the transparent interior stays a
// non-interactive backdrop, so card drags and the edge layers still pass through it
// (#833). Shared: every box node's `dragHandle` (buildBoardNodes) and its header element's
// class (PlotContainerNode, PlotDeckNode) must name the same selector.
export const CONTAINER_DRAG_HANDLE_CLASS = "plot-container-drag-handle";

// The class SvelteFlow's `dragHandle` targets on the CARD-like nodes — story cards
// (plotCard) AND plotline nodes (plotPlotline) — so each drags ONLY by a small leading
// grip, not by its whole body (#876). Their bodies are dense with inline-edit controls
// (title, synopsis, kebab, focus, beats), so a whole-body drag surface left only slivers
// between the controls to grab; a dedicated grip is a clear, fixed handle. Shared by both
// card-like node types and both node components, exactly as the box handle above — the
// node's `dragHandle` selector and the grip element's class must never drift apart.
export const CARD_DRAG_HANDLE_CLASS = "plot-card-drag-handle";

// `plotContainer` also draws the loose box.
export const isBoxNode = (n: { type?: string }): boolean => n.type === "plotContainer" || n.type === "plotDeck";

// The "Loose cards" box title.
const LOOSE_TITLE = "Loose cards";

function looseData(over: Partial<PlotContainerData> = {}): PlotContainerData {
  return {
    boxKind: "loose",
    depth: 0,
    topLevel: true,
    headerH: CONTAINER_HEADER,
    cardIds: [],
    memberIds: [],
    count: 0,
    title: LOOSE_TITLE,
    level: 0,
    containerId: "",
    ...over,
  };
}

// Build the board layout (ADR-0097 §8): box nodes outermost first, then the cards on top,
// then the plotline and arc bands. `saved` carries the stored positions — only the
// TOP-LEVEL boxes' and the plotline / arc nodes' are read; a card position an older board
// stored is ignored, because a card's slot is always derived from its box.
export function buildBoardNodes(projection: PlotBoardProjection, saved: Record<string, BoardXY> = {}): PlotBoardNode[] {
  const plotlineById = new Map(projection.plotlines.map((line) => [line.id, line]));
  const containerById = new Map(projection.containers.map((c) => [c.id, c]));
  const deckById = new Map(projection.decks.map((d) => [d.id, d]));
  const cardById = new Map(projection.cards.map((c) => [c.id, c]));
  // The deck each container stands in for (ADR-0097 §7).
  const realizedDeckOf = new Map(projection.decks.flatMap((d) => (d.realized_container ? [[d.realized_container, d.id] as const] : [])));
  const heightOf = (card: { title: string; synopsis: string; beats: unknown[] }) =>
    estCardHeight(card.title, card.synopsis, card.beats.length);

  const layout = layoutBoxes(boardBoxes(projection), saved);

  // --- Emit: boxes outermost first (pre-order, so a parent always precedes its children),
  // then cards on top — both array order and explicit zIndex, so a card is always
  // clickable above every box.
  const nodes: PlotBoardNode[] = [];
  for (const box of layout.boxes) {
    const { spec, rect } = box;
    const common = {
      id: spec.nodeId,
      position: { x: rect.x, y: rect.y },
      width: rect.w,
      height: rect.h,
      // Only a top-level box moves, and ONLY by its header band (`dragHandle`) — it carries
      // everything inside it along (the box drag in PlotEditor); the transparent interior
      // stays inert so card drags + edges pass through (#833). A nested box never drags.
      draggable: box.topLevel,
      dragHandle: `.${CONTAINER_DRAG_HANDLE_CLASS}`,
      selectable: false,
      connectable: false,
      // A deeper box stacks above its parent; every box stays below the cards.
      zIndex: Math.min(box.depth, NODE_Z_INDEX - 1),
    };
    const boxData = {
      boxKind: spec.kind,
      depth: box.depth,
      topLevel: box.topLevel,
      headerH: box.headerH,
      cardIds: box.cardIds,
      memberIds: box.memberIds,
      count: box.count,
    };
    if (spec.kind === "deck") {
      const deck = deckById.get(spec.ref)!;
      nodes.push({
        ...common,
        type: "plotDeck",
        data: {
          ...boxData,
          title: deck.title,
          synopsis: deck.synopsis,
          deckId: deck.id,
          movable: deck.movable,
          realizeLevel: deck.realize_level_name ?? null,
        },
      });
    } else if (spec.kind === "container") {
      const container = containerById.get(spec.ref)!;
      nodes.push({
        ...common,
        type: "plotContainer",
        // The container's level in the tree when the projection carries it, else its depth.
        data: {
          ...boxData,
          title: container.title,
          level: container.level != null ? container.level - 1 : box.depth,
          containerId: container.id,
          deckId: realizedDeckOf.get(container.id) ?? null,
        },
      });
    } else {
      nodes.push({ ...common, type: "plotContainer", data: looseData(boxData) });
    }
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

  const lateCauses = lateCausesByEffect(projection.cards);
  const storyOrdered = inStoryOrder(projection.cards);
  const storySwapOf = (id: string) => {
    const { earlier, later } = storySwapAnchors(storyOrdered, id);
    return { storyEarlier: earlier, storyLater: later };
  };

  // Cards, in the order their boxes list them. Every projected card sits in exactly one
  // box, so each has a derived slot.
  for (const box of layout.boxes) {
    for (const cardId of box.cardIds) {
      const card = cardById.get(cardId)!;
      const line = card.plotline ? plotlineById.get(card.plotline) : undefined;
      nodes.push({
        id: card.id,
        type: "plotCard",
        position: layout.cardAt.get(card.id)!,
        width: CARD_WIDTH,
        height: heightOf(card),
        // Seed `measured` from our own geometry (size is single-sourced here, not
        // DOM-measured): xyflow only draws an edge once BOTH endpoint nodes are
        // measured, and its ResizeObserver may not have run yet (never does in a
        // 0-size / headless pane) — so without this the edge layers render nothing.
        // Only card nodes carry it: the edge layers connect cards, never boxes.
        measured: { width: CARD_WIDTH, height: heightOf(card) },
        // Draggable, but ONLY by the leading grip (`dragHandle`, #876) — the card body is
        // full of inline-edit controls, so a whole-body drag surface was near-ungrabbable.
        // A drag moves the card between boxes, never to a spot: it snaps back into the
        // flow on release, wherever it lands.
        draggable: true,
        dragHandle: `.${CARD_DRAG_HANDLE_CLASS}`,
        selectable: false,
        zIndex: NODE_Z_INDEX,
        data: {
          title: card.title,
          synopsis: card.synopsis,
          attached: card.scene != null,
          planned: card.planned_in != null && card.scene == null,
          sceneId: card.scene,
          plannedAfter: card.planned_in != null && card.scene == null ? card.planned_after : null,
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
          leadsTo: card.causal_links.flatMap((tid) => {
            const target = cardById.get(tid);
            return target ? [{ id: tid, title: target.title }] : [];
          }),
          storyMovable: card.story_movable,
          ...storySwapOf(card.id),
          lateCauses: lateCauses.get(card.id) ?? [],
        },
      });
    }
  }

  // Plotline nodes (ADR-0053 §3): a plotline is a first-class board node holding its
  // beat roster, NOT a lane the cards sit in — so it floats free (draggable anywhere),
  // laid out by default in a loose row in a band below the stacked boxes. Once dragged its
  // position persists (same saved-override model as a top-level box). The node id IS the
  // plotline id; ids are distinct across node kinds, so one `saved` map (keyed by node
  // id) holds them all without collision.
  const plotlineBandY = layout.stackBottom;
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

// Serialize the current movable-node positions for persistence (S7c; ADR-0053; ADR-0097
// §9): the nodes the writer places by hand — plotline and arc nodes, and the TOP-LEVEL
// boxes (container / deck / loose) — keyed by node id in the shared `positions` map. A
// card is never stored (it flows in its box), nor is a nested box (it nests). Positions
// are stored raw (not rounded) so the persist threshold matches moveNodesCommand's
// raw-inequality drag record: rounding here would let a sub-pixel drag record an undo
// step that saved nothing, so a later Ctrl+Z would reverse an invisible move.
export function movableNodePositions(nodes: PlotBoardNode[]): Record<string, BoardXY> {
  const out: Record<string, BoardXY> = {};
  for (const n of nodes) {
    const placed = n.type === "plotPlotline" || n.type === "plotArc" || (isBoxNode(n) && (n.data as PlotBoxData).topLevel);
    if (placed) out[n.id] = { x: n.position.x, y: n.position.y };
  }
  return out;
}

// The sparse persist (S7d reflow): store a position ONLY for the nodes the writer has
// explicitly placed (dragged this session or already in the saved layout). An un-placed
// box or node is absent, so it derives its slot in the stack — a new one lands in the
// gap, and the rest close ranks around it.
export function overriddenNodePositions(nodes: PlotBoardNode[], overridden: Set<string>): Record<string, BoardXY> {
  const all = movableNodePositions(nodes);
  const out: Record<string, BoardXY> = {};
  for (const id of Object.keys(all)) {
    if (overridden.has(id)) out[id] = all[id];
  }
  return out;
}

// A content-identity key over the projection's DATA — board id + each card's fields
// (including its container and deck) + each plotline + each container + each deck — deliberately EXCLUDING
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
      // ADR-0097 §2: the home deck decides which box an unwritten card flows in.
      c.deck,
      c.page_status,
      // `holder_kind`/`character_id` (ADR-0080 §5) so a card's beat pill can distinguish
      // an event-beat from a change-beat and (in the next slice) show the right avatar —
      // rehydrated the moment either changes.
      c.beats.map((b) => [b.plotline_id, b.beat_id, b.title, b.plotline_color, b.holder_kind, b.character_id]),
      c.causal_links,
      // Story time (ADR-0097 §5): a move re-indexes cards, so the late-cause pills and
      // the Earlier/Later menu items rebuild with it.
      c.story_order,
      c.story_movable,
      // ADR-0097 §6: where a card sits inside its chapter box. A drag inside one chapter
      // (a planned card's new anchor, a written card's scene moved) changes ONLY these,
      // so leaving them out kept the old order on screen until some other change
      // rebuilt the board and everything jumped at once (#2397).
      c.container_order,
      c.planned_in,
      c.planned_after,
      // Manuscript reading rank: the manuscript edge layer and "Scene N" read it.
      c.sequence,
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
    p.containers.map((c) => [c.id, c.title, c.parent, c.level, c.level_name]),
    // A deck's title, synopsis, parent and ownership all show on its box.
    p.decks.map((d) => [d.id, d.title, d.synopsis, d.parent, d.movable, d.realized_container, d.realize_level_name]),
  ]);
}
