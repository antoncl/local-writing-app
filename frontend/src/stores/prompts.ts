// Prompts domain store — the Prompts roster (prompt templates by sub-type).
// Server-mirrored slice lifted out of App.svelte for the #14 reactive state
// layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "../api";
import type { PromptEntrySummary } from "../types";

export const promptEntriesStore = writable<PromptEntrySummary[]>([]);

export async function refreshPromptEntries(): Promise<void> {
  promptEntriesStore.set((await api.listPromptEntries()).entries);
}

// Write-through from a mutation that already returns the canonical roster
// (delete prompt entry, tag merge, …).
export function setPromptEntries(entries: PromptEntrySummary[]): void {
  promptEntriesStore.set(entries);
}

export function clearPrompts(): void {
  promptEntriesStore.set([]);
}
