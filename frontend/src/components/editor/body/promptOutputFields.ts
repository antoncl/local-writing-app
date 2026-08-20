// Pure schema-resolution helpers for PromptOutputEditor's commit sub-form
// (ADR-0062 D3). Kept separate from the component (mirrors offerOnTree.ts).

import type { MetadataSchema } from "@/lib/types";

export type EntryTypeOption = { id: string; label: string };

// The candidate types for `commit.target` (ADR-0063 S1) — every concrete
// (non-abstract) entry type, so the picker offers whatever the commit could
// plausibly create, not just one kind.
export function commitTargetOptions(schema: MetadataSchema | null): EntryTypeOption[] {
  if (!schema) return [];
  return Object.entries(schema.entry_types)
    .filter(([, def]) => !def.abstract)
    .map(([id, def]) => ({ id, label: `${def.name || id} (${id})` }))
    .sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
}
