// Tag-node domain store (ADR-0082 slice 1) — the successor of `knownTagsStore`
// (`stores/tags.ts`, the legacy name/colour registry): a roster of real `tag`
// kind nodes across the merged chain, mirrored server-side. `writable` for
// legacy-safe reads (see docs/frontend-architecture.md), matching the sibling
// store's shape.

import { derived, get, writable } from "svelte/store";
import { api } from "@/lib/api";
import type { TagEntry } from "@/lib/types";

export const tagNodesStore = writable<TagEntry[]>([]);

// Monotonic guard so an overlapping refresh (a save's refresh racing a
// delete's, or two rapid tag-manager edits) can't land an older response
// over a newer one — mirrors `aiSpend`'s `#seq` (`stores/aiSpend.svelte.ts`).
let latest = 0;

// Refresh swallows errors — backend may be offline, or (since
// `projectSession.loadMachineSettings` now awaits this on every app boot)
// not listening yet — and leaves the previous roster in place, matching
// `refreshAssistantEntries` (`stores/assistants.ts`). A throw here would
// otherwise abort `rehydrate()`/`startCreateWizard()` before the wizard even
// opens, and make `clearProjectData`'s fire-and-forget call an unhandled
// rejection.
export async function refreshTagNodes(): Promise<void> {
  const seq = ++latest;
  try {
    const tags = (await api.listTagEntries()).tags;
    if (seq !== latest) return; // superseded by a later refresh
    tagNodesStore.set(tags);
  } catch {
    // Leave previous list in place.
  }
}

export function clearTagNodes(): void {
  tagNodesStore.set([]);
}

// Id -> entry, derived once so every by-id consumer (ReferencePicker's
// `resolveRefById`, `tagTitleById` below) shares one Map instead of each
// re-deriving its own from the roster array.
export const tagById = derived(tagNodesStore, (tags) => {
  const map = new Map<string, TagEntry>();
  for (const tag of tags) map.set(tag.id, tag);
  return map;
});

// Id -> title, for resolving a tag reference's chip/bucket label (§3 of the
// ADR: the frontend keeps a tag roster store so `entity_ref`/`entity_ref_list`
// values pointing at a tag resolve to a title instead of a raw id).
export const tagTitleById = derived(tagById, (byId) => {
  const map = new Map<string, string>();
  for (const [id, tag] of byId) map.set(id, tag.title);
  return map;
});

// ADR-0082 §2 / F3: case-insensitive title resolution over the current
// roster, ahead of a create — a same-title tag one hop up the merged chain
// (or created moments ago by a sibling save) is referenced, not duplicated.
// `entryType` narrows to one vocabulary when given (a picker source names
// exactly one when `create_missing` is eligible, F1); omitted, any vocabulary
// matches.
export function findTagByTitle(title: string, entryType?: string): TagEntry | undefined {
  const needle = title.trim().toLowerCase();
  if (!needle) return undefined;
  return get(tagNodesStore).find(
    (tag) => tag.title.trim().toLowerCase() === needle && (!entryType || tag.entry_type === entryType),
  );
}
