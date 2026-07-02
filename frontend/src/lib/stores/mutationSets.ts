// Mutation-sets domain store — the reusable mutation-set roster for the
// Mutations pane and the /mutate "apply a saved set" picker. Server-
// mirrored slice; `writable` for legacy-safe reads (docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { MutationSetEntrySummary } from "@/lib/types";

export const mutationSetEntriesStore = writable<MutationSetEntrySummary[]>([]);

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
