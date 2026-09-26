// Mutation-sets domain store — the reusable mutation-set roster for the
// Mutations pane, the lore card's PinnedSetsPanel and the pill (ADR-0095 §1:
// a pill's label reads the set from HERE, live, never from its own doc
// attrs). Server-mirrored slice; `writable` for legacy-safe reads
// (docs/frontend-architecture.md).

import { derived, get, writable } from "svelte/store";
import { api } from "@/lib/api";
import { mutationsVersion } from "@/lib/stores/mutationsVersion.svelte";
import type { MutationSetEntry, MutationSetEntrySummary } from "@/lib/types";

export const mutationSetEntriesStore = writable<MutationSetEntrySummary[]>([]);

// True once the roster has loaded at least once — the pill NodeView (ADR-0095
// §1) needs this to tell "not in the roster yet" (still loading, render as
// normal) apart from "not in the roster any more" (render as missing).
export const mutationSetRosterLoadedStore = writable<boolean>(false);

// A by-id lookup of the loaded roster — the pill NodeView subscribes to this
// (not the array) so a relabel is a single Map lookup, not a linear scan on
// every keystroke elsewhere in the doc.
export const mutationSetsByIdStore = derived(mutationSetEntriesStore, (entries) => {
  const byId = new Map<string, MutationSetEntrySummary>();
  for (const entry of entries) byId.set(entry.id, entry);
  return byId;
});

// Anchor id → its set (ADR-0095 §1): the close pill resolves its `ref`
// through this, the same store the start pill's NodeView reads, rather than
// searching the open doc (today's `closeLabelFromDoc`, which only ever sees
// the anchor it shares a document with).
export const mutationSetByAnchorIdStore = derived(mutationSetEntriesStore, (entries) => {
  const byAnchor = new Map<string, MutationSetEntrySummary>();
  for (const entry of entries) {
    for (const anchor of entry.anchors) byAnchor.set(anchor.anchor_id, entry);
  }
  return byAnchor;
});

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

// `bump` defaults false — this never bumped `mutationsVersion` itself; every
// caller either doesn't need to (a plain roster reload) or bumps separately
// through a write-through (`upsertMutationSet`/`setMutationSetEntries`). A
// scene save that changed a set's ANCHOR count (add/remove/paste an anchor,
// ADR-0095 §6/§8) already bumps `mutationsVersion` itself when it saves
// (`bodyHasMutationMarkers`, editorPaneSave.ts) — that caller passes
// `{ bump: false }` (the default) explicitly, to refresh the roster's
// `anchors` (so the pill/dialog/caption tells go live) without a second bump.
export async function refreshMutationSetEntries(options?: { bump?: boolean }): Promise<void> {
  mutationSetEntriesStore.set((await api.listMutationSetEntries()).entries);
  mutationSetRosterLoadedStore.set(true);
  if (options?.bump) mutationsVersion.bump();
}

// Write-through from a mutation that already returns the canonical roster
// (delete mutation-set entry) — a delete is a set write too, so it bumps
// `mutationsVersion` the same as upsert/remove below.
export function setMutationSetEntries(entries: MutationSetEntrySummary[]): void {
  mutationSetEntriesStore.set(entries);
  mutationSetRosterLoadedStore.set(true);
  mutationsVersion.bump();
}

// Fold one created/saved/copied set into the roster at once — so a pill that
// names it relabels immediately, without waiting on a full re-list. Bumps
// `mutationsVersion` too: a set write can change what a scrub/timeline reads
// (a saved title, a re-pinned entity, a row that starts/stops validating).
export function upsertMutationSet(entry: MutationSetEntry | MutationSetEntrySummary): void {
  const summary: MutationSetEntrySummary = {
    id: entry.id,
    title: entry.title,
    entry_type: entry.entry_type,
    target_entry_type: entry.target_entry_type,
    target_entity: entry.target_entity,
    row_count: entry.rows.length,
    rows: entry.rows,
    anchors: entry.anchors,
    state: entry.state,
    pin_missing: entry.pin_missing,
    source_layer_id: entry.source_layer_id,
    source_layer_label: entry.source_layer_label,
  };
  mutationSetEntriesStore.update((entries) => {
    const idx = entries.findIndex((e) => e.id === summary.id);
    if (idx === -1) return [...entries, summary];
    const next = entries.slice();
    next[idx] = summary;
    return next;
  });
  mutationsVersion.bump();
}

// Drop one set from the roster (a delete outside the canonical-roster-return
// path, e.g. cascaded from elsewhere) — kept alongside setMutationSetEntries
// for callers that only know the id.
export function removeMutationSetFromStore(entryId: string): void {
  mutationSetEntriesStore.update((entries) => entries.filter((e) => e.id !== entryId));
  mutationsVersion.bump();
}

export function clearMutationSets(): void {
  mutationSetEntriesStore.set([]);
  mutationSetRosterLoadedStore.set(false);
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
