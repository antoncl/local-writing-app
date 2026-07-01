// Assistants domain store — the Assistants roster (the Chats pane reads it too)
// plus the derived default-assistant id. Server-mirrored slice lifted out of
// App.svelte for the #14 reactive state layer; `writable` for legacy-safe reads
// (see docs/frontend-architecture.md).

import { derived, writable } from "svelte/store";
import { api } from "@/lib/api";
import type { AssistantEntrySummary } from "@/lib/types";

export const assistantEntriesStore = writable<AssistantEntrySummary[]>([]);

// The id of the entry flagged `is_default`, or "" if none. A derived store (not
// a function) so consumers track the inner roster dependency — see
// feedback_svelte5_reactivity_traps; this is what App's `$:` derivation did.
export const defaultAssistantIdStore = derived(
  assistantEntriesStore,
  ($entries) => $entries.find((a) => Boolean(a.metadata?.is_default))?.id ?? "",
);

// Refresh swallows errors (backend may be unavailable) and leaves the previous
// list in place — matching the prior App.svelte behavior.
export async function refreshAssistantEntries(): Promise<void> {
  try {
    assistantEntriesStore.set((await api.listAssistantEntries()).entries);
  } catch {
    // Leave previous list in place.
  }
}

// Write-through from a mutation that already returns the canonical roster
// (reorder, delete assistant entry, …).
export function setAssistantEntries(entries: AssistantEntrySummary[]): void {
  assistantEntriesStore.set(entries);
}

export function clearAssistants(): void {
  assistantEntriesStore.set([]);
}
