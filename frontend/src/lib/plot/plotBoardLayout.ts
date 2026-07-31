// Plot-board layout (ADR-0048 S7b) — the PURE projection → SvelteFlow-nodes
// transform. This is where the board's real logic lives and where it is tested:
// the canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the graph-building is verified here and the composition in a real browser.
//
// The board groups cards into horizontal lanes, one per plotline (in projection
// order), plus a trailing "Unassigned" lane for cards with no plotline (or one
// that no longer resolves — refs are purged on delete, so this is just
// defensive). Each lane gets a header node at the left; its cards flow rightward.
//
// S7c makes card positions editable: `buildBoardNodes` takes the saved position
// overrides and a dragged card keeps its spot (lane headers stay derived/fixed).
// `readBoardPositions` / `cardPositionsFromNodes` are the read/write ends of the
// board's opaque `layout` dict that the PlotEditor round-trips.

import type { Node } from "@xyflow/svelte";
import type { BoardXY, PlotBoardLayout, PlotBoardProjection } from "@/lib/types";

// A lane header node: the plotline's name, its colour swatch id (for the accent),
// and how many cards sit in the lane.
export type PlotLaneData = {
  title: string;
  color: string | null;
  count: number;
};

// A card node: its synopsis (the body) and whether it is attached to a scene.
// `color` is the owning plotline's swatch id (null in the Unassigned lane), drawn
// as the card's left stripe so a card reads as belonging to its lane.
export type PlotCardData = {
  title: string;
  synopsis: string;
  attached: boolean;
  color: string | null;
};

export type PlotBoardNode = Node<PlotLaneData | PlotCardData>;

// Geometry (px). Exported so the unit test asserts against the same constants the
// layout uses rather than hard-coding magic numbers that could silently drift.
export const LANE_LABEL_WIDTH = 150;
export const CARD_WIDTH = 210;
export const CARD_HEIGHT = 110;
export const CARD_GAP_X = 30;
export const LABEL_TO_CARD_GAP = 40;
export const ROW_STRIDE = CARD_HEIGHT + 60;

// The synthetic lane id for cards with no (resolvable) plotline. Cannot collide
// with a real plotline node id, which is `lane:<plot_...>`.
export const UNASSIGNED_LANE_ID = "lane:__unassigned__";

// Build the board layout. Plotlines keep projection order; the Unassigned lane
// is appended only when it holds at least one card, so an all-assigned board
// shows no empty trailing lane. `saved` carries per-card position overrides
// (S7c): a card present there keeps that spot, otherwise it falls to its derived
// lane-grid slot.
export function buildBoardNodes(
  projection: PlotBoardProjection,
  saved: Record<string, BoardXY> = {},
): PlotBoardNode[] {
  const plotlineById = new Map(projection.plotlines.map((line) => [line.id, line]));

  // Bucket cards by their resolved lane, preserving projection card order within
  // each lane. A card whose plotline is null or unknown falls to Unassigned.
  // Keyed by plotline id (real lanes) or UNASSIGNED_LANE_ID.
  const cardsByLane = new Map<string, PlotBoardProjection["cards"]>();
  for (const line of projection.plotlines) cardsByLane.set(line.id, []);
  for (const card of projection.cards) {
    const laneId = card.plotline && plotlineById.has(card.plotline) ? card.plotline : UNASSIGNED_LANE_ID;
    if (!cardsByLane.has(laneId)) cardsByLane.set(laneId, []);
    cardsByLane.get(laneId)!.push(card);
  }

  // Every plotline gets a lane (even empty) so the thread is always visible;
  // Unassigned appears only when non-empty.
  const lanes: string[] = projection.plotlines.map((line) => line.id);
  if ((cardsByLane.get(UNASSIGNED_LANE_ID)?.length ?? 0) > 0) lanes.push(UNASSIGNED_LANE_ID);

  const nodes: PlotBoardNode[] = [];
  lanes.forEach((laneId, rowIndex) => {
    const y = rowIndex * ROW_STRIDE;
    const line = laneId === UNASSIGNED_LANE_ID ? null : plotlineById.get(laneId)!;
    const laneCards = cardsByLane.get(laneId) ?? [];

    // Node size is set here from the geometry constants (not left to SvelteFlow's
    // DOM measurement), so positions and rendered size share ONE source of truth;
    // the node components fill their box at 100%.
    nodes.push({
      id: line ? `lane:${line.id}` : UNASSIGNED_LANE_ID,
      type: "plotLane",
      position: { x: 0, y },
      width: LANE_LABEL_WIDTH,
      height: CARD_HEIGHT,
      draggable: false,
      selectable: false,
      data: {
        title: line ? line.title : "Unassigned",
        color: line ? line.color : null,
        count: laneCards.length,
      },
    });

    laneCards.forEach((card, colIndex) => {
      const derived = {
        x: LANE_LABEL_WIDTH + LABEL_TO_CARD_GAP + colIndex * (CARD_WIDTH + CARD_GAP_X),
        y,
      };
      nodes.push({
        id: card.id,
        type: "plotCard",
        // Saved position wins (S7c: a pinned card); an unsaved card falls to its
        // derived lane-grid slot, so a card added later flows in automatically.
        position: saved[card.id] ?? derived,
        width: CARD_WIDTH,
        height: CARD_HEIGHT,
        // Cards drag (S7c layout editing); lane headers stay fixed to the grid.
        draggable: true,
        selectable: false,
        data: {
          title: card.title,
          synopsis: card.synopsis,
          attached: card.scene != null,
          color: line ? line.color : null,
        },
      });
    });
  });

  return nodes;
}

// Read the typed position overrides out of the projection's opaque `layout`
// dict. An unknown / malformed shape degrades to no overrides (every card keeps
// its derived slot) rather than throwing — the board must always render.
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
// lane headers are derived (fixed) and never stored. Positions are stored raw (not
// rounded) so the persist threshold matches moveNodesCommand's raw-inequality drag
// record: rounding here would let a sub-pixel drag record an undo step that saved
// nothing, so a later Ctrl+Z would reverse an invisible move.
export function cardPositionsFromNodes(nodes: PlotBoardNode[]): Record<string, BoardXY> {
  const out: Record<string, BoardXY> = {};
  for (const n of nodes) {
    if (n.type === "plotCard") out[n.id] = { x: n.position.x, y: n.position.y };
  }
  return out;
}
