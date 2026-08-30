// Mutation-sets domain store — the reusable mutation-set roster for the
// Mutations pane and the /mutate "apply a saved set" picker. Server-
// mirrored slice; `writable` for legacy-safe reads (docs/frontend-architecture.md).

import { get, writable } from "svelte/store";
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

// Close the create/edit dialog if it is open EDITING this exact set — a
// mutation set has no autosave draft (Save is explicit), so there is nothing
// to persist before promoting; closing the dialog on the set about to move is
// the safety net instead (an open Save would otherwise target a file that's
// no longer there). Also promote's post-commit reconciliation, below. A no-op
// when the dialog is closed or editing a different set.
export function closeMutationSetEditorIfEditing(entryId: string): void {
  if (get(mutationSetEditorStore)?.editing?.id === entryId) closeMutationSetEditor();
}

// Fold a just-promoted mutation set (ADR-0078 §2/§9 slice 4) into the roster —
// PromoteModal already called `api.promoteMutationSetEntry` (so it can show a
// blocked/409/400 reason inline); this only applies the result. Unlike lore or
// a prompt, a set is not an editor pane — there is no draft to reseed, so
// refreshing the roster (it now shows inherited) plus the dialog close above
// is the whole reconciliation.
export async function applyPromotedMutationSet(entry: MutationSetEntry): Promise<void> {
  await refreshMutationSetEntries();
  closeMutationSetEditorIfEditing(entry.id);
}
