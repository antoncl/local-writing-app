// Mutation-sets domain store — the reusable mutation-set roster for the
// Mutations pane and the /mutate "apply a saved set" picker. Server-
// mirrored slice; `writable` for legacy-safe reads (docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { MutationSetEntry, MutationSetEntrySummary } from "@/lib/types";

export const mutationSetEntriesStore = writable<MutationSetEntrySummary[]>([]);

// The Mutations-pane editor request: `null` = closed; `{ editing }` = open
// (`editing` null → a new set). Lifted into the store because the "+ New set"
// action renders in the pane HANDLE bar (RegionActions) while the pane body and
// its dialog render in RegionBody — two component trees. A `bind:this` ref from
// the handle to the body does not survive that snippet → panelRegistry → Region*
// boundary (it stayed `undefined`, so the "+" was a silent no-op). A shared store
// drives one dialog from either trigger — the pattern every other pane's "+" uses.
export type MutationSetEditorRequest = { editing: MutationSetEntry | null };
export const mutationSetEditorStore = writable<MutationSetEditorRequest | null>(null);

export function openNewMutationSet(): void {
  mutationSetEditorStore.set({ editing: null });
}
export function openEditMutationSet(entry: MutationSetEntry): void {
  mutationSetEditorStore.set({ editing: entry });
}
export function closeMutationSetEditor(): void {
  mutationSetEditorStore.set(null);
}

export async function refreshMutationSetEntries(): Promise<void> {
  mutationSetEntriesStore.set((await api.listMutationSetEntries()).entries);
}

// Write-through from a mutation that already returns the canonical roster
// (delete mutation-set entry).
export function setMutationSetEntries(entries: MutationSetEntrySummary[]): void {
  mutationSetEntriesStore.set(entries);
}

export function clearMutationSets(): void {
  mutationSetEntriesStore.set([]);
}
