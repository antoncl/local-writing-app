// Machine-global assistant-tag vocabulary store (#88). Assistants live
// machine-globally, so their tag vocabulary can't come from a project's scoped
// KnownTags — it has its own store, loaded at startup and refreshed after an
// assistant/prompt save (which is what registers new tags server-side). Mirrors
// lib/stores/tags.ts; `writable` for legacy-safe reads.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import { getSwatch } from "@/lib/utils/colors";
import type { AssistantTag, ScopedTag } from "@/lib/types";

export const assistantTagsStore = writable<AssistantTag[]>([]);

export async function refreshAssistantTags(): Promise<void> {
  try {
    assistantTagsStore.set((await api.getAssistantTags()).tags);
  } catch {
    // Best-effort: a transient failure leaves the current vocabulary in place.
  }
}

export function clearAssistantTags(): void {
  assistantTagsStore.set([]);
}

// Present the assistant tags to the tag pickers as ScopedTag with an empty
// scope (suggest-everywhere), so they merge cleanly into a NodeEditor's
// `knownTags` for assistant/prompt editing without a picker-specific code path.
export function assistantTagsAsScoped(tags: AssistantTag[]): ScopedTag[] {
  return tags.map((tag) => ({ name: tag.name, scope: { sources: [] } }));
}

// name → resolved hex, for the colored NodeRow chips. Tags with no color (or an
// unknown swatch id) are absent from the map.
export function assistantTagColorHexes(tags: AssistantTag[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const tag of tags) {
    const hex = tag.color ? getSwatch(tag.color)?.hex ?? null : null;
    if (hex) map.set(tag.name, hex);
  }
  return map;
}
