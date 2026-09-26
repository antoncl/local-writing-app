// The glue between "the writer edited a field at a scrub stop" (NodeEditor's
// `onStopFieldEdit` routed from MetadataPanel, or its own title input) and the
// generic `applyStopFieldEdit` orchestrator (ADR-0095 §8): classify the
// field's stop-edit kind off the schema, gather its BASE value (never the
// scrubbed display — the orchestrator's own fallback baseline) and call
// through. Kept out of NodeEditor (already at the file-size cap) so the
// classification is unit-testable off the mega-component.
import { isCollectionType } from "./mutationFieldOptions";
import { keyedListKeyMember, keyedShapeFor } from "./keyedList";
import { applyStopFieldEdit, type MutationStopEditDeps } from "./mutationStopEdit";
import type { StopEditFieldKind } from "./stopEditRows";
import type { MutationUnitGroup } from "./mutationUnits";
import type { EntryMetadata, MetadataSchema, MetadataValue, MutationSetEntry } from "@/lib/types";

interface Classified {
  kind: StopEditFieldKind;
  keyed?: ReturnType<typeof keyedShapeFor>;
  baseValue: unknown;
}

function classifyStopField(
  fieldId: string,
  schema: MetadataSchema | null,
  metadata: EntryMetadata,
  title: string,
): Classified {
  if (fieldId === "title") return { kind: "scalar", baseValue: title };
  const def = schema?.fields[fieldId];
  if (def && isCollectionType(def.type)) return { kind: "collection", baseValue: metadata[fieldId] };
  const keyMember = def ? keyedListKeyMember(def) : null;
  if (def && keyMember) return { kind: "keyed", keyed: keyedShapeFor(def), baseValue: metadata[fieldId] };
  // long_text is never stop-targetable (Anton, 2026-09-26, replacing §8's text
  // rule) — `stopTargetableFieldIds` excludes it, so a caller reaching here
  // with one is a bug in that gate, not a shape this function should classify.
  if (def && def.type === "long_text") throw new Error(`classifyStopField: '${fieldId}' is a long_text field and is not stop-editable.`);
  return { kind: "scalar", baseValue: metadata[fieldId] };
}

export interface StopFieldEditContext {
  stopUnit: MutationUnitGroup | null;
  entityId: string;
  schema: MetadataSchema | null;
  metadata: EntryMetadata;
  title: string;
  deps: MutationStopEditDeps;
}

/** Commit one field's stop edit (ADR-0095 §8) — routed from MetadataPanel's
 *  `onStopFieldEdit` (a rail row's write/clear) and from the title input's
 *  commit gesture. `value === null` is a clear: edits to "" unless the
 *  baseline is already empty (then `rowsForStopEdit` drops the row on its
 *  own — equal-to-baseline removes it). */
export async function commitStopFieldEdit(
  fieldId: string,
  value: MetadataValue | null,
  ctx: StopFieldEditContext,
): Promise<MutationSetEntry> {
  if (!ctx.stopUnit) throw new Error("No stop is open to edit.");
  const { kind, keyed, baseValue } = classifyStopField(fieldId, ctx.schema, ctx.metadata, ctx.title);
  const edited = value === null ? "" : value;
  return applyStopFieldEdit({
    unit: ctx.stopUnit,
    entityId: ctx.entityId,
    field: fieldId,
    fieldType: kind,
    keyed,
    baseValue,
    editedValue: edited,
    deps: ctx.deps,
  });
}
