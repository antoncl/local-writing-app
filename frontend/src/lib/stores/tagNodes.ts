// Tag-node domain store (ADR-0082 slice 1) — the successor of `knownTagsStore`
// (`stores/tags.ts`, the legacy name/colour registry): a roster of real `tag`
// kind nodes across the merged chain, mirrored server-side. `writable` for
// legacy-safe reads (see docs/frontend-architecture.md), matching the sibling
// store's shape.

import { derived, writable } from "svelte/store";
import { api } from "@/lib/api";
import type { TagEntry } from "@/lib/types";

export const tagNodesStore = writable<TagEntry[]>([]);

export async function refreshTagNodes(): Promise<void> {
  tagNodesStore.set((await api.listTagEntries()).tags);
}

export function setTagNodes(tags: TagEntry[]): void {
  tagNodesStore.set(tags);
}

export function clearTagNodes(): void {
  tagNodesStore.set([]);
}

// Id -> title, for resolving a tag reference's chip/bucket label without every
// consumer re-deriving the same Map from the roster array (§3 of the ADR: the
// frontend keeps a tag roster store so `entity_ref`/`entity_ref_list` values
// pointing at a tag resolve to a title instead of a raw id).
export const tagTitleById = derived(tagNodesStore, (tags) => {
  const map = new Map<string, string>();
  for (const tag of tags) map.set(tag.id, tag.title);
  return map;
});
