// Plot-templates domain store (ADR-0048 S4c) — the resolved template shelf
// (built-in Library defaults + any owned clones). Server-mirrored slice, same
// shape as the prompts store; `writable` for legacy-safe reads
// (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { PlotTemplateSummary } from "@/lib/types";

export const plotTemplatesStore = writable<PlotTemplateSummary[]>([]);

export async function refreshPlotTemplates(): Promise<void> {
  plotTemplatesStore.set((await api.listPlotTemplates()).entries);
}

// Write-through from a mutation that already returns the canonical roster
// (delete owned template clone).
export function setPlotTemplates(entries: PlotTemplateSummary[]): void {
  plotTemplatesStore.set(entries);
}

// Delete an owned template clone from the board palette (ADR-0053 §2). The delete
// returns the refreshed roster (a Library default can't be deleted — the backend
// 409s / the palette only offers this on owned rows). A plotline instantiated from it
// is unaffected: its beats + lineage were SNAPSHOTTED at instantiate (S1), not linked.
export async function deletePlotTemplateEntry(id: string): Promise<void> {
  setPlotTemplates((await api.deletePlotTemplate(id)).entries);
}

export function clearPlotTemplates(): void {
  plotTemplatesStore.set([]);
}
