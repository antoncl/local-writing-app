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

export function clearPlotTemplates(): void {
  plotTemplatesStore.set([]);
}
