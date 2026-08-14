// The actions a PlotPlotlineNode invokes for ON-NODE editing (ADR-0053 §3). Provided
// by the PlotEditor via Svelte context so the presentational plotline node stays free
// of store/api imports (and mountable in happy-dom for its render test — where the
// context is ABSENT, so the node renders its read-only roster, exactly as in S2a).
//
// A plotline is edited in place on the board (ADR-0038 §A expand-on-select): the node's
// header toggles it expanded, and expanded it hosts a rename / recolour / beat editor.
// The board owns the ephemeral `expandedId` (only one plotline expands at a time, cleared
// on a canvas-background click), mirroring the view designer's `designerContext`. The
// node loads the FULL plotline entry on expand (the board projection carries only beat
// titles, not their function/guidance/specifics, and a save must preserve the hidden
// lineage fields), edits a local draft, and flushes the whole entry back through `save`.
import type { PlotlineEntry } from "@/lib/types";

export type PlotPlotlineActions = {
  // Which plotline node is expanded to its editor, or null. A getter so the node reads
  // it fresh from the board's reactive state (the `plotCardActions.plotlines` idiom).
  readonly expandedId: string | null;
  // The node header is the toggle; a second toggle (or a pane-background click on the
  // board) collapses. Independent of Svelte Flow selection — plotline nodes are not
  // selectable, so selection can't drive this.
  toggleExpanded: (id: string) => void;
  // Which plotline's thread is FOCUSED across the board (ADR-0053 §6), or null. The
  // node's eye toggle reflects it; the edge builder emphasises this thread's beat-
  // sequence chain and dims the rest, and cards off it recede. A getter (fresh read).
  readonly focusedId: string | null;
  // The eye toggles focus for this plotline; a second toggle (or a pane-background
  // click) clears it. Only one thread is focused at a time.
  toggleFocus: (id: string) => void;
  // Load the full plotline entry when the node expands — the editable source of truth
  // (title + metadata.color + metadata.instance_beats + the hidden lineage fields).
  loadPlotline: (id: string) => Promise<PlotlineEntry>;
  // Flush an edited entry: persist it and refresh the board + rail so the change shows
  // on the node's read-only view, the cards it tints, and the roster. Returns the SAVED
  // entry so the node can advance its optimistic revision + capture backend-stamped beat
  // ids. The provider surfaces a failure in the app banner AND rethrows, so the node
  // resyncs from the server rather than looping stale-revision saves.
  save: (entry: PlotlineEntry) => Promise<PlotlineEntry>;
  // Delete the plotline (ADR-0053 §3 — the Plotlines rail that used to own delete is
  // retired). The provider confirms (destructive) before the backend delete; cards on
  // the thread revert to Unassigned. Fire-and-forget from the node's perspective.
  onDelete: (id: string) => void;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_PLOTLINE_ACTIONS = Symbol("plotPlotlineActions");
