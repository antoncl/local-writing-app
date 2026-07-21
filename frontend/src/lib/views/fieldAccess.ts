// Field-value access for the view evaluator — how a node's value for a field
// key is read and shaped. Split out of `evaluateView.ts` (which sat in the
// file-size warn zone) so the ν-by-attribute module (`groupBy.ts`) and the
// evaluator share one source for value semantics: intrinsic-vs-metadata
// routing (ADR-0029 §D) and collection-vs-scalar shaping (ADR-0031 §E, #202).

import type { EvalNode } from "@/lib/views/evaluateView";
import type { MetadataFieldDefinition, MetadataSchema, ViewFieldOf } from "@/lib/types";

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
  if (isIntrinsicField(schema, key)) return (node as unknown as Record<string, unknown>)[key];
  // A `computed` field's value is resolver-stamped, so it lives in
  // `computed_metadata` and never in the stored `metadata` dict (which
  // round-trips to disk). Routing on the declared category — the same rule
  // intrinsic already uses — is what lets #333 group the assistants roster on
  // `listed` with no key-specific branch anywhere in the evaluator.
  if (schema?.fields?.[key]?.category === "computed") return node.computed_metadata?.[key];
  return node.metadata?.[key];
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
// Derived from COLLECTION_FIELD_TYPES (every set-of-tokens type is unsortable by
// construction) plus the two scalar-but-orderless types, so a future collection
// type is excluded automatically rather than drifting into the sort picker.
const UNSORTABLE_FIELD_TYPES = new Set<string>([...COLLECTION_FIELD_TYPES, "entity_ref", "color"]);
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

// Coerce a raw value (array / CSV string / scalar) to a list of trimmed, non-empty
// strings — the single shared coercion behind the evaluator's `toStringSet` and the
// param strip's binding fold (#204: `viewParams.toStringList` re-implemented this).
export function coerceStringList(v: unknown): string[] {
  const out: string[] = [];
  for (const item of asArray(v)) {
    const s = String(item).trim();
    if (s) out.push(s);
  }
  return out;
}

// The shared operand-shape guards (ADR-0031 §E). A predicate value slot holds a
// bare literal, a promoted formal `{var: name}`, or a `{field_of}` projection —
// exported ONCE here (was hand-rolled and drifting in evaluateView / viewGraph /
// viewParams, #204) so membership-vs-binding semantics can't diverge by file.
export function isVarOperand(v: unknown): v is { var: string } {
  return typeof v === "object" && v !== null && typeof (v as { var?: unknown }).var === "string";
}

export function isFieldOfOperand(v: unknown): v is { field_of: ViewFieldOf } {
  return typeof v === "object" && v !== null && (v as { field_of?: unknown }).field_of != null;
}

// Does a field yield a NODE-SET (ids) rather than a value-set when projected /
// overlapped? An entity_ref(_list) field, or a computed field the schema declares
// node-set-valued (#204: generic on `computed.value_type`, so a second node-set
// computed field works without a hardcoded key like `references`).
export function isNodeSetField(def: MetadataFieldDefinition | null | undefined): boolean {
  if (!def) return false;
  if (def.type === "entity_ref" || def.type === "entity_ref_list") return true;
  return def.type === "computed" && def.computed?.value_type === "node_set";
}

// The type a field BEHAVES as. For a stored field that is just its type; for a
// computed one it is the declared `computed.value_type` — the payload, not the
// authorship (`type: "computed"` says who produces the value, ADR-0029 §D, and
// says nothing about its shape). Same generic move `isNodeSetField` already
// makes, lifted so pickers can ask "can I group/sort on this?" without knowing
// which fields happen to be computed. #333's `listed` is a computed select, and
// is offerable because of this and not because of a key check.
export function effectiveFieldType(def: MetadataFieldDefinition | null | undefined): string | undefined {
  if (!def) return undefined;
  return def.type === "computed" ? def.computed?.value_type : def.type;
}
