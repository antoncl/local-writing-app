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
 * Whether an open prompt document is read-only in place — i.e. inherited from the
 * built-in Library or an ancestor project, so a save would 409.
 *
 * The backend already computes this and carries it on the prompt read-model as
 * `editable` (#689); this is the single frontend reader of that verdict, shared by
 * NodeEditor's editability lock AND App's "Clone to edit" ancestor banner so the
 * two cannot drift (the #676 divergence). Unlike the old front-end ownership
 * re-derivation (source-layer compared against the open project's own layer), it
 * does NOT consult the async schema-layer store, so there is no load-gap where an
 * inherited prompt flashes editable.
 *
 * Fail CLOSED for prompts: a prompt document is treated as read-only unless the
 * server affirmatively marked it editable (`editable === true`). A missing flag
 * (stale/partial payload) locks rather than letting a save reach the 409. A null
 * document is not locked — there is nothing to edit yet. Non-prompt kinds are
 * never locked by this; their editability is a different axis (lore forks in
 * place, scenes are always owned).
 */
export function promptReadOnlyInPlace(
  documentKind: string,
  // The open document, any editor kind. The index signature lets the whole
  // `EditableDocument` union assign in (a `Scene` carries no `editable`, which a
  // bare `{ editable?: boolean }` would reject as a weak type) while `editable`
  // stays typed for the read below.
  scene: { editable?: boolean; [key: string]: unknown } | null | undefined,
): boolean {
  if (documentKind !== "prompt") return false;
  return !!scene && scene.editable !== true;
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
