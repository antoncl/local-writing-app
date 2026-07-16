// Field-value access for the view evaluator — how a node's value for a field
// key is read and shaped. Split out of `evaluateView.ts` (which sat in the
// file-size warn zone) so the ν-by-attribute module (`groupBy.ts`) and the
// evaluator share one source for value semantics: intrinsic-vs-metadata
// routing (ADR-0029 §D) and collection-vs-scalar shaping (ADR-0031 §E, #202).

import type { EvalNode } from "@/lib/views/evaluateView";
import type { MetadataSchema } from "@/lib/types";

// The three canonical intrinsic keys — top-level properties on EVERY node/
// summary, forced intrinsic by the backend (`default_schema.INTRINSIC_FIELD_KEYS`)
// in every resolved schema, and NOT user-extensible. Encoding this invariant
// (not the mutable set) lets id/title/entry_type resolve correctly even before
// the schema store loads — #227: a group_by/sort on entry_type no longer reads
// undefined `metadata.entry_type` during the first-render race (schema and
// entries load in parallel), which flashed the Lore pane flat then regrouped.
const CANONICAL_INTRINSIC = new Set(["id", "title", "entry_type"]);

// A field routes to the node top-level property (id/title/entry_type) instead
// of the `metadata` dict iff it is a canonical intrinsic OR the resolver stamped
// it `intrinsic` (ADR-0029 §D). The EXTENSIBLE set still comes only from the
// resolved schema — the frontend does not mirror it. Unknown keys → metadata.
export function isIntrinsicField(schema: MetadataSchema | null | undefined, key: string): boolean {
  return CANONICAL_INTRINSIC.has(key) || schema?.fields?.[key]?.category === "intrinsic";
}

// A node's value for a predicate/sort key. Intrinsic fields (id/title/
// entry_type) live on the node top-level, not in metadata, so read them from
// the node property; everything else reads from metadata. Which is which comes
// from the resolver-stamped `category` (ADR-0029 §D), never a mirrored set.
export function fieldValue(node: EvalNode, key: string, schema: MetadataSchema | null | undefined): unknown {
  return isIntrinsicField(schema, key)
    ? (node as unknown as Record<string, unknown>)[key]
    : node.metadata?.[key];
}

// A node's link-field values as a list of trimmed strings — entity_ref (a bare
// id string), entity_ref_list (a list of ids), a CSV string, or a tag list. The
// stored shape is always plain strings/lists of strings (no ref wrappers).
export function fieldValueList(node: EvalNode, field: string): string[] {
  return asArray(node.metadata?.[field]).map((v) => String(v).trim()).filter(Boolean);
}

// Collection field types (ADR-0031 §E): a value that is inherently a SET of
// tokens. Only these tokenize a comma-bearing string; every other type is scalar
// and compares whole (#202). An array value is always treated as a collection
// regardless of the declared type, since it is already multi-valued.
const COLLECTION_FIELD_TYPES = new Set<string>(["multi_select", "entity_ref_list", "tags"]);
export function isCollectionField(schema: MetadataSchema | null | undefined, key: string): boolean {
  const t = schema?.fields?.[key]?.type;
  return t != null && COLLECTION_FIELD_TYPES.has(t);
}

// Field types with NO natural total order — a set of tokens (tags/multi_select/
// ref list), an opaque reference id, or a named color swatch has no defined
// position to sort by (#237). Views sort offers only orderable fields; excluding
// these at the picker is what stops the comparator from ever collapsing an array
// to a stringly-coerced key. A field whose type is unknown (e.g. the synthetic
// structural `parent` ref, absent from the schema) is treated as unsortable.
const UNSORTABLE_FIELD_TYPES = new Set<string>([
  "multi_select",
  "tags",
  "entity_ref",
  "entity_ref_list",
  "color",
]);
export function isSortableField(type: string | null | undefined): boolean {
  return type != null && !UNSORTABLE_FIELD_TYPES.has(type);
}

export function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
}

export function asArray(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  if (v === null || v === undefined) return [];
  if (typeof v === "string") return v.split(",").map((s) => s.trim()).filter(Boolean);
  return [v];
}
