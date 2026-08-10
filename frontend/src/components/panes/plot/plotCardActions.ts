// The per-card action handlers a PlotCardNode invokes (ADR-0048 S7d). Provided by
// the PlotEditor via Svelte context so the presentational card node stays free of
// store/editor imports (and mountable in happy-dom for its render test — where the
// context is absent, so the card renders read-only, exactly as in S7b). The card
// passes its own id back; the handlers own the store/editor wiring.
//
// Content ops (realize/detach/set-plotline) are intentful backend mutations OUTSIDE
// the ADR-0050 layout caretaker (binding decision 1) — they never join the Ctrl+Z
// history.
import type { PlotBoardPlotline, TemplateInstanceSummary } from "@/lib/types";
import type { PlotBeatLink } from "@/lib/stores/plotBoard";

export type PlotCardActions = {
  // Open the card as a NodeEditor document (full fields: plotline / scene / synopsis).
  onOpen: (cardId: string) => void;
  // Mint a scene from the card and attach it (unattached cards only).
  onRealize: (cardId: string) => void;
  // Clear the card's scene ref (attached cards only).
  onDetach: (cardId: string) => void;
  // Persist an in-place title (name) edit. Empty titles are dropped by the card.
  onEditTitle: (cardId: string, title: string) => void;
  // Persist an in-place synopsis (body) edit.
  onEditSynopsis: (cardId: string, synopsis: string) => void;
  // Reassign the card's plotline ("" → Unassigned) — the reflow trigger.
  onSetPlotline: (cardId: string, plotlineId: string) => void;
  // Set the card's whole beat-link set (Slice 5b) — the beat picker owns the desired
  // selection and writes it here.
  onSetBeats: (cardId: string, links: PlotBeatLink[]) => void;
  // Set an unattached card's page status (Slice 5b) — off_page vs unwritten; on_page
  // is derived from the scene, so it is never authored here.
  onSetPageStatus: (cardId: string, status: "off_page" | "unwritten") => void;
  // The current lanes, for the "Set plotline" submenu. A getter on the provider so
  // the card reads them fresh from the projection.
  readonly plotlines: PlotBoardPlotline[];
  // The book's arcs (template instances) + their beats, for the beat picker. A getter
  // so the picker reads the live roster fresh (the plotlines precedent).
  readonly arcs: TemplateInstanceSummary[];
};

// Symbol key so the context can't collide with a string-keyed one.
export const PLOT_CARD_ACTIONS = Symbol("plotCardActions");
