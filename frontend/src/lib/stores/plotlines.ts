// Plotlines domain store (ADR-0048 §2) — the plotline roster, loaded on project
// open. The ReferencePicker's `plot` source (#742) reads it directly rather than
// having every caller thread the roster (the assistants precedent, #257). Kept
// separate from the heavy on-demand board projection: this is the light list the
// card's plotline picker needs whether or not the board pane is open. Server-
// mirrored slice, same shape as the prompts/templates stores.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { PlotlineSummary } from "@/lib/types";

export const plotlineEntriesStore = writable<PlotlineSummary[]>([]);

export async function refreshPlotlines(): Promise<void> {
  plotlineEntriesStore.set((await api.listPlotlines()).entries);
}

export function clearPlotlines(): void {
  plotlineEntriesStore.set([]);
}
