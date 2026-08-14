// Plot-board domain store (ADR-0048 S7b) — the projection the PlotEditor board
// renders from. Unlike the always-loaded slices (structure/lore/…), the board is
// heavy (a SvelteFlow canvas) and needed only while its pane is open, so it is
// refreshed on demand (mirrors chats/assistants), NOT on project open. `null` =
// not loaded yet. Two callers refresh it — the menu opener (surfaces errors in
// the banner) and PlotBoardPane on restore (a persisted tab whose store is null
// after reload) — so the fetch is in-flight-guarded to collapse the redundant
// pair into one request.

import { get, writable } from "svelte/store";
import { api } from "@/lib/api";
import { setStructure } from "@/lib/stores/structure";
import type { CardEntry, PlotBoardLayout, PlotBoardProjection, Scene } from "@/lib/types";

export const plotBoardStore = writable<PlotBoardProjection | null>(null);

// The last load's failure message, or null. Distinguishes a load ERROR from a
// not-yet-loaded null (#756): PlotBoardPane surfaces it as a retryable inline
// state instead of the permanent "Loading…" a failed fetch used to leave behind.
// Only meaningful while the projection is still null (an initial load / restore) —
// once the board is shown, a failed background refresh keeps the last-good board
// and the error is ignored. Cleared when a fresh load starts or succeeds.
export const plotBoardError = writable<string | null>(null);

let inFlight: Promise<void> | null = null;

