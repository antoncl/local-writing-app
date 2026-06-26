// Field icon resolution for the metadata revision.
//
// Every field type has a default Tabler glyph; a field may override it
// with its own `icon` (a Tabler name without the `ti-` prefix). The icon
// is display-only — the stable macro contract is the field key, never the
// glyph. See memory note `decisions-metadata-revision` for the table.

import type { MetadataFieldDefinition, MetadataFieldType } from "./types";

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
  tags: "tag",
  computed: "calculator",
  color: "palette",
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
