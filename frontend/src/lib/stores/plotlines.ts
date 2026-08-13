// Plotlines domain store (ADR-0048 §2) — the plotline roster, loaded on project
// open. The ReferencePicker's `plot` source (#742) reads it directly rather than
// having every caller thread the roster (the assistants precedent, #257). Kept
// separate from the heavy on-demand board projection: this is the light list the
// card's plotline picker needs whether or not the board pane is open. Server-
// mirrored slice, same shape as the prompts/templates stores.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { refreshPlotBoard, refreshAfterMutation } from "@/lib/stores/plotBoard";
import type { PlotlineEntry, PlotlineSummary } from "@/lib/types";

export const plotlineEntriesStore = writable<PlotlineSummary[]>([]);

// A one-shot cross-pane signal (ADR-0053 §3): a card's `plotline` backlink no longer
// opens an editor pane — a plotline is edited on its board node now — so it asks to be
// REVEALED on the board instead. The App shell opens the board pane when this goes
// non-null; PlotEditor expands the matching node and clears it. Null = nothing pending.
export const plotlineReveal = writable<string | null>(null);

export function revealPlotline(id: string): void {
  plotlineReveal.set(id);
}

export async function refreshPlotlines(): Promise<void> {
  plotlineEntriesStore.set((await api.listPlotlines()).entries);
}

// Set the roster directly from a mutation that already returns it (a plotline
// delete returns the refreshed list), avoiding a second round-trip — the
// setPromptEntries convention.
export function setPlotlines(entries: PlotlineSummary[]): void {
  plotlineEntriesStore.set(entries);
}

// Delete a plotline from the rail (#737) — the delete returns the refreshed roster.
// Also refresh the board so any card that was on this thread loses its colour axis
// (the backend blanks the cards' now-dangling plotline ref). The editor-pane delete
// path (editorPaneDelete) is separate.
export async function deletePlotline(id: string): Promise<void> {
  setPlotlines((await api.deletePlotline(id)).entries);
  await refreshPlotBoard();
}

// Load the full plotline entry (title + metadata.color + metadata.instance_beats +
// the hidden lineage) — what the on-node editor edits, since the board projection
// carries only beat titles. A plain read passthrough (the node stays store-only, no
// direct api import).
export function getPlotlineEntry(id: string): Promise<PlotlineEntry> {
  return api.getPlotline(id);
}

// Persist an on-node plotline edit (ADR-0053 §3) — rename / recolour / a beat-roster
// change. The node hands back the whole edited entry (loaded fresh on expand, so it
// carries the live revision + the hidden lineage fields untouched); `savePlotline`
// replaces title + body + metadata wholesale. Then refresh BOTH the board (so a
// recolour retints cards + rename/beat edits refresh their badges) and the rail roster
// (so its name + swatch update). Refreshing the board uses the post-mutation drain, not
// the coalescing read, so the new state always lands.
export async function savePlotlineEntry(entry: PlotlineEntry): Promise<PlotlineEntry> {
  const saved = await api.savePlotline(entry, entry.body);
  // Independent reads (roster GET + board GET) — run them together, not chained.
  await Promise.all([refreshPlotlines(), refreshAfterMutation()]);
  return saved;
}

// Board-native create (ADR-0053 §3): mint an empty (ad-hoc) plotline, refresh the roster
// + board, and return its id so the caller can expand the new node for editing. Replaces
// the rail's create-then-open-a-pane gesture — a plotline is authored on the board now.
export async function createPlotlineOnBoard(): Promise<string> {
  const line = await api.createPlotline("New plotline");
  await refreshPlotlines();
  await refreshAfterMutation();
  return line.id;
}

export function clearPlotlines(): void {
  plotlineEntriesStore.set([]);
}
