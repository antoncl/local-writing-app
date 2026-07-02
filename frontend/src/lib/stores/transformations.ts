// Transformation-sets domain store — the reusable mutation-set roster for the
// Transformations pane and the /mutate "apply a saved set" picker. Server-
// mirrored slice; `writable` for legacy-safe reads (docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { TransformationEntrySummary } from "@/lib/types";

export const transformationEntriesStore = writable<TransformationEntrySummary[]>([]);

export async function refreshTransformationEntries(): Promise<void> {
  transformationEntriesStore.set((await api.listTransformationEntries()).entries);
}

// Write-through from a mutation that already returns the canonical roster
// (delete transformation entry).
export function setTransformationEntries(entries: TransformationEntrySummary[]): void {
  transformationEntriesStore.set(entries);
}

export function clearTransformations(): void {
  transformationEntriesStore.set([]);
}
