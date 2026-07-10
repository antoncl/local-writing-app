// Reference-index domain store (#184 Phase 2) — the project-wide reverse
// reference index (`Map<targetId, Set<referrerId>>`) the view evaluator's
// `references` computed field projects over. Server-mirrored, loaded on project
// open like the other domain slices (see docs/frontend-architecture.md);
// `writable` for legacy-safe reads. Rebuilt from one bulk `referenceGraph()`
// payload so backlinks compose with set algebra instead of a per-node call.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { buildReferenceIndex } from "@/lib/views/referenceIndex";

const EMPTY: ReadonlyMap<string, ReadonlySet<string>> = new Map();

export const referenceIndexStore = writable<ReadonlyMap<string, ReadonlySet<string>>>(EMPTY);

export async function refreshReferenceIndex(): Promise<void> {
  const { refs } = await api.referenceGraph();
  referenceIndexStore.set(buildReferenceIndex(refs));
}

export function clearReferenceIndex(): void {
  referenceIndexStore.set(EMPTY);
}
