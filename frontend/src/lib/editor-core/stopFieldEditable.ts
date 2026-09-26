// ADR-0095 §8: at a scrub stop, every field a mutation can target is editable
// in place — the header title, the rail, the list tabs — while the body stays
// a read-only overlay and the entry-type selector stays locked. Pure — no
// Svelte, no store reads — so NodeEditor/EditorBodyHost/MetadataPanel/FootDock
// all gate on the SAME answer instead of re-deriving it (ADR-0095 replaces
// ADR-0013's/ADR-0088's whole-card read-only stop with this per-field one).
import { buildFieldOptions } from "./mutationFieldOptions";
import type { DocumentKind, MetadataSchema } from "@/lib/types";

export interface StopEditGateContext {
  scrubbed: boolean;
  snapshotParked: boolean;
  reviewing: boolean;
  inheritedReadOnly: boolean;
  documentKind: DocumentKind;
}

/** The shared gate every stop-edit surface asks first: scrubbed, and none of
 *  the other read-only axes (a parked snapshot, an AI review, an inherited
 *  prompt) is active. `stopFieldEditable` narrows this to one field;
 *  `MutationScrubber`'s "editing this stop" caption (§8) and FootDock's
 *  keyboard gate (§8's dock rule) just need this — SOME field is editable, not
 *  which one. */
export function stopEditingEngaged(ctx: StopEditGateContext): boolean {
  if (!ctx.scrubbed || ctx.snapshotParked || ctx.reviewing) return false;
  return !(ctx.inheritedReadOnly && ctx.documentKind !== "prompt");
}

/** The field-membership half of `stopFieldEditable`, split out so a caller
 *  that has ALREADY merged the other read-only axes into one flag (e.g.
 *  MetadataPanel, whose `readOnly` prop already folds snapshotParked/
 *  reviewing/inheritedReadOnly per ADR-0095 §8's redefinition of
 *  `editorReadOnly`) can ask just this half instead of re-deriving the merge
 *  to call the full predicate below. The same roster `buildFieldOptions`
 *  offers for `/mutate` (so: not computed, not a non-keyed `list`, plus the
 *  intrinsic `title`) — EXCEPT the body, which stays a read-only overlay at a
 *  stop even though a mutation can append to it (body rows are edited in the
 *  pill dialog, never here).
 *
 *  Returns the whole Set rather than testing one field: `buildFieldOptions`
 *  walks every field on the entry type, so a caller asking per-row (the rail,
 *  one row per field per render) would otherwise rebuild that whole roster
 *  once per row. Callers that only ever need ONE field's answer (a single
 *  event handler, not a render loop — `stopFieldEditable` below) still just
 *  build the Set and `.has()` it; it's the render-loop callers (MetadataPanel)
 *  that must build it ONCE per render instead. */
export function stopTargetableFieldIds(schema: MetadataSchema | null, entryType: string): Set<string> {
  const ids = buildFieldOptions(schema, entryType, true)
    .map((option) => option.id)
    .filter((id) => id !== "body");
  return new Set(ids);
}

export interface StopFieldEditContext extends StopEditGateContext {
  schema: MetadataSchema | null;
  entryType: string;
}

/** Whether `fieldId` is editable AT THE OPEN SCRUB STOP (ADR-0095 §8): the
 *  card must be engaged (see `stopEditingEngaged`) and the field must be in
 *  `stopTargetableFieldIds`. A field the rail already locks for another reason
 *  (`ai_temperature` unsupported by the model, a derived-state select) stays
 *  locked too — those never co-occur with a lore card's scrub axis today, but
 *  `fieldRowModel.ts`'s `fieldReadOnly` still checks them ahead of this
 *  predicate, so a future co-occurrence fails closed. A single-call form (one
 *  field, not a render loop) — EditorBodyHost asks this per event, not per
 *  row, so rebuilding the Set here is fine. */
export function stopFieldEditable(fieldId: string, ctx: StopFieldEditContext): boolean {
  return stopEditingEngaged(ctx) && stopTargetableFieldIds(ctx.schema, ctx.entryType).has(fieldId);
}
