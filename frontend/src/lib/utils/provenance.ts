// Node provenance surfacing (#313 / ADR-0039 slice D).
//
// A node resolved into the open project may be *owned* by an ancestor layer —
// it is inherited, not authored here. The backend stamps every entry with the
// winning layer's `source_layer_id` / `source_layer_label`; this decides, per
// node, whether to draw the "level pill" that names that ancestor.
//
// Pure so it is unit-testable: the frontend has no component-test infra, so any
// UI decision worth pinning is factored out to a plain function (the same reason
// projectChain.ts exists).

/** The provenance fields every inheritable entry summary carries. */
export type NodeProvenance = {
  source_layer_id?: string;
  source_layer_label?: string;
};

/**
 * The label for an inherited node's owning layer, or `null` when the node
 * belongs to the open project (or provenance is not yet known).
 *
 * `ownLayerId` is the open project's own layer id — `projectSchemaLayerId()`,
 * the innermost merged schema layer. A node whose `source_layer_id` matches it
 * is authored here and gets no pill; a differing id is inherited and shows the
 * ancestor's label (falling back to the raw id if the backend sent no label).
 *
 * Returns `null` while either id is missing rather than guessing: an empty
 * `ownLayerId` means the schema has not loaded, and drawing a pill then would
 * flag every row as inherited until it does.
 */
export function inheritedLayerLabel(
  node: NodeProvenance,
  ownLayerId: string,
): string | null {
  const layerId = node.source_layer_id;
  if (!layerId || !ownLayerId) return null;
  if (layerId === ownLayerId) return null;
  return node.source_layer_label || layerId;
}

/** Whether the node is inherited from an ancestor layer (has a level pill). */
export function isInherited(node: NodeProvenance, ownLayerId: string): boolean {
  return inheritedLayerLabel(node, ownLayerId) !== null;
}

/**
 * Whether the open project positively OWNS this node — its source layer is known
 * AND equals the project's own layer.
 *
 * Unlike `isInherited`, this FAILS CLOSED: it returns false whenever either id is
 * missing. That difference is load-bearing for a WRITE gate (a read-only lock).
 * `isInherited` fails OPEN — while `ownLayerId` is empty (schema still loading) it
 * returns false, i.e. "not inherited", which is right for a display pill (don't
 * flag every row until the schema lands) but wrong for editability: it would
 * present an inherited node as editable in that gap and let a save reach the
 * backend's 409. Gating editability on `!isOwnedHere(...)` locks until ownership
 * is proven, so the load gap is safe (#676 review).
 */
export function isOwnedHere(node: NodeProvenance, ownLayerId: string): boolean {
  return !!node.source_layer_id && !!ownLayerId && node.source_layer_id === ownLayerId;
}

/** How a metadata field's effective value is sourced, for the rail's tint (#517). */
export type FieldProvenance = "local" | "layer-inherited" | "overridden";

/**
 * Classify one field's provenance on the entry the rail is showing — the
 * "one visual language" of create-project-wizard.md §8:
 *
 * - `overridden` — the entry is inherited but this field's value comes from an
 *   override at a consuming layer. Reads *live*, led by the interactive
 *   `ti-versions` mark whose hover reveals the "Reset to <source>" gesture.
 * - `layer-inherited` — the entry is inherited and this field is not overridden,
 *   so its value flows from the owning ancestor. Reads *muted*, source in the
 *   tooltip, no reset (nothing to clear).
 * - `local` — the entry is authored in the open project. No layer treatment.
 *
 * `entryIsInherited` is `inheritedLayerLabel(...) !== null`, passed in rather
 * than recomputed so the caller keeps the single provenance read. An overridden
 * field wins even if `entryIsInherited` were somehow false — the override is the
 * stronger fact — so the check is ordered override-first.
 */
export function fieldProvenance(
  fieldId: string,
  entryIsInherited: boolean,
  overriddenFields: readonly string[],
): FieldProvenance {
  if (overriddenFields.includes(fieldId)) return "overridden";
  return entryIsInherited ? "layer-inherited" : "local";
}

/**
 * Whether an owned entry's field offers the clear-to-default gesture (#522) —
 * the intra-project twin of the #517 layer reset. A field qualifies only when it
 * is authored in the open project (not `entryIsInherited`), is not a layer
 * override (those revert via #517), is an editable stored field (never `status`,
 * which has its own control, nor `computed`, which is read-only — ADR-0029 §D),
 * and currently carries a value in its own metadata (`hasStoredValue`), so there
 * is something to delete. Pure so the gate is unit-tested rather than buried in
 * the component (the frontend has no component-test infra).
 */
export function isFieldOwnClearable(params: {
  fieldId: string;
  fieldExists: boolean;
  fieldType?: string;
  fieldCategory?: string;
  entryIsInherited: boolean;
  isOverridden: boolean;
  hasStoredValue: boolean;
}): boolean {
  const { fieldId, fieldExists, fieldType, fieldCategory, entryIsInherited, isOverridden, hasStoredValue } =
    params;
  if (!fieldExists) return false;
  if (entryIsInherited || isOverridden) return false;
  if (fieldId === "status" || fieldType === "computed" || fieldCategory === "computed") return false;
  return hasStoredValue;
}
