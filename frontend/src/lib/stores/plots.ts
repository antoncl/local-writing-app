// Plot domain store — lightweight plot node roster for context pickers and
// plot-board entry points. Full plot nodes are still loaded on demand.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { PlotNodeSummary } from "@/lib/types";

export const plotEntriesStore = writable<PlotNodeSummary[]>([]);

export async function refreshPlotEntries(): Promise<void> {
  plotEntriesStore.set((await api.listPlotNodes()).entries);
}

export function setPlotEntries(entries: PlotNodeSummary[]): void {
  plotEntriesStore.set(entries);
}

export function clearPlots(): void {
  plotEntriesStore.set([]);
}
