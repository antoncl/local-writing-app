// Dragging a top-level box (ADR-0097 §8, §9; #877) — pure. A box drag moves the box AND
// everything inside it: SvelteFlow moves the node it grabbed, and `followBoxDrag`
// live-translates the members (nested boxes and cards) by the same delta so the box moves
// as one piece. Only the box's own position is stored on release — the members re-derive
// from it on the rebuild — and dragging a box never moves the manuscript.

import type { BoardXY } from "@/lib/types";
import type { PlotBoardNode, PlotBoxData } from "./plotBoardLayout";

export type BoxDrag = {
  boxId: string;
  start: BoardXY;
  // Every member node → its start position.
  from: Map<string, BoardXY>;
};

/** Capture the box's start and each member's start position (a member is anything in the
 *  box's `memberIds`). */
export function startBoxDrag(nodes: readonly PlotBoardNode[], box: PlotBoardNode): BoxDrag {
  const members = new Set((box.data as PlotBoxData).memberIds);
  const from = new Map<string, BoardXY>();
  for (const n of nodes) if (members.has(n.id)) from.set(n.id, { ...n.position });
  return { boxId: box.id, start: { ...box.position }, from };
}

/** The nodes with every member translated by the box's delta from its start (absolute, not
 *  incremental, so repeated frames can't drift). The dragged box keeps SvelteFlow's own
 *  position. */
export function followBoxDrag(nodes: PlotBoardNode[], drag: BoxDrag, box: PlotBoardNode): PlotBoardNode[] {
  const dx = box.position.x - drag.start.x;
  const dy = box.position.y - drag.start.y;
  return nodes.map((n) => {
    const from = drag.from.get(n.id);
    return from ? { ...n, position: { x: from.x + dx, y: from.y + dy } } : n;
  });
}
