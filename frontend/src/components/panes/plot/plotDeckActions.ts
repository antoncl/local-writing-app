// The actions a PlotDeckNode invokes (ADR-0097 §8's deck menu). Provided by PlotEditor via
// Svelte context so the deck node's own script stays free of store/api imports and mounts in
// happy-dom for its render test — where the context is ABSENT, so the box renders read-only:
// title and synopsis, no menu. The node passes its own deck id back; the board owns the
// store wiring (and the undo recording).

export type PlotDeckActions = {
  // The deck whose title is being edited inline, or null — owned by the board so a new deck
  // can open straight into its title edit, and "Rename" in the menu can start one. A getter
  // so the node reads it fresh from the board's reactive state.
  readonly editingId: string | null;
  // "Rename" in the menu: start editing this deck's title.
  startRename: (deckId: string) => void;
  // Commit (a changed, non-empty title) or abandon (title null) the inline edit.
  finishRename: (deckId: string, title: string | null) => void;
  // "New card": create an unwritten card in this deck (planned in its container when realized).
  onNewCard: (deckId: string) => void;
  // "New deck inside": create a deck nested in this one.
  onNewDeckInside: (deckId: string) => void;
  // "Realize as <level>": make the deck a manuscript container; its cards become planned there.
  onRealize: (deckId: string) => void;
  // "Detach from deck" (on the realized container's box): unlink the deck; the chapter stays.
  onDetach: (deckId: string) => void;
  // "Open": the deck in a NodeEditor pane (title, synopsis, and its parent deck in the rail).
  onOpen: (deckId: string) => void;
  // "Delete": confirmed by the board when the deck holds cards or decks; only the deck goes.
  onDelete: (deckId: string) => void;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_DECK_ACTIONS = Symbol("plotDeckActions");
