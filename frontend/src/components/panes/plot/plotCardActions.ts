// The per-card action handlers a PlotCardNode invokes (ADR-0048 S7d). Provided by
// the PlotEditor via Svelte context so the presentational card node stays free of
// store/editor imports (and mountable in happy-dom for its render test — where the
// context is absent, so the card renders read-only, exactly as in S7b). The card
// passes its own id back; the handlers own the store/editor wiring.
//
// Content ops (realize/detach/set-plotline) are intentful backend mutations OUTSIDE
// the ADR-0050 layout caretaker (binding decision 1) — they never join the Ctrl+Z
// history.
import type { PlotBoardPlotline, StructureDocument } from "@/lib/types";
import type { PlotRealizeLocation } from "@/lib/plot/realizeLocations";
import type { StoryAnchor } from "@/lib/api/plot";

export type PlotCardActions = {
  // Open the card as a NodeEditor document (full fields: plotline / scene / synopsis).
  onOpen: (cardId: string) => void;
  // Mint a scene from the card and attach it (unattached cards only). `parentId`
  // is the manuscript container the new scene lands under (#879); null defers to
  // the backend's first-container default (offered when the project has no
  // containers to choose from).
  onRealize: (cardId: string, parentId: string | null) => void;
  // Bind the card to an existing scene picked in the Attach picker (unattached cards
  // only, ADR-0097 §4). May ask the writer which summary survives.
  onAttach: (cardId: string, sceneId: string) => void;
  // Release the card's scene (attached cards only); the card takes the scene's title.
  onDetach: (cardId: string) => void;
  // Persist an in-place title (name) edit. Empty titles are dropped by the card.
  onEditTitle: (cardId: string, title: string) => void;
  // Persist an in-place synopsis (body) edit.
  onEditSynopsis: (cardId: string, synopsis: string) => void;
  // Reassign the card's plotline ("" → Unassigned) — the reflow trigger.
  onSetPlotline: (cardId: string, plotlineId: string) => void;
  // Link a beat DROPPED onto the card (#824; from its plotline node in S4); deduped
  // downstream. `holderKind` (ADR-0080 §4) is the dragged beat's holder subtype off the
  // drag payload — undefined/"plot:plotline" for an event-beat, "plot:character_arc"
  // for a change-beat (which must never adopt primary).
  onLinkBeat: (cardId: string, plotline: string, beatId: string, holderKind?: string) => void;
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
  // Move the card in story time (ADR-0097 §4) — the menu's Earlier / Later / Place
  // after…, and the Story time view's drag. One recorded undo step.
  onStoryMove: (cardId: string, anchor: StoryAnchor) => void;
  // The cards a "Place after…" can anchor on: the open layer's own, in story time (the
  // backend refuses an inherited card as an anchor). A getter, like `plotlines`.
  readonly storyAnchors: { id: string; title: string }[];
  // The current lanes, for the "Set plotline" submenu. A getter on the provider so
  // the card reads them fresh from the projection.
  readonly plotlines: PlotBoardPlotline[];
  // The manuscript containers, for the "Write as scene" location submenu (#879). A
  // getter so the card reads the live manuscript tree (containers can be added while
  // the board is open). Empty ⇒ realize takes the backend default (no picker shown).
  readonly locations: PlotRealizeLocation[];
  // The manuscript the Attach picker browses, and the scenes it leaves out (a scene
  // holds at most one card, ADR-0097 §1). Getters so the picker reads them live.
  readonly structure: StructureDocument | null;
  readonly heldSceneIds: string[];
  // The focused plotline (ADR-0053 §6, S5b), or null. A card dims when a thread is
  // focused and this card is neither on it (its primary plotline) nor fulfilling one
  // of its beats. A getter so the card tracks it reactively (the `plotlines` idiom).
  readonly focusedPlotlineId: string | null;
  // The cards a selected diagnostic finding lights (ADR-0048 S7): when a finding is
  // selected in the diagnostics panel, its cards are LIT and every other card recedes
  // — the same lit/dimmed treatment as plotline focus, keyed on a card-id set instead
  // of a thread. Null (or empty) ⇒ no finding selected. Takes precedence over
  // `focusedPlotlineId` (only one is ever active — selecting a finding clears focus).
  readonly highlightedCardIds: ReadonlySet<string> | null;
  // The card last pressed (#2363), or null. PlotEditor lifts it above the other cards
  // with a CSS `:has()` rule, so a card partly hidden under another is brought to the
  // front by clicking any visible part of it. Ephemeral display state, never saved.
  readonly raisedCardId: string | null;
  onRaise: (cardId: string) => void;
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