export function refreshPlotBoard(): Promise<void> {
  if (inFlight) return inFlight;
  plotBoardError.set(null);
  inFlight = api
    .getPlotBoardProjection()
    .then((projection) => {
      plotBoardStore.set(projection);
    })
    .catch((error: unknown) => {
      // Record the failure for the inline error state and SWALLOW it: the sole
      // read callers are `void refreshPlotBoard()` (PlotBoardPane mount/restore) and
      // the menu opener — neither should raise an unhandled rejection, and the pane
      // now shows the error itself rather than relying on a transient banner.
      plotBoardError.set(error instanceof Error ? error.message : String(error));
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
// it is fine. `refreshPlotBoard` records its own errors and never rejects, so the
// drain needs no catch.
export async function refreshAfterMutation(): Promise<void> {
  if (inFlight) await inFlight;
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
// Returns the minted scene's id (from the card's `metadata.scene`) so realize can be
// recorded as an undoable command (ADR-0053 §7 / S6b) — undo deletes that scene.
export async function realizeCard(cardId: string, parentId: string | null = null): Promise<string> {
  const card = await api.realizeCard(cardId, parentId);
  await refreshAfterMutation();
  return typeof card.metadata.scene === "string" ? card.metadata.scene : "";
}

// Seed: one attached card per un-carded leaf scene, in manuscript order (idempotent).
// Returns the ids of the cards this run CREATED (for the undo command, §7) — the seed
// endpoint returns the whole card set, so we diff it against the ids the board already
// held. Reads plotBoardStore directly (synchronous, reliable) rather than a lagging
// projection prop, and uses the endpoint's own returned set as "after" (no extra list
// round-trip). Empty when nothing new was seeded (a re-run).
export async function seedCardsFromManuscript(): Promise<string[]> {
  const before = new Set((get(plotBoardStore)?.cards ?? []).map((c) => c.id));
  const after = await api.seedFromManuscript();
  await refreshAfterMutation();
  return after.entries.filter((c) => !before.has(c.id)).map((c) => c.id);
}

// Create a single unattached card — the board's direct-authoring entry point (#793,
// the plotter's construction surface). No scene, so it projects homeless until the
// writer attaches / realizes it. Refetches the projection, and returns the new id so
// the caller can open the card to name it. `id` is supplied only by redo-of-create
// (ADR-0053 §7) to restore the card's original identity.
export async function createCard(title: string, id?: string): Promise<string> {
  const card = await api.createCard(title, id);
  await refreshAfterMutation();
  return card.id;
}

// Delete a card outright (the board kebab's "Delete card", #860) — book-local, the
// board re-projects without it. Distinct from Detach, which only clears the scene
// ref; the scene:scene node (if any) is untouched. Uses the same endpoint the card
// editor pane's Delete does.
// `refresh` is false only inside a batched undo (a seed-undo deletes N cards) — the
// caller does ONE trailing refresh instead of N (the refetch-storm fix, #909).
export async function deleteCard(cardId: string, refresh = true): Promise<void> {
  await api.deleteCard(cardId);
  if (refresh) await refreshAfterMutation();
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

// ── Realize-undo substrate (ADR-0053 §7 / S6b) ──────────────────────────────
// Realize mints a scene FILE; its undo deletes that scene when the card is its sole
// referent. These helpers back the realize command's undo (see plotCommands.ts).

// The card ids that currently reference a scene — read synchronously off the live
// board store (reliable, not a lagging prop). One = a sole referent (safe to delete
// the scene); more = shared (detach this card only); the realize command reads it at
// UNDO time, since another card may have attached since the realize.
export function sceneReferents(sceneId: string): string[] {
  return (get(plotBoardStore)?.cards ?? []).filter((c) => c.scene === sceneId).map((c) => c.id);
}

// Read a scene (title + body) — the realize-undo confirm gates on whether the scene
// it is about to delete holds prose, and names it.
export function readScene(sceneId: string): Promise<Scene> {
  return api.getScene(sceneId);
}

// Delete a scene (realize-undo of a sole-referent scene). `delete_scene` purges the
// referencing card's `scene` ref backend-side, so this also detaches the card — no
// separate detach needed. Updates the manuscript structure store (the scene leaves
// the tree, mirroring editorPaneDelete) AND the board (the card projects homeless).
export async function deleteScene(sceneId: string): Promise<void> {
  setStructure(await api.deleteScene(sceneId));
  await refreshAfterMutation();
}

// One card→beat link: a (plotline id, beat id) pair — the stored shape of a
// `beat_links` item (both plain text, healed plot-locally on save; ADR-0048 S7 5b;
// ADR-0053 renamed the plotline half from `instance`).
export type PlotBeatLink = { plotline: string; beat_id: string };

// Beat links are authored by DRAGGING a beat onto a card (#824), so these are
// incremental add/remove ops over the card's current `beat_links`, not a whole-set
// write. Each reads the card's live metadata (via mutateCardMetadata's
// get→mutate→save) so a concurrent change never gets clobbered; the backend heals
// dangling links regardless.
function beatLinksOf(metadata: CardEntry["metadata"]): PlotBeatLink[] {
  const raw = metadata.beat_links;
  return Array.isArray(raw)
    ? raw.filter((l): l is PlotBeatLink => !!l && typeof l === "object" && "plotline" in l && "beat_id" in l)
    : [];
}

// Drop a beat onto a card → add the link (deduped; a card fulfils a beat once).
// Already linked → no change, so skip the save + board rebuild.
//
// The first beat dropped onto a card with no PRIMARY plotline adopts that beat's
// plotline as the card's primary — its tint/stripe (#863) — so the drop visibly
// lights the card in that thread's colour (ADR-0053 §4 resolves "how is the primary
// chosen?" as first-dragged). Sticky: a card that already has a primary keeps it, and
// later beats from other plotlines show only as badges (#871); the writer can still
// re-pick via the kebab. This runs only in the add-a-new-link branch, so a redundant
// re-drop of an already-linked beat stays a no-op (never resurrecting a cleared primary).
export function linkCardBeat(cardId: string, plotline: string, beat_id: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    const links = beatLinksOf(metadata);
    if (links.some((l) => l.plotline === plotline && l.beat_id === beat_id)) return false;
    links.push({ plotline, beat_id });
    metadata.beat_links = links;
    if (!metadata.plotline) metadata.plotline = plotline;
  });
}

// Remove a beat from a card (the badge's × on the card). An empty result drops the key
// (sparse), matching the backend's all-dangling→sparse heal.
export function unlinkCardBeat(cardId: string, plotline: string, beat_id: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => {
    const links = beatLinksOf(metadata).filter((l) => !(l.plotline === plotline && l.beat_id === beat_id));
    if (links.length) metadata.beat_links = links;
    else delete metadata.beat_links;
  });
}

// Move a beat link from one card to another (drag a badge card→card, #941): unlink it
// off the source, link it on the target — the target adopts the beat's plotline as its
// primary if it has none, exactly like a fresh drop (#863). Two saves, ONE refetch (not
// the per-op refresh of link+unlink). A drop back on the same card is a no-op; a target
// that already holds the beat still loses the source's link (idempotent target).
export async function moveCardBeat(
  fromId: string,
  toId: string,
  plotline: string,
  beat_id: string,
): Promise<void> {
  if (fromId === toId) return;
  const from = await api.getCard(fromId);
  const fromMeta = { ...from.metadata };
  const fromLinks = beatLinksOf(fromMeta).filter((l) => !(l.plotline === plotline && l.beat_id === beat_id));
  if (fromLinks.length) fromMeta.beat_links = fromLinks;
  else delete fromMeta.beat_links;
  await api.saveCard({ ...from, metadata: fromMeta }, from.body);

  const to = await api.getCard(toId);
  const toMeta = { ...to.metadata };
  const toLinks = beatLinksOf(toMeta);
  if (!toLinks.some((l) => l.plotline === plotline && l.beat_id === beat_id)) {
    toLinks.push({ plotline, beat_id });
    toMeta.beat_links = toLinks;
    if (!toMeta.plotline) toMeta.plotline = plotline;
  }
  await api.saveCard({ ...to, metadata: toMeta }, to.body);
  await refreshAfterMutation();
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

// ── Undo substrate (ADR-0053 §7) ────────────────────────────────────────────
//
// Content-op undo/redo captures a card's WHOLE authored state (title + synopsis
// body + metadata) rather than a per-field diff: a single op can touch several
// fields at once (dropping a beat also adopts a primary, #863), and a whole-state
// flip reverses every side-effect uniformly. undo/redo then re-fetch the live card
// for its current revision before saving the captured state, so a reversal can't
// 409 on a stale base_revision the way replaying an old entry verbatim would.

export type CardState = { title: string; body: string; metadata: CardEntry["metadata"] };

// A card's authored state, deep-copied so a later live mutation can't reach back
// into a captured snapshot the undo stack still holds.
export function cardStateOf(card: CardEntry): CardState {
  return { title: card.title, body: card.body, metadata: structuredClone(card.metadata) };
}

export async function getCardState(cardId: string): Promise<CardState> {
  return cardStateOf(await api.getCard(cardId));
}

// Restore a captured state onto a card that still exists (a field-edit reversal).
// Fetch-fresh for the live revision so the save can't conflict; refetch rebuilds
// the board. `refresh` is false inside a batched delete-undo, where N referrer
// restores run in parallel and the caller does ONE trailing refresh (#909).
export async function restoreCardState(cardId: string, state: CardState, refresh = true): Promise<void> {
  const card = await api.getCard(cardId);
  await api.saveCard({ ...card, title: state.title, metadata: state.metadata }, state.body);
  if (refresh) await refreshAfterMutation();
}

// Recreate a deleted card under its ORIGINAL id, then restore its content
// (create-then-PUT — the create sets only title, the PUT lands metadata + body).
// The one refetch is the restore's; the create is a plain api call to avoid a
// redundant board rebuild between the two writes.
export async function recreateCard(cardId: string, state: CardState, refresh = true): Promise<void> {
  await api.createCard(state.title, cardId);
  await restoreCardState(cardId, state, refresh);
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
  plotBoardError.set(null);
}
