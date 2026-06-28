// Shared, pure helpers for the Detail Type editor (SchemaTypeEditor) and a
// handful of remaining callers in App.svelte. Extracted alongside the
// SchemaTypeEditor split (#14, second slice) so the component and the
// parent's API-touching handlers (saveSchemaField, applyGroupToType, …)
// both source the same definitions instead of duplicating them.
//
// Everything here is pure: schema/layer state is passed in as arguments
// rather than read from a closure, so the helpers work the same whether
// they're invoked from the component (where schema lives on props) or from
// App.svelte (where it lives on its own `let` bindings).

import type {
  EntryTypeDefinition,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataSchemaLayer,
} from "./types";

// Slugify a free-text label into a stable field/type id.
export function slugifyFieldId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[0-9]/, "field_$&");
}

// Suggest a key prefix for a group application from its label.
export function suggestPrefixFromLabel(label: string): string {
  const slug = slugifyFieldId(label);
  return slug ? `${slug}_` : "";
}

// Display name for a built-in or custom entry type.
export function nodeTypeDisplayName(
  typeId: string,
  definition: EntryTypeDefinition | undefined,
): string {
  if (typeId === "scene") return "Scenes";
  if (typeId === "lore_entry") return "Lore Entries";
  if (typeId === "prompt") return "Prompts";
  return definition?.name ?? typeId;
}

// Source-layer index (used as a CSS `--source-index`) for the colored
// badge that distinguishes system, project, and machine layers.
export function sourceLayerIndex(
  source: { layer_id: string; built_in: boolean } | undefined | null,
  layers: MetadataSchemaLayer[],
): number {
  if (!source || source.built_in) return 0;
  return Math.max(0, layers.findIndex((layer) => layer.id === source.layer_id) + 1);
}

// Short text for the source badge ("System" / layer label / "Unknown").
export function sourceBadgeLabel(
  source: { layer_label: string; built_in: boolean } | undefined | null,
): string {
  return source?.built_in ? "System" : (source?.layer_label ?? "Unknown");
}

// The type a given field is inherited from (its defining entry-type's
// display name) — for the "extends" jump label. Best-effort: the nearest
// ancestor whose own_fields includes the field.
export function inheritedFromLabel(
  entryTypeId: string,
  fieldId: string,
  schema: MetadataSchema | null,
): string {
  let cursor = schema?.entry_types[entryTypeId]?.parent ?? null;
  let guard = 0;
  while (cursor && guard < 20) {
    const def = schema?.entry_types[cursor];
    if (!def) break;
    if (Array.isArray(def.own_fields) ? def.own_fields.includes(fieldId) : def.fields?.includes(fieldId)) {
      return nodeTypeDisplayName(cursor, def);
    }
    cursor = def.parent ?? null;
    guard += 1;
  }
  return "parent";
}

// Display name for a group-derived field's origin marker.
export function groupOriginLabel(
  field: MetadataFieldDefinition,
  schema: MetadataSchema | null,
): string {
  if (field.group) return field.group;
  const def = field.group_origin ? schema?.groups?.[field.group_origin] : null;
  return def?.name ?? "group";
}

// L1 grouping for the type editor field rows. Ungrouped fields render
// first under no header, then each group in first-appearance order under
// its own section header. Preserves the underlying entry order so drag-
// reorder still operates on the stored sequence.
export type SchemaFieldSection = {
  group: string | null;
  entries: [string, MetadataFieldDefinition][];
};

export function buildSchemaFieldSections(
  entries: [string, MetadataFieldDefinition][],
): SchemaFieldSection[] {
  const ungrouped: [string, MetadataFieldDefinition][] = [];
  const groups = new Map<string, [string, MetadataFieldDefinition][]>();
  for (const entry of entries) {
    const group = (entry[1].group ?? "").trim();
    if (!group) {
      ungrouped.push(entry);
    } else {
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group)!.push(entry);
    }
  }
  const out: SchemaFieldSection[] = [];
  if (ungrouped.length) out.push({ group: null, entries: ungrouped });
  for (const [group, groupEntries] of groups) out.push({ group, entries: groupEntries });
  return out;
}
