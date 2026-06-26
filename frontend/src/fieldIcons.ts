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

// Curated, themed subset of Tabler icons for the per-field icon picker.
// NOT the full 5,800 — a writer-relevant set grouped by theme. Names are
// the Tabler glyph (no `ti-` prefix); all are real v3 icons.
export type IconCategory = { label: string; icons: string[] };

export const CURATED_ICON_CATEGORIES: IconCategory[] = [
  {
    label: "People",
    icons: [
      "user", "users", "user-circle", "mood-smile", "friends", "crown",
      "shield", "shield-half", "skull", "ghost", "heart", "heart-broken",
    ],
  },
  {
    label: "Places",
    icons: [
      "map-pin", "map", "map-2", "world", "building", "building-castle",
      "home", "tent", "mountain", "tree", "trees", "compass", "anchor",
      "sailboat", "route", "door",
    ],
  },
  {
    label: "Objects",
    icons: [
      "sword", "swords", "key", "lock", "lock-open", "book", "books",
      "notebook", "writing-sign", "bookmark", "feather", "brush", "palette",
      "camera", "bell", "gift", "coin", "coins", "diamond", "tools",
      "hammer", "flask", "bottle", "cup", "briefcase", "bulb",
    ],
  },
  {
    label: "Nature & Time",
    icons: [
      "sun", "moon", "cloud", "cloud-rain", "snowflake", "leaf", "flower",
      "plant", "droplet", "flame", "bolt", "clock", "hourglass", "calendar",
      "calendar-event",
    ],
  },
  {
    label: "Story & Status",
    icons: [
      "target", "crosshair", "wall", "eye", "eye-off", "star", "sparkles",
      "flag", "alert-triangle", "check", "x", "circle-dot", "point",
      "wand", "mask",
    ],
  },
  {
    label: "Symbols",
    icons: [
      "tag", "tags", "link", "affiliate", "hash", "pin", "paperclip",
      "quote", "list-check", "letter-case", "align-left", "toggle-right",
      "calculator",
    ],
  },
];

// Flat de-duplicated list, for search.
export const CURATED_ICONS: string[] = Array.from(
  new Set(CURATED_ICON_CATEGORIES.flatMap((category) => category.icons)),
);
