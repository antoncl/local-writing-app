// Plot-board domain store (ADR-0048 S7b) — the projection the PlotEditor board
// renders from. Unlike the always-loaded slices (structure/lore/…), the board is
// heavy (a SvelteFlow canvas) and needed only while its pane is open, so it is
// refreshed on demand (mirrors chats/assistants), NOT on project open. `null` =
// not loaded yet. Two callers refresh it — the menu opener (surfaces errors in
// the banner) and PlotBoardPane on restore (a persisted tab whose store is null
// after reload) — so the fetch is in-flight-guarded to collapse the redundant
// pair into one request.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { CardEntry, PlotBoardLayout, PlotBoardProjection } from "@/lib/types";

export const plotBoardStore = writable<PlotBoardProjection | null>(null);

let inFlight: Promise<void> | null = null;

export function refreshPlotBoard(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = api
    .getPlotBoardProjection()
    .then((projection) => {
      plotBoardStore.set(projection);
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

// A mutation's refresh must reflect state AFTER the mutation. The coalescing guard
// above is right for READ triggers (mount + opener collapse into one fetch), but a
// mutation must NOT piggyback on a read-refresh that began BEFORE it — that fetch
// resolves with a pre-mutation projection and the new state never lands. Drain any
// such in-flight read first, then run one fresh fetch whose (post-mutation) result
// sets the store last. A fetch that starts here is post-mutation, so coalescing with
// it is fine.
async function refreshAfterMutation(): Promise<void> {
  const pending = inFlight;
  if (pending) {
    try {
      await pending;
    } catch {
      // A failed read-refresh is retried by the fresh fetch below.
    }
  }
  await refreshPlotBoard();
}

// Persist the board layout (ADR-0048 S7c) and return the board's advanced
// revision (the mounted editor's next optimistic base). Deliberately does NOT
// touch plotBoardStore: the store's projection is only the editor's initial seed
// (refetched on the next open), and re-setting it would rebuild the canvas from
// under an in-progress edit. The PlotEditor owns the live revision from here on.
export async function savePlotBoardLayout(layout: PlotBoardLayout, baseRevision: string): Promise<string> {
  const saved = await api.savePlotBoard({ base_revision: baseRevision, layout });
  return saved.revision;
}

// Card content ops (ADR-0048 §1, S7d). These are intentful backend mutations,
// deliberately OUTSIDE the ADR-0050 layout caretaker — an in-memory undo must
// never reverse a scene mint (binding decision 1). Each mutates, then refetches
// the projection so the board re-projects the changed card set. attach/detach have
// no endpoint of their own: they are a saveCard that sets / clears `metadata.scene`
// (get the current card first, so the save carries its live revision + metadata).

// Realize: mint a scene from the card and attach it. 409 if already attached.
export async function realizeCard(cardId: string, parentId: string | null = null): Promise<void> {
  await api.realizeCard(cardId, parentId);
  await refreshAfterMutation();
}

// Seed: one attached card per un-carded leaf scene, in manuscript order (idempotent).
export async function seedCardsFromManuscript(): Promise<void> {
  await api.seedFromManuscript();
  await refreshAfterMutation();
}

// Create a single unattached card — the board's direct-authoring entry point (#793,
// the plotter's construction surface). No scene, so it projects homeless until the
// writer attaches / realizes it. Refetches the projection, and returns the new id so
// the caller can open the card to name it.
export async function createCard(title: string): Promise<string> {
  const card = await api.createCard(title);
  await refreshAfterMutation();
  return card.id;
}

// Save an in-place synopsis edit — the synopsis IS the card body. Fetch first so
// the save carries the card's live revision + metadata unchanged.
export async function saveCardSynopsis(cardId: string, synopsis: string): Promise<void> {
  const card = await api.getCard(cardId);
  await api.saveCard({ ...card }, synopsis);
  await refreshAfterMutation();
}

// The single get → mutate a clone of the card's metadata → save (body unchanged) →
// refetch path the metadata-ref content ops share (detach, reassign — and attach
// once a board affordance wires it). saveCard replaces metadata wholesale, so the
// mutator adds/removes keys on a copy.
async function mutateCardMetadata(cardId: string, mutate: (metadata: CardEntry["metadata"]) => void): Promise<void> {
  const card = await api.getCard(cardId);
  const metadata = { ...card.metadata };
  mutate(metadata);
  await api.saveCard({ ...card, metadata }, card.body);
  await refreshAfterMutation();
}

// Reassign the card's plotline ("" clears it → the Unassigned lane). The refetched
// projection changes the board's data-key, so the board rebuilds and an un-pinned
// card reflows into the new lane (a pinned one keeps its spot — S7d reflow).
export function reassignCardPlotline(cardId: string, plotlineId: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    if (plotlineId) metadata.plotline = plotlineId;
    else delete metadata.plotline;
  });
}

// Detach: clear the card's scene ref (drop the key — the save replaces metadata).
export function detachCardScene(cardId: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    delete metadata.scene;
  });
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
}
