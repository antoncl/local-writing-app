// Lore domain store — the Lore-pane roster (entries grouped by entry_type).
// Server-mirrored slice lifted out of App.svelte for the #14 reactive state
// layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { LoreEntrySummary } from "@/lib/types";

export const loreEntriesStore = writable<LoreEntrySummary[]>([]);

export async function refreshLoreEntries(): Promise<void> {
  loreEntriesStore.set((await api.listLoreEntries()).entries);
}

// Write-through from a mutation that already returns the canonical roster
// (delete lore entry, move-note-to-research, tag merge, …).
export function setLoreEntries(entries: LoreEntrySummary[]): void {
  loreEntriesStore.set(entries);
}

export function clearLore(): void {
  loreEntriesStore.set([]);
}
