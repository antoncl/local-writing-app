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

// Rename a card in place (#798) — the title is intrinsic, not metadata. Fetch first
// so the save carries the card's live revision + body + metadata unchanged. The card
// UI drops empty titles before calling, matching the backend's non-empty requirement.
export async function renameCard(cardId: string, title: string): Promise<void> {
  const card = await api.getCard(cardId);
  await api.saveCard({ ...card, title }, card.body);
  await refreshAfterMutation();
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
// mutator adds/removes keys on a copy. A mutator that returns `false` signals "no
// change" — the save + refetch (and its board rebuild) are skipped, so e.g. dropping
// an already-linked beat is a cheap no-op instead of a redundant round-trip.
async function mutateCardMetadata(
  cardId: string,
  mutate: (metadata: CardEntry["metadata"]) => boolean | void,
): Promise<void> {
  const card = await api.getCard(cardId);
  const metadata = { ...card.metadata };
  if (mutate(metadata) === false) return;
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

// One card→beat link: an (arc instance id, beat id) pair — the stored shape of a
// `beat_links` item (both plain text, healed plot-locally on save; ADR-0048 S7 5b).
export type PlotBeatLink = { instance: string; beat_id: string };

// Beat links are authored by DRAGGING a beat from the Arcs palette onto a card (#824),
// so these are incremental add/remove ops over the card's current `beat_links`, not a
// whole-set write. Each reads the card's live metadata (via mutateCardMetadata's
// get→mutate→save) so a concurrent change never gets clobbered; the backend heals
// dangling links regardless.
function beatLinksOf(metadata: CardEntry["metadata"]): PlotBeatLink[] {
  const raw = metadata.beat_links;
  return Array.isArray(raw)
    ? raw.filter((l): l is PlotBeatLink => !!l && typeof l === "object" && "instance" in l && "beat_id" in l)
    : [];
}

// Drop a beat onto a card → add the link (deduped; a card fulfils a beat once).
// Already linked → no change, so skip the save + board rebuild.
export function linkCardBeat(cardId: string, instance: string, beat_id: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    const links = beatLinksOf(metadata);
    if (links.some((l) => l.instance === instance && l.beat_id === beat_id)) return false;
    links.push({ instance, beat_id });
    metadata.beat_links = links;
  });
}

// Remove a beat from a card (the badge's × on the card). An empty result drops the key
// (sparse), matching the backend's all-dangling→sparse heal.
export function unlinkCardBeat(cardId: string, instance: string, beat_id: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    const links = beatLinksOf(metadata).filter((l) => !(l.instance === instance && l.beat_id === beat_id));
    if (links.length) metadata.beat_links = links;
    else delete metadata.beat_links;
  });
}

// Causal ("leads to") edges are authored by DRAGGING a wire from one card's handle to
// another (#824, SvelteFlow onconnect), and removed by deleting the edge — so these are
// incremental over the source card's `causal_links`. Self-links are refused (the
// backend heals them anyway); dedup keeps one edge per pair.
function causalTargetsOf(metadata: CardEntry["metadata"]): { target: string }[] {
  const raw = metadata.causal_links;
  return Array.isArray(raw)
    ? raw.filter((l): l is { target: string } => !!l && typeof l === "object" && typeof (l as { target?: unknown }).target === "string")
    : [];
}

export function linkCardCausal(cardId: string, targetId: string): Promise<void> {
  if (cardId === targetId) return Promise.resolve(); // a card does not lead to itself
  return mutateCardMetadata(cardId, (metadata) => {
    const links = causalTargetsOf(metadata);
    if (links.some((l) => l.target === targetId)) return false; // already linked → no-op
    links.push({ target: targetId });
    metadata.causal_links = links;
  });
}

export function unlinkCardCausal(cardId: string, targetId: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    const links = causalTargetsOf(metadata).filter((l) => l.target !== targetId);
    if (links.length) metadata.causal_links = links;
    else delete metadata.causal_links;
  });
}

// Set the card's authored page status (ADR-0048 S7 Slice 5b) — only off_page vs
// unwritten; on_page is derived by the backend from the scene, so this is offered
// only for an unattached card. `unwritten` is the sparse default, so it drops the
// key rather than materializing a value (a save on an attached card would be
// overridden back to on_page regardless).
export function setCardPageStatus(cardId: string, status: "off_page" | "unwritten"): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    if (status === "off_page") metadata.page_status = "off_page";
    else delete metadata.page_status;
  });
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
}
