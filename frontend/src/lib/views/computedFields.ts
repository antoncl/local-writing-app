// Lift-synthesized fields a kind's view universe carries in `metadata` but the
// metadata schema never declares — `disposition` on prompts (promptNodes) and
// `seed_disposition` on chats (chatNodes). A pane lift stamps their VALUE at render;
// this registry declares that the FIELD exists (key + descriptor with its choices)
// so the view designer's field picker can offer it. Without this, a built-in view
// could filter/group on such a field while a user building a custom view could not
// pick it — the asymmetry #960 closes.
//
// This generalizes the pre-existing structural-`parent` injection in ViewBodyView
// (which does exactly this for scenes/research). `parent` stays there because its
// picker_config is kind-scoped; these lift fields are kind-static, so they live with
// their lifts and register here.

import type { MetadataFieldDefinition } from "@/lib/types";
import { DISPOSITION_FIELD, dispositionFieldDef } from "@/lib/views/promptNodes";
import { SEED_DISPOSITION_FIELD, seedDispositionFieldDef } from "@/lib/views/chatNodes";

export type ComputedField = { key: string; def: MetadataFieldDefinition };

// One entry per kind that has a lift-synthesized field. A thunk so each caller gets
// a fresh descriptor object (defs are handed to pickers that may mutate copies).
const REGISTRY: Record<string, () => ComputedField> = {
  prompt: () => ({ key: DISPOSITION_FIELD, def: dispositionFieldDef() }),
  chat: () => ({ key: SEED_DISPOSITION_FIELD, def: seedDispositionFieldDef() }),
};

// The lift-synthesized computed fields for a kind (empty for kinds that have none).
export function liftFieldsForKind(kind: string): ComputedField[] {
  const make = REGISTRY[kind];
  return make ? [make()] : [];
}

// The descriptor for a lift-synthesized field key on a kind, or null. Mirrors
// `schema.fields[key]` resolution for computed fields the schema doesn't carry.
export function liftFieldByKey(kind: string, key: string): MetadataFieldDefinition | null {
  return liftFieldsForKind(kind).find((field) => field.key === key)?.def ?? null;
}
