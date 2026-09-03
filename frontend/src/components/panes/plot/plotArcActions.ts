// The actions a PlotArcNode invokes for ON-NODE editing (ADR-0080 §5 / Amendment 1).
// Mirrors plotPlotlineActions.ts — a character arc is the plotline's sibling beat-
// holder, edited the same way (expand-in-place, load-full-entry-on-expand, whole-entry
// save). Provided by PlotEditor via Svelte context so the presentational arc node stays
// free of store/api imports (and mountable in happy-dom for its render test — where the
// context is ABSENT, so the node renders its read-only roster, mirroring PlotPlotlineNode's
// S2a degrade).
//
// Two differences from the plotline actions, both because an arc is never a card's
// primary/colour thread (§4) and has no dedicated full-pane editor this slice:
//   - no `focusedId`/`toggleFocus` — a plotline's focus eye lights its beat-sequence
//     edges across the board; an arc's change-beats don't drive any edge layer yet (that
//     lands with the card pills, slice 3b-ii), so there's nothing for an arc's eye to
//     light or dim.
//   - no `onOpenInEditor` — an arc has no full-pane escape hatch this slice; on-node
//     editing is the only surface.
import type { CharacterArcEntry } from "@/lib/types";

export type PlotArcActions = {
  // Which arc node is expanded to its editor, or null. A getter so the node reads it
  // fresh from the board's reactive state.
  readonly expandedId: string | null;
  // The node header is the toggle; a second toggle (or a pane-background click on the
  // board) collapses.
  toggleExpanded: (id: string) => void;
  // Load the full arc entry when the node expands — the editable source of truth
  // (title + metadata.color + metadata.character + metadata.instance_beats + the
  // hidden lineage fields).
  loadArc: (id: string) => Promise<CharacterArcEntry>;
  // Flush an edited entry: persist it and refresh the board + roster. Returns the
  // SAVED entry so the node can advance its optimistic revision + capture backend-
  // stamped beat ids, mirroring the plotline `save`.
  save: (entry: CharacterArcEntry) => Promise<CharacterArcEntry>;
  // Bind (id) or clear (empty string) the arc's bound character. A DEDICATED action
  // rather than folding through the generic draft/commit chain: the ReferencePicker
  // commits the instant a reference is picked (no blur-to-commit gesture the way a
  // text field has), so this round-trips its own get→edit→save and returns the saved
  // entry, letting the node resync its local draft (revision + metadata.character)
  // without a full reload.
  setCharacter: (id: string, characterId: string) => Promise<CharacterArcEntry>;
  // Delete the arc (its kebab's "Delete character arc"). The provider confirms
  // (destructive) before the backend delete; cards that fulfilled one of its change-
  // beats lose that beat_link (an arc is never a primary, so no card recolours).
  onDelete: (id: string) => void;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_ARC_ACTIONS = Symbol("plotArcActions");
