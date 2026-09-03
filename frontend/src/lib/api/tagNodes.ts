import type { TagEntry, TagEntryList } from "@/lib/types";
import { request } from "./core";

// Tag-node CRUD (ADR-0082 slice 1) against `/api/tag-entries` — the `tag`
// kind's own endpoint. The legacy name/colour registry (`/api/tags`) retired
// with ADR-0082 slice 3.
export const tagNodesApi = {
  listTagEntries() {
    return request<TagEntryList>("/tag-entries");
  },
  createTagEntry(title: string, entryType = "tag:tag", color: string | null = null, layerId: string | null = null) {
    return request<TagEntry>("/tag-entries", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType, color, layer_id: layerId }),
    });
  },
  getTagEntry(tagId: string) {
    return request<TagEntry>(`/tag-entries/${encodeURIComponent(tagId)}`);
  },
  saveTagEntry(entry: TagEntry) {
    return request<TagEntry>(`/tag-entries/${encodeURIComponent(entry.id)}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
        base_revision: entry.revision,
      }),
    });
  },
  // 204 No Content — the dedicated delete deliberately does not return the
  // roster (review fix); callers `refreshTagNodes()` themselves.
  deleteTagEntry(tagId: string) {
    return request<void>(`/tag-entries/${encodeURIComponent(tagId)}`, {
      method: "DELETE",
    });
  },
  // ADR-0082 §5: a `merged_into` redirect, not a delete — returns the
  // survivor. Callers `refreshTagNodes()` + `refreshReferenceIndex()`
  // themselves (F3).
  mergeTagEntries(sourceId: string, targetId: string) {
    return request<TagEntry>(`/tag-entries/${encodeURIComponent(sourceId)}/merge`, {
      method: "POST",
      body: JSON.stringify({ into: targetId }),
    });
  },
};
