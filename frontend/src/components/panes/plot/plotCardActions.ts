// The per-card action handlers a PlotCardNode invokes (ADR-0048 S7d). Provided by
// the PlotEditor via Svelte context so the presentational card node stays free of
// store/editor imports (and mountable in happy-dom for its render test — where the
// context is absent, so the card renders read-only, exactly as in S7b). The card
// passes its own id back; the handlers own the store/editor wiring.
//
// Content ops (realize/detach) are intentful backend mutations OUTSIDE the
// ADR-0050 layout caretaker (binding decision 1) — they never join the Ctrl+Z
// history. Reassignment (onSetPlotline) arrives with the reflow slice.
export type PlotCardActions = {
  // Open the card as a NodeEditor document (full fields: plotline / scene / synopsis).
  onOpen: (cardId: string) => void;
  // Mint a scene from the card and attach it (unattached cards only).
  onRealize: (cardId: string) => void;
  // Clear the card's scene ref (attached cards only).
  onDetach: (cardId: string) => void;
  // Persist an in-place synopsis (body) edit.
  onEditSynopsis: (cardId: string, synopsis: string) => void;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_CARD_ACTIONS = Symbol("plotCardActions");
