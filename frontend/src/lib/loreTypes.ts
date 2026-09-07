// Lore + research-note wire types. Extracted from types.ts to keep that
// barrel under the file-size cap; re-exported from `@/lib/types` so it stays
// the single import surface.

import type { EntryMetadata } from "./metadataTypes";
import type { StructureDocument } from "./manuscriptTypes";

export type LoreEntrySummary = {
  id: string;
  title: string;
  body: string;
  entry_type: string;
  metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntry = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
  // Set when this entry was fork-to-here'd (#313): the relative path from the
  // base folder to the layer it was copied down from. Null for a plain entry.
  forked_from?: string | null;
  // Metadata fields whose effective value comes from a layer override in this
  // project's chain rather than inherited canon (#314 / ADR-0039). The backend
  // computes it during the fold; the rail draws the `ti-versions` override mark
  // against these. Empty for an entry with no overrides above its owning layer.
  overridden_fields?: string[];
};

// One leaf in the research tree — prose body + tags-only metadata.
// Mirrors the backend ResearchNote shape; no status / aliases /
// related_entries (see docs/research-strategy.md).
export type ResearchNote = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: EntryMetadata;
  // ResearchNote doesn't currently carry computed fields on the backend, but
  // shared consumers (NodeEditor) probe `.computed_metadata?.[k]`.
  computed_metadata?: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type LoreEntryList = {
  entries: LoreEntrySummary[];
};

export type MoveLoreNoteToResearchResponse = {
  note_id: string;
  tree: StructureDocument;
  dropped_fields: string[];
  lore: LoreEntryList;
};
