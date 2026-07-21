// Assistants domain store — the Assistants roster (the Chats pane reads it too)
// plus the derived default-assistant id. Server-mirrored slice lifted out of
// App.svelte for the #14 reactive state layer; `writable` for legacy-safe reads
// (see docs/frontend-architecture.md).

import { derived, writable } from "svelte/store";
import { api } from "@/lib/api";
import { activeAssistants } from "@/lib/chat/assistantScope";
import type { AssistantEntrySummary } from "@/lib/types";

export const assistantEntriesStore = writable<AssistantEntrySummary[]>([]);

// The dynamic default assistant id: the **topmost** entry in roster (manual
// drag) order, or "" if none. The ★ is_default flag is retired (ADR-0024) —
// manual order already expresses global preference. A derived store (not a
// function) so consumers track the inner roster dependency — see
// feedback_svelte5_reactivity_traps; this is what App's `$:` derivation did.
// The topmost ACTIVE entry (ADR-0024 Amendment 1). The roster carries un-listed
// entries since #333, so `$entries[0]` stopped meaning "top of my roster" — an
// assistant the author just un-listed sorts first often enough that un-listing
// became a way to make the app start USING it. Mirrors the backend's
// `resolve_assistant`, which takes the first listed id and returns nothing when
// there is none.
export const defaultAssistantIdStore = derived(
  assistantEntriesStore,
  ($entries) => activeAssistants($entries)[0]?.id ?? "",
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
