// Plot-card roster (ADR-0074 slice 6) — the flat list of `plot:card` nodes,
// loaded on project open. The context picker's plotline selectors expand over
// this roster: a picked plotline is a live container whose members are the cards
// whose `metadata.plotline` points at it (evaluated frontend-side at invocation).
//
// Kept separate from the heavy board projection (plotBoard.ts): this is the light
// list the picker needs whether or not the board pane is open, the plotline
// roster's (plotlines.ts) card twin. Server-mirrored slice, same shape as the
// plotlines / prompts stores.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { CardSummary } from "@/lib/types";

export const cardEntriesStore = writable<CardSummary[]>([]);

export async function refreshCards(): Promise<void> {
  cardEntriesStore.set((await api.listCards()).entries);
}

// Set the roster directly from a mutation that already returns it (a card
// delete returns the refreshed list), avoiding a second round-trip — the
// setPlotlines / setPromptEntries convention.
export function setCards(entries: CardSummary[]): void {
  cardEntriesStore.set(entries);
}

export function clearCards(): void {
  cardEntriesStore.set([]);
}
