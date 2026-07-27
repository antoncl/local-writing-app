// The create-project wizard's review pane (#318 slice 4 — design-doc §5 step 4).
//
// One row per authored field of the project node, resolved over the ticked
// ancestor chain. The chain-walk (pop-key) model, NOT the id-keyed overrides of
// the everyday MetadataPanel: a field the wizard sets is written into the new
// book's own `project.md`; a field left alone is absent and inherits (from an
// ancestor) or falls to its schema default. Pure and dependency-free so the
// row logic is unit-tested — the frontend has no component-test infra, so any
// decision worth pinning lives in a plain function (as wizardSteps.ts and
// projectChain.ts do).

import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";
import { effectiveFieldHidden, effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";

// The project node's kind — the review pane only ever shows this entry type.
export const PROJECT_ENTRY_TYPE = "project:project";

// How a field's shown value is sourced, for the row's tint (design-doc §8):
// - `local` — the author set it here; it will be written to this book. Reads
//   live, and offers "Reset to <source>" back to what it would otherwise be.
// - `inherited` — an ancestor states it; reads muted, source in the tooltip.
// - `default` — no ancestor states it, so it falls to the schema default; shown
//   filled-in (defaulted-and-shown, §6), no layer treatment.
export type ReviewProvenance = "local" | "inherited" | "default";

export type ProjectReviewRow = {
  fieldId: string;
  field: MetadataFieldDefinition;
  label: string;
  // The effective value to show/edit: the local override if set, else the
  // inherited value, else the field's default.
  value: MetadataValue;
  provenance: ReviewProvenance;
  // The ancestor layer that supplies (or would supply) this field when it is
  // not set locally — the "Reset to <source>" target. `null` when nothing above
  // states it, so a reset returns to the plain default.
  sourceLabel: string | null;
  // The author has set this field here, so it can be reset back to inherit.
  clearable: boolean;
};

/**
 * Build the review rows for a prospective project.
 *
 * @param schema     the merged schema over the ticked chain (prospective — NOT
 *                   the open-project `$metadataSchemaStore`)
 * @param inherited  the resolved authored values (nearest-explicit-wins); a key
 *                   no ancestor states is simply absent
 * @param sources    per resolved key, the ancestor layer label that supplied it
 * @param overrides  the fields the author has set in the wizard (its own draft)
 */
export function projectReviewRows(
  schema: MetadataSchema,
  inherited: Record<string, MetadataValue>,
  sources: Record<string, string>,
  overrides: Record<string, MetadataValue>,
  entryType: string = PROJECT_ENTRY_TYPE,
): ProjectReviewRow[] {
  const fieldIds = schema.entry_types[entryType]?.fields ?? [];
  const rows: ProjectReviewRow[] = [];
  for (const fieldId of fieldIds) {
    const field = schema.fields[fieldId];
    if (!field) continue;
    // Intrinsic fields (id/title/entry_type) live on the node, not its metadata;
    // computed fields are derived and read-only — neither is an author ask.
    if (field.intrinsic) continue;
    if (field.type === "computed" || field.category === "computed") continue;
    if (effectiveFieldHidden(schema, entryType, fieldId)) continue;

    const hasLocal = Object.prototype.hasOwnProperty.call(overrides, fieldId);
    // A field is inherited when an ancestor *states the key* — which is exactly
    // its presence in `inherited`/`sources` (the backend fold carries only
    // stated keys). Key-presence, NOT value-non-emptiness: an ancestor that
    // states an empty value is inheriting that empty value, and the runtime
    // channel resolves it so — the review must agree, or the preview lies. Only
    // a key no ancestor states falls to the field's own default.
    const hasInherited = Object.prototype.hasOwnProperty.call(inherited, fieldId);
    const inheritedValue = hasInherited ? inherited[fieldId] : (field.default ?? null);
    // The source is the ancestor that states it, independent of whether the
    // author has overridden it — that is exactly the reset target.
    const sourceLabel = sources[fieldId] ?? null;

    rows.push({
      fieldId,
      field,
      label: effectiveFieldLabel(schema, entryType, fieldId),
      value: hasLocal ? overrides[fieldId] : inheritedValue,
      provenance: hasLocal ? "local" : hasInherited ? "inherited" : "default",
      sourceLabel,
      clearable: hasLocal,
    });
  }
  return rows;
}

/** The "Reset to <x>" wording for a locally-set field (§8): name the ancestor
 *  it would defer to, or "default" when nothing above states it. */
export function resetTargetLabel(row: ProjectReviewRow): string {
  return row.sourceLabel ?? "default";
}
