// Cross-domain derived stores — values computed from more than one domain
// slice, kept here so no single domain module reaches into another's state
// (see docs/frontend-architecture.md).

import { derived } from "svelte/store";
import { compileMatcher, type CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";

// Compiled matcher for implicit-context highlighting in editors. Recompiles
// whenever the lore set OR the schema changes — schema is needed so the matcher
// resolves per-entry colors for the highlight decorations. Cheap (sub-ms at
// Honorverse-scale per the benchmark) so we don't debounce. Replaces App's
// `$: implicitContextMatcher = compileMatcher(loreEntries, metadataSchema)`.
export const implicitContextMatcherStore = derived<
  [typeof loreEntriesStore, typeof metadataSchemaStore],
  CompiledMatcher
>(
  [loreEntriesStore, metadataSchemaStore],
  ([$lore, $schema]) => compileMatcher($lore, $schema),
);
