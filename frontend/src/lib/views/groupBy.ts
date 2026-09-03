// group_by — ν by attribute (ADR-0037 §2), applied to the evaluator's already-
// denormalized `(node, path)` rows. Split out of `evaluateView.ts` (which sat
// in the file-size warn zone); this is the result-level half of the two ν
// operators — Nest (ν by join) stays in the evaluator's pipeline. Type-only
// imports from `evaluateView` keep this dependency cycle-free at runtime.

import type { EvalNode, PathSegment, ViewRow } from "@/lib/views/evaluateView";
import type { MetadataSchema, ViewGroupByLevel, ViewSpec } from "@/lib/types";
import { asArray, fieldValue, isCollectionField, isEmpty, isNodeSetField } from "@/lib/views/fieldAccess";
import { walkViewExpr } from "@/lib/views/walkViewExpr";

// Whether ANY `group_by` level in `spec` groups on a node-set field —
// entity_ref(_list), or a computed field the schema declares node-set-valued
// (`isNodeSetField`) — the only shape `segmentForField`'s ref branch below
// can call `ctx.resolveTitle` for. Callers gate a reactive tag-roster
// resolver on this (ADR-0082 slice 1 review fix, F7): a view whose
// `group_by` never touches a ref-shaped field never subscribes to the tag
// roster (so an unrelated tag save doesn't re-evaluate it), and a view that
// DOES re-evaluates correctly on a tag rename.
export function groupByHasRefLevel(
  spec: Pick<ViewSpec, "group_by"> | null | undefined,
  schema: MetadataSchema | null | undefined,
): boolean {
  const levels = spec?.group_by;
  if (!levels || levels.length === 0) return false;
  return levels.some((level) => isNodeSetField(schema?.fields?.[level.field]));
}

// Whether ANY signal in `spec` touches a tag id: a `group_by` ref-level
// (`groupByHasRefLevel`, above), a `tagged:` leaf anywhere in the expr tree, OR
// a `field` predicate over a reference field's `key` (#1805 X2 — the shipped
// assistant view's TAG param filter, `field: {key: assistant_tags, op:
// overlap, value: {var: TAG}}`, is exactly this shape; ADR-0082 §5 / #1805 X1
// canonicalises its operand/values the same way the ref-group bucket does).
// Callers gate BOTH the reactive tag-roster `resolveTitle` AND `canonicalId`
// readers on this (widened from the group_by-only F7 gate): a view that
// touches no tag ids at all never subscribes to the tag store, but a ref
// group_by, a `tagged:` filter, or a ref-field `field` predicate — with no
// grouping at all — all do.
export function viewUsesTagIds(
  spec: Pick<ViewSpec, "group_by" | "expr"> | null | undefined,
  schema: MetadataSchema | null | undefined,
): boolean {
  if (groupByHasRefLevel(spec, schema)) return true;
  let found = false;
  walkViewExpr(spec?.expr, (e) => {
    // Same null-check style as `evalLeaf` — the backend serializes every
    // slot with unset ones as explicit `null` (Pydantic default dump), so
    // `!= null` (not a truthiness/`in` check) is the correct "is this leaf
    // set" test.
    if (e.tagged != null) found = true;
    if (e.field != null && isNodeSetField(schema?.fields?.[e.field.key])) found = true;
  });
  return found;
}

// The slice of the evaluator's run state ν-by-attribute reads: the schema (per-
// field bucket semantics) and the node index (reference levels resolve their
// value to a real-node bucket). `RunState` satisfies it structurally.
export type GroupByContext<T extends EvalNode> = {
  schema?: MetadataSchema | null;
  nodeById: ReadonlyMap<string, T>;
  // ADR-0082 slice 1 §3: fallback title lookup for a ref value outside the
  // view's own roster — a tag id in a scene/lore view grouped by an
  // `entity_ref_list` field, most commonly. Optional so a caller with no
  // off-roster vocabulary (or an existing test) needs no change.
  resolveTitle?: (id: string) => string | undefined;
  // ADR-0082 §5: follows a merged tag's id to its survivor, applied to the ref
  // branch BEFORE the title lookup — so a scene view grouped by Motifs buckets
  // a carrier that still holds a merged id under the survivor's header, not a
  // second one. Identity when absent.
  canonicalId?: (id: string) => string;
};

