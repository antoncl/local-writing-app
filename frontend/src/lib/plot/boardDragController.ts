// The board's drag gestures (ADR-0097 §8, §9; #877) — what SvelteFlow's three drag callbacks
// do, kept out of the component. SvelteFlow is not headless-testable, so the gestures talk
// to the canvas through a narrow host (its node array, the undo caretaker, the pointer
// converter) and the pure parts live beside this: `boxDrag` (a box carries its contents),
// `boardDrop` (which box and slot a card is over, and what releasing it does).
//
//   • a top-level BOX drag moves the box and everything inside it live; on release only the
//     box's own position is pinned, as ONE layout undo step, and the contents re-derive;
//   • a CARD drag shows an insertion bar (an overlay) where it would land; on release it becomes one
//     recorded `place` call (or a notice, for a written card), and the card snaps back into
//     the flow either way;
//   • a plotline / arc node drag is the plain Tier-1 position drag.

import type { Edge } from "@xyflow/svelte";
import type { PlaceRequest } from "@/lib/api/plot";
import { moveNodesCommand, type GraphPort } from "@/lib/graph/graphCommands";
import type { GraphUndoController } from "@/lib/graph/graphUndoController.svelte";
import type { BoardXY } from "@/lib/types";
import { dropBoxesFrom, hitTestDrop, planDrop, type DropTarget } from "./boardDrop";
import type { Box } from "./boardGeometry";
import { followBoxDrag, startBoxDrag, type BoxDrag } from "./boxDrag";
import { isBoxNode, type PlotBoardNode, type PlotCardData } from "./plotBoardLayout";

export interface BoardDragHost {
  // The bound SvelteFlow node array.
  nodes: PlotBoardNode[];
  // The graph port the box move's command replays through, and the board's caretaker.
  port: GraphPort<PlotBoardNode, Edge>;
  undo: Pick<GraphUndoController<PlotBoardNode, Edge>, "dragStart" | "dragStop" | "record">;
  // The insertion bar is an overlay, not a node: the bound node array must not be reassigned
  // mid-gesture (a full reconcile froze the board, #1095 → #1100). null hides it.
  setDropBar(bar: Box | null): void;
  // The autosave waits while a gesture is in flight.
  setDragging(on: boolean): void;
  // Mark a node's position as placed by hand, so it persists and stops deriving.
  pinPosition(id: string): void;
  // Re-derive every box and card slot from the layout state (a snap-back).
  rebuild(): void;
  focusBoard(): void;
  // Screen → flow coordinates; null before the canvas mounts.
  toFlow(screen: BoardXY): BoardXY | null;
  // The recorded content op behind a card drop.
  placeCard(cardId: string, place: PlaceRequest): Promise<void>;
  say(message: string): void;
  fail(error: unknown): void;
}

type CardDrag = { id: string; written: boolean; barKey: string; target: DropTarget | null };

function pointerOf(event: MouseEvent | TouchEvent): BoardXY | null {
  const at = "touches" in event ? (event.touches[0] ?? event.changedTouches[0]) : event;
  return at ? { x: at.clientX, y: at.clientY } : null;
}

export class BoardDragController {
  readonly #host: BoardDragHost;
  // The in-flight gesture, if any. Plain fields: read only inside the handlers.
  #box: BoxDrag | null = null;
  #card: CardDrag | null = null;

  constructor(host: BoardDragHost) {
    this.#host = host;
  }

  onStart = ({ nodes }: { nodes: PlotBoardNode[] }): void => {
    const host = this.#host;
    host.setDragging(true);
    this.#box = null; // clean slate each gesture
    this.#card = null;
    const box = nodes.find(isBoxNode);
    const card = nodes.find((n) => n.type === "plotCard");
    if (box) {
      this.#box = startBoxDrag(host.nodes, box);
    } else if (card) {
      this.#card = { id: card.id, written: (card.data as PlotCardData).attached, barKey: "", target: null };
    } else {
      host.undo.dragStart(nodes);
    }
  };

  onDrag = ({ event, nodes }: { event: MouseEvent | TouchEvent; nodes: PlotBoardNode[] }): void => {
    const host = this.#host;
    if (this.#box) {
      const drag = this.#box;
      const box = nodes.find((n) => n.id === drag.boxId);
      if (box) host.nodes = followBoxDrag(host.nodes, drag, box);
      return;
    }
    const card = this.#card;
    const screen = pointerOf(event);
    const at = screen && host.toFlow(screen);
    if (!card || !at) return;
    const target = hitTestDrop(dropBoxesFrom(host.nodes, card.id), at);
    card.target = target;
    // The bar shows only where a release would do something.
    const bar = planDrop(target, card).kind === "place" ? target!.bar : null;
    const key = bar ? `${bar.x},${bar.y},${bar.h}` : "";
    if (key === card.barKey) return;
    card.barKey = key;
    host.setDropBar(bar);
  };

  onStop = ({ nodes }: { nodes: PlotBoardNode[] }): void => {
    const host = this.#host;
    host.setDragging(false);
    // Return focus to the board (§7): the drag landed it on <body> (cards are
    // selectable:false), so without this the very Ctrl+Z that would undo the
    // drag wouldn't reach the caretaker.
    host.focusBoard();
    host.setDropBar(null);
    if (this.#box) {
      const drag = this.#box;
      this.#box = null;
      this.#dropBox(drag, nodes);
      return;
    }
    if (this.#card) {
      const drag = this.#card;
      this.#card = null;
      void this.#dropCard(drag);
      return;
    }
    host.undo.dragStop(nodes);
    // A dragged plotline or arc node becomes overridden (pinned): it now persists and
    // keeps its spot instead of reflowing to its derived slot.
    for (const node of nodes) {
      if (node.type === "plotPlotline" || node.type === "plotArc") host.pinPosition(node.id);
    }
  };

  // Pin ONLY the box's own position (one undo step); everything inside re-derives from it
  // on the rebuild. A drag that went nowhere records nothing.
  #dropBox(drag: BoxDrag, nodes: PlotBoardNode[]): void {
    const host = this.#host;
    const box = nodes.find((n) => n.id === drag.boxId) ?? host.nodes.find((n) => n.id === drag.boxId);
    const base = box && moveNodesCommand(host.port, [{ id: drag.boxId, from: drag.start, to: { ...box.position } }]);
    if (base) {
      host.pinPosition(drag.boxId);
      // Wrap so undo/redo ALSO re-derive the box's contents around the restored position.
      host.undo.record({
        ...base,
        undo: () => {
          base.undo();
          host.rebuild();
        },
        redo: () => {
          base.redo();
          host.rebuild();
        },
      });
    }
    host.rebuild();
  }

  // A card dropped into a deck or the loose area becomes one recorded `place` call; a
  // written card is refused with a line saying why. Either way the card snaps back into the
  // flow — the board re-derives its slot from the refetched projection.
  async #dropCard(drag: CardDrag): Promise<void> {
    const host = this.#host;
    const plan = planDrop(drag.target, drag);
    host.rebuild();
    if (plan.kind === "refuse") {
      host.say(plan.message);
    } else if (plan.kind === "place") {
      try {
        await host.placeCard(drag.id, plan.place);
      } catch (error) {
        host.fail(error);
      }
    }
  }
}
