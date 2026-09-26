// The mutable-field roster shared by both mutation dialogs AND the scrub-stop
// editor (ADR-0095 §8). Moved out of `MutationFieldRows.svelte`'s module
// script (#2222/ADR-0095 S2) the same way `keyedShapeFor` moved to
// `keyedList.ts`: a lib module (`stopFieldEditable.ts`) needs this roster too,
// and a lib module must not import a component's module script.
// `MutationFieldRows.svelte` re-exports these so its existing imports keep
// working unchanged.
import { keyedListKeyMember } from "./keyedList";
import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

export const COLLECTION_TYPES = ["multi_select", "entity_ref_list"];
export const isCollectionType = (type: string) => COLLECTION_TYPES.includes(type);

// Scalar text types that accept an additive `add` (append) op — the backend
// resolves base + appends in start order (ADR-0009 amendment).
export const TEXT_APPEND_TYPES = ["text", "long_text"];
export const isTextAppendType = (type: string) => TEXT_APPEND_TYPES.includes(type);

// Intrinsic node fields (not schema fields) that are always mutable.
export const INTRINSIC_FIELDS: Array<{ id: string; def: MetadataFieldDefinition }> = [
  { id: "title", def: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition },
  { id: "body", def: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition },
];

export type FieldOption = { id: string; label: string; def: MetadataFieldDefinition };

// The mutable fields for an entry type: intrinsic title/body + its resolved
// schema fields, minus computed (derived) and most `list` fields (#698: the
// marker grammar is string-typed — a structured item has no honest
// representation in a mutation row, and String() would write
// "[object Object]" into the scene body). A reference-keyed list (ADR-0089
// §2/§5) is the one `list` shape that DOES have a record grammar — offered
// only when `allowItemLists` is set, since it needs an entity baseline to
// diff against (the /mutate authoring form has one; the set editor, which
// authors a template with no entity, does not and keeps skipping every list).
export function buildFieldOptions(
  schema: MetadataSchema | null,
  entryType: string,
  allowItemLists = false,
): FieldOption[] {
  const opts = INTRINSIC_FIELDS.map((f) => ({ id: f.id, label: f.def.name, def: f.def }));
  const seen = new Set(opts.map((o) => o.id));
  for (const id of schema?.entry_types[entryType]?.fields ?? []) {
    const def = schema?.fields[id];
    if (!def || def.type === "computed") continue;
    if (def.type === "list" && !(allowItemLists && keyedListKeyMember(def))) continue;
    // The resolver injects the intrinsic identity triple (title/entry_type/id)
    // into every type's resolved membership (schema.py). title is already
    // seeded above and entry_type/id aren't author-mutable, so skip anything
    // intrinsic; the seen-guard then keeps any duplicate id out of a keyed
    // {#each} (a duplicate `title` key crashes the whole editor render).
    if (def.category === "intrinsic" || seen.has(id)) continue;
    seen.add(id);
    opts.push({ id, label: def.name ?? id, def });
  }
  return opts;
}

export function fieldDefFor(fieldId: string, schema: MetadataSchema | null): MetadataFieldDefinition {
  return (
    schema?.fields[fieldId] ??
    INTRINSIC_FIELDS.find((f) => f.id === fieldId)?.def ??
    ({ name: fieldId, type: "text", options: [] } as MetadataFieldDefinition)
  );
}
