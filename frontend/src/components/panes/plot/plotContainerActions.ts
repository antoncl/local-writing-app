// The action a PlotContainerNodeFlow invokes when its resize handle is dragged (#878).
// Provided by the PlotEditor via Svelte context so the container node stays free of
// store/api imports (and the presentational PlotContainerNode stays mountable in
// happy-dom, where the context is ABSENT — a container mounted without it simply has
// no resize handle, exactly the read-only backdrop of Slice 4).
//
// A container is otherwise a derived, soft backdrop; resizing gives it a STORED size —
// a minimum the auto-wrap never shrinks below (see BoardSize) — which the PlotEditor
// pins in the board layout and feeds back into buildBoardNodes. The board owns that
// `sizes` map; the node only reports the size it was dragged to, keyed by container id.
import type { BoardSize } from "@/lib/types";

export type PlotContainerActions = {
  // Persist the size a container's resize handle was dragged to. `containerId` is the
  // raw id (the flow node id is `container:<id>`); `size` is the box's final w/h. The
  // board records it in the layout's `sizes` map and autosaves, and the next rebuild
  // grows the box to at least this — widening its member cards' drag extent (#874).
  onResize: (containerId: string, size: BoardSize) => void;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_CONTAINER_ACTIONS = Symbol("plotContainerActions");
