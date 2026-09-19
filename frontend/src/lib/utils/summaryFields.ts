// Pure "one-line detail" synthesis for an entry's row (#2008). MUST match the
// backend twin `backend/app/services/project/schema_summary.py` exactly — a
// rule change here needs the same change there, and vice versa.
//
// `summaryFieldKeys` prefers the type's own explicit `summary_fields`
// nomination (kept to keys that still exist on the schema, in the author's
// order); with no nomination it falls back to the first three fields — in
// schema declaration order — whose type is a "summary scalar" AND whose
// value is present on this instance. `summaryValues`/`summaryLine` render
// those keys' present values into display text.

import { isMetadataValuePresent, metadataValueDisplayString } from "./schemaTypeHelpers";
import type { EntryMetadata, EntryTypeDefinition, MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

// Field types eligible for the FALLBACK synthesis (no explicit nomination).
// Mirrors the backend's SUMMARY_SCALAR_TYPES.
export const SUMMARY_SCALAR_TYPES = new Set(["text", "number", "boolean", "select", "multi_select", "date"]);

// The nominated (or synthesized) field keys for a type, on a specific
// instance's metadata — the instance matters only for the fallback path,
// which skips a scalar field the instance leaves empty.
export function summaryFieldKeys(
  def: EntryTypeDefinition | undefined,
  schema: MetadataSchema,
  metadata: EntryMetadata,
): string[] {
  const nominated = (def?.summary_fields ?? []).filter((key) => Boolean(schema.fields?.[key]));
  if (nominated.length > 0) return nominated;
  const out: string[] = [];
  for (const key of def?.fields ?? []) {
    if (out.length >= 3) break;
    const field = schema.fields?.[key];
    if (!field || !SUMMARY_SCALAR_TYPES.has(field.type)) continue;
    // The identity triple lives on the node, not in metadata, and a field the
    // type hides is hidden here too — neither summarises anything.
    if (field.intrinsic || fieldHidden(def, field, key)) continue;
    if (!isMetadataValuePresent(metadata?.[key])) continue;
    out.push(key);
  }
  return out;
}

// A field's effective hidden flag for this type — `effectiveFieldHidden`'s
// rule (a per-type override, true OR false, wins over the def's default), read
// off `def.field_overrides` for the same reason `fieldLabel` below does.
function fieldHidden(def: EntryTypeDefinition | undefined, field: MetadataFieldDefinition, key: string): boolean {
  const override = def?.field_overrides?.[key];
  if (override && typeof override.hidden === "boolean") return override.hidden;
  return Boolean(field.hidden);
}

export type SummaryValue = { key: string; label: string; text: string };

function optionLabel(field: MetadataFieldDefinition | undefined, rawValue: string): string {
  const option = field?.options?.find((o) => o.value === rawValue);
  return option?.label || rawValue;
}

// Render one field's present value into display text, dispatching on the
// field's type — the same per-type rendering rules the backend twin applies.
function valueText(
  field: MetadataFieldDefinition | undefined,
  value: EntryMetadata[string],
  resolveTitle?: (id: string) => string | undefined,
): string {
  const type = field?.type;
  if (type === "select") {
    return typeof value === "string" ? optionLabel(field, value) : metadataValueDisplayString(value);
  }
  if (type === "multi_select") {
    const items = Array.isArray(value) ? value : [];
    return items
      .map((item) => optionLabel(field, String(item)))
      .filter(Boolean)
      .join(", ");
  }
  if (type === "boolean") return value ? "Yes" : "No";
  if (type === "entity_ref") {
    const id = typeof value === "string" ? value : null;
    return id ? resolveTitle?.(id) ?? id : "";
  }
  if (type === "entity_ref_list") {
    const items = Array.isArray(value) ? value.map((item) => String(item)) : [];
    return items.map((id) => resolveTitle?.(id) ?? id).join(", ");
  }
  return metadataValueDisplayString(value);
}

// A field's effective label — mirrors `effectiveFieldLabel`'s rule (a
// per-type `field_overrides` label wins, else the field def's `name`), read
// off `def.field_overrides` directly since that map is already the resolved,
// parent-merged overlay for this exact type (see schemaTypes.ts) — callers
// here only have the definition, not its entry-type id, which is what
// `effectiveFieldLabel` would otherwise need to look the map up itself.
function fieldLabel(def: EntryTypeDefinition | undefined, schema: MetadataSchema, key: string): string {
  const override = def?.field_overrides?.[key];
  const label = override?.label;
  if (typeof label === "string" && label.trim()) return label;
  return schema.fields?.[key]?.name ?? key;
}

export function summaryValues(
  def: EntryTypeDefinition | undefined,
  schema: MetadataSchema,
  metadata: EntryMetadata,
  resolveTitle?: (id: string) => string | undefined,
): SummaryValue[] {
  const out: SummaryValue[] = [];
  for (const key of summaryFieldKeys(def, schema, metadata)) {
    const value = metadata?.[key];
    if (!isMetadataValuePresent(value)) continue;
    const text = valueText(schema.fields?.[key], value, resolveTitle);
    if (!text) continue;
    out.push({ key, label: fieldLabel(def, schema, key), text });
  }
  return out;
}

export function summaryLine(
  def: EntryTypeDefinition | undefined,
  schema: MetadataSchema,
  metadata: EntryMetadata,
  resolveTitle?: (id: string) => string | undefined,
): string | null {
  const texts = summaryValues(def, schema, metadata, resolveTitle).map((v) => v.text);
  return texts.length > 0 ? texts.join(" · ") : null;
}
