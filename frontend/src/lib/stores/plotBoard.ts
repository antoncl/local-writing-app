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
import { type CardTextChoice, type PlaceRequest, type PlaceTo, type StoryAnchor, textChoiceConflict } from "@/lib/api/plot";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { refreshStructure, setStructure } from "@/lib/stores/structure";
import { refreshCards } from "@/lib/stores/plotCards";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
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

// Open the plot board pane (#1920): fetch-then-show, so the pane opens at once and
// shows "Loading…" until the projection resolves. `refreshPlotBoard` records a
// failure in `plotBoardError` (the pane renders it inline) and never rejects, so no
// run()/banner is needed here. Lives with the store it opens (review of #1922) —
// `paneOpeners.ts` re-exports it for its App-level callers.
export function openPlotBoardPane(): void {
  void refreshPlotBoard();
  workspaceLayout.ensureVisible("plotEditor");
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
  // Refresh the board projection AND the lightweight card roster in parallel: the
  // context picker's plotline selectors expand over that roster (ADR-0074 slice 6),
  // so a card created / deleted / reassigned here stays live without a reload.
  // refreshCards records nothing and its failure is independent of the board's.
  await Promise.all([refreshPlotBoard(), refreshCards().catch(() => {})]);
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
// the projection so the board re-projects the changed card set. attach / detach /
// the displayed-text edit are endpoints of their own (ADR-0097 §3/§4) — saveCard
// ignores a client-sent `scene` and refuses a written card's title/body change.

// Realize: mint a scene from the card and attach it. 409 if already attached.
// Returns the minted scene's id (from the card's `metadata.scene`) so realize can be
// recorded as an undoable command (ADR-0053 §7 / S6b) — undo deletes that scene.
// The minted scene joins the manuscript, and the endpoint returns the card, not the
// tree — so the structure is refetched too, or the manuscript pane misses the new
// scene until a reload (#2359). Redo re-realizes through here, so it is covered.
// A failed tree refetch must not fail a realize that already happened (the undo
// recorder would then never record it), so it is swallowed like refreshCards.
export async function realizeCard(cardId: string, parentId: string | null = null): Promise<string> {
  const card = await api.realizeCard(cardId, parentId);
  await Promise.all([refreshAfterMutation(), refreshStructure().catch(() => {})]);
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
// (ADR-0053 §7) to restore the card's original identity. `to` creates it in a deck
// (ADR-0097 §4) — a deck's "New card".
export async function createCard(title: string, id?: string, to?: PlaceTo): Promise<string> {
  const card = await api.createCard(title, id, undefined, to);
  await refreshAfterMutation();
  return card.id;
}

// Delete a card outright (the board kebab's "Delete card", #860) — book-local, the
// board re-projects without it. Distinct from Detach, which only clears the scene
// ref; the manuscript:scene node (if any) is untouched. Uses the same endpoint the card
// editor pane's Delete does.
// `refresh` is false only inside a batched undo (a seed-undo deletes N cards) — the
// caller does ONE trailing refresh instead of N (the refetch-storm fix, #909).
export async function deleteCard(cardId: string, refresh = true): Promise<void> {
  await api.deleteCard(cardId);
  if (refresh) await refreshAfterMutation();
}

// Move a card in story time (ADR-0097 §4): right after / before another card. The
// rank lives on the backend; the refetch re-indexes every card's `story_order`.
export async function moveCardInStoryTime(cardId: string, anchor: StoryAnchor): Promise<void> {
  await api.placeCard(cardId, { story: anchor });
  await refreshAfterMutation();
}

// Place a card (ADR-0097 §4): into a deck or the loose area, and/or beside a neighbour in
// story time. A drag between two cards sends both; the refetch re-derives every box.
export async function placeCardOnBoard(cardId: string, place: PlaceRequest): Promise<void> {
  await api.placeCard(cardId, place);
  await refreshAfterMutation();
}

// Rename a card in place (#798) — the title is intrinsic, not metadata. Edits the
// DISPLAYED title (ADR-0097 §3): the scene's while the card is written. The card UI
// drops empty titles before calling, matching the backend's non-empty requirement.
export async function renameCard(cardId: string, title: string): Promise<void> {
  await setCardText(cardId, { title });
}

// Save an in-place synopsis edit — the synopsis IS the card body, or the scene's
// summary while the card is written (ADR-0097 §3).
export async function saveCardSynopsis(cardId: string, synopsis: string): Promise<void> {
  await setCardText(cardId, { synopsis });
}

// Edit the displayed title and/or synopsis in one write (the text command's undo/redo
// replays both). A written card's title edit renames its scene, so the manuscript tree
// is refetched too; a failed tree refetch must not fail an edit that already happened.
export async function setCardText(cardId: string, text: { title?: string; synopsis?: string }): Promise<void> {
  await api.setCardText(cardId, text);
  await Promise.all([refreshAfterMutation(), refreshStructure().catch(() => {})]);
}

// The single get → mutate a clone of the card's metadata → save (body unchanged) →
// refetch path the metadata-ref content ops share (reassign, beat and causal links,
// page status). saveCard replaces metadata wholesale, so the
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

// ── Attach / detach (ADR-0097 §3/§4) ────────────────────────────────────────
// Both move text between the card and its scene. When the scene's summary and the
// card's synopsis both hold something different the backend 409s with both texts and
// the writer picks which survives; the pick is retried through the same op. The
// result is the choice actually used (null: none was needed) so undo / redo replay it
// without asking again, or "cancelled" when the writer backed out (nothing changed, so
// the caller records no undo step).
export type CardTextOutcome = CardTextChoice | null | "cancelled";

type TextChoiceAsk = {
  title: string;
  confirmLabel: string;
  confirmChoice: CardTextChoice;
  secondaryLabel: string;
  secondaryChoice: CardTextChoice;
};

const CLIP = 200;
const clip = (text: string): string => (text.length > CLIP ? `${text.slice(0, CLIP)}…` : text);

function askTextChoice(
  ask: TextChoiceAsk,
  conflict: { sceneSummary: string; cardSynopsis: string },
): Promise<CardTextChoice | null> {
  return new Promise((resolve) => {
    confirmService.request({
      title: ask.title,
      message: "The scene's summary and the card's synopsis are different.",
      details: [`Scene summary: ${clip(conflict.sceneSummary)}`, `Card synopsis: ${clip(conflict.cardSynopsis)}`],
      confirmLabel: ask.confirmLabel,
      secondaryLabel: ask.secondaryLabel,
      destructive: false,
      onConfirm: async () => resolve(ask.confirmChoice),
      onSecondary: () => resolve(ask.secondaryChoice),
      onCancel: () => resolve(null),
    });
  });
}

async function withTextChoice(
  ask: TextChoiceAsk,
  op: (text?: CardTextChoice) => Promise<unknown>,
  text?: CardTextChoice,
): Promise<CardTextOutcome> {
  let used: CardTextChoice | null = text ?? null;
  try {
    await op(text);
  } catch (error) {
    const conflict = textChoiceConflict(error);
    if (!conflict) throw error;
    const chosen = await askTextChoice(ask, conflict);
    if (!chosen) return "cancelled";
    await op(chosen);
    used = chosen;
  }
  // A scene's summary may have moved, and the card's text with it.
  await Promise.all([refreshAfterMutation(), refreshStructure().catch(() => {})]);
  return used;
}

// Detach: the card leaves its scene and takes the scene's title; `text` says which
// synopsis it keeps when both differ (asked when omitted and needed).
export function detachCardScene(cardId: string, text?: CardTextChoice): Promise<CardTextOutcome> {
  return withTextChoice(
    {
      title: "Which synopsis should the card keep?",
      confirmLabel: "Keep the card's synopsis",
      confirmChoice: "card",
      secondaryLabel: "Take the scene's summary",
      secondaryChoice: "scene",
    },
    (choice) => api.detachCard(cardId, choice),
    text,
  );
}

// Attach: bind the card to an existing scene; `text` says which summary the scene
// keeps when both differ (asked when omitted and needed).
export function attachCardScene(cardId: string, sceneId: string, text?: CardTextChoice): Promise<CardTextOutcome> {
  return withTextChoice(
    {
      title: "Which summary should the scene keep?",
      confirmLabel: "Keep the scene's summary",
      confirmChoice: "scene",
      secondaryLabel: "Use the card's synopsis",
      secondaryChoice: "card",
    },
    (choice) => api.attachCard(cardId, sceneId, choice),
    text,
  );
}

// ── Realize-undo substrate (ADR-0053 §7 / S6b) ──────────────────────────────
// Realize mints a scene FILE; its undo deletes that scene (the card is its sole
// referent, ADR-0097 §1). These helpers back the realize command's undo (see plotCommands.ts).

// The scenes any card on the board holds — the Attach picker excludes them (a scene
// has at most one card, ADR-0097 §1). Read off the live board store.
export function heldSceneIds(): string[] {
  return (get(plotBoardStore)?.cards ?? []).map((c) => c.scene).filter((id): id is string => !!id);
}

// The card ids that currently reference a scene — read synchronously off the live
// board store (reliable, not a lagging prop). The realize command reads it at UNDO
// time to tell whether the realize was already reversed elsewhere.
export function sceneReferents(sceneId: string): string[] {
  return (get(plotBoardStore)?.cards ?? []).filter((c) => c.scene === sceneId).map((c) => c.id);
}

// Read a scene (title + body) — the realize-undo confirm gates on whether the scene
// it is about to delete holds prose, and names it.
export function readScene(sceneId: string): Promise<Scene> {
  return api.getScene(sceneId);
}

// A scene's summary — attach-undo puts it back when the attach overwrote it.
export async function readSceneSummary(sceneId: string): Promise<string> {
  return String((await api.getScene(sceneId)).metadata?.summary ?? "");
}

// Delete a scene (realize-undo). `delete_scene` purges the
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

// The two beat-link mutations, as PURE metadata edits so link / unlink / move share
// one definition of what a link is and how the primary + sparse-delete rules behave
// (#941 — a move is unlink-here + link-there, and must not re-implement either). Each
// mutates `metadata` in place and returns whether it changed anything.
//
// The first beat added to a card with no PRIMARY plotline adopts that beat's plotline as
// the card's primary — its tint/stripe (#863; ADR-0053 §4 "first-dragged"). Sticky: a
// card that already has a primary keeps it, and later beats from other plotlines show
// only as badges (#871); the writer re-picks via the kebab. A re-add of an already-linked
// beat is a no-op, so it never resurrects a cleared primary.
//
// `holderKind` (ADR-0080 §4): a change-beat's holder is a character arc, which the
// backend 422s as a card's `plotline` — so a change-beat drop must NEVER adopt primary,
// even onto a primary-less card. The beat_link is still created either way; only the
// primary-adoption is arc-specific.
function linkBeatInMetadata(
  metadata: CardEntry["metadata"],
  plotline: string,
  beat_id: string,
  holderKind: string = "plot:plotline",
): boolean {
  const links = beatLinksOf(metadata);
  if (links.some((l) => l.plotline === plotline && l.beat_id === beat_id)) return false;
  links.push({ plotline, beat_id });
  metadata.beat_links = links;
  if (!metadata.plotline && holderKind !== "plot:character_arc") metadata.plotline = plotline;
  return true;
}

// An empty result drops the key (sparse), matching the backend's all-dangling→sparse heal.
function unlinkBeatInMetadata(metadata: CardEntry["metadata"], plotline: string, beat_id: string): boolean {
  const before = beatLinksOf(metadata);
  const links = before.filter((l) => !(l.plotline === plotline && l.beat_id === beat_id));
  if (links.length === before.length) return false; // nothing removed
  if (links.length) metadata.beat_links = links;
  else delete metadata.beat_links;
  return true;
}

// Drop a beat onto a card → add the link (deduped; a card fulfils a beat once).
// Already linked → no change, so mutateCardMetadata skips the save + board rebuild.
// `holderKind` (ADR-0080 §4) is the dragged beat's holder subtype — threaded from the
// drag payload so a change-beat drop never adopts the arc as the card's primary.
export function linkCardBeat(cardId: string, plotline: string, beat_id: string, holderKind?: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => linkBeatInMetadata(metadata, plotline, beat_id, holderKind));
}

// Remove a beat from a card (the badge's × on the card).
export function unlinkCardBeat(cardId: string, plotline: string, beat_id: string): Promise<void> {
  return mutateCardMetadata(cardId, (metadata) => unlinkBeatInMetadata(metadata, plotline, beat_id));
}

// Move a beat link from one card to another (drag a badge card→card, #941): unlink it
// off the source, link it on the target (adopting the target's primary if unset, like a
// fresh drop). Two saves, ONE refetch (calling link+unlink would refetch twice). A drop
// back on the same card is a no-op; a target that already holds the beat still loses the
// source's link (idempotent target).
export async function moveCardBeat(
  fromId: string,
  toId: string,
  plotline: string,
  beat_id: string,
): Promise<void> {
  if (fromId === toId) return;
  const from = await api.getCard(fromId);
  const fromMeta = { ...from.metadata };
  unlinkBeatInMetadata(fromMeta, plotline, beat_id);
  await api.saveCard({ ...from, metadata: fromMeta }, from.body);

  const to = await api.getCard(toId);
  const toMeta = { ...to.metadata };
  linkBeatInMetadata(toMeta, plotline, beat_id);
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
// only for an unattached card. The schema default (unwritten, unless a layer says
// otherwise) is the sparse blank — the rail's rule (#1421): picking it drops the
// key rather than materializing a value, so reader and writer agree on what a
// blank means (a save on an attached card would be overridden back to on_page
// regardless).
export function setCardPageStatus(cardId: string, status: "off_page" | "unwritten"): Promise<void> {
  const schemaDefault = get(metadataSchemaStore)?.fields?.page_status?.default ?? "unwritten";
  return mutateCardMetadata(cardId, (metadata) => {
    if (status === schemaDefault) delete metadata.page_status;
    else metadata.page_status = status;
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

export type CardState = {
  title: string;
  body: string;
  metadata: CardEntry["metadata"];
  // The card's read-only place in story time (ADR-0097 §5): never saved back, only
  // handed to a re-create so an undone delete returns it to the same spot.
  story_rank?: number | null;
};

// A card's authored state, deep-copied so a later live mutation can't reach back
// into a captured snapshot the undo stack still holds.
export function cardStateOf(card: CardEntry): CardState {
  return {
    title: card.title,
    body: card.body,
    metadata: structuredClone(card.metadata),
    story_rank: card.story_rank ?? null,
  };
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

// Recreate a deleted card under its ORIGINAL id and story rank, then restore its
// content (create-then-PUT — the create sets only title, the PUT lands metadata +
// body). The card is unwritten until the final attach, so its own text restores
// freely; a written card is then re-bound to its scene ("scene": the scene already
// holds the summary the card showed, so nothing is asked). The one refetch is the
// restore's; the create is a plain api call to avoid a redundant board rebuild.
export async function recreateCard(cardId: string, state: CardState, refresh = true): Promise<void> {
  await api.createCard(state.title, cardId, state.story_rank);
  const { scene, ...own } = state.metadata;
  await restoreCardState(cardId, { ...state, metadata: own }, false);
  if (typeof scene === "string" && scene) await api.attachCard(cardId, scene, "scene");
  if (refresh) await refreshAfterMutation();
}

// Drop the previous project's board so it can't flash on the next project's pane
// (called from the project-clear fan-out).
export function clearPlotBoard(): void {
  plotBoardStore.set(null);
  plotBoardError.set(null);
}
