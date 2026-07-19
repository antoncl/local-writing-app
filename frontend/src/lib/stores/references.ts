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

// Monotonic request token guarding the fire-and-forget refresh (#200). Callers
// fire `void refreshReferenceIndex()` on save/delete/open, so rapid mutations
// can have several graph fetches in flight at once; without a token a slow early
// fetch could resolve LAST and overwrite the store with a stale index, or a
// fetch could land after the project was cleared/switched and repopulate it. A
// refresh applies its result only while it is still the newest issued; a clear
// bumps the token so any in-flight refresh is superseded.
let generation = 0;

export async function refreshReferenceIndex(): Promise<void> {
  const token = ++generation;
  try {
    const { refs } = await api.referenceGraph();
    if (token !== generation) return; // superseded by a newer refresh or a clear
    referenceIndexStore.set(buildReferenceIndex(refs));
  } catch (error) {
    // Background refresh: swallow so it never surfaces as an unhandled rejection
    // (callers `void` it). A stale index self-heals on the next save/delete.
    console.warn("Failed to refresh reference index", error);
  }
}

export function clearReferenceIndex(): void {
  generation++; // supersede any in-flight refresh so it can't repopulate the store
  referenceIndexStore.set(EMPTY);
}
