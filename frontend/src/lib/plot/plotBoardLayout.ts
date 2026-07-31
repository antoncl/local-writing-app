// Plot-board layout (ADR-0048 S7b) — the PURE projection → SvelteFlow-nodes
// transform. This is where the board's real logic lives and where it is tested:
// the canvas itself is not headless-testable ([[reference_svelteflow_headless_limits]]),
// so the graph-building is verified here and the composition in a real browser.
//
// The read-only board groups cards into horizontal lanes, one per plotline (in
// projection order), plus a trailing "Unassigned" lane for cards with no plotline
// (or one that no longer resolves — refs are purged on delete, so this is just
// defensive). Each lane gets a header node at the left; its cards flow rightward.
// Layout editing / drag / persistence is S7c — here positions are derived, fixed.

import type { Node } from "@xyflow/svelte";
import type { PlotBoardProjection } from "@/lib/types";

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

// Build the fixed read-only layout. Plotlines keep projection order; the
// Unassigned lane is appended only when it holds at least one card, so an
// all-assigned board shows no empty trailing lane.
export function buildBoardNodes(projection: PlotBoardProjection): PlotBoardNode[] {
  const plotlineById = new Map(projection.plotlines.map((line) => [line.id, line]));

  // Bucket cards by their resolved lane, preserving projection card order within
  // each lane. A card whose plotline is null or unknown falls to Unassigned.
  const laneOrder: string[] = projection.plotlines.map((line) => line.id);
  const cardsByLane = new Map<string, PlotBoardProjection["cards"]>();
  for (const id of laneOrder) cardsByLane.set(id, []);
  for (const card of projection.cards) {
    const laneId = card.plotline && plotlineById.has(card.plotline) ? card.plotline : UNASSIGNED_LANE_ID;
    if (!cardsByLane.has(laneId)) cardsByLane.set(laneId, []);
    cardsByLane.get(laneId)!.push(card);
  }

  // Every plotline gets a lane (even empty) so the thread is always visible;
  // Unassigned appears only when non-empty.
  const lanes: string[] = [...laneOrder];
  if ((cardsByLane.get(UNASSIGNED_LANE_ID)?.length ?? 0) > 0) lanes.push(UNASSIGNED_LANE_ID);

  const nodes: PlotBoardNode[] = [];
  lanes.forEach((laneId, rowIndex) => {
    const y = rowIndex * ROW_STRIDE;
    const line = laneId === UNASSIGNED_LANE_ID ? null : plotlineById.get(laneId)!;
    const laneCards = cardsByLane.get(laneId) ?? [];

    nodes.push({
      id: `lane:${line ? line.id : "__unassigned__"}`,
      type: "plotLane",
      position: { x: 0, y },
      draggable: false,
      selectable: false,
      data: {
        title: line ? line.title : "Unassigned",
        color: line ? line.color : null,
        count: laneCards.length,
      },
    });

    laneCards.forEach((card, colIndex) => {
      nodes.push({
        id: card.id,
        type: "plotCard",
        position: {
          x: LANE_LABEL_WIDTH + LABEL_TO_CARD_GAP + colIndex * (CARD_WIDTH + CARD_GAP_X),
          y,
        },
        draggable: false,
        selectable: false,
        data: {
          title: card.title,
          synopsis: card.synopsis,
          attached: card.scene !== null,
          color: line ? line.color : null,
        },
      });
    });
  });

  return nodes;
}
