// Field icon resolution for the metadata revision.
//
// Every field type has a default Tabler glyph; a field may override it
// with its own `icon` (a Tabler name without the `ti-` prefix). The icon
// is display-only — the stable macro contract is the field key, never the
// glyph. See memory note `decisions-metadata-revision` for the table.

import { firstInEntryTypeChain } from "@/lib/utils/colors";
import type { MetadataFieldDefinition, MetadataFieldType, MetadataSchema } from "@/lib/types";

// Default glyph per field type (Tabler names, no `ti-` prefix).
// `ti-links` is NOT a real Tabler icon — ref-list uses `affiliate`.
export const DEFAULT_FIELD_GLYPH: Record<MetadataFieldType, string> = {
  text: "letter-case",
  long_text: "align-left",
  number: "hash",
  boolean: "toggle-right",
  date: "calendar",
  select: "circle-dot",
  multi_select: "list-check",
  entity_ref: "link",
  entity_ref_list: "affiliate",
  computed: "calculator",
  color: "palette",
  list: "list-numbers",
};

// The Tabler name for a field: its own `icon` override, else the type
// default. Returns the bare name (no `ti-` prefix).
export function fieldGlyph(field: Pick<MetadataFieldDefinition, "type" | "icon">): string {
  const override = field.icon?.trim();
  if (override) return override;
  return DEFAULT_FIELD_GLYPH[field.type] ?? "letter-case";
}

// Full Tabler className for a field's icon, e.g. "ti ti-shield-half".
export function fieldIconClass(field: Pick<MetadataFieldDefinition, "type" | "icon">): string {
  return `ti ti-${fieldGlyph(field)}`;
}

// The Tabler name for an entry TYPE's icon (#316), the first explicit `icon` up
// the parent chain — the twin of `resolveColorForType`, sharing its walk via
// `firstInEntryTypeChain`. Unlike color there is NO kind-default table: a type
// icon is opt-in, so a type (and its ancestors) without one resolves to null and
// rows render exactly as before.
export function resolveTypeIcon(
  entryTypeId: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  return firstInEntryTypeChain(entryTypeId, schema, (def) => def.icon?.trim() || null);
}

// Full Tabler className for an entry type's icon, or null when the type (and its
// ancestors) declare none — callers skip the glyph entirely on null.
export function entryTypeIconClass(
  entryTypeId: string | null | undefined,
  schema: MetadataSchema | null | undefined,
): string | null {
  const name = resolveTypeIcon(entryTypeId, schema);
  return name ? `ti ti-${name}` : null;
}

// Ordered list of field types surfaced in the type editor's
// type-picker grid. `date` is intentionally omitted (deprecated per
// [[decisions-field-types]]) and stays out of the picker; existing fields
// of that type still render correctly via DEFAULT_FIELD_GLYPH. `tags` is
// retired (ADR-0082 slice 2b) — a tag vocabulary is authored as
// `entity_ref_list` → source kind `tag` → `create_missing`.
export const FIELD_TYPE_CHOICES: MetadataFieldType[] = [
  "text",
  "long_text",
  "number",
  "boolean",
  "select",
  "multi_select",
  "list",
  "entity_ref",
  "entity_ref_list",
  "computed",
  "color",
];

// Human label for a field type. Used by the type chip and the type-picker
// grid. Falls through to the raw type id for any future variant that
// hasn't been labelled yet.
export function fieldTypeLabel(type: MetadataFieldType): string {
  const labels: Record<MetadataFieldType, string> = {
    text: "Text",
    long_text: "Long Text",
    number: "Number",
    boolean: "Checkbox",
    date: "Date",
    select: "Select",
    multi_select: "Select, Multiple",
    entity_ref: "Entry Reference",
    entity_ref_list: "Entry Reference, Multiple",
    computed: "Computed",
    color: "Colour",
    // Plain "List" — the type a writer actually calls a list (an ordered
    // collection you add items to). multi_select now takes "Select, Multiple"
    // (mirroring entity_ref_list = "Entry Reference, Multiple"), which frees
    // the bare "List" for this type (#1209).
    list: "List",
  };
  return labels[type] ?? type;
}

// The curated per-field icon palette lives in `./fieldIconsData` — a
// dependency-free module so the subset-font build script can load it without a
// bundler (it can't resolve this file's `@/lib/utils/colors` import). Re-exported
// here so consumers keep importing the palette from `@/lib/utils/fieldIcons`.
export { CURATED_ICON_CATEGORIES, CURATED_ICONS } from "./fieldIconsData";
export type { IconCategory } from "./fieldIconsData";
