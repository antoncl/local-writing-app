// Pure schema-resolution helpers for PromptOutputEditor's commit sub-form
// (ADR-0062 D3). Kept separate from the component (mirrors offerOnTree.ts)
// so the field-filtering rule is unit-testable without mounting CodeMirror.

import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

export type FieldOption = { id: string; label: string };
export type EntryTypeOption = { id: string; label: string };

// Mirrors the backend's `is_proposable_field` (entry_patch.py): references (no
// reliable way to name the right node id) and computed values are never
// proposable, nor is a field the type marks `ai_proposable: false` or hides
// from the author. `id`/`entry_type` are structural, not schema fields.
const NON_PROPOSABLE_TYPES = new Set(["computed", "entity_ref", "entity_ref_list"]);
const NON_PROPOSABLE_IDS = new Set(["id", "entry_type"]);

function isProposableField(id: string, def: MetadataFieldDefinition | undefined): boolean {
  if (!def) return false;
  if (NON_PROPOSABLE_IDS.has(id)) return false;
  if (NON_PROPOSABLE_TYPES.has(def.type)) return false;
  if (def.ai_proposable === false) return false;
  return !def.hidden;
}

// The commit `fields` allow-list candidates for a target entry_type: `body`
// (always proposable, ADR-0059 §A — it isn't a schema field so it's seeded by
// hand) plus the type's resolved, proposable fields. Returns just `body` when
// the schema or target can't be resolved (a fresh/unset target, or one this
// project's schema doesn't define) — the multi-select degrades to that single
// option rather than erroring.
export function proposableFieldOptions(
  schema: MetadataSchema | null,
  targetEntryType: string,
): FieldOption[] {
  const options: FieldOption[] = [{ id: "body", label: "Body" }];
  const entryType = schema?.entry_types[targetEntryType];
  if (!entryType) return options;
  for (const id of entryType.fields ?? []) {
    if (id === "body") continue;
    const def = schema?.fields[id];
    if (!isProposableField(id, def)) continue;
    options.push({ id, label: def?.name || id });
  }
  return options;
}

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
