// group_by — ν by attribute (ADR-0037 §2), applied to the evaluator's already-
// denormalized `(node, path)` rows. Split out of `evaluateView.ts` (which sat
// in the file-size warn zone); this is the result-level half of the two ν
// operators — Nest (ν by join) stays in the evaluator's pipeline. Type-only
// imports from `evaluateView` keep this dependency cycle-free at runtime.

import type { EvalNode, PathSegment, ViewRow } from "@/lib/views/evaluateView";
import type { MetadataSchema, ViewGroupByLevel } from "@/lib/types";
import { asArray, fieldValue, isCollectionField, isEmpty } from "@/lib/views/fieldAccess";

// The slice of the evaluator's run state ν-by-attribute reads: the schema (per-
// field bucket semantics) and the node index (reference levels resolve their
// value to a real-node bucket). `RunState` satisfies it structurally.
export type GroupByContext<T extends EvalNode> = {
  schema?: MetadataSchema | null;
  nodeById: ReadonlyMap<string, T>;
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
    const next: ViewRow<T>[] = [];
    for (const r of out) {
      const segs = segmentForField(ctx, r.node, level);
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

// The buckets a node falls into for one `group_by` level (ADR-0037 §2 — the only
// genuinely new evaluator logic). Returns 0 segments (missing → bare), 1 (single
// value), or many (a multi-valued field fans out):
//  - `entry_type` (intrinsic) → one synthetic bucket, labelled by type display
//    name, keyed by the FQN.
//  - a reference field (entity_ref / entity_ref_list) → REAL-NODE buckets: the
//    target's title as label, its id as `nodeId` — an openable header (§6: a
//    value, never a member).
//  - enum / select (and multi_select) → synthetic buckets labelled by the OPTION
//    LABEL, keyed by the value.
//  - anything else (tags, text, …) → synthetic buckets labelled by the value.
// `order: "label"` is carried onto the segment so `buildLevel` can sort this
// level's sibling buckets alphabetically instead of first-seen.
function segmentForField<T extends EvalNode>(
  ctx: GroupByContext<T>,
  node: T,
  level: ViewGroupByLevel,
): PathSegment[] {
  const { field, order } = level;

  // `source_layer` (ADR-0037 §7 — the Assistants default): resolved off the
  // node's summary-level projection (`source_layer_id`/`source_layer_label`),
  // like `entry_type` routes to a top-level property — there is no schema field
  // to consult. One synthetic bucket per layer, keyed by id, labelled by label.
  if (field === "source_layer") {
    const layerId = (node.source_layer_id ?? "").trim();
    if (!layerId) return []; // missing → bare at this level
    return [
      {
        key: layerId,
        label: node.source_layer_label || layerId,
        nodeId: null,
        origin: "field",
        ...(order ? { order } : {}),
      },
    ];
  }

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
      out.push(seg(value, ctx.nodeById.get(value)?.title ?? value, value));
    } else {
      const option = fieldDef?.options?.find((o) => o.value === value);
      out.push(seg(value, option?.label ?? value, null));
    }
  }
  return out;
}
