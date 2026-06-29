// Structure domain store — the manuscript tree (acts/chapters/scenes ordering)
// and the parallel research tree (topics + notes; see docs/research-strategy.md).
// Both are server-mirrored slices lifted out of App.svelte for the #14 reactive
// state layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "../api";
import type { StructureDocument } from "../types";

export const structureStore = writable<StructureDocument | null>(null);
export const researchStructureStore = writable<StructureDocument | null>(null);

export async function refreshStructure(): Promise<void> {
  structureStore.set(await api.getStructure());
}

export async function refreshResearchStructure(): Promise<void> {
  researchStructureStore.set(await api.getResearchStructure());
}

// Write-through from a mutation that already returns the canonical tree
// (delete scene, delete/move research node, …).
export function setStructure(doc: StructureDocument | null): void {
  structureStore.set(doc);
}

export function setResearchStructure(doc: StructureDocument | null): void {
  researchStructureStore.set(doc);
}

export function clearStructure(): void {
  structureStore.set(null);
  researchStructureStore.set(null);
}
