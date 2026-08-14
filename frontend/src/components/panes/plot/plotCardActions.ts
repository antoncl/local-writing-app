// The per-card action handlers a PlotCardNode invokes (ADR-0048 S7d). Provided by
// the PlotEditor via Svelte context so the presentational card node stays free of
// store/editor imports (and mountable in happy-dom for its render test — where the
// context is absent, so the card renders read-only, exactly as in S7b). The card
// passes its own id back; the handlers own the store/editor wiring.
//
// Content ops (realize/detach/set-plotline) are intentful backend mutations OUTSIDE
// the ADR-0050 layout caretaker (binding decision 1) — they never join the Ctrl+Z
// history.
import type { PlotBoardPlotline } from "@/lib/types";
import type { PlotRealizeLocation } from "@/lib/plot/realizeLocations";

export type PlotCardActions = {
  // Open the card as a NodeEditor document (full fields: plotline / scene / synopsis).
  onOpen: (cardId: string) => void;
  // Mint a scene from the card and attach it (unattached cards only). `parentId`
  // is the manuscript container the new scene lands under (#879); null defers to
  // the backend's first-container default (offered when the project has no
  // containers to choose from).
  onRealize: (cardId: string, parentId: string | null) => void;
  // Clear the card's scene ref (attached cards only).
  onDetach: (cardId: string) => void;
  // Persist an in-place title (name) edit. Empty titles are dropped by the card.
  onEditTitle: (cardId: string, title: string) => void;
  // Persist an in-place synopsis (body) edit.
  onEditSynopsis: (cardId: string, synopsis: string) => void;
  // Reassign the card's plotline ("" → Unassigned) — the reflow trigger.
  onSetPlotline: (cardId: string, plotlineId: string) => void;
  // Link a beat DROPPED onto the card (#824; from its plotline node in S4); deduped downstream.
  onLinkBeat: (cardId: string, plotline: string, beatId: string) => void;
  // Remove a linked beat via the × on its badge (#824).
  onUnlinkBeat: (cardId: string, plotline: string, beatId: string) => void;
  // Move a beat link from one card to another (#941) — drag a badge from card A onto
  // card B. Unlinks off `fromCard`, links on `toCard`, recorded as one undo step.
  onMoveBeat: (fromCard: string, toCard: string, plotline: string, beatId: string) => void;
  // Set an unattached card's page status (Slice 5b) — off_page vs unwritten; on_page
  // is derived from the scene, so it is never authored here.
  onSetPageStatus: (cardId: string, status: "off_page" | "unwritten") => void;
  // Delete the card outright (the kebab's "Delete card", #860). Distinct from Detach,
  // which only clears the scene ref. The provider confirms before the backend delete.
  onDelete: (cardId: string) => void;
  // The current lanes, for the "Set plotline" submenu. A getter on the provider so
  // the card reads them fresh from the projection.
  readonly plotlines: PlotBoardPlotline[];
  // The manuscript containers, for the "Realize scene" location submenu (#879). A
  // getter so the card reads the live manuscript tree (containers can be added while
  // the board is open). Empty ⇒ realize takes the backend default (no picker shown).
  readonly locations: PlotRealizeLocation[];
  // The focused plotline (ADR-0053 §6, S5b), or null. A card dims when a thread is
  // focused and this card is neither on it (its primary plotline) nor fulfilling one
  // of its beats. A getter so the card tracks it reactively (the `plotlines` idiom).
  readonly focusedPlotlineId: string | null;
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_CARD_ACTIONS = Symbol("plotCardActions");

// Actions the custom causal EDGE renders (#824): a visible × to remove the "leads to"
// link (select-edge + Delete stays too, but the × makes removal discoverable). Provided
// by PlotEditor so the edge component stays free of store imports, like the card.
export type PlotEdgeActions = {
  onUnlinkCausal: (source: string, target: string) => void;
};

export const PLOT_EDGE_ACTIONS = Symbol("plotEdgeActions");
