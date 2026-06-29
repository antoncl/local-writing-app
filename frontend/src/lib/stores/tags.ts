// Tags domain store — the scoped known-tag roster used by tag pickers and the
// tag manager. Server-mirrored slice extracted from App.svelte for the #14
// state layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { ScopedTag } from "@/lib/types";

export const knownTagsStore = writable<ScopedTag[]>([]);

export async function refreshKnownTags(): Promise<void> {
  knownTagsStore.set((await api.getKnownTags()).tags);
}

export function setKnownTags(tags: ScopedTag[]): void {
  knownTagsStore.set(tags);
}

export function clearKnownTags(): void {
  knownTagsStore.set([]);
}
