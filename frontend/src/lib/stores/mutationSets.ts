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
// `preset` (ADR-0055 §3) pins a NEW set to an entity by construction — the
// lore-card "＋ New" mutation-set affordance seeds it so the set is entity-pinned
// and type-locked from the start. Absent (the Mutations-pane "+") ⇒ a reusable,
// type-picked template, unchanged.
export type MutationSetPinPreset = { target_entity: string; target_entry_type: string };
export type MutationSetEditorRequest = {
  editing: MutationSetEntry | null;
  preset?: MutationSetPinPreset;
};
export const mutationSetEditorStore = writable<MutationSetEditorRequest | null>(null);

export function openNewMutationSet(preset?: MutationSetPinPreset): void {
  mutationSetEditorStore.set({ editing: null, preset });
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
  mutationSetEditorStore.set(null);
}
