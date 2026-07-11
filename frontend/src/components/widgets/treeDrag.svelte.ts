// Drag-reorder gesture state for ViewNodeTree (#112 step 4c). The recursive tree
// renderer can't hold this itself — each recursion level is a fresh component
// instance — so ViewNodeList owns ONE holder and threads it down, exactly like
// the `collapsed` SvelteSet. Mutations on its `$state` fields are reactive at
// every level regardless of where they happen.
//
// The wrapper owns the whole gesture (which node is dragged, the current drop
// target + position, the before/after/into ratio zones); the consumer only
// supplies the domain classification via `isContainer` and receives the settled
// intent through `onReorder(moved, target, position)` (ADR-0035 escape hatch).

import type { EvalNode } from "@/lib/views/evaluateView";

export type DropPosition = "before" | "after" | "into";

export class TreeDrag<T extends EvalNode> {
  // The node currently being dragged (set on dragstart), or null when idle.
  dragged = $state<T | null>(null);
  // The row the cursor is over + where a drop would land, for the indicator.
  overId = $state<string | null>(null);
  position = $state<DropPosition | null>(null);

  reset(): void {
    this.dragged = null;
    this.overId = null;
    this.position = null;
  }
}
