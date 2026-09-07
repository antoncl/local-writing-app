// Assistant entry wire types. Extracted from types.ts to keep that barrel
// under the file-size cap; re-exported from `@/lib/types` so it stays the
// single import surface.

import type { EntryMetadata } from "./metadataTypes";

export type AssistantEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  // Curation (`listed`, `position`), stamped by the layer traversal (#332) as
  // declared computed fields — never in `metadata`, which round-trips to disk.
  // Not inferable from array order: the unlisted tail is contiguous with the
  // listed run. #333's Active/Unlisted grouping reads `listed` through the
  // ordinary field machinery, so nothing special-cases the key.
  computed_metadata?: EntryMetadata;
};

export type AssistantEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // has_body: false — these are present so AssistantEntry satisfies the
  // EditableDocument shape used by NodeEditor, but they are always
  // empty / undefined for assistant kind.
  body?: string;
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type AssistantEntryList = {
  entries: AssistantEntrySummary[];
};
