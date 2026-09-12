// Assistants domain store — the Assistants roster (the Chats pane reads it too)
// plus the derived default-assistant id. Server-mirrored slice lifted out of
// App.svelte for the #14 reactive state layer; `writable` for legacy-safe reads
// (see docs/frontend-architecture.md).

import { derived, writable } from "svelte/store";
import { api } from "@/lib/api";
import { activeAssistants } from "@/lib/chat/assistantScope";
import type { AssistantEntrySummary } from "@/lib/types";

export const assistantEntriesStore = writable<AssistantEntrySummary[]>([]);

// Whether an assistant is in the active roster (vs. un-listed). `listed` is a
// computed field stamped by the layer traversal (#332/#333); this predicate is
// the single definition, shared by the Assistants pane and the create wizard.
export function isAssistantListed(entry: AssistantEntrySummary): boolean {
  return entry.computed_metadata?.listed === "listed";
}

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
// list in place — matching the prior App.svelte behavior. Monotonic `latest`
// (same guard as `refreshTagNodes`): the no-project hydration and the
// project-open refresh (#1878) can be in flight together, and the earlier,
// machine-only answer must never land over the later, project-scoped one.
let latest = 0;

export async function refreshAssistantEntries(): Promise<void> {
  const seq = ++latest;
  try {
    const entries = (await api.listAssistantEntries()).entries;
    if (seq !== latest) return; // superseded by a later refresh
    assistantEntriesStore.set(entries);
  } catch {
    // Leave previous list in place.
  }
}

// Write-through from a mutation that already returns the canonical roster
// (reorder, delete assistant entry, …).
// A write-through (a mutation's response IS the canonical roster) or a clear
// also bumps `latest`, so a refresh already in flight cannot land its older
// answer over it — e.g. open the Assistants pane (fires a refresh) and reorder
// at once: without the bump the earlier GET resolved last and reverted the
// order on screen (review of #1879).
export function setAssistantEntries(entries: AssistantEntrySummary[]): void {
  latest += 1;
  assistantEntriesStore.set(entries);
}

export function clearAssistants(): void {
  latest += 1;
  assistantEntriesStore.set([]);
}