// Apply the ordered `group_by` levels to already-denormalized rows. Each level
// appends ONE path segment above the leaf (innermost), beneath every pipeline-
// produced segment, in declared order (outer → inner). A multi-valued field fans
// the row out under EACH value (groups repeat, `normalize` dedupes membership);
// a missing/unset value leaves the row BARE at that level (no segment, no
// "Ungrouped" bucket). Pure fold over the rows, level by level.
export function applyGroupBy<T extends EvalNode>(
  ctx: GroupByContext<T>,
  rows: ViewRow<T>[],
  levels: ViewGroupByLevel[],
): ViewRow<T>[] {
  let out = rows;
  for (const level of levels) {
    // Build the option value→label/index lookup ONCE per level: segmentForField
    // would otherwise run a linear `options.find` per row, O(rows×options) (#232).
    const options = optionLookup(ctx.schema, level.field);
    const next: ViewRow<T>[] = [];
    for (const r of out) {
      const segs = segmentForField(ctx, r.node, level, options);
      if (segs.length === 0) {
        next.push(r); // missing value → bare at this level
        continue;
      }
      for (const seg of segs) next.push({ node: r.node, path: [...r.path, seg] });
    }
    out = next;
  }
  return out;
}

// value→{label, index} lookup for an option-carrying level, or null when the
// field declares none — entry_type, reference, and free-text buckets label
// themselves and never consult it. The index is the option's position in the
// DECLARED order (ADR-0037 Amendment 3): buildLevel orders such buckets by it
// instead of first-seen, so a closed vocabulary renders in its own sequence
// (the prompt shelves, a status ladder) regardless of which rows exist.
type OptionLookup = { labels: Map<string, string>; index: Map<string, number> };

function optionLookup(
  schema: MetadataSchema | null | undefined,
  field: string,
): OptionLookup | null {
  const options = schema?.fields?.[field]?.options;
  if (!options || options.length === 0) return null;
  const labels = new Map<string, string>();
  const index = new Map<string, number>();
  options.forEach((o, i) => {
    index.set(o.value, i);
    // Only labelled options enter the label map; an option with no label falls
    // back to its raw value at the call site (`?? value`).
    if (o.label != null) labels.set(o.value, o.label);
  });
  return { labels, index };
}

// The buckets a node falls into for one `group_by` level (ADR-0037 §2 — the only
// genuinely new evaluator logic). Returns 0 segments (missing → bare), 1 (single
// value), or many (a multi-valued field fans out):
//  - `entry_type` (intrinsic) → one synthetic bucket, labelled by type display
//    name, keyed by the FQN.
//  - a reference field (entity_ref / entity_ref_list) → REAL-NODE buckets: the
//    target's title as label, its id as `nodeId` — an openable header (§6: a
//    value, never a member).
//  - enum / select (and multi_select) → synthetic buckets labelled by the OPTION
//    LABEL, keyed by the value, carrying the option's declared-order index
//    (ADR-0037 Amendment 3) so buildLevel orders siblings by vocabulary order.
//  - anything else (tags, text, …) → synthetic buckets labelled by the value.
// `order: "label"` is carried onto the segment so `buildLevel` can sort this
// level's sibling buckets alphabetically instead.
function segmentForField<T extends EvalNode>(
  ctx: GroupByContext<T>,
  node: T,
  level: ViewGroupByLevel,
  options: OptionLookup | null,
): PathSegment[] {
  const { field, order } = level;

  const raw = fieldValue(node, field, ctx.schema);
  if (isEmpty(raw)) return [];

  const fieldDef = ctx.schema?.fields?.[field];
  const type = fieldDef?.type;
  const isRef = type === "entity_ref" || type === "entity_ref_list";
  const values = isCollectionField(ctx.schema, field) || Array.isArray(raw) ? asArray(raw) : [raw];

  const seg = (key: string, label: string, nodeId: string | null): PathSegment => ({
    key,
    label,
    nodeId,
    origin: "field",
    ...(order ? { order } : {}),
  });

  const out: PathSegment[] = [];
  for (const v of values) {
    const value = String(v).trim();
    if (!value) continue;
    if (field === "entry_type") {
      out.push(seg(value, ctx.schema?.entry_types?.[value]?.name ?? value, null));
    } else if (isRef) {
      const canonical = ctx.canonicalId?.(value) ?? value;
      out.push(seg(canonical, ctx.nodeById.get(canonical)?.title ?? ctx.resolveTitle?.(canonical) ?? canonical, canonical));
    } else if (options) {
      // Option-carrying field: stamp the declared-order index (null = a value
      // outside the vocabulary, ordered after the declared buckets).
      out.push({ ...seg(value, options.labels.get(value) ?? value, null), optionIndex: options.index.get(value) ?? null });
    } else {
      out.push(seg(value, value, null));
    }
  }
  return out;
}
