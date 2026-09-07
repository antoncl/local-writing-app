// Tag-node wire types (ADR-0082). Extracted from types.ts to keep that barrel
// under the file-size cap; re-exported from `@/lib/types` so it stays the
// single import surface.

import type { EntryMetadata } from "./metadataTypes";

// A tag node (ADR-0082 slice 1): a body-less node of kind `tag`. Mirrors
// backend TagEntry (models/tag_nodes.py).
export type TagEntry = {
  id: string;
  title: string;
  entry_type: string;
  metadata: EntryMetadata;
  revision?: string;
  // EditableDocument compatibility — a tag carries no prose body or fields.
  body?: string;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  // Set when this tag was merged into another (ADR-0082 §5) — the id it
  // redirects to. `tagNodesStore`'s `canonicalTagId`/`liveTags` follow it the
  // same way the backend's `NodeIndex.canonical_id` does.
  merged_into?: string | null;
};

export type TagEntryList = {
  tags: TagEntry[];
};
