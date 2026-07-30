// Tags domain store — the scoped known-tag roster used by tag pickers and the
// tag manager. Server-mirrored slice extracted from App.svelte for the #14
// state layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { ScopedTag } from "@/lib/types";

export const knownTagsStore = writable<ScopedTag[]>([]);

// Bumped whenever a vocabulary-governance op (merge / rename / scope) rewrites
// tags on disk from anywhere — the + popover's governance surface or the tag
// manager. A single App-level subscriber runs the full reconcile
// (`refreshAfterTagChange`: roster + entry lists + open-editor baselines), so
// no picker has to thread a callback up through the five components between it
// and App just to re-sync after a disk rewrite (#247).
export const tagVocabularyRevision = writable(0);

export function bumpTagVocabularyRevision(): void {
  tagVocabularyRevision.update((n) => n + 1);
}

export async function refreshKnownTags(): Promise<void> {
  knownTagsStore.set((await api.getKnownTags()).tags);
}

export function setKnownTags(tags: ScopedTag[]): void {
  knownTagsStore.set(tags);
}

export function clearKnownTags(): void {
  knownTagsStore.set([]);
}
