// Plotlines domain store (ADR-0048 §2) — the plotline roster, loaded on project
// open. The ReferencePicker's `plot` source (#742) reads it directly rather than
// having every caller thread the roster (the assistants precedent, #257). Kept
// separate from the heavy on-demand board projection: this is the light list the
// card's plotline picker needs whether or not the board pane is open. Server-
// mirrored slice, same shape as the prompts/templates stores.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import type { PlotlineSummary } from "@/lib/types";

export const plotlineEntriesStore = writable<PlotlineSummary[]>([]);

export async function refreshPlotlines(): Promise<void> {
  plotlineEntriesStore.set((await api.listPlotlines()).entries);
}

// Set the roster directly from a mutation that already returns it (a plotline
// delete returns the refreshed list), avoiding a second round-trip — the
// setPromptEntries / setTemplateInstances convention.
export function setPlotlines(entries: PlotlineSummary[]): void {
  plotlineEntriesStore.set(entries);
}

// Delete a plotline from the rail (#737) — the delete returns the refreshed roster.
// Also refresh the board so any card that was on this thread loses its colour axis
// (the backend blanks the cards' now-dangling plotline ref). Mirrors the arc rail's
// deleteTemplateInstance; the editor-pane delete path (editorPaneDelete) is separate.
export async function deletePlotline(id: string): Promise<void> {
  setPlotlines((await api.deletePlotline(id)).entries);
  await refreshPlotBoard();
}

export function clearPlotlines(): void {
  plotlineEntriesStore.set([]);
}
