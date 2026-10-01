// Deck domain store (ADR-0097 §2) — the deck roster, modelled on
// `lib/stores/characterArcs.ts`. A deck is a plot-only box of cards: a title, a body (its
// synopsis) and an optional `plot_deck` parent reference that nests it inside another
// deck. Same book-local flat-node CRUD, whole-entry save, and undo substrate shape as
// the plotline / arc — kept as its own store so a deck is never routed through their
// undo commands (which would recreate it as the wrong kind).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { refreshPlotBoard, refreshAfterMutation } from "@/lib/stores/plotBoard";
import type { DeckEntry, DeckSummary } from "@/lib/types";

export const deckEntriesStore = writable<DeckSummary[]>([]);

// A deck's parent lives in this metadata key, and so does a card's home deck.
const DECK_FIELD = "plot_deck";

export async function refreshDecks(): Promise<void> {
  deckEntriesStore.set((await api.listDecks()).entries);
}

// Set the roster directly from a mutation that already returns it (a delete returns the
// refreshed list), avoiding a second round-trip.
export function setDecks(entries: DeckSummary[]): void {
  deckEntriesStore.set(entries);
}

export function clearDecks(): void {
  deckEntriesStore.set([]);
}

// Board-native create (the toolbar's "New deck", a deck's "New deck inside"): mint a deck,
// refresh the roster + board, and return its id so the caller can place it and start its
// title edit. `parent` nests it inside another deck in the same write.
export async function createDeckOnBoard(title = "New deck", parent?: string): Promise<string> {
  const deck = await api.createDeck(title, { parent });
  await Promise.all([refreshDecks(), refreshAfterMutation()]);
  return deck.id;
}

// Delete a deck. Only the deck goes: the backend's reference purge frees its cards and
// child decks, so the board refetch shows them loose / top level.
export async function deleteDeck(id: string, refresh = true): Promise<void> {
  setDecks((await api.deleteDeck(id)).entries);
  if (refresh) await refreshPlotBoard();
}

// Load the full deck entry (title + body + metadata) — what a rename or a pane edits.
export function getDeckEntry(id: string): Promise<DeckEntry> {
  return api.getDeck(id);
}

// Persist a whole-entry deck edit (rename, synopsis, re-parent), then refresh the roster
// and the board so the box re-derives.
export async function saveDeckEntry(entry: DeckEntry): Promise<DeckEntry> {
  const saved = await api.saveDeck(entry, entry.body);
  await Promise.all([refreshDecks(), refreshAfterMutation()]);
  return saved;
}

// ── Undo substrate (ADR-0053 §7, mirrored for decks) ────────────────────────
// A deck's whole authored state = title + synopsis body + metadata (the `plot_deck`
// parent), so a restore flips all of it, parent included.

export type DeckState = { title: string; body: string; metadata: DeckEntry["metadata"] };

export function deckStateOf(entry: DeckEntry): DeckState {
  return { title: entry.title, body: entry.body, metadata: structuredClone(entry.metadata) };
}

export async function getDeckState(id: string): Promise<DeckState> {
  return deckStateOf(await api.getDeck(id));
}

// Restore a captured state onto a deck that still exists. Fetch-fresh for the live
// revision, then refresh roster + board (unless a batched undo does one trailing refresh).
export async function restoreDeckState(id: string, state: DeckState, refresh = true): Promise<void> {
  const entry = await api.getDeck(id);
  await api.saveDeck({ ...entry, title: state.title, metadata: state.metadata }, state.body);
  if (refresh) await Promise.all([refreshDecks(), refreshAfterMutation()]);
}

// Recreate a deleted deck under its ORIGINAL id, then restore its content (create-then-
// PUT) — its body and its parent come back with it.
export async function recreateDeck(id: string, state: DeckState, refresh = true): Promise<void> {
  await api.createDeck(state.title, { id });
  await restoreDeckState(id, state, refresh);
}

// Refresh just the deck roster — the batched delete-undo's trailing roster refresh.
export function refreshDeckRoster(): Promise<void> {
  return refreshDecks();
}

// Put a card back in a deck after the deck's delete was undone (membership only — story
// time is untouched by a delete, so the order returns by itself). An unwritten card goes
// through `place`; a written card refuses `to`, so its home deck is set by a card save.
export async function restoreCardDeck(
  cardId: string,
  deckId: string,
  written: boolean,
  refresh = true,
): Promise<void> {
  if (written) {
    const card = await api.getCard(cardId);
    await api.saveCard({ ...card, metadata: { ...card.metadata, [DECK_FIELD]: deckId } }, card.body);
  } else {
    await api.placeCard(cardId, { to: { deck: deckId } });
  }
  if (refresh) await refreshAfterMutation();
}
