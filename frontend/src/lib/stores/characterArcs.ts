// Character-arc domain store (ADR-0080) — the arc roster, mirroring
// `lib/stores/plotlines.ts` field-for-field. A character arc is the plotline's
// SIBLING beat-holder (§1): same book-local flat-node CRUD, same on-node editing
// model (load-full-entry-on-expand, whole-entry save), same undo substrate shape —
// kept as its own store (not folded into plotlines.ts) so an arc is never routed
// through the plotline undo commands (which would recreate it AS a plotline, #3b-i
// correctness point).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { refreshPlotBoard, refreshAfterMutation } from "@/lib/stores/plotBoard";
import type { CharacterArcEntry, CharacterArcSummary } from "@/lib/types";

export const characterArcEntriesStore = writable<CharacterArcSummary[]>([]);

export async function refreshCharacterArcs(): Promise<void> {
  characterArcEntriesStore.set((await api.listCharacterArcs()).entries);
}

// Set the roster directly from a mutation that already returns it (a delete
// returns the refreshed list), avoiding a second round-trip.
export function setCharacterArcs(entries: CharacterArcSummary[]): void {
  characterArcEntriesStore.set(entries);
}

// Delete an arc from the board (its node's "Delete character arc"). Also refresh
// the board so any card that fulfilled one of its change-beats loses that badge.
export async function deleteArc(id: string): Promise<void> {
  setCharacterArcs((await api.deleteCharacterArc(id)).entries);
  await refreshPlotBoard();
}

// Load the full arc entry (title + metadata.color + metadata.character +
// metadata.instance_beats + the hidden lineage) — what the on-node editor edits,
// since the board projection carries only beat titles + the resolved character
// display fields, not the editable id.
export function getArcEntry(id: string): Promise<CharacterArcEntry> {
  return api.getCharacterArc(id);
}

// Persist an on-node arc edit (rename / recolour / rebind character / beat-roster
// change): the node hands back the whole edited entry, `saveCharacterArc` replaces
// title + body + metadata wholesale. Refresh BOTH the board (a recolour retints its
// node, a rebind changes the bound character shown) and the roster.
export async function saveArcEntry(entry: CharacterArcEntry): Promise<CharacterArcEntry> {
  const saved = await api.saveCharacterArc(entry, entry.body);
  await Promise.all([refreshCharacterArcs(), refreshAfterMutation()]);
  return saved;
}

// ── Undo substrate (ADR-0053 §7, mirrored for arcs) ─────────────────────────
// The arc twin of plotlines.ts's capture/restore/recreate helpers. An arc's whole
// authored state = title + description body + metadata (colour + character +
// instance_beats + the hidden source_template_* lineage), so a restore keeps the
// lineage a per-field diff would forget — exactly the plotline rationale.

export type ArcState = { title: string; body: string; metadata: CharacterArcEntry["metadata"] };

export function arcStateOf(entry: CharacterArcEntry): ArcState {
  return { title: entry.title, body: entry.body, metadata: structuredClone(entry.metadata) };
}

export async function getArcState(id: string): Promise<ArcState> {
  return arcStateOf(await api.getCharacterArc(id));
}

// Restore a captured state onto an arc that still exists (a field/beat-edit
// reversal). Fetch-fresh for the live revision, then refresh roster + board.
export async function restoreArcState(id: string, state: ArcState, refresh = true): Promise<void> {
  const entry = await api.getCharacterArc(id);
  await api.saveCharacterArc({ ...entry, title: state.title, metadata: state.metadata }, state.body);
  if (refresh) await Promise.all([refreshCharacterArcs(), refreshAfterMutation()]);
}

// Recreate a deleted arc under its ORIGINAL id, then restore its content
// (create-then-PUT) — so an instantiated arc returns with its beats + lineage +
// character binding. NEVER routed through `api.createPlotline` (that would recreate
// it as a plotline, not an arc) — this calls `createCharacterArc`.
export async function recreateArc(id: string, state: ArcState, refresh = true): Promise<void> {
  await api.createCharacterArc(state.title, id);
  await restoreArcState(id, state, refresh);
}

// Refresh just the arc roster — the batched delete-undo's trailing roster refresh
// (paired with the board refresh), mirroring plotlines.ts's `refreshRoster`.
export function refreshArcRoster(): Promise<void> {
  return refreshCharacterArcs();
}

export function clearCharacterArcs(): void {
  characterArcEntriesStore.set([]);
}
